#!/usr/bin/env bash
# The check of a published build, for a release that changes what it can find a fault in
# (decide.py's rc_check.required: the update, the install, the packaging, a migration, the
# service unit, and every promotion to stable). It runs on the build itself, any tag: a nightly
# (vX.Y.0-devN) before the owner's install takes it, a held stable (vX.Y.Z: a promotion or a
# fix) before gate.py releases it; an old rc tag (vX.Y.Z-rcN) still works. On a scratch copy of
# this machine's kranto home (scripts/release/e2e_update.sh setup: the live home copied read-only
# without secrets; no model is called), as its own unit on 127.0.0.1:$PORT:
#
#   PORT=8940 E2E_DIR=~/somewhere scripts/release/rc_check.sh TAG [vPREVIOUS]
#
#   0. a fresh HOME: the rc's own install.sh, then 'kranto setup --yes' with an answers file
#      (scripts/release/fresh_install.sh; a release before the wizard: 'kranto up');
#   1. install the previous release from its wheels (default: guards.py previous, the release
#      before it on its line; the gate and hotfix.sh name it);
#   2. kranto update to the rc: done, the rc answers, the old server stopped on SIGTERM;
#   3. kranto update --rollback: the previous release answers again;
#   4. kranto update to the rc again: done, the rc answers;
#   5. kranto doctor --routes: every page the rc serves, read once on the copy's data, answers
#      below 500 (the post-update self-check, D1);
#   6. the same on the odd installs (scripts/dev/odd_walk.sh,): homes holding
#      every odd value the rc's writers store (odd, empty, projects), each served by the rc on
#      127.0.0.1:$ODD_PORT (default PORT+1);
#   7. no request storm: signed in on the copy, Home and three pages in a headless browser, every
#      write refused; no address asked more than 20 times in 30 s (storm_walk.py; Playwright's
# python from $PW_PYTHON).
#
# Each step prints PASS or FAIL and its log; the scratch instance is removed at the end, pass or
# fail. Exit 0 when all eight pass, 1 otherwise. Needs gh, uv, curl and a systemd user manager.
set -euo pipefail

RC="${1:?usage: rc_check.sh TAG [vPREVIOUS]}"
[[ "$RC" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+|-dev[0-9]+)?$ ]] || {
  echo "rc_check: $RC is not a release tag (vX.Y.Z, vX.Y.0-devN)" >&2; exit 2; }
: "${E2E_DIR:?set E2E_DIR to a scratch folder}" "${PORT:?set PORT (served on 127.0.0.1)}"
REPO="${REPO:-iddv/kranto}"
# the release before it on its line, by tag (a held stable is a GitHub prerelease until it is
# released): for a nightly, the newest nightly before it, else the newest stable; for a stable
# tag, the newest stable before it
PREV="${2:-$(gh release list -R "$REPO" --exclude-drafts -L 100 --json tagName -q '.[].tagName' \
  | python3 "$(dirname "$0")/guards.py" previous "$RC")}"
[ -n "$PREV" ] || { echo "rc_check: no release before $RC to update from; name it" >&2; exit 2; }
pep440() { local v="${1#v}"; v="${v/-rc/rc}"; echo "${v/-dev/.dev}"; }
RC_V="$(pep440 "$RC")" PREV_V="$(pep440 "$PREV")"
# the scratch install's channel: rc, which a release from before the nightly line accepts and a
# newer one reads as nightly (a 0.5.x previous would refuse the word nightly at start)
export E2E_DIR PORT CHANNEL=rc KRANTO_UNIT="kranto-rc-$PORT.service"
E2E="$(cd "$(dirname "$0")" && pwd)/e2e_update.sh"
KRANTO="$E2E_DIR/bin/kranto" STATE="$E2E_DIR/kb/update/state.json"
mkdir -p "$E2E_DIR"
echo "rc_check: $PREV -> $RC on 127.0.0.1:$PORT ($KRANTO_UNIT), logs in $E2E_DIR"

trap 'bash "$E2E" teardown > "$E2E_DIR/teardown.log" 2>&1 || true' EXIT
bash "$E2E" setup > "$E2E_DIR/setup.log" 2>&1

failed=0
say() { if [ "$1" = PASS ]; then echo "PASS $2"; else echo "FAIL $2: $3 (see $E2E_DIR/$4.log)"; failed=1; fi; }
runs() { "$KRANTO" --version 2>/dev/null | grep -q "^kranto $1 " \
  && curl -sf "http://127.0.0.1:$PORT/api/status" | grep -q "\"version\": *\"$1\""; }
