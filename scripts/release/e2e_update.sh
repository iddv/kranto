#!/usr/bin/env bash
# The update's end-to-end test (section 11): a real release, a scratch instance,
# a rollback and a forced failure, on this machine's own user manager,
# beside the real install and never touching it.
#
#   E2E_DIR=~/somewhere scripts/release/e2e_update.sh STEP
#
# STEP, in order: live (record the real service), setup, install, check, update, rollback,
# fail, teardown, live (again: compare). Each prints its evidence.
#
# The scratch instance: $KRANTO_UNIT (kranto-test.service; never a real install's unit) on
# 127.0.0.1:$PORT (8766), its own uv tool dir and bin dir ($UV_TOOL_DIR, $UV_TOOL_BIN_DIR, under
# E2E_DIR unless set). Its home: an empty one (E2E_DIR/kb), or with HOME_COPY=<a home> a copy
# made by scripts/preview/copy_live.py's rules (no .env, no data/secrets, the databases through
# SQLite's backup API, its folders rewritten to the copy's; LOOP_COPY=<a loop home> copies that
# too). Either way its usage reports are off, a fresh loop.yaml builds in a scratch task folder
# with maintenance and publishing off. No model is called: every server job is off, the API
# key's variable is one nobody sets.
#
# install with FROM_TAG=vX.Y.Z installs that release's wheels from $PREV_REPO (default
# public.toml's repo): the final shape (one wheel) as install.sh does, the old shape (three
# wheels, a release made before the rename or the crossing) as the old update helper does. An
# old release reads the old names of KRANTO_UNIT and KRANTO_HOME: they are set too.
set -euo pipefail

: "${E2E_DIR:?set E2E_DIR to a scratch folder}"
HERE="$(cd "$(dirname "$0")" && pwd)"
PORT="${PORT:-8766}"
CHANNEL="${CHANNEL:-rc}"
TO_ARGS=()                     # TO=v0.2.0-rc2: update to that tag instead of what is offered
[ -n "${TO:-}" ] && TO_ARGS=(--to "$TO")
REPO="${REPO:-$(python3 "$HERE/names.py" repo)}"
PREV_REPO="${PREV_REPO:-$REPO}"
SPEC="${MAIN_SPEC:-git+https://github.com/$REPO}"
DIST_NAME="$(python3 "$HERE/names.py" dist)"
ALIAS="$(python3 "$HERE/names.py" alias)"
mapfile -t COMPAT < <(python3 "$HERE/names.py" compat)        # meta, server, page
mapfile -t UNITS < <(python3 "$HERE/names.py" units)
mapfile -t CONFIG_DIRS < <(python3 "$HERE/names.py" config-dirs)
mapfile -t HOME_FILES < <(python3 "$HERE/names.py" home-files)
mapfile -t DB_FILES < <(python3 "$HERE/names.py" db-files)
export KRANTO_UNIT="${KRANTO_UNIT:-kranto-test.service}"
for u in "${UNITS[@]}"; do
  [ "$KRANTO_UNIT" != "$u" ] || {
    echo "e2e: KRANTO_UNIT=$KRANTO_UNIT is a real install's unit; name a scratch one" >&2; exit 2; }
done
NAME="${KRANTO_UNIT%.service}"
if [ -n "${HOME_COPY:-}" ]; then
  export KRANTO_HOME="$E2E_DIR/copy/home"
  LOOP="$E2E_DIR/copy/loop" TASKS="$E2E_DIR/copy/tasks"
else
  export KRANTO_HOME="$E2E_DIR/kb"
  LOOP="$KRANTO_HOME/loop" TASKS="$E2E_DIR/tasks"
fi
export UV_TOOL_DIR="${UV_TOOL_DIR:-$E2E_DIR/uv-tools}" UV_TOOL_BIN_DIR="${UV_TOOL_BIN_DIR:-$E2E_DIR/bin}"
# an install made before the rename reads the old names of the unit's and the home's variables
for var in KRANTO_UNIT KRANTO_HOME; do
  while read -r old; do [ -n "$old" ] && export "$old=${!var}"; done \
    < <(python3 "$HERE/names.py" old-env "$var")
