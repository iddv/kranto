#!/usr/bin/env bash
# The check of a published build, for a release that changes what it can find a fault in
# (decide.py's rc_check.required: the update, the install, the packaging, a migration, the
# service unit, and every promotion to stable). It runs on the build itself, any tag: a nightly
# (vX.Y.0-devN) before the maintainer's install takes it, a held stable (vX.Y.Z: a promotion or a
# fix) before gate.py releases it; an old rc tag (vX.Y.Z-rcN) still works. On a scratch
# instance (scripts/release/e2e_update.sh: no model is called), as its own unit on
# 127.0.0.1:$PORT:
#
#   PORT=8940 E2E_DIR=~/somewhere scripts/release/rc_check.sh TAG [vPREVIOUS]
#                                 [--home-copy DIR [--loop-copy DIR]] [--dry-run]
#
# Settings: PORT (required; refused when something already answers there), E2E_DIR (required),
# KRANTO_UNIT (default kranto-rc-$PORT.service; a real install's unit is refused), REPO (where
# TAG is published, default public.toml's repo), PREV_REPO (where the previous release is, when
# it lives in another repository; default REPO), UV_TOOL_DIR and UV_TOOL_BIN_DIR (default under
# E2E_DIR), HOME (the scratch install's own, when the caller gives it one). --home-copy DIR starts
# the scratch install from a copy of the home DIR instead of an empty one, made by
# scripts/preview/copy_live.py's rules (no data/secrets, no .env); --loop-copy DIR copies that
# loop home too. --dry-run prints what it would run, and runs nothing.
#
#   0. a fresh HOME: the rc's own install.sh, then 'kranto setup --yes' with an answers file
#      (scripts/release/fresh_install.sh; a release before the wizard: 'kranto up');
#   1. install the previous release from its wheels (default: guards.py previous, the release
#      before it on its line; the gate and hotfix.sh name it), in its own shape;
#   2. kranto update to the rc: done, the rc answers, the old server stopped on SIGTERM;
#   3. kranto update --rollback: the previous release answers again;
#   4. kranto update to the rc again: done, the rc answers;
#   5. kranto doctor --routes: every page the rc serves, read once on the scratch data, answers
#      below 500 (the post-update self-check);
#   6. the same on the odd installs (scripts/dev/odd_walk.sh,): homes holding
#      every odd value the rc's writers store (odd, empty, projects), each served by the rc on
#      127.0.0.1:$ODD_PORT (default PORT+1);
#   7. no request storm: signed in on the scratch instance, Home and three pages in a headless
#      browser, every write refused; no address asked more than 20 times in 30 s
#      (storm_walk.py; Playwright's python from $PW_PYTHON).
#
# Each step prints PASS or FAIL and its log; the scratch instance is removed at the end, pass or
# fail. Exit 0 when all eight pass, 1 otherwise. Needs gh, uv, curl and a systemd user manager.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ARGS=() HOME_COPY="" LOOP_COPY="" DRY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --home-copy) HOME_COPY="${2:?--home-copy needs a folder}"; shift 2 ;;
    --loop-copy) LOOP_COPY="${2:?--loop-copy needs a folder}"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -*) echo "rc_check: unknown option $1" >&2; exit 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done
RC="${ARGS[0]:-}"
[ -n "$RC" ] || { echo "usage: rc_check.sh TAG [vPREVIOUS] [--home-copy DIR] [--dry-run]" >&2; exit 2; }
[[ "$RC" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc[0-9]+|-dev[0-9]+)?$ ]] || {
  echo "rc_check: $RC is not a release tag (vX.Y.Z, vX.Y.0-devN)" >&2; exit 2; }
: "${E2E_DIR:?set E2E_DIR to a scratch folder}" "${PORT:?set PORT (served on 127.0.0.1)}"
[[ "$PORT" =~ ^[0-9]+$ ]] || { echo "rc_check: PORT is a number, not '$PORT'" >&2; exit 2; }
if [ -n "$HOME_COPY" ] && [ ! -d "$HOME_COPY" ]; then
  echo "rc_check: --home-copy $HOME_COPY is not a folder" >&2; exit 2
fi
REPO="${REPO:-$(python3 "$HERE/names.py" repo)}"
PREV_REPO="${PREV_REPO:-$REPO}"
# never a real install's unit: the scratch instance's own (its stores get its name too)
export KRANTO_UNIT="${KRANTO_UNIT:-kranto-rc-$PORT.service}"
while read -r u; do
  [ "$KRANTO_UNIT" != "$u" ] || {
    echo "rc_check: KRANTO_UNIT=$KRANTO_UNIT is a real install's unit; name a scratch one" >&2
    exit 2; }
done < <(python3 "$HERE/names.py" units)
export UV_TOOL_DIR="${UV_TOOL_DIR:-$E2E_DIR/uv-tools}" UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-$E2E_DIR/bin}"
# the release before it on its line, by tag (a held stable is a GitHub prerelease until it is
# released): for a nightly, the newest nightly before it, else the newest stable; for a stable
# tag, the newest stable before it
PREV="${ARGS[1]:-}"
if [ -z "$PREV" ] && [ -z "$DRY" ]; then
  PREV="$(gh release list -R "$PREV_REPO" --exclude-drafts -L 100 --json tagName -q '.[].tagName' \
    | python3 "$HERE/guards.py" previous "$RC")"
