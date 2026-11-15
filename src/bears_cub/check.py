"""``python -m bears_cub.check path/to/cub``: is this folder a cub Kranto can install?

Checks ``cub.yaml`` against the manifest's schema (defaults filled), that the paths it names are
in the folder, that the entry file loads and registers every handler the manifest names, and
that ``requirements.txt`` (when there is one) is exact pins with hashes. With Kranto installed
in the same environment it also runs Kranto's own validator (what ``kranto cub check`` says).
Exit 0 when the cub passes, 1 when it does not; the reasons are printed in words.
"""

from __future__ import annotations

import copy
import re
import sys
from pathlib import Path

from . import schema, widgets

REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+"
                         r"(\s+--hash=sha256:[0-9a-f]{64})+")


def problems(folder: Path) -> list[str]:
    out: list[str] = []
    try:
        data = schema.load_file(folder / "cub.yaml")
        m = schema.check(copy.deepcopy(data))
    except FileNotFoundError:
        return ["no cub.yaml in the folder"]
    except schema.ManifestError as exc:
        return [str(exc)]
    for key, rel in (("entry", m.get("entry")), ("requirements", m.get("requirements")),
                     ("docs.page", (m.get("docs") or {}).get("page"))):
        if rel and not (folder / rel).is_file():
            out.append(f"{key}: {rel} is not in the folder")
    req = m.get("requirements")
    if req and (folder / req).is_file():
        text = (folder / req).read_text(encoding="utf-8").replace("\\\n", " ")
        for n, line in enumerate(text.splitlines(), 1):
            line = " ".join(line.split("#", 1)[0].split())
            if line and not REQUIREMENT.fullmatch(line):
                out.append(f"requirements: line {n} is not name==version --hash=sha256:…")
    if not out:
        try:
            from .testing import FakeHost
            FakeHost.from_folder(folder)
        except schema.ManifestError as exc:
            out.append(str(exc))
        except Exception as exc:  # noqa: BLE001 - the entry file's own failure, in words
            out.append(f"the entry file failed to load: {type(exc).__name__}: {exc}")
    try:
        from kranto.core import registry
    except ImportError:
        return out
    try:
        files = {str(p.relative_to(folder)) for p in folder.rglob("*") if p.is_file()}
        registry.validate_cub(copy.deepcopy(data), files=files)
    except schema.ManifestError as exc:
        out.append(f"Kranto: {exc}")
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m bears_cub.check path/to/cub", file=sys.stderr)
        return 2
    folder = Path(args[0])
    found = problems(folder)
    if found:
        for p in found:
            print(f"refused: {p}")
        return 1
    m = schema.check(schema.load_file(folder / "cub.yaml"))
    print(f"ok: {m.get('id')} {m.get('version')} is a cub Kranto can install")
    for w in (m.get("ui") or {}).get("widgets", []):
        print(f"widget: shows on the home, if its owner adds it: {widgets.describe(w)}")
    line = settings_words(m)
    if line:
        print(f"settings: {line}")
    for line in page_words(m):
        print(f"page: {line}")
    return 0


def page_words(m: dict) -> list[str]:
    """How Kranto draws its page, in words: its one primary, what each list
    says when empty, which objects open as a page of their own."""
    ui = m.get("ui") or {}
    out = []
    forms = {f.get("id"): f.get("word") for f in ui.get("forms") or []}
    primary = ui.get("primary") or next(iter(forms), None)
    if primary:
        out.append(f"its one primary in the head: {forms.get(primary) or primary}")
    for x in ui.get("lists") or []:
        out.append(f"its {x.get('word')} list says, when empty: "
                   + (x.get("empty") or "Nothing here yet."))
    for name, card in (ui.get("cards") or {}).items():
        if card.get("open") == "page":
            a = "an" if name[:1] in "aeiou" else "a"
            out.append(f"{a} {name} opens as a page, its {card.get('body')} drawn as text")
    return out


def settings_words(m: dict) -> str | None:
    """Where its keys sit on its Settings page, in words: "on Settings ›
    Newsletter: The issue (4 keys), Sending (1 key); 1 under Advanced"."""
    keys = (m.get("settings") or {}).get("keys") or {}
    if not keys:
        return None
    title = m.get("title") or m.get("id")
    groups: dict[str, int] = {}
    adv = 0
    for rule in keys.values():
        if rule.get("advanced"):
            adv += 1
        else:
            g = rule.get("group") or f"{title}'s settings"
            groups[g] = groups.get(g, 0) + 1
    parts = [f"{g} ({n} key{'' if n == 1 else 's'})" for g, n in groups.items()]
    said = ", ".join(parts)
    if adv:
        said += ("; " if said else "") + f"{adv} under Advanced"
    return f"on Settings › {title}: {said}"


if __name__ == "__main__":
    sys.exit(main())