done
# the command: the product's when the scratch tool has it, else its old name (an old release)
kr() {
  if [ -x "$UV_TOOL_BIN_DIR/$DIST_NAME" ]; then "$UV_TOOL_BIN_DIR/$DIST_NAME" "$@"
  else "$UV_TOOL_BIN_DIR/$ALIAS" "$@"; fi
}
# the python of the tool the command lives in
tool_py() {
  local exe="$UV_TOOL_BIN_DIR/$DIST_NAME"
  [ -x "$exe" ] || exe="$UV_TOOL_BIN_DIR/$ALIAS"
  echo "$(dirname "$(readlink -f "$exe")")/python"
}
# an empty home holds only the values setup wrote, and 'kranto up' writes the release's own
# settings only where no settings file exists, so a one-wheel release refused to start on it
# ("llm.models is required"): put the installed release's own new-home settings under them
complete_settings() {
  "$(tool_py)" - "$KRANTO_HOME" "$PORT" "${HOME_FILES[@]}" <<'PY'
import sys
from pathlib import Path

import yaml
from kranto import launcher

home, port, names = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3:]
cfg = next((home / n for n in names if (home / n).exists()), None)
ours = (yaml.safe_load(cfg.read_text()) if cfg else None) or {}
if cfg is None or "models" in (ours.get("llm") or {}):
    sys.exit(0)                                      # a copied home has its own settings


def under(base: dict, top: dict) -> dict:
    for k, v in top.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            under(base[k], v)
        else:
            base[k] = v
    return base


base = yaml.safe_load(launcher.home_config_text(home, port, Path.home())) or {}
cfg.write_text("# e2e scratch home\n" + yaml.safe_dump(under(base, ours), sort_keys=False))
print("the release's own settings under e2e's:", cfg)
PY
}
say() { printf '\n== %s\n' "$*"; }
api() { curl -sf "http://127.0.0.1:$PORT$1"; }
listen() { ss -ltnH "( sport = :$1 )" || true; }

case "${1:?step}" in
live)
  say "the real service (must not change)"
  mkdir -p "$E2E_DIR"
  {
    for u in "${UNITS[@]}"; do
      echo "$u: $(systemctl --user is-active "$u" || true)"
      echo "MainPID: $(systemctl --user show -p MainPID --value "$u")"
      echo "unit sha: $(sha256sum "$HOME/.config/systemd/user/$u" 2>/dev/null | cut -c1-16)"
    done
    for d in "${CONFIG_DIRS[@]}"; do
      echo "pointer $d: $(cat "$HOME/.config/$d/home" 2>/dev/null || echo none)"
    done
  } | tee "$E2E_DIR/live-$(date -u +%H%M%S).txt"
  ;;

setup)
  mkdir -p "$E2E_DIR" "$LOOP" "$TASKS"
  if [ -n "${HOME_COPY:-}" ]; then
    say "scratch home: a copy of $HOME_COPY (scripts/preview/copy_live.py's rules)"
    src_loop="${LOOP_COPY:-$E2E_DIR/empty-loop}"
    mkdir -p "$E2E_DIR/empty-loop"
    "${COPY_PY:-python3}" "$HERE/../preview/copy_live.py" --src-home "$HOME_COPY" \
      --src-loop "$src_loop" --src-tasks "$E2E_DIR/empty-tasks" --root "$E2E_DIR/copy" \
      --port "$PORT"
  else
    say "scratch home: empty ($KRANTO_HOME)"
    mkdir -p "$KRANTO_HOME"
  fi
  python3 - "$KRANTO_HOME" "$LOOP" "$TASKS" "$PORT" "$CHANNEL" "${HOME_FILES[@]}" <<'PY'
