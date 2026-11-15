#!/usr/bin/env bash
# The update's end-to-end test (section 11): a real release, a scratch instance,
# a rollback, a forced failure and the interrupt path, on this machine's own user manager,
# beside the real kranto.service and never touching it.
#
#   E2E_DIR=~/somewhere scripts/release/e2e_update.sh STEP
#
# STEP, in order: live (record the real service), setup, install, check, update, rollback,
# fail, interrupt, teardown, live (again: compare). Each prints its evidence.
#
# The scratch instance: $KRANTO_UNIT (kranto-test.service) on 127.0.0.1:$PORT (8766), its home a
# copy of $SRC_HOME without .env, data/secrets, *.jsonl, backups/ or telemetry/ (the database
# through SQLite's backup API), its usage reports off, a fresh loop home whose loop.yaml builds
# in a scratch task folder with maintenance and publishing off, its own uv tool dir and bin dir. No model is called: every
# the server job is off, the API key's variable is one nobody sets, nothing is sent to build,
# and the one "build" (interrupt) is a sleeper run by build.command.
set -euo pipefail

: "${E2E_DIR:?set E2E_DIR to a scratch folder}"
PORT="${PORT:-8766}"
SRC_HOME="${SRC_HOME:-$HOME/kranto-kb}"
CHANNEL="${CHANNEL:-rc}"
TO_ARGS=()                     # TO=v0.2.0-rc2: update to that tag instead of what is offered
[ -n "${TO:-}" ] && TO_ARGS=(--to "$TO")
SPEC="${MAIN_SPEC:-git+https://github.com/iddv/kranto}"
export KRANTO_UNIT="${KRANTO_UNIT:-kranto-test.service}"
NAME="${KRANTO_UNIT%.service}"
export KRANTO_HOME="$E2E_DIR/kb"
export UV_TOOL_DIR="$E2E_DIR/uv-tools" UV_TOOL_BIN_DIR="$E2E_DIR/bin"
KRANTO="$UV_TOOL_BIN_DIR/kranto"
PY="$UV_TOOL_DIR/kranto/bin/python"
LOOP="$KRANTO_HOME/loop"
say() { printf '\n== %s\n' "$*"; }
api() { curl -sf "http://127.0.0.1:$PORT$1"; }
listen() { ss -ltnH "( sport = :$1 )" || true; }

case "${1:?step}" in
live)
  say "the real service (must not change)"
  mkdir -p "$E2E_DIR"
  {
    echo "kranto.service: $(systemctl --user is-active kranto.service || true)"
    echo "MainPID: $(systemctl --user show -p MainPID --value kranto.service)"
    echo "pointer: $(cat "$HOME/.config/kranto/home" 2>/dev/null || echo none)"
    echo "8765: $(listen 8765)"
    echo "unit sha: $(sha256sum "$HOME/.config/systemd/user/kranto.service" | cut -c1-16)"
  } | tee "$E2E_DIR/live-$(date -u +%H%M%S).txt"
  ;;

setup)
  say "scratch home from $SRC_HOME"
  mkdir -p "$E2E_DIR" "$LOOP" "$E2E_DIR/tasks"
  rsync -a --exclude .env --exclude 'data/secrets' --exclude '*.jsonl' --exclude 'backups/' \
    --exclude 'update/' --exclude 'data/*.db' --exclude 'data/*.db-*' --exclude '*.lock' \
    --exclude 'telemetry/' \
    "$SRC_HOME/" "$KRANTO_HOME/"
  python3 - "$SRC_HOME/data/kranto.db" "$KRANTO_HOME/data/kranto.db" <<'PY'
import sqlite3, sys
s = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True); d = sqlite3.connect(sys.argv[2])
s.backup(d); print("kranto.db copy:", d.execute("pragma integrity_check").fetchone()[0])
d.close(); s.close()
PY
  python3 - "$KRANTO_HOME" "$LOOP" "$E2E_DIR/tasks" "$PORT" "$CHANNEL" <<'PY'
import re, sys, yaml
from pathlib import Path
home, loop, tasks, port, channel = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
cfg = next(p for p in (home / "kranto.yaml", home / "kranto.yaml") if p.exists())
data = yaml.safe_load(cfg.read_text()) or {}
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
cfg.write_text("# e2e scratch copy\n" + yaml.safe_dump(data, sort_keys=False))
(loop / "loop.yaml").write_text(yaml.safe_dump({
    "tasks_dir": tasks, "concurrency": 1, "intake": {"auto": {"mode": "manual"}},
    "kranto": {"url": f"http://127.0.0.1:{port}"},
    "feed": {"ui_url": f"http://127.0.0.1:{port}/brb/"},
    "maintain": {"enabled": False}, "publish": {"enabled": False},
    "build": {"harness": "fake"}}, sort_keys=False))
