"""Salt waits for its guard.

More salt on thin items is off by default (a stored "on" is kept). Every shipped writer passes
the words it writes from to the checker, so ``salt.person`` (a post names the people its material
names, and nobody else) runs where posts are written, and the draft page's check reads them
too. The name rule catches a one-word surname after a title or beside a verb of saying, a name
with a lower-case particle or an inner capital, and leaves a two-word place or product alone. A
short post carries one link at most, no mention and no bare site name its sources lack, and a
link too long for the site is refused in words.
"""

from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest

from kranto import prose, social
from kranto.core import sites
from kranto.core.cubs.brokers.social import FILER
from kranto.prose import profile as profile_mod
from kranto.prose.checker import RULES, people_not_in
from kranto.prose.composer import salt_of
from kranto.web import post_api

from .test_social import Model, _material, _rt

SRC = Path(__file__).resolve().parents[1] / "src"


def salted(salt: str) -> prose.Profile:
    p = prose.default()
    return replace(p, switches={**p.switches, "salt": salt})


# -- the default --------------------------------------------------------------------------------

def test_with_salt_at_plain_and_nothing_else_touched_a_small_tool_is_written_plain():
    p = prose.default()
    assert p.switches["salt"] == "plain" and p.switches["salt_thin"] == "off"
    small_tool = {"title": "A tiny CLI that prints your git branch", "facts": "[1] ex.com: a CLI"}
    assert salt_of(p, small_tool) == "plain"
    # a stored "on" is kept: the owner's own choice
    on = replace(p, switches=profile_mod._clean_switches({"salt_thin": "on"}))
    assert salt_of(on, small_tool) == "wry"


# -- every shipped writer passes its material -----------------------------------------------------

