"""Filter ▾ (3.1 rule 6;): a list with two filters or more shows the search, Filter ▾
and the active filters as chips with ×, and its sort inline; the URL keeps the state as before;
one filter stays an inline select. The toolbar never wraps (the browser check: ≤ 40 px at 1360
and 1000 px on every list)."""
import re
from pathlib import Path

from kranto.page.ui import api

from .webui import css, everything, src

UI = Path(api.__file__).parent
JS = everything()
CSS = css()




def test_filters_fold_and_the_sort_stays():
    f = src("ui/FilterBar.svelte")          # moved
    assert 'selects.filter((s) => s[0] === "sort")' in f and "{#if filters.length < 2}" in f
    assert '<span class="fchips">' in f and "{#each sorts as s (s[0])}{@render sel(s)}{/each}" in f
    assert 'onclick={() => to(key, "")}' in f and 'go(base, { ...r.q, [key]: v, page: "" })' in f, "× clears one filter, in the URL"
    assert 'aria-haspopup="dialog"' in f and 'popWith(anchor, "Filters", FilterPop' in f
    p = src("ui/FilterPop.svelte")
    assert '<label for={"fpop-" + key}>{name}</label>' in p and "pick(key, e.currentTarget.value)" in p
    assert 'role: "tab' not in JS


def test_the_lists_that_fold():
    # Evidence and the library, Ideas and Settings › Sources pass two filters or more (Projects' left)
    # Settings › Sources moved: its selects are sources.svelte.ts's srcSelects; the library
    # and a topic's Evidence are library.ts's obsSelects
    # Ideas moved: its selects are ideas.ts's IDEA_SELECTS
    ideas = re.search(r"export const IDEA_SELECTS.*?\n\];", src("pages/ideas/ideas.ts"), re.S).group(0)
    assert "selects={IDEA_SELECTS as never}" in src("pages/ideas/IdeasList.svelte")
    for f, text in (("obsSelects", src("pages/library/library.ts")), ("IDEA_SELECTS", ideas), ("srcSelects", src("pages/settings/sources.svelte.ts"))):
        sels = re.findall(r'\["(\w+)", "[A-Z]\w*", \[', text)
        assert len([s for s in sels if s != "sort"]) >= 2, (f, sels)
    assert ".wl .tb .tbn.filters { flex-wrap: nowrap; }" in CSS and ".tb .fchip" in CSS
