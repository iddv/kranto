#!/usr/bin/env bash
# Every page kranto serves, read on the odd installs (#): for each variant of scripts/dev/odd_install.py (odd, empty,
# projects; upgraded, the committed home every release since v0.2.0 wrote, opened by this
# version), a home in a scratch folder, a server on 127.0.0.1:PORT on it (no
# scheduler, no loop lane), and 'kranto doctor --routes' on that server: exit 1 when any page
# answers 500 or does not answer on any variant.
#
#   scripts/dev/odd_walk.sh PORT [KRANTO]
#
# KRANTO: the kranto to check (an installed rc's bin/kranto, as rc_check.sh and smoke.sh pass it);
# default this checkout's venv. The generator runs with that kranto' own Python ($ODD_PY, else
# the script's first line), so the homes are what that version's writers store. Scratch
# folder: $ODD_DIR, else a temporary one, removed at the end; HOME is a folder of its own there
# for each variant, so nothing is written under the caller's HOME. No model, no network: the
# stub embedder, jobs off, telemetry off.
set -euo pipefail

PORT="${1:?usage: odd_walk.sh PORT [KRANTO]}"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
if [ -n "${2:-}" ]; then
  KRANTO=("$2")
  # the installed tool's own interpreter (its script's first line)
  PY="${ODD_PY:-$(head -1 "$2" | sed 's/^#!//')}"
else
  PY="$ROOT/.venv/bin/python"
  KRANTO=("$PY" -m kranto.launcher)
fi
DIR="${ODD_DIR:-$(mktemp -d)}"
[ -n "${ODD_DIR:-}" ] || trap 'rm -rf "$DIR"' EXIT
export DO_NOT_TRACK=1 KRANTO_TELEMETRY=off

failed=0
for variant in odd empty projects upgraded; do
  home="$DIR/$variant" own="$DIR/$variant-home"
  rm -rf "$home" "$own"
  mkdir -p "$own"
  "$PY" "$HERE/odd_install.py" --variant "$variant" --out "$home" > "$DIR/$variant.gen.log" 2>&1 \
    || { echo "FAIL $variant: the generator failed (see $DIR/$variant.gen.log)"; failed=1; continue; }
  HOME="$own" KRANTO_HOME="$home" KRANTO_HOME="$home" "${KRANTO[@]}" serve --host 127.0.0.1 --port "$PORT" \
    --no-scheduler --no-loop > "$DIR/$variant.serve.log" 2>&1 &
  pid=$!
  up=0
  for _ in $(seq 1 90); do
    if curl -sf "http://127.0.0.1:$PORT/api/status" > /dev/null; then up=1; break; fi
    kill -0 "$pid" 2>/dev/null || break
    sleep 1
  done
  if [ "$up" = 1 ] && HOME="$own" KRANTO_HOME="$home" KRANTO_HOME="$home" \
      "${KRANTO[@]}" doctor --routes \
      --port "$PORT" > "$DIR/$variant.routes.log" 2>&1; then
    echo "PASS $variant: $(grep -m1 'routes' "$DIR/$variant.routes.log" | sed 's/^ok *routes *//')"
  else
    echo "FAIL $variant: $( [ "$up" = 1 ] && grep -m1 'routes' "$DIR/$variant.routes.log" \
      || echo 'the server did not answer') (see $DIR/$variant.*.log)"
    failed=1
  fi
  kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
done
exit "$failed"