import sys, yaml
from pathlib import Path
home, loop, tasks, port, channel = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
names = sys.argv[6:]
# the home's settings file (any of its names); an empty home gets the product's (install renames
# it for a release made before the rename, which reads only the old names)
cfg = next((home / n for n in names if (home / n).exists()), home / names[0])
data = (yaml.safe_load(cfg.read_text()) if cfg.exists() else None) or {}
# the model key is read from an environment variable nobody sets, so no call can be paid for
unset_var = "_".join(("KRANTO", "E2E", "UNSET"))
data.setdefault("llm", {})["api_" + "key_env"] = unset_var
for sec in ("ingest", "map", "ideas", "retention"):
    data.setdefault(sec, {})["every_hours"] = 0
data.setdefault("deep_dive", {})["enabled"] = False
n = data.setdefault("notify", {}); n["urls"] = []; n["heartbeat_every_hours"] = 0
n["base_url"] = f"http://127.0.0.1:{port}"
data["brb"] = {"enabled": True, "loop_home": str(loop), "root": tasks}
data["update"] = {"channel": channel, "check_every_hours": 24, "download": True, "auto": "off"}
# the copy never reports as the home it came from (telemetry/, its install id, is not copied)
data["telemetry"] = {"mode": "off"}
# copy_live.py marks its copy as the preview, which is never updated; this copy must be
data.pop("preview", None)
cfg.write_text("# e2e scratch home\n" + yaml.safe_dump(data, sort_keys=False))
(loop / "loop.yaml").write_text(yaml.safe_dump({
    "tasks_dir": tasks, "concurrency": 1, "intake": {"auto": {"mode": "manual"}},
    "kranto": {"url": f"http://127.0.0.1:{port}"},
    "feed": {"ui_url": f"http://127.0.0.1:{port}/brb/"},
    "maintain": {"enabled": False}, "publish": {"enabled": False},
    "build": {"harness": "fake"}}, sort_keys=False))
print("wrote", cfg, "and", loop / "loop.yaml")
PY
  ls -la "$KRANTO_HOME"
  ;;

install)
  mkdir -p "$E2E_DIR"
  if [ -n "${FROM_TAG:-}" ]; then
    # FROM_TAG=v0.3.56: that release's wheels, installed the way its own installs are. A build
    # from git has no web page (the release builds it), so the scratch instance the update
    # starts from is a release.
    say "install $FROM_TAG from $PREV_REPO's release into the scratch tool dir, then up on $PORT"
    rel="$E2E_DIR/from-$FROM_TAG"
    gh release download "$FROM_TAG" -R "$PREV_REPO" -p '*.whl' -p SHA256SUMS -D "$rel" --clobber
    (cd "$rel" && sha256sum -c SHA256SUMS)
    if compgen -G "$rel/$DIST_NAME-*.whl" > /dev/null; then          # the final shape
      whl="$(ls "$rel/$DIST_NAME"-*.whl)"
      uv tool install --force --python 3.12 \
        "$DIST_NAME[connections,notify] @ file://$whl" 2>&1 | tail -n 5
      complete_settings
    else                                                              # the old shape
      # a release made before the rename reads its settings file by an old name only; every
      # later one reads the old names too
      if [ -f "$KRANTO_HOME/${HOME_FILES[0]}" ] && [ ! -e "$KRANTO_HOME/${HOME_FILES[1]}" ]; then
        mv "$KRANTO_HOME/${HOME_FILES[0]}" "$KRANTO_HOME/${HOME_FILES[1]}"
      fi
      uv tool install --force --python 3.12 \
        --with-executables-from "${COMPAT[1]},${COMPAT[2]}" \
        --with "$rel/${COMPAT[1]}"-*.whl --with "$rel/${COMPAT[2]}"-*.whl \
        "$rel/${COMPAT[0]}"-*.whl 2>&1 | tail -n 5
    fi
  else
    say "install main from git into the scratch tool dir, then up on $PORT"
    # MAIN_REF=v0.7.0-dev2: main as it was at that tag
    at="${MAIN_REF:+@$MAIN_REF}"
    uv tool install --force --python 3.12 \
      "$DIST_NAME[connections,notify] @ $SPEC$at" 2>&1 | tail -n 5
    complete_settings
  fi
  kr --version
  # the library marked set up (the welcome is not what is being checked), with the package the
  # installed release has: the product's, or the server's old name
  "$(tool_py)" - "$KRANTO_HOME" "$DIST_NAME" "${COMPAT[1]}" "${DB_FILES[@]}" <<'PY'
