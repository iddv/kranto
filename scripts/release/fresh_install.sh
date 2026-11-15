#!/usr/bin/env bash
# rc_check.sh's step 0: install a release the way a newcomer does, in a fresh HOME.
#
#   PORT=8941 scripts/release/fresh_install.sh vX.Y.Z[-devN] DIR
#
# Downloads the release's own install.sh, runs it with HOME=DIR/home and a bare PATH (no uv,
# no kranto; uv comes from astral's installer as it would for a stranger), with gh's login read
# from this machine's gh config (GH_CONFIG_DIR) so the private download works, as a friend's
# logged-in gh would. Then, when the release has 'kranto setup': 'kranto setup --yes' with an
# answers file (foreground, no start, this PORT), twice: the second run changes nothing. A
# release without it: 'kranto up --foreground' on 127.0.0.1:PORT until /api/status answers, then
# stopped. Exit 0 when every check passes. Nothing outside DIR is written; the tool tree and
# the caches under DIR/home are removed at the end (the logs stay in DIR).
set -euo pipefail

TAG="${1:?usage: fresh_install.sh vX.Y.Z[-devN] DIR}" DIR="${2:?usage: fresh_install.sh TAG DIR}"
: "${PORT:?set PORT (served on 127.0.0.1)}"
REPO="${REPO:-$(python3 "$(dirname "$0")/names.py" repo)}"
VERSION="${TAG#v}" VERSION="${VERSION/-rc/rc}" VERSION="${VERSION/-dev/.dev}"
GH_DIR="${GH_CONFIG_DIR:-$HOME/.config/gh}"
rm -rf "$DIR/home" "$DIR/dl"
mkdir -p "$DIR/home" "$DIR/dl"
FRESH="$DIR/home"
cleanup() {
  [ -n "${SERVER:-}" ] && kill "$SERVER" 2>/dev/null && wait "$SERVER" 2>/dev/null
  rm -rf "$FRESH/.local/share/uv" "$FRESH/.cache"
}
trap cleanup EXIT

gh release download "$TAG" -R "$REPO" -p install.sh -D "$DIR/dl"
fresh() {   # a command in the fresh HOME: nothing of this shell's environment but the basics
  env -i HOME="$FRESH" PATH="$FRESH/.local/bin:/usr/bin:/bin" USER="${USER:-}" \
    LOGNAME="${LOGNAME:-}" LANG="${LANG:-C.UTF-8}" TMPDIR="$DIR" GH_CONFIG_DIR="$GH_DIR" \
    NO_COLOR=1 "$@"
}
fresh sh "$DIR/dl/install.sh" --version "$TAG" --no-setup > "$DIR/install.log" 2>&1 || {
  echo "install.sh failed (see $DIR/install.log)"; exit 1; }
[ "$(fresh kranto --version | head -n 1 | awk '{print $2}')" = "$VERSION" ] || {
  echo "kranto --version is not $VERSION: $(fresh kranto --version 2>&1)"; exit 1; }
grep -q "SHA256SUMS\|: OK" "$DIR/install.log" || { echo "install.sh checked no hashes"; exit 1; }

if fresh kranto setup --help > /dev/null 2>&1; then
  cat > "$DIR/answers.yaml" <<YAML
service: foreground
port: $PORT
watch: {provider: later}
github: later
start: false
YAML
  for run in 1 2; do
    fresh kranto setup --yes --answers "$DIR/answers.yaml" --json > "$DIR/setup-$run.json" \
      2> "$DIR/setup-$run.log" || { echo "kranto setup run $run failed (see $DIR/setup-$run.log)"; exit 1; }
  done
  python3 - "$DIR/setup-1.json" "$DIR/setup-2.json" <<'PY'
import json, sys
first, second = (json.load(open(p)) for p in sys.argv[1:3])
if not first.get("written"):
    sys.exit("the first kranto setup wrote nothing")
if second.get("written"):
    sys.exit(f"the second kranto setup wrote {second['written']}: it should change nothing")
PY
  echo "fresh install: install.sh, then kranto setup --yes twice (the second changed nothing)"
else
  env -i HOME="$FRESH" PATH="$FRESH/.local/bin:/usr/bin:/bin" USER="${USER:-}" \
    LOGNAME="${LOGNAME:-}" LANG="${LANG:-C.UTF-8}" TMPDIR="$DIR" NO_COLOR=1 \
    "$FRESH/.local/bin/kranto" up --foreground --port "$PORT" --no-browser > "$DIR/up.log" 2>&1 &
  SERVER=$!
  for _ in $(seq 1 90); do
    curl -sf "http://127.0.0.1:$PORT/api/status" > /dev/null && break
    sleep 1
  done
  curl -sf "http://127.0.0.1:$PORT/api/status" | grep -q "\"version\": *\"$VERSION\"" || {
    echo "the fresh kranto did not answer on 127.0.0.1:$PORT (see $DIR/up.log)"; exit 1; }
  kill "$SERVER"; wait "$SERVER" 2>/dev/null || true; SERVER=""
  sleep 1
  ! curl -sf "http://127.0.0.1:$PORT/api/status" > /dev/null || {
    echo "the fresh kranto still answers on 127.0.0.1:$PORT after SIGTERM"; exit 1; }
  echo "fresh install: install.sh, then kranto up answered on 127.0.0.1:$PORT and stopped"
fi