print("wrote", cfg, "and", loop / "loop.yaml")
PY
  ls -la "$KRANTO_HOME" "$KRANTO_HOME/data"
  ;;

install)
  mkdir -p "$E2E_DIR"
  if [ -n "${FROM_TAG:-}" ]; then
    # FROM_TAG=v0.3.56: that release's wheels, as the setup guide installs them. A kranto built
    # from git has no web page since the page's (the release builds it), so the scratch
    # instance the update starts from is a release.
    say "install $FROM_TAG from its release's wheels into the scratch tool dir, then kranto up on $PORT"
    rel="$E2E_DIR/from-$FROM_TAG"
    gh release download "$FROM_TAG" -R iddv/kranto -p '*.whl' -p SHA256SUMS -D "$rel" --clobber
    (cd "$rel" && sha256sum -c SHA256SUMS)
    uv tool install --force --python 3.12 --with-executables-from kranto,kranto.page \
      --with "$rel"/kranto-*.whl --with "$rel"/kranto.page-*.whl "$rel"/kranto-*.whl 2>&1 | tail -n 5
  else
  say "install main from git into the scratch tool dir, then kranto up on $PORT"
  # MAIN_REF=v0.2.0-rc1: main as it was at that tag in both repos. The meta-package depends on
  # both by git URL with no ref, so the pins go in an overrides file (as the helper does).
  at="${MAIN_REF:+@$MAIN_REF}"
  printf '%s\n' "kranto[connections,notify] @ git+https://github.com/iddv/kranto$at" \
    "kranto.page @ git+https://github.com/iddv/kranto$at" > "$E2E_DIR/main-overrides.txt"
  uv tool install --force --python 3.12 --with-executables-from kranto,kranto.page \
    --overrides "$E2E_DIR/main-overrides.txt" \
    "kranto @ $SPEC$at#subdirectory=packages/kranto" 2>&1 | tail -n 5
  fi
  "$KRANTO" --version
  "$PY" - "$KRANTO_HOME" <<'PY'
import sys
from pathlib import Path
from kranto.store import Store
s = Store.open(Path(sys.argv[1]) / "data" / "kranto.db"); s.set_setting("setup.done", "e2e"); s.close()
PY
  "$KRANTO" up --port "$PORT" --no-browser
  systemctl --user cat "$KRANTO_UNIT" | grep -E '^(Environment|ExecStart)'
  listen "$PORT"
  api /api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("status", d["version"], d["update"])'
  ;;

check)
  say "kranto update --check (exit 10: an update is available)"
  set +e; "$KRANTO" update --check; code=$?; set -e
  echo "exit $code"
  ls -la "$KRANTO_HOME/update/releases/"*/
  (cd "$KRANTO_HOME"/update/releases/v*/ && sha256sum -c SHA256SUMS)
  ;;

update)
  say "kranto update --yes"
  t0=$(date +%s)
  set +e; "$KRANTO" update "${TO_ARGS[@]}" --yes; code=$?; set -e
  echo "exit $code after $(( $(date +%s) - t0 )) s"
  "$KRANTO" --version
  journalctl --user -u "$NAME-update" --no-pager -o cat | grep -E 'state ' || true
  cat "$KRANTO_HOME/update/previous.json"
  for b in "$KRANTO_HOME"/backups/update-*/; do echo "$b"; ls "$b"; done
  api /api/update | python3 -c 'import json,sys; d=json.load(sys.stdin); print("apply", d["apply"]["state"], "installed", d["installed"]["version"])'
  "$KRANTO" status || true
  ;;

rollback)
  say "kranto update --rollback --yes"
  set +e; "$KRANTO" update --rollback --yes; code=$?; set -e
  echo "exit $code"
  "$KRANTO" --version
  "$KRANTO" doctor 2>/dev/null | grep -E 'migrations' || true
  api /api/status | python3 -c 'import json,sys; d=json.load(sys.stdin); print("status", d["version"], "lane", d["lanes"].get("loop", {}).get("state"))'
  ;;

