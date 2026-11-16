#!/usr/bin/env bash
# Install a release's wheels the way an install does, into a throwaway tool dir, and start it.
#
#   VERSION=0.2.0 DIST=... WORK=... [PORT=8799] [SHAPE=final|compat] smoke.sh [setup]
#
# SHAPE=final (the default): the one wheel, as install.sh and the update helper install it
# (uv tool install "kranto[connections,notify,mcp] @ file://...whl"). SHAPE=compat: the three
# wheels of the crossing, the way the update helper of an install made before the rename installs
# them (the meta-package with --with each of the other two, under the old tool's name); both
# commands, the product's and its old name, must answer VERSION.
#
# setup: instead of 'kranto up', the non-interactive wizard on a bare HOME
# (WORK/setup/home, PATH = the tool's bin and /usr/bin:/bin only): 'kranto setup --yes
# --service foreground --watch later --github later' starts the server as its child;
# /api/status answers VERSION, GET /api/setup says needs_setup, 'kranto doctor' fails on nothing
# but the pieces a bare machine lacks (claude, gh, the model key) and says the model is missing
# (smoke_doctor.py: a FAIL on the key, or "none chosen yet"), SIGTERM stops the wizard and
# its server, a second run writes nothing, and nothing listens on PORT at the end.
#
# Checks: 'kranto --version' names VERSION; 'kranto up --foreground' on a new home in WORK
# answers /api/status with version VERSION and /brb/api/header 200 (the page's header, which an
# install made before the rename checks after its update) within 60 s, and the page at / links
# and serves the web UI's built module from the wheel. The server is
# bound to 127.0.0.1 and stopped at the end. HOME is WORK/home for the server, so nothing is
# written to the real ~/.config/kranto. No model is called: the new home has no key.
# Only PyPI is reached (third-party dependencies).
set -euo pipefail

: "${VERSION:?}" "${DIST:?}" "${WORK:?}"
PORT="${PORT:-8799}" SHAPE="${SHAPE:-final}"
mkdir -p "$WORK"
export UV_TOOL_DIR="$WORK/tools" UV_TOOL_BIN_DIR="$WORK/bin"
HERE="$(cd "$(dirname "$0")" && pwd)"
DIST_NAME="$(python3 "$HERE/names.py" dist)"

case "$SHAPE" in
  final)
    TOOL="$DIST_NAME"
    uv tool install --force --python 3.12 \
      "$DIST_NAME[connections,notify,mcp] @ file://$DIST/$DIST_NAME-$VERSION-py3-none-any.whl" ;;
  compat)
    mapfile -t compat < <(python3 "$HERE/names.py" compat)     # meta, server, page
    TOOL="${compat[0]}"
    uv tool install --force --python 3.12 --with-executables-from "${compat[1]},${compat[2]}" \
      --with "$DIST/${compat[1]}-$VERSION-py3-none-any.whl" \
      --with "$DIST/${compat[2]}-$VERSION-py3-none-any.whl" \
      "${compat[0]}[mcp] @ file://$DIST/${compat[0]}-$VERSION-py3-none-any.whl" ;;
  *) echo "smoke: SHAPE is final or compat, not '$SHAPE'" >&2; exit 2 ;;
esac
TOOL_PY="$WORK/tools/$TOOL/bin/python"

cmds=(kranto)
[ "$SHAPE" = compat ] && cmds+=("$(python3 "$HERE/names.py" alias)")
for c in "${cmds[@]}"; do
  got="$("$WORK/bin/$c" --version)"
  if [ "$got" != "kranto $VERSION" ]; then
    echo "smoke: $c --version says '$got', not 'kranto $VERSION'" >&2
    exit 1
  fi
  echo "ok: $c --version: $got"
done

