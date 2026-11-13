#!/usr/bin/env python3
"""rc_check's request-storm step: sign a headless browser in to the scratch
instance, open Home and three pages, and fail when any address is asked more than LIMIT times
in WINDOW seconds.

v0.6.0-dev3 passed rc_check 7/7 and the scratch walk 13/13 while its console panel posted
``console/open`` without end (32,369 times in one live walk): nothing counted requests. Every
write is aborted here (and counted), as on the live walk that found it, so nothing on the
scratch is started or changed by the walk.

    STORM_LINK=<a one-time sign-in link> python storm_walk.py http://127.0.0.1:PORT

Needs Playwright and its Chromium (the python running it). Prints one line per page and the
busiest addresses; exit 1 on a storm, 2 when it cannot walk.
"""
from __future__ import annotations

import os
import sys
import time
from collections import Counter
from urllib.parse import urlsplit

LIMIT = 20            # asks of one address
WINDOW = 30.0         # seconds: the whole walk
PAGES = ("#/", "#/needs", "#/activity", "#/settings/assistant")


def key(method: str, url: str) -> str:
    """One address: the method and the path (a query's values vary; the path is the loop)."""
    return f"{method} {urlsplit(url).path}"


def storms(asked: list[tuple[float, str]], limit: int = LIMIT, window: float = WINDOW) -> dict:
    """The addresses asked more than ``limit`` times within any ``window`` seconds."""
    by: dict[str, list[float]] = {}
    for t, k in asked:
        by.setdefault(k, []).append(t)
    out = {}
    for k, ts in by.items():
        ts.sort()
        lo = 0
        for hi, t in enumerate(ts):
            while t - ts[lo] > window:
                lo += 1
            if hi - lo + 1 > limit:
                out[k] = max(out.get(k, 0), hi - lo + 1)
    return out


def walk(base: str, link: str, dwell: float) -> list[tuple[float, str]]:
    from playwright.sync_api import sync_playwright
    asked: list[tuple[float, str]] = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1400, "height": 900})
        page.on("request", lambda r: asked.append((time.monotonic(), key(r.method, r.url))))
        # the sign-in itself is a GET; every write after it is refused here, never sent
        page.route("**/*", lambda rt: rt.abort() if rt.request.method not in ("GET", "HEAD")
                   else rt.continue_())
        page.goto(link, wait_until="domcontentloaded")
        for h in PAGES:
            page.goto(f"{base.rstrip('/')}/{h}", wait_until="domcontentloaded")
            page.wait_for_timeout(int(dwell * 1000))
            n = Counter(k for _, k in asked)
            print(f"  {h}: {len(asked)} requests so far, the most asked "
                  f"{n.most_common(1)[0][1] if n else 0}")
        browser.close()
    return asked


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__.split("\n\n")[2].strip(), file=sys.stderr)
        return 2
    link = os.environ.get("STORM_LINK") or ""
    if not link:
        print("storm_walk: STORM_LINK is not set (kranto open --no-browser prints one)",
              file=sys.stderr)
        return 2
    try:
        asked = walk(argv[1], link, WINDOW / len(PAGES))
    except ImportError:
        print("storm_walk: this python has no Playwright: set PW_PYTHON", file=sys.stderr)
        return 2
    found = storms(asked)
    busiest = Counter(k for _, k in asked).most_common(3)
    print("  busiest: " + "; ".join(f"{k} x{n}" for k, n in busiest))
    if found:
        print("storm: " + "; ".join(f"{k} asked {n} times within {WINDOW:g} s"
                                    for k, n in sorted(found.items())))
        return 1
    print(f"no address asked more than {LIMIT} times in {WINDOW:g} s")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