fail)
  say "KRANTO_UPDATE_FAIL=verify kranto update --yes"
  set +e; KRANTO_UPDATE_FAIL=verify "$KRANTO" update "${TO_ARGS[@]}" --yes; code=$?; set -e
  echo "exit $code (3: rolled back)"
  "$KRANTO" --version
  "$KRANTO" status | grep -E '^update' || true
  api /api/update | python3 -c 'import json,sys; d=json.load(sys.stdin); a=d["apply"]; print("apply", a["state"], a.get("reason"))'
  systemctl --user is-active "$KRANTO_UNIT"
  ;;

interrupt)
  say "a running build: update waits, cancel lets go, --when now stops it and resumes it"
  "$PY" - "$LOOP" "$E2E_DIR/tasks" "$PY" <<'PY'
import sys, yaml
from pathlib import Path
from kranto.page.loop.ledger import Ledger
loop, tasks, py = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
cfg = yaml.safe_load((loop / "loop.yaml").read_text())
cfg["build"]["command"] = [py, "-c", "import time; time.sleep(900)"]
(loop / "loop.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False))
task = tasks / "e2e-sleeper"; task.mkdir(parents=True, exist_ok=True)
(task / "spec.md").write_text("# e2e sleeper\nA stand-in build: sleeps; no model.\n")
led = Ledger(loop / "loop.db")
idea, _ = led.add("e2e sleeper build", "e2e", title="E2E sleeper", state="queued")
led.update(idea["id"], task_dir=str(task), note="queued by the e2e")
print("queued", idea["id"])
PY
  for _ in $(seq 1 30); do
    n=$(api /brb/api/header | python3 -c 'import json,sys; print(json.load(sys.stdin)["running"])')
    [ "$n" -ge 1 ] && break; sleep 2
  done
  echo "builds running: $n"; pgrep -af "$PY -c import time" || true
  "$KRANTO" update "${TO_ARGS[@]}" --yes > "$E2E_DIR/interrupt-wait.log" 2>&1 &
  upd=$!
  for _ in $(seq 1 30); do
    st=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("state"))' "$KRANTO_HOME/update/state.json" 2>/dev/null || true)
    [ "$st" = draining ] && break; sleep 2
  done
  sleep 6
  python3 -c 'import json,sys; s=json.load(open(sys.argv[1])); print("state", s["state"], "|", s.get("detail"))' "$KRANTO_HOME/update/state.json"
  "$KRANTO" update --cancel
  wait $upd || echo "kranto update exit $? (5: cancelled)"
  cat "$E2E_DIR/interrupt-wait.log"
  api /api/status | python3 -c 'import json,sys; print("hold after cancel:", json.load(sys.stdin)["hold"])'
  say "--when now"
  set +e; "$KRANTO" update "${TO_ARGS[@]}" --when now --yes; code=$?; set -e
  echo "exit $code"
  "$KRANTO" --version
  for _ in $(seq 1 45); do
    n=$(api /brb/api/header | python3 -c 'import json,sys; print(json.load(sys.stdin)["running"])' || echo 0)
    [ "$n" -ge 1 ] && break; sleep 2
  done
  echo "builds running after the restart: $n"
  sleep 35                       # one loop tick: the stopped round is started again
  pgrep -af "$PY -c import time" || true
  "$PY" - "$LOOP" <<'PY'
import sys
from pathlib import Path
from kranto.page.loop.ledger import Ledger
led = Ledger(Path(sys.argv[1]) / "loop.db")
for i in led.all():
    if i["title"] == "E2E sleeper":
        print("ledger:", i["state"], "pid", (i.get("build") or {}).get("pid"))
        for h in led.history(i["id"]):
            print(" ", h.get("state"), "|", h.get("note"))
PY
  ;;

teardown)
  say "teardown"
  pkill -f "$PY -c import time" || true
  systemctl --user disable --now "$KRANTO_UNIT" || true
  rm -f "$HOME/.config/systemd/user/$KRANTO_UNIT"
  rm -rf "$HOME/.config/systemd/user/$KRANTO_UNIT.d"
  systemctl --user daemon-reload
  systemctl --user reset-failed "$KRANTO_UNIT" "$NAME-update" 2>/dev/null || true
  rm -f "$HOME/.config/kranto/home.$NAME"
  rm -rf "$UV_TOOL_DIR" "$UV_TOOL_BIN_DIR" "$KRANTO_HOME" "$E2E_DIR/tasks"
  listen "$PORT"
  echo "scratch removed; left: $(ls "$E2E_DIR")"
  ;;

*) echo "unknown step $1" >&2; exit 2 ;;
esac