if [ "${1:-}" = setup ]; then
  S="$WORK/setup"
  rm -rf "$S"
  mkdir -p "$S/home"
  # a command on a bare machine: this HOME, the tool's bin and the system's only (an array, not
  # a function: started with &, $! is then kranto itself, which SIGTERM must reach)
  bare=(env -i HOME="$S/home" PATH="$WORK/bin:/usr/bin:/bin" LANG="${LANG:-C.UTF-8}" TMPDIR="$S"
        NO_COLOR=1 UV_TOOL_DIR="$UV_TOOL_DIR" UV_TOOL_BIN_DIR="$UV_TOOL_BIN_DIR")
  listening() { curl -sf -o /dev/null "http://127.0.0.1:$PORT/api/status"; }
  if listening; then
    echo "smoke setup: 127.0.0.1:$PORT already answers; choose another PORT" >&2
    exit 1
  fi
  wizard_pid=""
  trap '[ -n "$wizard_pid" ] && kill "$wizard_pid" 2>/dev/null; wait 2>/dev/null || true' EXIT
  one_run() {   # $1: 1 or 2. The wizard, its server up, the checks, then SIGTERM.
    "${bare[@]}" "$WORK/bin/kranto" setup --yes --service foreground --watch later --github later \
      --port "$PORT" --no-browser --json > "$S/setup-$1.json" 2> "$S/setup-$1.log" &
    wizard_pid=$!
    up=""
    for _ in $(seq 1 90); do
      if body="$(curl -sf "http://127.0.0.1:$PORT/api/status")"; then up=1; break; fi
      kill -0 "$wizard_pid" 2>/dev/null || break
      sleep 1
    done
    if [ -z "$up" ]; then
      echo "smoke setup: run $1 did not start kranto on 127.0.0.1:$PORT within 90 s" >&2
      tail -n 30 "$S/setup-$1.log" >&2
      exit 1
    fi
    v="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
    [ "$v" = "$VERSION" ] || { echo "smoke setup: /api/status says $v, not $VERSION" >&2; exit 1; }
    if [ "$1" = 1 ]; then
      curl -sf "http://127.0.0.1:$PORT/api/setup" > "$S/api-setup.json"
      python3 - "$S/api-setup.json" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
if d.get("needs_setup") is not True:
    sys.exit(f"smoke setup: GET /api/setup says needs_setup {d.get('needs_setup')!r} on a new home")
print("ok: GET /api/setup says needs_setup on the new home")
PY
      set +e
      "${bare[@]}" "$WORK/bin/kranto" doctor > "$S/doctor.log" 2>&1
      code=$?
      set -e
      python3 "$HERE/smoke_doctor.py" "$S/doctor.log" "$code"
    fi
    for _ in $(seq 1 60); do     # its JSON is written once every section has run
      [ -s "$S/setup-$1.json" ] && break
      sleep 1
    done
    kill -TERM "$wizard_pid"
    for _ in $(seq 1 100); do kill -0 "$wizard_pid" 2>/dev/null || break; sleep 1; done
    if kill -0 "$wizard_pid" 2>/dev/null; then
      echo "smoke setup: the wizard did not stop on SIGTERM within 100 s" >&2
      exit 1
    fi
    wizard_pid=""
    sleep 1
    if listening; then
      echo "smoke setup: 127.0.0.1:$PORT still answers after the wizard stopped" >&2
      exit 1
    fi
  }
  one_run 1
  one_run 2
  python3 - "$S/setup-1.json" "$S/setup-2.json" <<'PY'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
for n, run in ((1, first), (2, second)):
    if run.get("exit") != 0 or not run.get("started") or not run.get("answering"):
        sys.exit(f"smoke setup: run {n} said exit {run.get('exit')}, started "
                 f"{run.get('started')}, answering {run.get('answering')}")
if not first.get("written"):
    sys.exit("smoke setup: the first kranto setup wrote nothing")
if second.get("written"):
    sys.exit(f"smoke setup: the second kranto setup wrote {second['written']}")
PY
  echo "ok: kranto setup --yes on a bare HOME served $VERSION on 127.0.0.1:$PORT, stopped on SIGTERM, and a second run changed nothing"
  exit 0
fi