def _check_calls(path: Path) -> list[ast.Call]:
    """Every call of a prose check in a module: ``prose.check(...)``, ``ctx.prose.check(...)``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "check":
            owner = node.func.value
            name = owner.attr if isinstance(owner, ast.Attribute) else \
                owner.id if isinstance(owner, ast.Name) else ""
            if name == "prose":
                out.append(node)
    return out


# a cub's check goes through the SDK and the cub host; both take the material once the SDK's
# prose.check carries it, and these marks come off then (strict: a pass fails until they do)
CUB_HALF = pytest.mark.xfail(strict=True, reason="the cub host and the SDK pass a cub's "
                                                 "material once prose.check takes sources")
WRITERS = [
    pytest.param("kranto/social/__init__.py", id="short posts"),
    pytest.param("kranto/core/cubs/host.py", id="the cub host", marks=CUB_HALF),
    pytest.param("kranto/cubs/examples/blog/main.py", id="blog", marks=CUB_HALF),
    pytest.param("kranto/cubs/examples/toot/main.py", id="toot", marks=CUB_HALF),
    pytest.param("kranto/cubs/examples/newsletter/main.py", id="newsletter", marks=CUB_HALF),
]


@pytest.mark.parametrize("rel", WRITERS)
def test_every_writers_check_passes_the_material(rel):
    calls = _check_calls(SRC / rel)
    assert calls, f"{rel} has no prose check: the list of writers is stale"
    missing = [c.lineno for c in calls if not any(k.arg == "sources" for k in c.keywords)]
    assert missing == [], f"{rel}: the check on line(s) {missing} drops the material"


def test_the_writer_list_holds_every_module_that_checks():
    found = {str(p.relative_to(SRC)) for p in SRC.rglob("*.py") if _check_calls(p)}
    listed = {p.values[0] for p in WRITERS}
    # the page's own Check and Fix them (web/prose_api.py) check what the person typed, and
    # the SDK's test double mirrors the host: neither writes a post
    assert found - listed <= {"kranto/web/prose_api.py", "bears_cub/testing.py"}, found - listed


def test_the_social_writer_hands_its_material_to_the_check(store, tmp_path, monkeypatch):
    seen = []
    real = prose.check

    def spy(*a, **k):
        seen.append(k.get("sources"))
        return real(*a, **k)
    monkeypatch.setattr(prose, "check", spy)
    social.write_variant(_rt(store, tmp_path), sites.Choice(sites.SITES["x"]), _material(),
                         "Kiosks need ledgers.", complete=Model("Kiosks lose batteries."),
                         profile=prose.default())
    assert seen and all(s and "Battery swap ledger" in s and "kiosks lose track" in s
                        and "Kiosks need ledgers." in s for s in seen), seen


# -- a salty short post that names a stranger is flagged -----------------------------------------

STRANGER = "Kiosks lose batteries. Somewhere Dario Amodei is counting them, and Altman said so."


def test_a_salty_short_post_naming_a_stranger_is_flagged_on_its_draft_page(store, tmp_path):
    rt = _rt(store, tmp_path)
    v = social.write_variant(rt, sites.Choice(sites.SITES["bluesky"]), _material(), "a",
                             complete=Model(STRANGER), profile=salted("salty"))
    assert "salt.person" in v["prose"]["left"]
    assert RULES["salt.person"][1] == "names a person the sources don't name"
    # the draft keeps its material, and the page's check of it flags the name
    set_sites(store, ["bluesky"])
    out = social.write_all(rt, sites.choices(store), _material(), "a", about="card:7",
                           complete=Model(STRANGER), profile=salted("salty"))
    assert out["written"] == ["bluesky"]
    did = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    rt.cubs = None
    sheet = post_api.draft_sheet(rt, did)
    assert sheet["sources"] and "Battery swap ledger" in sheet["sources"]
    flags = prose.check(sheet["parts"][0]["text"], "bluesky", salted("salty"), kind="short",
                        sources=sheet["sources"])["flags"]
    named = [(f["text"], f["words"]) for f in flags if f["rule"] == "salt.person"]
    assert ("Dario Amodei", "names a person the sources don't name") in named
    assert ("Altman", "names a person the sources don't name") in named


def set_sites(store, ticked):
    from kranto.stored.settings import PostingSites, set_blob
    set_blob(store, PostingSites.SETTING, PostingSites(sites=list(ticked), direct={}))


def test_the_check_route_reads_the_sources(store, tmp_path):
    from types import SimpleNamespace

    from kranto.web import prose_api
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path, prose=None))
    out = prose_api.check(rt, {"text": "Altman said it.", "site": "bluesky",
                               "sources": "A ledger for kiosks"})
    assert "salt.person" in {f["rule"] for f in out["flags"]}
    out = prose_api.check(rt, {"text": "Altman said it.", "site": "bluesky"})
    assert "salt.person" not in {f["rule"] for f in out["flags"]}


# -- the name rule ------------------------------------------------------------------------------

SOURCES = "Visual Studio Code adds a ledger\n[1] ex.com: kiosks lose track of batteries"


@pytest.mark.parametrize("text, names", [
    ("Altman said it was fine.", ["Altman"]),
    ("It was fine, said Altman.", ["Altman"]),
    ("According to Altman, it is fine.", ["Altman"]),
    ("As Dr. Patel put it, kiosks leak.", ["Patel"]),
    ("Ian de Villiers wrote the ledger.", ["Ian de Villiers"]),
    ("John McCarthy would have liked it.", ["John McCarthy"]),
    ("Ask Sean O'Brien about it.", ["Sean O'Brien"]),
    ("Somewhere Dario Amodei is counting.", ["Dario Amodei"]),
    ("Ping @limitwatcher about it.", ["@limitwatcher"]),
    # not a person
    ("New York kiosks lose batteries.", []),
    ("Visual Studio users will like it.", []),         # the title's own two words
    ("Claude Code said nothing about it.", []),         # a product beside a verb of saying
    ("He said kiosks lose batteries.", []),
    ("Kiosks lose batteries daily.", []),
    ("Built on Node.js, it reads README.md.", []),
])
def test_the_name_rule(text, names):
    assert [text[a:b] for a, b in people_not_in(text, SOURCES)] == names


def test_a_name_the_sources_have_is_not_flagged_even_possessive():
    src = "Google DeepMind ships a model\n[1] ex.com: a model"
    assert people_not_in("Google DeepMind's model ships.", src) == []
    assert people_not_in("Altman said so.", "Sam Altman on kiosks\n[1] ex.com") == []


# -- one link, no mention, no bare site name -----------------------------------------------------

def test_a_short_post_never_carries_a_second_link_a_mention_or_a_bare_site_name(store, tmp_path):
    answer = ("Kiosks lose batteries https://ex.com/source and @someone@mastodon.social knows, "
              "see evil.example for more.")
    v = social.write_variant(_rt(store, tmp_path), sites.Choice(sites.SITES["bluesky"]),
                             _material(), "a", complete=Model(answer), profile=prose.default())
    whole = "\n".join(v["parts"])
    assert whole.count("https://ex.com/source") == 1
    assert "@someone" not in whole and "evil.example" not in whole
    said = next(e["words"] for e in v["extras"] if e["key"] == "removed")
    assert "mention" in said and "evil.example" in said


def test_a_mention_or_site_the_sources_name_is_kept():
    known = "Battery swap ledger\n[1] ex.com: kiosks lose track; ask @kiosk_ops"
    out, gone = sites.scrub("ex.com and @kiosk_ops say so.", set(), known)
    assert out == "ex.com and @kiosk_ops say so." and gone == []
    out, gone = sites.scrub("me@ex.com is an address, Node.js a word.", set(), "")
    assert out == "me@ex.com is an address, Node.js a word." and gone == []


def test_a_link_too_long_for_the_site_is_refused_in_words(store, tmp_path):
    long_link = "https://ex.com/" + "a" * 200
    with pytest.raises(social.SocialError) as e:
        social.write_variant(_rt(store, tmp_path), sites.Choice(sites.SITES["bluesky"]),
                             _material(long_link), "a", complete=Model("Kiosks."),
                             profile=prose.default())
    assert "too long for Bluesky" in e.value.words and e.value.code == 422


def test_the_blog_draft_linked_is_the_one_its_own_write_returned(store, tmp_path):
    from kranto.core.cubs.brokers.base import new_draft
    mine = new_draft(store, cub="blog", service="sanity", content={"title": "Mine"},
                     run_uuid=None)
    new_draft(store, cub="blog", service="sanity", content={"title": "Another write's"},
              run_uuid=None)
    got = post_api._blog_draft(store, mine["ref"], 0)
    assert got is not None and got["content"]["title"] == "Mine"
    # a writer that returns no ref: the newest since the write began, as before
    assert post_api._blog_draft(store, None, 0)["content"]["title"] == "Another write's"
    assert json.loads(json.dumps(got["content"])) == {"title": "Mine"}
