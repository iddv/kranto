"""The resizable columns: two splitters, ARIA separators in the tab order that
the keyboard and a pointer move; the widths are kept per browser in kranto.layout, applied by
theme.js before the first paint and clamped to the window; a splitter never redraws the page.
The browser half (keys, drag, reload, storage denied, 1000 and 390 px) runs on a scratch copy."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, src, static

UI = Path(api.__file__).parent
JS = everything()
THEME = static("theme.js")
CSS = css()
HTML = (UI / "app.html").read_text()


SPLITTER = src("shell/Splitter.svelte")


def splitter_code():
    """Splitter.svelte and the module whose width functions it calls (lib/shell.svelte.ts)."""
    return SPLITTER + src("lib/shell.svelte.ts")


def test_two_separators_in_the_tab_order():
    app = src("App.svelte")
    assert app.count('<Splitter col="nav" />') == 1 and app.count('<Splitter col="detail" />') == 1
    tag = re.search(r'<div class=\{"split"[^>]*>', SPLITTER).group(0)
    for attr in ('role="separator"', 'tabindex="0"', 'aria-orientation="vertical"', "aria-controls={col}", "data-col={col}",
                 'id={"split-" + col}', "aria-label=", "aria-valuenow={aria.now}"):
        assert attr in tag, attr


def test_the_splitter_never_redraws():
    code = splitter_code()
    assert not re.search(r"(?<![\w.])render\(", code), "a splitter writes CSS variables and localStorage, never render()"
    assert 'ui.split = "split-" + col;' in code         # the status bar's key hint only
    for k in ('"ArrowLeft"', '"ArrowRight"', '"Home"', '"End"', '"Escape"', "e.shiftKey ? 64 : 16", "ondblclick=", "setPointerCapture", "aria-valuenow"):
        assert k in code, k


def test_every_storage_call_is_inside_try():
    for code in (THEME, splitter_code()):
        for line in code.splitlines():
            if re.search(r"localStorage\.\w+\(", line):
                assert "try {" in line, line.strip()
    assert "LAYOUT.save(" in splitter_code() and "localStorage." not in splitter_code(), "the splitters store through theme.js's save"


def test_theme_js_applies_and_clamps_the_widths_before_the_first_paint():
    for part in ('const KEY = "kranto.layout"', "NAV = { min: 168, max: 400, icons: 56, def: 224 }", "DET = { min: 360 }", "LIST = 320",
                 "W * (wide ? 0.7 : 0.6)", 'st.setProperty("--nav-w"', 'st.setProperty("--detail-w"', 'html.classList.toggle("nav-icons", icons)',
                 "apply();", "window.krantoLayout = { read, save, apply"):
        assert part in THEME, part
    assert ".split { grid-area: sn;" in CSS and "#split-detail { grid-area: sd; }" in CSS
    assert "@media (pointer: coarse) { .split::before" in CSS, "a 16 px hit area on a finger"
    mid = re.search(r"@media \(max-width: 1179px\) \{(.*?)\n\}", CSS, re.S).group(1)
    assert "#split-nav { display: none; }" in mid and '"list sd detail"' in mid
    assert ".split { display: none; }" in re.search(r"@media \(max-width: 759px\) \{(.*?)\n\}", CSS, re.S).group(1)


def test_reset_layout_is_in_the_palette_and_the_sheet():
    assert '"Layout: reset the column widths"' in JS and 'id="reset-layout"' in src("shell/KeySheet.svelte")