mkdir -p "$WORK/home"
HOME="$WORK/home" KRANTO_HOME="$WORK/home/kranto" \
  "$WORK/bin/kranto" up --foreground --no-browser --port "$PORT" > "$WORK/serve.log" 2>&1 &
pid=$!
trap 'kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true' EXIT

ok=""
for _ in $(seq 1 60); do
  if body="$(curl -sf "http://127.0.0.1:$PORT/api/status")"; then
    v="$(printf '%s' "$body" | python3 -c 'import json,sys; print(json.load(sys.stdin)["version"])')"
    if [ "$v" = "$VERSION" ] && curl -sf -o /dev/null "http://127.0.0.1:$PORT/brb/api/header"; then
      ok=1
      break
    fi
  fi
  sleep 1
done
if [ -z "$ok" ]; then
  echo "smoke: the server did not answer as $VERSION with the page's header within 60 s" >&2
  tail -n 40 "$WORK/serve.log" >&2
  exit 1
fi
echo "ok: /api/status says $VERSION and /brb/api/header answers on 127.0.0.1:$PORT"

# The post-update self-check: every page the server serves, read once on
# this (new, empty) home, none answers 500. A release from before it has no --routes.
if "$WORK/bin/kranto" doctor --help 2>/dev/null | grep -q -- '--routes'; then
  if ! HOME="$WORK/home" KRANTO_HOME="$WORK/home/kranto" \
      "$WORK/bin/kranto" doctor --routes --port "$PORT" > "$WORK/routes.log" 2>&1; then
    echo "smoke: kranto doctor --routes failed: a page answered 500 or did not answer" >&2
    cat "$WORK/routes.log" >&2
    exit 1
  fi
  echo "ok: $(head -n 1 "$WORK/routes.log")"
  # ... and on the odd installs (A4; scripts/dev/odd_walk.sh): homes holding every
  # odd value this version's writers store, each served by it on 127.0.0.1:PORT+1
  if ! ODD_DIR="$WORK/odd" ODD_PY="$TOOL_PY" \
      bash "$(dirname "$0")/../dev/odd_walk.sh" "$((PORT + 1))" "$WORK/bin/kranto" \
      > "$WORK/odd.log" 2>&1; then
    echo "smoke: a page answered 500 or did not answer on an odd install" >&2
    cat "$WORK/odd.log" >&2
    exit 1
  fi
  echo "ok: the odd installs: $(tr '\n' ';' < "$WORK/odd.log")"
fi

# The web UI's build is in the installed the page wheel: the page links one hashed
# module at this version's address, and the mount serves it. (A version of the page from before the web
# UI has no static.APP_DIR and nothing to check.)
if [ "$("$TOOL_PY" -P -c 'from kranto.page.ui.routes import static; print(hasattr(static, "APP_DIR"))')" != "True" ]; then
  echo "ok: this kranto.page has no web UI build to check"
  exit 0
fi
# Kranto is served at / (the old address /brb/ redirects there)
page="$(curl -sfL "http://127.0.0.1:$PORT/")"
asset="$(printf '%s' "$page" | grep -o 'static/v[A-Za-z0-9._-]*/app/app-[A-Za-z0-9_-]*\.js' | head -n 1 || true)"
if [ -z "$asset" ]; then
  echo "smoke: the page at / links no built UI module (static/v<version>/app/app-<hash>.js)" >&2
  exit 1
fi
# at this version's address: a new release is a new address, so a browser never keeps the old
# page's files (they are cached for good)
case "$asset" in
  "static/v${VERSION//[^A-Za-z0-9._-]/-}/app/"*) ;;
  *) echo "smoke: the page links $asset, not at this version's address (static/v$VERSION/)" >&2
     exit 1 ;;
esac
curl -sf -o /dev/null "http://127.0.0.1:$PORT/brb/$asset" || {
  echo "smoke: /brb/$asset is not served" >&2
  exit 1
}
echo "ok: the page at / loads the built UI ($asset)"
