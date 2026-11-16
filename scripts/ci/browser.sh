#!/usr/bin/env bash
# The browser smoke (tests/page/test_browser_smoke.py) on a CI runner, with no root: Playwright's
# headless Chromium in the runner's cache (downloaded once), and the one system library the
# the server lacks (libasound) unpacked from its Debian package beside it when it is missing.
#
#   scripts/ci/browser.sh            (from the checkout, after `uv sync --locked --group browser`)
set -euo pipefail

CACHE="${KRANTO_BROWSER_CACHE:-$HOME/.cache/kranto-browser}"
export PLAYWRIGHT_BROWSERS_PATH="$CACHE/ms-playwright"
LIBS="$CACHE/libs"
mkdir -p "$PLAYWRIGHT_BROWSERS_PATH" "$LIBS"

uv run --no-sync playwright install --only-shell chromium

if ! ldconfig -p | grep -q 'libasound\.so\.2 ' && [ ! -e "$LIBS/usr/lib/x86_64-linux-gnu/libasound.so.2" ]; then
  echo "browser.sh: libasound.so.2 is missing; unpacking it into $LIBS"
  tmp="$(mktemp -d)"
  (cd "$tmp" && apt-get download libasound2t64 2>/dev/null || apt-get download libasound2)
  dpkg-deb -x "$tmp"/libasound2*.deb "$LIBS"
  rm -rf "$tmp"
fi
export LD_LIBRARY_PATH="$LIBS/usr/lib/x86_64-linux-gnu${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"

KRANTO_BROWSER_REQUIRED=1 uv run --no-sync pytest -q -m browser tests/page/test_browser_smoke.py tests/page/test_browser_contrast.py tests/page/test_browser_activity.py tests/page/test_browser_rowsafe.py tests/page/test_browser_console.py tests/page/test_browser_incident.py tests/page/test_browser_topbar.py tests/page/test_browser_console_resize.py tests/page/test_browser_trace.py tests/page/test_browser_buttons.py tests/page/test_browser_budget.py tests/page/test_browser_words.py tests/page/test_browser_post.py
