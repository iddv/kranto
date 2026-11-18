"""The owner's site cub as a registry alias of Kranto's blog writer (the ``cubs`` row; CUT,
handed over by G4).

A copy whose registry holds an ``examplecom`` install row (from a git repository's
``cubs/examplecom`` or the old
example's folder) lists one cub, ``blog``, at Kranto's version; ``/api/cubs/blog`` reaches it; the
blog writer reads the examplecom settings it has none of its own for; once Kranto's own blog writer
is
installed there is still one ``blog``; and an old examplecom draft still reads and copies. No row is
ever rewritten. No sandbox, no model: the rows are written as an older Kranto wrote them."""

from __future__ import annotations

import json

from kranto.core import tickets
from kranto.core.cubs import registry, views
from kranto.core.cubs import settings as cub_settings
from kranto.core.cubs.brokers.base import new_draft
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

OLD_EXAMPLE = "/home/someone/.local/share/uv/tools/kranto/lib/python3.12/site-packages/" \
              "kranto/cubs/examples/examplecom"


def cub_row(store, cid: str, source: dict, *, kind: str = "folder", state: str = "installed",
            version: str = "0.9.0") -> int:
    return store.insert("cubs", {
        "cub": cid, "state": state, "version": version, "trust": "owner", "source_kind": kind,
        "source": json.dumps(source), "sha": None, "tree_hash": "t" * 8,
        "manifest_hash": "m" * 8, "grants": "{}", "bears_range": None, "note": None,
        "created_at": iso(utcnow())})


def rows_of(store) -> list[tuple]:
    return [tuple(r) for r in store.query("SELECT * FROM cubs ORDER BY id")]


def test_an_examplecom_row_lists_one_blog_cub_at_kranto_version(rt, monkeypatch):  # noqa: F811
    store = rt.store
    cub_row(store, "examplecom", {"path": OLD_EXAMPLE})
    cub_row(store, "newsletter", {"path": "/x/newsletter"})
    before = rows_of(store)
    got = {c["id"]: c for c in views.listing(rt)["cubs"]}
    assert set(got) == {"blog", "newsletter"}                     # one blog, no examplecom
    blog = got["blog"]
    assert blog["alias_of"] == "examplecom" and blog["title"] == "Blog"
    assert blog["source"] == {"kind": "built-in"} and blog["source_gone"] is None
    assert blog["version"] == registry.builtin_version("blog") != "0.9.0"
    assert registry.resolve(store, "blog") == "examplecom"
    assert registry.resolve(store, "newsletter") == "newsletter"
    one = views.detail(rt, "blog")
    assert one is not None and one["id"] == "blog" and one["alias_of"] == "examplecom"
    assert rows_of(store) == before                                 # read, never rewritten
    # (the server's start pauses these hand-made rows: they have no files; the alias holds)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        listed = [c["id"] for c in web.get("/api/cubs").json()["cubs"]]
        assert listed.count("blog") == 1 and "examplecom" not in listed
        assert web.get("/api/cubs/blog").json()["alias_of"] == "examplecom"


def test_a_git_examplecom_is_the_site_cub_and_another_source_is_not(rt):  # noqa: F811
    assert registry.is_site_row({"cub": "examplecom", "source": json.dumps(
        {"kind": "git", "url": "https://example.invalid/cubs.git", "ref": "main",
         "subdirectory": "cubs/examplecom"})})
    assert registry.is_site_row({"cub": "examplecom", "source": "{}"})
    assert registry.is_site_row({"cub": "examplecom", "source": None})          # any stored shape
    assert not registry.is_site_row({"cub": "examplecom", "source": json.dumps(
        {"url": "https://example.com/other-cub"})})
    assert not registry.is_site_row({"cub": "toot", "source": "{}"})
    assert not registry.is_site_row(None)


def test_the_blog_reads_the_examplecom_settings_by_id_alias(rt, monkeypatch):  # noqa: F811
    tickets.kind_names()
    section = cub_settings.parse({"examplecom": {"monthly_usd": 7, "live": ["draft.sanity"],
                                             "enabled": True}})
    monkeypatch.setattr(cub_settings, "values", lambda cfg: section)
    cfg = rt.cfg
    assert cub_settings.cub_value(cfg, "blog", "monthly_usd", trust="owner") == 7
    assert cub_settings.live_kinds(cfg, "blog") == ["draft.sanity"] or \
        "draft.sanity" in cub_settings.live_kinds(cfg, "blog")
    assert cub_settings.own_value(cfg, "blog", "monthly_usd") == 7
    # its own value, once written, wins; the examplecom one stays as written
    section["per"]["blog"] = {"monthly_usd": 3}
    assert cub_settings.cub_value(cfg, "blog", "monthly_usd", trust="owner") == 3
    assert section["per"]["examplecom"]["monthly_usd"] == 7
    # no other cub reads another's settings
    assert cub_settings.own_value(cfg, "toot", "monthly_usd") is None


def test_once_kranto_blog_is_installed_there_is_still_one_blog(rt):  # noqa: F811
    store = rt.store
    cub_row(store, "examplecom", {"path": OLD_EXAMPLE})
    cub_row(store, "blog", {"path": "/x/kranto/cubs/examples/blog"}, version="1.0.0")
    got = [c for c in views.listing(rt)["cubs"] if c["id"] in ("blog", "examplecom")]
    assert [c["id"] for c in got] == ["blog"] and "alias_of" not in got[0]
    assert registry.resolve(store, "blog") == "blog"
    # removed again: the site cub stands in once more
    cub_row(store, "blog", {"path": "/x"}, state="removed", version="1.0.0")
    assert registry.resolve(store, "blog") == "examplecom"


def test_an_old_examplecom_draft_still_reads_and_copies(rt):  # noqa: F811
    store = rt.store
    cub_row(store, "examplecom", {"path": OLD_EXAMPLE})
    d = new_draft(store, cub="examplecom", service="sanity",
                  content={"doc": "post-tide", "title": "Tide clocks", "slug": "tide-clocks",
                           "category": "dispatch", "excerpt": "Clocks that read the sea.",
                           "body": "A tide clock reads the moon."}, run_uuid=None)
    tickets.kind_names()
    tid = tickets.file(store, cub="examplecom", trust="owner", granted=("draft.sanity",),
                       kind="draft.sanity", fields={"draft_ref": d["ref"], "slug": "tide-clocks",
                                                    "title": "Tide clocks",
                                                    "category": "dispatch"},
                       subject=("examplecom_post", d["ref"]))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        post = web.get("/api/post").json()
        mine = [x for x in post["drafts"] + post["earlier"] if x["ref"] == d["ref"]]
        assert mine and mine[0]["kind"] == "blog" and mine[0]["word"] == "blog post"
        assert mine[0]["cub"] == "examplecom"                           # its own id underneath
        sheet = web.get(f"/api/post/d/{mine[0]['id']}")
        assert sheet.status_code == 200, sheet.text
        assert "Tide clocks" in sheet.json()["markdown"]
        md = web.get(f"/api/post/d/{mine[0]['id']}.md")
        assert md.status_code == 200 and "A tide clock reads the moon." in md.text
    assert tickets.get(store, tid)["cub"] == "examplecom"                # its data, as it was