fi
[ -n "$PREV" ] || { echo "rc_check: no release before $RC to update from; name it" >&2; exit 2; }
pep440() { local v="${1#v}"; v="${v/-rc/rc}"; echo "${v/-dev/.dev}"; }
RC_V="$(pep440 "$RC")" PREV_V="$(pep440 "$PREV")"
# the scratch install's channel: rc, which a release from before the nightly line accepts and a
# newer one reads as nightly (a 0.5.x previous would refuse the word nightly at start)
export E2E_DIR PORT REPO PREV_REPO CHANNEL=rc HOME_COPY LOOP_COPY
E2E="$HERE/e2e_update.sh"
STATE="$E2E_DIR/kb/update/state.json"
[ -n "$HOME_COPY" ] && STATE="$E2E_DIR/copy/home/update/state.json"
echo "rc_check: $PREV ($PREV_REPO) -> $RC ($REPO) on 127.0.0.1:$PORT ($KRANTO_UNIT), home" \
     "${HOME_COPY:+a copy of $HOME_COPY}${HOME_COPY:-empty}, tools $UV_TOOL_DIR, logs in $E2E_DIR"
if [ -n "$DRY" ]; then
  echo "dry run: would run, in order:"
  echo "  e2e_update.sh setup"
  echo "  fresh_install.sh $RC $E2E_DIR/fresh"
  echo "  FROM_TAG=$PREV e2e_update.sh install        (expects $PREV_V)"
  echo "  TO=$RC e2e_update.sh update                 (expects $RC_V)"
  echo "  e2e_update.sh rollback                      (expects $PREV_V)"
  echo "  TO=$RC e2e_update.sh update                 (expects $RC_V)"
  echo "  kranto doctor --routes --port $PORT; odd_walk.sh ${ODD_PORT:-$((PORT + 1))}; storm_walk.py"
  echo "  e2e_update.sh teardown"
  exit 0
fi
if curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/status"; then
  echo "rc_check: something already answers on 127.0.0.1:$PORT; choose a free PORT" >&2; exit 2
fi
mkdir -p "$E2E_DIR"
DIST_NAME="$(python3 "$HERE/names.py" dist)" ALIAS="$(python3 "$HERE/names.py" alias)"
kr() {
  if [ -x "$UV_TOOL_BIN_DIR/$DIST_NAME" ]; then "$UV_TOOL_BIN_DIR/$DIST_NAME" "$@"
  else "$UV_TOOL_BIN_DIR/$ALIAS" "$@"; fi
}

trap 'bash "$E2E" teardown > "$E2E_DIR/teardown.log" 2>&1 || true' EXIT
bash "$E2E" setup > "$E2E_DIR/setup.log" 2>&1

failed=0
say() { if [ "$1" = PASS ]; then echo "PASS $2"; else echo "FAIL $2: $3 (see $E2E_DIR/$4.log)"; failed=1; fi; }
# the installed command answers V (its first line's second word: "kranto 0.7.0", and a release
# made before the rename says its own name first), and so does the server
runs() { [ "$(kr --version 2>/dev/null | head -n 1 | awk '{print $2}')" = "$1" ] \
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

fresh() { REPO="$REPO" bash "$HERE/fresh_install.sh" "$RC" "$E2E_DIR/fresh"; }
step "0. a fresh HOME: install.sh, then kranto setup --yes" fresh/install fresh || true
FROM_TAG="$PREV" bash "$E2E" install > "$E2E_DIR/install.log" 2>&1 || true
step "1. install $PREV" install runs "$PREV_V" || exit 1
TO="$RC" bash "$E2E" update > "$E2E_DIR/update.log" 2>&1 || true
step "2. update to $RC" update on_rc || true
bash "$E2E" rollback > "$E2E_DIR/rollback.log" 2>&1 || true
step "3. roll back to $PREV" rollback runs "$PREV_V" || true
TO="$RC" bash "$E2E" update > "$E2E_DIR/update-again.log" 2>&1 || true
step "4. update to $RC again" update-again on_rc || true
# the post-update self-check, on the scratch data: every
# page the rc serves answers below 500 (an rc from before it has no --routes: not run)
routes() { if kr doctor --help 2>/dev/null | grep -q -- '--routes'; then
  kr doctor --routes --port "$PORT"; else echo "this rc has no doctor --routes"; fi; }
step "5. every page of $RC on the scratch data (doctor --routes)" routes routes \
  || true
# the odd installs: every page of the rc on data no one install holds
odd() { ODD_DIR="$E2E_DIR/odd" bash "$HERE/../dev/odd_walk.sh" \
  "${ODD_PORT:-$((PORT + 1))}" "$(command -v "$UV_TOOL_BIN_DIR/$DIST_NAME" || echo "$UV_TOOL_BIN_DIR/$ALIAS")"; }
step "6. every page of $RC on the odd installs (scripts/dev/odd_walk.sh)" odd/odd odd || true
# a request storm: v0.6.0-dev3's console posted console/open without end and passed
# every step above. Signed in on the scratch instance (its own unit's one-time link, never
# logged), Home and three pages in a headless browser, every write refused; any address asked
# more than 20 times in 30 s fails. Playwright's python: $PW_PYTHON, else python3 when it has it.
storm() {
  local py="${PW_PYTHON:-python3}" link home="$E2E_DIR/kb"
  [ -n "$HOME_COPY" ] && home="$E2E_DIR/copy/home"
  "$py" -c 'import playwright' 2>/dev/null \
    || { echo "no Playwright in $py: set PW_PYTHON to a python with it and its Chromium"; return 1; }
  link="$(KRANTO_HOME="$home" kr open --no-browser 2>/dev/null | grep -o 'http://[^ ]*auth/open[^ ]*' | tail -1)"
  [ -n "$link" ] || { echo "open printed no sign-in link"; return 1; }
  STORM_LINK="$link" "$py" "$HERE/storm_walk.py" "http://127.0.0.1:$PORT" \
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
