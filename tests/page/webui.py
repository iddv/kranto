"""The web UI's files, for the tests that read them whole: a component or a
module (``src("pages/today/Needs.svelte")``), every source file joined for the scans that hold for
the whole app (no HTML sinks, no internal references, the text diet), the static files (the
stylesheets, theme.js), and the tables the app reads as JSON (the routes, the key map). What a
function or a component does is pressed in Vitest beside it (``ui/web/src/**/*.test.ts``), never
read off its source here."""
import json
from functools import cache
from pathlib import Path

UI = Path(__file__).resolve().parents[2] / "src" / "kranto" / "page" / "ui"
STATIC = UI / "static"
WEB = UI / "web"
SRC = WEB / "src"


def sources() -> list[Path]:
    """The app's own files: every .ts, .svelte and .json under src/ but the tests, their
    helpers (testing.ts) and the generated types."""
    return sorted(p for p in SRC.rglob("*") if p.suffix in (".ts", ".svelte", ".json")
                  and not p.name.endswith((".test.ts", ".gen.ts", ".d.ts")) and not p.name.startswith("testing."))


@cache
def everything() -> str:
    """Every source file joined, for the scans that hold for the whole app."""
    return "\n".join(p.read_text() for p in sources())


def src(name: str) -> str:
    """One file under ui/web/src/ (``App.svelte``, ``shell/Nav.svelte``, ``lib/keys.ts``)."""
    return (SRC / name).read_text()


def static(name: str) -> str:
    """One static file (``theme.js``, ``kranto.css``, ``looks.css``)."""
    return (STATIC / name).read_text()


def css() -> str:
    """The page's stylesheets in the order it loads them: static/kranto.css (the tokens, the resets,
    the help page), then the app's own rules (src/lib/base.css)."""
    return static("kranto.css") + "\n" + src("lib/base.css")


@cache
def nodes() -> list[dict]:
    """Every route (lib/nodes.json)."""
    return json.loads(src("lib/nodes.json"))


@cache
def keymap() -> list[dict]:
    """The one key map (lib/keys.json's KEYMAP)."""
    return json.loads(src("lib/keys.json"))["KEYMAP"]