import importlib, sys
from pathlib import Path
home, pkgs, dbs = Path(sys.argv[1]), sys.argv[2:4], sys.argv[4:]
for i, pkg in enumerate(pkgs):
    try:
        Store = importlib.import_module(pkg + ".store").Store
        break
    except ImportError:
        continue
else:
    sys.exit(f"neither {pkgs} has a store")
data = home / "data"
db = next((data / n for n in dbs if (data / n).exists()), data / dbs[i])
s = Store.open(db); s.set_setting("setup.done", "e2e"); s.close()
print("set up:", db)
PY
  kr up --port "$PORT" --no-browser
  systemctl --user cat "$KRANTO_UNIT" | grep -E '^(Environment|ExecStart)'
  listen "$PORT"
  api /api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("status", d["version"], d.get("update"))'
  ;;

check)
  say "update --check (exit 10: an update is available)"
  set +e; kr update --check; code=$?; set -e
  echo "exit $code"
  ls -la "$KRANTO_HOME/update/releases/"*/
  (cd "$KRANTO_HOME"/update/releases/v*/ && sha256sum -c SHA256SUMS)
  ;;

update)
  say "update --yes"
  t0=$(date +%s)
  set +e; kr update "${TO_ARGS[@]}" --yes; code=$?; set -e
  echo "exit $code after $(( $(date +%s) - t0 )) s"
  kr --version
  journalctl --user -u "$NAME-update" --no-pager -o cat | grep -E 'state ' || true
  cat "$KRANTO_HOME/update/previous.json"
  for b in "$KRANTO_HOME"/backups/update-*/; do echo "$b"; ls "$b"; done
  api /api/update | python3 -c 'import json,sys; d=json.load(sys.stdin); print("apply", d["apply"]["state"], "installed", d["installed"]["version"])'
  kr status || true
  ;;

rollback)
  say "update --rollback --yes"
  set +e; kr update --rollback --yes; code=$?; set -e
  echo "exit $code"
  kr --version
  kr doctor 2>/dev/null | grep -E 'migrations' || true
  api /api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("status", d["version"], "lane", d["lanes"].get("loop", {}).get("state"))'
  ;;

fail)
  say "KRANTO_UPDATE_FAIL=verify update --yes"
  set +e; KRANTO_UPDATE_FAIL=verify kr update "${TO_ARGS[@]}" --yes; code=$?; set -e
  echo "exit $code (3: rolled back)"
  kr --version
  kr status | grep -E '^update' || true
  api /api/update | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d["apply"]; print("apply", a["state"], a.get("reason"))'
  systemctl --user is-active "$KRANTO_UNIT"
  ;;

teardown)
  say "teardown"
  pkill -f "$UV_TOOL_DIR/.*-c import time" || true
  systemctl --user disable --now "$KRANTO_UNIT" || true
  rm -f "$HOME/.config/systemd/user/$KRANTO_UNIT"
  rm -rf "$HOME/.config/systemd/user/$KRANTO_UNIT.d"
  systemctl --user daemon-reload
  systemctl --user reset-failed "$KRANTO_UNIT" "$NAME-update" 2>/dev/null || true
  for d in "${CONFIG_DIRS[@]}"; do rm -f "$HOME/.config/$d/home.$NAME"; done
  rm -rf "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" "$KRANTO_HOME" "$TASKS" "$E2E_DIR/copy"
  listen "$PORT"
  echo "scratch removed; left: $(ls "$E2E_DIR")"
  ;;

*) echo "unknown step $1" >&2; exit 2 ;;
esac