updated() {          # the helper's last state: done, and the old server stopped on SIGTERM
  python3 - "$STATE" "$1" <<'PY'
import json, sys
st = json.load(open(sys.argv[1]))
if st.get("state") != "done" or st.get("to") != sys.argv[2]:
    sys.exit(f"the update ended {st.get('state')}: {st.get('reason') or st.get('detail')}")
if (st.get("stop") or {}).get("killed"):
    sys.exit(st.get("warning") or "the old server was killed")
PY
}
on_rc() { updated "$RC_V" && runs "$RC_V"; }
step() {             # step NAME LOG CHECK... : run the e2e step (env set by the caller), then check
  local name="$1" log="$2"; shift 2
  local why
  if ! why="$("$@" 2>&1)"; then say FAIL "$name" "${why:-check failed}" "$log"; return 1; fi
  say PASS "$name"
}

fresh() { bash "$(dirname "$0")/fresh_install.sh" "$RC" "$E2E_DIR/fresh"; }
step "0. a fresh HOME: install.sh, then kranto setup --yes" fresh/install fresh || true
FROM_TAG="$PREV" bash "$E2E" install > "$E2E_DIR/install.log" 2>&1 || true
step "1. install $PREV" install runs "$PREV_V" || exit 1
TO="$RC" bash "$E2E" update > "$E2E_DIR/update.log" 2>&1 || true
step "2. update to $RC" update on_rc || true
bash "$E2E" rollback > "$E2E_DIR/rollback.log" 2>&1 || true
step "3. roll back to $PREV" rollback runs "$PREV_V" || true
TO="$RC" bash "$E2E" update > "$E2E_DIR/update-again.log" 2>&1 || true
step "4. update to $RC again" update-again on_rc || true
# the post-update self-check, on the copy of this machine's own data: every
# page the rc serves answers below 500 (an rc from before it has no --routes: not run)
routes() { if "$KRANTO" doctor --help 2>/dev/null | grep -q -- '--routes'; then
  "$KRANTO" doctor --routes --port "$PORT"; else echo "this rc has no doctor --routes"; fi; }
step "5. every page of $RC on this machine's data (kranto doctor --routes)" routes routes \
  || true
# the odd installs: every page of the rc on data no one install holds
odd() { ODD_DIR="$E2E_DIR/odd" bash "$(dirname "$0")/../dev/odd_walk.sh" \
  "${ODD_PORT:-$((PORT + 1))}" "$KRANTO"; }
step "6. every page of $RC on the odd installs (scripts/dev/odd_walk.sh)" odd/odd odd || true
# a request storm: v0.6.0-dev3's console posted console/open without end and passed
# every step above. Signed in on the copy (its own unit's one-time link, never logged), Home and
# three pages in a headless browser, every write refused; any address asked more than 20 times in
# 30 s fails. Playwright's python: $PW_PYTHON, else python3 when it has it.
storm() {
  local py="${PW_PYTHON:-python3}" link
  "$py" -c 'import playwright' 2>/dev/null \
    || { echo "no Playwright in $py: set PW_PYTHON to a python with it and its Chromium"; return 1; }
  link="$(KRANTO_HOME="$E2E_DIR/kb" "$KRANTO" open --no-browser 2>/dev/null | grep -o 'http://[^ ]*auth/open[^ ]*' | tail -1)"
  [ -n "$link" ] || { echo "kranto open printed no sign-in link"; return 1; }
  STORM_LINK="$link" "$py" "$(dirname "$0")/storm_walk.py" "http://127.0.0.1:$PORT" \
    > "$E2E_DIR/storm.log" 2>&1 || { tail -3 "$E2E_DIR/storm.log"; return 1; }
}
step "7. no request storm on Home and three pages of $RC (storm_walk.py)" storm storm || true
if [ "$failed" -eq 0 ]; then
  # the pass gate.py offer asks for before it offers a nightly published unoffered
  mkdir -p "${RC_PASSED_DIR:-$HOME/.cache/kranto-release/passed}"
  date -u +%Y-%m-%dT%H:%M:%SZ > "${RC_PASSED_DIR:-$HOME/.cache/kranto-release/passed}/$RC"
  echo "rc_check: $RC passed"
else
  echo "rc_check: $RC FAILED"
fi
exit "$failed"
