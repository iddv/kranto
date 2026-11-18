"""The navigator as icons: 56 px, an icon an entry with its words in its label
and tooltip and its count as a badge, a topic a letter, Settings one gear; ‹ at its top, enter on
its splitter, ⌘K and a drag under the least width; kept in kranto.layout; ignored where the
navigator is the drawer. The badge's colours are pairs test_looks.py holds in every theme."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, src

UI = Path(api.__file__).parent
JS = everything()
CSS = css()




def test_every_entry_has_an_icon_and_its_words_as_a_label():
    n = src("shell/Nav.svelte")
    assert 'id="nav-icons"' in n and 'aria-pressed={icons ? "true" : "false"}' in n
    assert 'aria-label={icons ? named(x) + (x.n ? `, ${x.n}` : "") : null}' in n
    assert 'const named = (x: NavRow) => (x.to === "settings" ? "Settings" : x.w);' in n
    assert '<span class={"ic" + (TOPIC.test(x.to) ? " letter" : "")} aria-hidden="true">' in n
    icon = re.search(r"const ICONS: Record<string, string> = \{(.*?)\};", n, re.S).group(1)
    for to, name in (("needs", "today"), ("review", "check"), ("library", "book"), ("ideas", "open"), ("settings", "gear")):
        assert f'{to}: "{name}"' in icon, to
    assert "builds:" not in icon and "today:" not in icon      # Builds left; Today is Needs you
    for name in ("today", "book", "gear"):
        assert re.search(rf"\n  {name}: \[\[", JS), name


def test_the_ways_to_collapse_and_where_it_is_kept():
    # kept in kranto.layout, without the width it was dragged to, the frame drawn again: pressed in
    # lib/app/topics.test.ts ("collapses to icons and back, kept in kranto.layout without the width
    # it was dragged to")
    assert 'e.key === "Enter" && col === "nav") navIcons(!iconsNow())' in JS
    assert "(iconsNow() ? px < 150 : px < 120)" in JS, "a drag snaps it, with no flicker between"
    assert '"Layout: collapse the navigator"' in JS and '"Layout: expand the navigator"' in JS


def test_icons_only_where_the_navigator_is_a_column():
    wide = re.search(r"@media \(min-width: 1180px\) \{(.*?)\n\}", CSS, re.S).group(1)
    for part in (":root.nav-icons #nav .ni .w, :root.nav-icons #nav .ni .tw { display: none; }", ":root.nav-icons #nav .ni.sub, :root.nav-icons #nav .ni.setx { display: none; }",
                 ":root.nav-icons #nav .ni .ct.new { background: var(--side-new); color: var(--side-bg); }"):
        assert part in wide, part
    assert "nav-icons" not in re.sub(r"@media \(min-width: 1180px\) \{.*?\n\}", "", CSS, flags=re.S), "never on the drawer"
