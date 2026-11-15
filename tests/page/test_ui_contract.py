"""The page's DOM contract (ui/web/CONTRACT.md,): every id and class the browser
smoke, the click stories and the page-source tests find things by is still written by the
sources the contract names, so a page that moves keeps them."""
import re

from .webui import SRC, WEB

CONTRACT = (WEB / "CONTRACT.md").read_text()
SHELL = "\n".join(p.read_text() for p in sorted([SRC / "App.svelte", SRC / "ui" / "DialogHost.svelte", *(SRC / "shell").glob("*.svelte")]))
# the pages and the parts they share (Welcome's key field is pages/settings/KeyField.svelte;
# a dialog's frame is ui/DialogFrame.svelte, the one popover ui/popover.ts)
PAGES = "\n".join([*(p.read_text() for d in ("pages", "ui") for p in sorted((SRC / d).rglob("*.svelte"))), (SRC / "ui" / "popover.ts").read_text()])
# ids the shell writes from a value: the splitters' id={"split-" + col}
DRAWN = {"split-nav": 'id={"split-" + col}', "split-detail": 'id={"split-" + col}'}


def selectors(section: str) -> list[str]:
    part = CONTRACT[CONTRACT.index(section):]
    part = part[:part.index("\n## ", 1)] if "\n## " in part[1:] else part
    return re.findall(r"^\| `([^`]+)` \|", part, re.M)


def writes_id(src: str, name: str) -> bool:
    """An id in markup (id="x"), in an h() call (id: "x"), set on a node (.id = "x"), or one
    of the shell's drawn ids."""
    return any(p in src for p in (f'id="{name}"', f'id: "{name}"', f'.id = "{name}"', DRAWN.get(name, "\0")))


def writes_class(src: str, name: str) -> bool:
    """A class in markup (class="a b", class={"a" + ...}), in an h() call (class: "a b"), or
    the start of a class worked out in a component's script ("ni" + ...)."""
    for m in re.finditer(r'class(?:=|: )(?:\{)?"([^"]*)"', src):
        if name in m.group(1).split():
            return True
    return f'"{name}" + ' in src or f'.className = "{name}"' in src


def check(src: str, sel: str) -> bool:
    tag, _, rest = sel.partition(".") if not sel.startswith((".", "#")) else ("", "", sel)
    if sel.startswith("#"):
        return writes_id(src, sel[1:])
    cls = (rest or sel).lstrip(".").split(".")
    return all(writes_class(src, c) for c in cls) and (not tag or f'h("{tag}"' in src or f"<{tag}" in src)


def test_the_contract_lists_the_shell_and_the_pages():
    assert len(selectors("## The shell")) >= 30 and len(selectors("## The pages")) >= 10


def test_the_shell_writes_every_id_and_class_it_promises():
    missing = [s for s in selectors("## The shell") if not check(SHELL, s)]
    assert missing == []


def test_the_pages_write_every_id_and_class_they_promise():
    missing = [s for s in selectors("## The pages") if not check(PAGES, s)]
    assert missing == []
