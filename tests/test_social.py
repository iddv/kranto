"""Short posts for the sites people use (``core.sites``, ``kranto.social``, ``post.open``,
``post.bluesky``): Open first, post directly only when switched on, site first, every variant
through compose, check and revise, each site's limit kept, and nothing ever posted by a test
(every request is a ``MockTransport``'s or refused)."""

from __future__ import annotations

import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from hypothesis import given
from hypothesis import strategies as st

from kranto import prose, social
from kranto.core import sites, tickets
from kranto.core.cubs.brokers import bluesky as bsky
from kranto.core.cubs.brokers.base import draft_of
from kranto.core.cubs.brokers.social import FILER, POSTED_BY_YOU, parts_of
from kranto.store import iso, utcnow
from kranto.stored.settings import PostingSites, SanitySite, set_blob
from kranto.web import post_api

FIX = json.loads((Path(__file__).parent / "fixtures" / "social" / "bluesky.json").read_text())
UI = {"origin": "ui", "via": "cookie"}
AGENT = {"origin": "token", "token": "agent"}


# -- the registry: two ways only, Open first --------------------------------------------------

def test_every_offered_site_has_open_and_no_way_is_copy():
    for s in sites.offered():
        # Open comes first wherever a site has one; LinkedIn has none, so it is posted directly
        assert s.ways()[0] == "open" or s.ways() == ("direct",), s.id
        assert set(s.ways()) <= {"open", "direct"}
    assert {s.id for s in sites.offered()} == {"bluesky", "mastodon", "x", "threads",
                                               "linkedin"}
    assert "x" in sites.SITES and sites.SITES["x"].direct is None      # X: Open only, no API


def test_substack_is_not_offered_and_linkedin_only_posted_directly():
    s = sites.get("substack")
    assert s is not None and s.ways() == () and "no link that fills" in s.not_offered
    assert sites.open_address(s, "x", None) is None
    assert sites.open_address(sites.get("linkedin"), "x", None) is None


def test_open_addresses_carry_the_text_and_the_link():
    x = sites.open_address(sites.SITES["x"], "A claim.", "https://ex.com/a")
    assert x.startswith("https://x.com/intent/tweet?text=A%20claim.&url=https%3A%2F%2Fex.com%2Fa")
    b = sites.open_address(sites.SITES["bluesky"], "A claim.", "https://ex.com/a")
    assert b == "https://bsky.app/intent/compose?text=A%20claim.%0A%0Ahttps%3A%2F%2Fex.com%2Fa"
    m = sites.SITES["mastodon"]
    assert sites.open_address(m, "A claim.", None) is None            # its server first
    assert sites.open_address(m, "Hi", None, instance="mastodon.social") == \
        "https://mastodon.social/share?text=Hi"
    assert sites.open_address(m, "Hi", None, instance="evil/x?") is None
    t = sites.open_address(sites.SITES["threads"], "Hi", "https://ex.com/a")
    assert t.startswith("https://www.threads.com/intent/post?text=Hi&url=")


# -- counting, the site's way -----------------------------------------------------------------

def test_graphemes_count_emoji_flags_and_accents_as_one():
    assert sites.graphemes("👍🏽") == 1                     # a skin tone
    assert sites.graphemes("🇳🇱🇰🇪") == 2                   # two flags
    assert sites.graphemes("é") == 1                 # a combining accent
    assert sites.graphemes("👩‍💻 ok") == 4                 # a joined emoji, a space, two letters


def test_x_and_mastodon_count_a_link_as_23():
    long = "https://example.com/" + "a" * 200
    assert sites.count("x", f"hi {long}") == 3 + 23
    assert sites.count("mastodon", f"hi {long}") == 3 + 23
    assert sites.count("x", "日本") == 4                    # CJK weighs two on X
    assert sites.count("threads", "日本") == 2
    assert sites.count("threads", "ok 👍") == 3 + 4       # an emoji is its UTF-8 bytes


def test_fit_keeps_whole_sentences_and_says_it_cut():
    s = sites.SITES["bluesky"]
    text = "First sentence here. " * 30
    out, cut = sites.fit(s, text, 300)
    assert cut and sites.count(s, out) <= 300 and out.endswith(".")
    assert sites.fit(s, "Short.", 300) == ("Short.", False)


def test_clean_takes_off_foreign_links_and_extra_tags():
    s = sites.SITES["bluesky"]
    out, removed = sites.clean(s, "See https://spam.example/x and #Aa #Bb #Cc",
                               {"https://ex.com/a"})
    assert "spam.example" not in out and out.count("#") == 2 and len(removed) == 2


@given(st.text(min_size=0, max_size=40))
def test_a_bluesky_link_facet_slices_exactly_the_link(prefix):
    url = "https://ex.com/path?q=1"
    text = f"{prefix} {url} end"
    f = [x for x in bsky.facets(text) if x["features"][0]["$type"].endswith("#link")]
    raw = text.encode()
    got = [raw[x["index"]["byteStart"]:x["index"]["byteEnd"]].decode() for x in f]
    assert url in got


# -- the writer: compose, check, revise, and each site's limit ---------------------------------

def _rt(store, tmp_path):
    return SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), embedder=None)


def _material(link="https://ex.com/source"):
    return social.Material(title="Battery swap ledger\nA phone page per kiosk.\nThe thesis.",
                           facts="[1] ex.com: kiosks lose track",
                           link=link, link_to="source",
                           card={"url": link, "title": "Battery swap ledger", "description": ""},
                           because={"ideas": [7]})


class Model:
    """A fake model: the variant's answer, then the reviser's rewrite; records what it was sent."""

    def __init__(self, answer: str, fixed: str | None = None):
        self.answer, self.fixed, self.calls = answer, fixed, []

    def __call__(self, messages, schema):
        self.calls.append(messages)
        if "parts" in json.dumps(schema):
            return {"text": json.dumps({"parts": [self.answer]}), "structured": None}
        if "edits" in json.dumps(schema):          # the reviser: the flagged span, rewritten
            return {"structured": {"edits": [{"id": 1, "text": self.fixed or self.answer}]},
                    "text": ""}
        return {"structured": {"text": self.fixed or self.answer}, "text": ""}


@pytest.mark.parametrize("sid", ["bluesky", "mastodon", "x", "threads"])
def test_each_sites_limit_is_kept_whatever_the_model_writes(store, tmp_path, sid):
    site = sites.SITES[sid]
    choice = sites.Choice(site, instance="mastodon.social" if site.needs else None)
    long = "Kiosks lose track of batteries, and a phone page could fix it today. " * 20
    v = social.write_variant(_rt(store, tmp_path), choice, _material(), "Kiosks need ledgers.",
                             complete=Model(long), profile=prose.default())
    assert len(v["parts"]) == 1
    full = v["parts"][0]
    assert sites.count(site, full) <= site.limit, (sid, sites.count(site, full))
    assert "limits" not in str(v["prose"]["verdict"])     # the check of the words kept
    if site.open_takes_url:
        assert "https://ex.com/source" not in full     # the composer adds the link
    else:
        assert full.endswith("https://ex.com/source")


def test_a_bluesky_thread_only_when_posted_directly_and_each_part_within_300(store, tmp_path):
    site = sites.SITES["bluesky"]
    part = "A claim about ledgers that is long enough to need room. " * 8

    def model(messages, schema):
        if "parts" in json.dumps(schema):
            return {"structured": {"parts": [part, part, part]}, "text": ""}
        if "edits" in json.dumps(schema):
            return {"structured": {"edits": []}, "text": ""}
        return {"structured": {"text": part[:250]}, "text": ""}
    rt = _rt(store, tmp_path)
    opened = social.write_variant(rt, sites.Choice(site), _material(), "x", complete=model,
                                  profile=prose.default())
    assert len(opened["parts"]) == 1                     # Open fills one post
    direct = social.write_variant(rt, sites.Choice(site, direct=True), _material(), "x",
                                  complete=model, profile=prose.default())
    assert len(direct["parts"]) == 3
    assert all(sites.count(site, p) <= 300 for p in direct["parts"])


def test_every_variant_goes_through_compose_check_and_revise(store, tmp_path):
    """The model opens with announced structure; the check flags it and the reviser's words
    are what is kept: no variant opens with "Here's a thread"."""
    model = Model("Here's a thread on why kiosks need ledgers. Kiosks lose batteries daily.",
                  fixed="Kiosks need ledgers: they lose batteries daily.")
    v = social.write_variant(_rt(store, tmp_path), sites.Choice(sites.SITES["bluesky"]),
                             _material(), "Kiosks need ledgers.", complete=model,
                             profile=prose.default())
    system = model.calls[0][0]["content"]
    assert "The site's limits" in system and "Bluesky" in system      # composed for the site
    assert len(model.calls) >= 2                                       # revised
    assert not v["parts"][0].lower().startswith("here's")
    assert v["prose"]["rounds"] >= 1


def test_the_disclosure_line_is_off_by_default_and_reads_the_products_name(store, tmp_path):
    from kranto import product
    rt = _rt(store, tmp_path)
    plain = social.write_variant(rt, sites.Choice(sites.SITES["x"]), _material(), "a",
                                 complete=Model("Kiosks lose batteries."),
                                 profile=prose.default())
    assert "Drafted with" not in plain["parts"][0]
    on = social.write_variant(rt, sites.Choice(sites.SITES["x"], disclose=True), _material(),
                              "a", complete=Model("Kiosks lose batteries."),
                              profile=prose.default())
    assert on["parts"][0].endswith(f"Drafted with {product.NAME}.")


# -- site first: the post's own address, from its own words --------------------------------------

def _connect(store, provider, instance="x", account="@me"):
    cid = store.insert("connections", dict(provider=provider, instance=instance, account=account,
                                           scopes="[]", created_at=iso(utcnow())))
    store.insert("connection_events", dict(connection_id=cid, event="connected", note=None,
                                           created_at=iso(utcnow())))
    return cid


def _blog_draft(store):
    from kranto.core.cubs.brokers.base import new_draft
    return new_draft(store, cub="blog", service="sanity", run_uuid=None, content={
        "title": "Ledgers for battery kiosks", "slug": "ledgers-for-battery-kiosks",
        "excerpt": "Kiosks lose track of batteries.",
        "body": "Every kiosk swaps batteries all day and writes nothing down."})


def test_with_a_site_connected_the_posts_link_to_the_post_and_use_its_words(store, tmp_path):
    _connect(store, "sanity", "proj", "my project")
    set_blob(store, SanitySite.SETTING, SanitySite(post_url="https://me.example/blog"))
    assert social.blog_target(store) is not None
    m = social.from_blog(store, _blog_draft(store), {"ideas": [7]})
    assert m.link == "https://me.example/blog/ledgers-for-battery-kiosks" and m.link_to == "post"
    assert "writes nothing down" in m.facts
    model = Model("Kiosks lose batteries daily.")
    v = social.write_variant(_rt(store, tmp_path), sites.Choice(sites.SITES["bluesky"]), m,
                             "a", complete=model, profile=prose.default())
    assert v["parts"][0].endswith(m.link)
    assert "blog post" in model.calls[0][0]["content"]
    assert any("Put it on your blog before you post this" in e["words"] for e in v["extras"])


def test_without_a_site_the_posts_link_to_the_source(store):
    assert social.blog_target(store) is None
    m = social.from_sources({"title": "t", "facts": "f"}, "https://ex.com/1", {}, "t")
    assert m.link == "https://ex.com/1" and m.link_to == "source"


def test_write_short_writes_the_blog_post_first_then_links_every_variant(store, tmp_path,
                                                                         monkeypatch):
    _connect(store, "sanity", "proj", "my project")
    set_blob(store, SanitySite.SETTING, SanitySite(post_url="https://me.example/blog"))
    set_blob(store, PostingSites.SETTING, PostingSites(sites=["bluesky", "x"]))
    order = []

    def blog_write(rt, about, as_, *, door, angle=None, take=None):
        if as_ == "short":
            return real_write(rt, about, as_, door=door, angle=angle)
        order.append("blog")
        _blog_draft(store)
        return {"cub": "blog"}
    real_write = post_api.write
    monkeypatch.setattr(post_api, "write", blog_write)
    monkeypatch.setattr(post_api, "_sources_of", lambda rt, about: (None, "t", {"ideas": [7]}))

    class LLM:
        has_key = True

        def complete(self, **kw):
            order.append("variant")
            return SimpleNamespace(text=json.dumps({"parts": ["Kiosks lose batteries."]}),
                                   structured={"parts": ["Kiosks lose batteries."]},
                                   model="m")
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path), llm=LLM(),
                         embedder=None)
    out = post_api.write_short(rt, "card:7", "Kiosks need ledgers.", door="ui")
    assert order[0] == "blog" and "Your blog post is written first" in out["say"]
    rows = store.query("SELECT * FROM cub_drafts WHERE cub = ?", (FILER,))
    assert {r["service"] for r in rows} == {"bluesky", "x"}
    for r in rows:
        c = json.loads(r["content"])
        assert c["link"] == "https://me.example/blog/ledgers-for-battery-kiosks"
        assert c["group"] == out["group"]


def test_short_posts_need_ticked_sites(store, tmp_path):
    rt = SimpleNamespace(store=store, cfg=SimpleNamespace(root=tmp_path))
    with pytest.raises(post_api.WriteError) as e:
        post_api.write_short(rt, "card:1", "", door="ui")
    assert e.value.code == 409 and "Settings › Posting" in e.value.words


def test_what_a_short_write_asks_for():
    assert post_api.plan_write("card:3", "short", angle="A claim.") == (
        "short", "short", "short", {"about": "card:3", "angle": "A claim."})
    assert post_api.plan_write("brief:4:1", "short")[3] == {"about": "brief:4:1"}
    with pytest.raises(post_api.WriteError):
        post_api.plan_write("week", "short")


# -- filing, Post's read and the draft's page -----------------------------------------------------

def _write(store, tmp_path, ticked=("bluesky", "x", "mastodon", "threads"), direct=None,
           instance="mastodon.social"):
    set_blob(store, PostingSites.SETTING, PostingSites(sites=list(ticked), direct=direct or {},
                                                       instance=instance))
    rt = _rt(store, tmp_path)
    out = social.write_all(rt, sites.choices(store), _material(), "Kiosks need ledgers.",
                           about="card:7", complete=Model("Kiosks lose batteries daily."),
                           profile=prose.default())
    return rt, out


def test_open_sites_wait_on_post_as_one_row_naming_the_sites(store, tmp_path):
    rt, out = _write(store, tmp_path)
    assert out["written"] == ["bluesky", "mastodon", "x", "threads"] and not out["failed"]
    kinds = {r["kind"] for r in store.query("SELECT kind FROM cub_tickets WHERE cub = ?",
                                            (FILER,))}
    assert kinds == {"post.open"}
    rt.cubs = None
    read = post_api.post_read(rt)
    (row,) = [d for d in read["drafts"] if d.get("write") == out["group"]]
    assert [s["word"] for s in row["sites"]] == ["Bluesky", "Mastodon", "X", "Threads"]
    assert row["word"] == "short posts" and row["title"] == "Battery swap ledger"
    assert "open in the site" in read["sites"]["line"]


def test_the_draft_page_has_open_first_parts_counted_and_siblings(store, tmp_path):
    rt, out = _write(store, tmp_path)
    rt.cubs = None
    bid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ? AND service = 'bluesky'",
                          (FILER,))["id"]
    s = post_api.draft_sheet(rt, bid)
    assert s["tier"] == "open" and s["open"].startswith("https://bsky.app/intent/compose?text=")
    assert s["direct"] is None and s["posted_by_you"] is True
    assert s["limit"] == {"max": 300, "unit": "characters"}
    assert all(p["used"] <= 300 for p in s["parts"])
    assert [x["site"] for x in s["siblings"]] == ["bluesky", "mastodon", "x", "threads"]
    assert any(e["words"].startswith("Links to the source") for e in s["extras"])
    xid = next(x["id"] for x in s["siblings"] if x["site"] == "x")
    sx = post_api.draft_sheet(rt, xid)
    assert len(sx["parts"]) == 1 and "url=https%3A%2F%2Fex.com%2Fsource" in sx["open"]


def test_on_the_preview_open_is_off_in_words(store, tmp_path, monkeypatch):
    rt, _ = _write(store, tmp_path, ticked=("x",))
    from kranto import preview
    monkeypatch.setattr(preview, "enabled", lambda *a, **k: True)
    xid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    s = post_api.draft_sheet(rt, xid)
    assert s["open"] is None and s["open_off"] == "This is the preview: nothing is posted."


def test_post_directly_files_the_sites_own_send_and_open_still_comes_first(store, tmp_path):
    rt, _ = _write(store, tmp_path, ticked=("bluesky",), direct={"bluesky": True})
    (t,) = store.query("SELECT kind, fields FROM cub_tickets WHERE cub = ?", (FILER,))
    assert t["kind"] == "post.bluesky" and json.loads(t["fields"])["parts"] == 1
    bid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    s = post_api.draft_sheet(rt, bid)
    assert s["open"] and s["tier"] == "send"
    assert s["direct"] == {"word": "Post to Bluesky", "ready": False,
                           "why": "Connect Bluesky (posting) on Settings › Posting to post it "
                                  "from here"}


def test_mastodon_posted_directly_uses_the_existing_send(store, tmp_path):
    _write(store, tmp_path, ticked=("mastodon",), direct={"mastodon": True})
    (t,) = store.query("SELECT kind, fields FROM cub_tickets WHERE cub = ?", (FILER,))
    f = json.loads(t["fields"])
    assert t["kind"] == "post.mastodon" and len(f["text"]) <= 500
    d = draft_of(store, f["draft_ref"])
    assert d["content"]["visibility"] == "public" and d["content"]["text"] == f["text"]


# -- I posted it: a record, no request, the page only, never the preview -------------------------

def _no_network(monkeypatch):
    from kranto.sources import base as sbase

    def refuse(*a, **k):
        raise AssertionError("a request left Kranto")
    monkeypatch.setattr(sbase.HTTP, "post", refuse)
    monkeypatch.setattr(sbase.HTTP, "get", refuse)


def test_i_posted_it_records_posted_by_you_and_sends_nothing(store, tmp_path, monkeypatch):
    rt, _ = _write(store, tmp_path, ticked=("x",))
    _no_network(monkeypatch)
    xid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    with pytest.raises(post_api.WriteError) as e:
        post_api.posted_by_you(rt, xid, AGENT)
    assert e.value.code == 403
    out = post_api.posted_by_you(rt, xid, UI)
    assert "Nothing was sent" in out["say"]
    t = tickets.get(store, out["ticket"])
    assert t["state"] == "done" and t["note"] == POSTED_BY_YOU
    rt.cubs = None
    assert [r["id"] for r in post_api.post_read(rt)["sent"]] == [xid]
    with pytest.raises(post_api.WriteError):
        post_api.posted_by_you(rt, xid, UI)                 # once


def test_i_posted_it_is_refused_on_the_preview(store, tmp_path, monkeypatch):
    rt, _ = _write(store, tmp_path, ticked=("x",))
    from kranto import preview
    monkeypatch.setattr(preview, "enabled", lambda *a, **k: True)
    xid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    with pytest.raises(post_api.WriteError) as e:
        post_api.posted_by_you(rt, xid, UI)
    assert e.value.code == 409 and "nothing is sent" in e.value.words


def test_no_door_but_the_page_confirms_a_short_post(store, tmp_path):
    _write(store, tmp_path, ticked=("x", "bluesky"), direct={"bluesky": True})
    for t in store.query("SELECT id FROM cub_tickets WHERE cub = ?", (FILER,)):
        for who in (AGENT, {"origin": "cli"}, {"origin": "assistant"}):
            with pytest.raises(tickets.TicketError) as e:
                tickets.confirm(store, t["id"], identity=who, confirm=True, context=None)
            assert e.value.code == 403 and "page only" in str(e.value)


def test_a_cub_may_not_ask_for_kranto_s_own_posting_kinds():
    for kind in ("post.open", "post.bluesky"):
        assert not tickets.grantable_to(kind, "owner")
        assert tickets.grantable_to(kind, "core")


# -- the edit: counted the site's way --------------------------------------------------------------

def test_an_edit_past_the_sites_limit_is_refused_in_words(store, tmp_path):
    rt, _ = _write(store, tmp_path, ticked=("bluesky",))
    rt.cubs = None
    bid = store.query_one("SELECT id FROM cub_drafts WHERE cub = ?", (FILER,))["id"]
    with pytest.raises(post_api.WriteError) as e:
        post_api.edit_draft(rt, bid, {"parts": [{"text": "x" * 301}]})
    assert "Bluesky takes 300" in e.value.words
    with pytest.raises(post_api.WriteError):
        post_api.edit_draft(rt, bid, {"parts": [{"text": "a"}, {"text": "b"}]})  # Open: one
    out = post_api.edit_draft(rt, bid, {"parts": [{"text": "My own words."}]})
    new = draft_of(store, out["ref"])
    assert parts_of(new["content"]) == ["My own words."] and new["content"]["group"]
    t = tickets.get(store, out["ticket"])
    assert t["kind"] == "post.open" and t["fields"]["text"] == "My own words."


# -- the Bluesky send, against the documented shapes ---------------------------------------------

class Ctx:
    """What the adapter's perform reads; ``send`` answers from ``handler`` and records."""

    def __init__(self, store, handler, connected=True):
        self.store, self.handler, self.sent = store, handler, []
        self.connected = connected
        self.connection = {"id": 1, "state": "connected"} if connected else None
        self.label, self.instance = "@alice.example", "bsky.social"

    def send(self, method, url, *, json=None, **kw):
        self.sent.append((method, url, json))
        return self.handler(len(self.sent), json)


def _bsky_ticket(store, tmp_path, parts):
    from kranto.core.cubs.brokers.base import new_draft
    d = new_draft(store, cub=FILER, service="bluesky", run_uuid=None, content={
        "site": "bluesky", "parts": [{"text": p} for p in parts], "text": parts[0],
        "language": "en", "card": {"url": "https://ex.com/a", "title": "A page",
                                   "description": "d"}})
    fields = {"draft_ref": d["ref"], "text": parts[0], "parts": len(parts), "language": "en"}
    tid = tickets.file(store, cub=FILER, trust="core", granted=("post.bluesky",),
                       kind="post.bluesky", fields=fields, capped=False)
    return tickets.get(store, tid)


def test_a_bluesky_thread_goes_part_by_part_with_facets_and_its_card(store, tmp_path):
    t = _bsky_ticket(store, tmp_path, ["A claim 👍🏽 https://ex.com/a #Ledgers", "The rest."])
    ctx = Ctx(store, lambda n, body: httpx.Response(
        200, json=FIX["createRecord"] if n == 1 else FIX["createRecordReply"]))
    out = bsky.BlueskyAdapter().perform("post.bluesky", t, "live", ctx)
    assert out == {"state": "done",
                   "note": "posted: https://bsky.app/profile/alice.example/post/3lfakepost0001"}
    (m1, u1, b1), (_, _, b2) = ctx.sent
    assert m1 == "POST" and u1 == "https://bsky.social/xrpc/com.atproto.repo.createRecord"
    rec = b1["record"]
    assert rec["embed"]["external"]["uri"] == "https://ex.com/a"
    link = next(f for f in rec["facets"] if f["features"][0]["$type"].endswith("#link"))
    raw = rec["text"].encode()
    assert raw[link["index"]["byteStart"]:link["index"]["byteEnd"]] == b"https://ex.com/a"
    assert b2["record"]["reply"]["root"]["uri"] == FIX["createRecord"]["uri"]


def test_a_bluesky_thread_that_stops_half_way_says_so_and_retries_nothing(store, tmp_path):
    t = _bsky_ticket(store, tmp_path, ["One.", "Two.", "Three."])
    ctx = Ctx(store, lambda n, body: httpx.Response(200, json=FIX["createRecord"]) if n == 1
              else httpx.Response(400, json=FIX["invalid"]))
    out = bsky.BlueskyAdapter().perform("post.bluesky", t, "live", ctx)
    assert out["state"] == "unknown" and out["note"].startswith("posted 1 of 3 on Bluesky")
    assert len(ctx.sent) == 2


def test_bluesky_refusals_and_timeouts_in_words(store, tmp_path):
    from kranto.sources.base import SourceError
    t = _bsky_ticket(store, tmp_path, ["One."])
    refused = bsky.BlueskyAdapter().perform(
        "post.bluesky", t, "live", Ctx(store, lambda n, b: httpx.Response(400,
                                                                         json=FIX["invalid"])))
    assert refused == {"state": "refused",
                       "note": "refused: Record/text must not be longer than 3000 graphemes"}

    def timeout(n, b):
        raise SourceError("Timeout", transient=True, sent=True)
    unsure = bsky.BlueskyAdapter().perform("post.bluesky", t, "live", Ctx(store, timeout))
    assert unsure["state"] == "unknown"
    off = bsky.BlueskyAdapter().perform("post.bluesky", t, "live",
                                        Ctx(store, timeout, connected=False))
    assert off["state"] == "refused" and "not connected" in off["note"]


def test_a_changed_bluesky_draft_is_refused_at_the_press(store, tmp_path):
    t = _bsky_ticket(store, tmp_path, ["One."])
    t = {**t, "fields": {**t["fields"], "text": "Other words."}}
    out = bsky.BlueskyAdapter().perform("post.bluesky", t, "live", Ctx(store, None))
    assert out["state"] == "refused" and "changed" in out["note"]


def test_the_preview_refuses_a_bluesky_send_before_it_leaves(store, tmp_path, monkeypatch):
    from kranto import preview
    from kranto.core.cubs.brokers.base import BrokerContext
    from kranto.sources.base import SourceError
    monkeypatch.setattr(preview, "enabled", lambda *a, **k: True)
    ctx = BrokerContext(store=store, cub=FILER, rt=SimpleNamespace(cfg=SimpleNamespace(
        root=tmp_path)), provider="bluesky_post")
    with pytest.raises(SourceError) as e:
        ctx.send("POST", "https://bsky.social/xrpc/com.atproto.repo.createRecord", json={})
    assert not e.value.sent and "nothing is sent" in str(e.value)


# -- the posting connection ---------------------------------------------------------------------

def test_the_bluesky_posting_connection_checks_the_app_password_once():
    from kranto.connections.bluesky_post import BlueskyPostProvider
    from kranto.connections.oauth import OAuthError
    from kranto.sources.base import HTTP
    jwt = secrets.token_urlsafe(24)
    seen = []

    def handler(request):
        seen.append(request.url.path)
        body = json.loads(request.content)
        if body["password"] == "wrong-one":
            return httpx.Response(401, json=FIX["expired"])
        return httpx.Response(200, json={**FIX["createSession"], "accessJwt": jwt})
    http = HTTP(transport=httpx.MockTransport(handler), resolver=lambda h: ["93.184.216.34"])
    p = BlueskyPostProvider(http)
    pw = "-".join(secrets.token_hex(2) for _ in range(4))
    g = p.paste({"handle": "@Alice.example", "app_password": pw})
    assert g.account == "@alice.example" and g.secrets["access_token"] == jwt
    assert seen == ["/xrpc/com.atproto.server.createSession"]
    assert p.paste_instance({}) == "bsky.social"
    with pytest.raises(OAuthError, match="refused this handle"):
        p.paste({"handle": "alice.example", "app_password": "wrong-one"})


# -- Settings › Posting's choices ---------------------------------------------------------------

def test_posting_refuses_what_is_not_offered_in_words(store):
    with pytest.raises(post_api.WriteError, match="Substack has no link"):
        post_api.posting_write(store, {"sites": ["substack"]})
    with pytest.raises(post_api.WriteError, match="cannot be posted from Kranto"):
        post_api.posting_write(store, {"direct": {"x": True}})
    with pytest.raises(post_api.WriteError, match="host name"):
        post_api.posting_write(store, {"instance": "not a host"})
    out = post_api.posting_write(store, {"sites": ["x", "bluesky"], "direct": {"bluesky": True},
                                         "instance": "https://Mastodon.Social/"})
    got = {s["id"]: s for s in out["sites"]}
    assert got["x"]["ticked"] and got["bluesky"]["direct"] and not got["x"]["direct"]
    assert got["mastodon"]["instance"] == "mastodon.social"
    assert {g["id"] for g in out["not_offered"]} >= {"substack"}
    assert got["linkedin"]["ways"] == ["direct"]
    assert out["disclosure"].startswith("Drafted with ")


# -- the stored-field readers: a draft from before, a key stored as null -------------------------

def test_readers_take_a_draft_from_before_and_keys_stored_as_null(store, tmp_path):
    from kranto.core.cubs.brokers.base import new_draft
    old = new_draft(store, cub="toot", service="mastodon", run_uuid=None,
                    content={"text": "An old toot.", "visibility": "public", "language": "en"})
    nulls = new_draft(store, cub=FILER, service="bluesky", run_uuid=None, content={
        "site": None, "group": None, "parts": None, "text": "Words.", "extras": None,
        "link": None, "about_title": None, "instance": None})
    assert parts_of({"parts": None, "text": "Words."}) == ["Words."]
    assert parts_of({"parts": [{"text": None}], "text": None}) == []
    rt = _rt(store, tmp_path)
    rt.cubs = None
    read = post_api.post_read(rt)
    ids = {d["id"] for d in read["earlier"] + read["drafts"]}
    assert {old["id"], nulls["id"]} <= ids
    s = post_api.draft_sheet(rt, nulls["id"])
    assert s["site"] == "bluesky" and s["parts"] == [{"text": "Words.", "used": 6}]
    assert s["siblings"] == [] and s["extras"] == []
    assert post_api.draft_sheet(rt, old["id"]).get("site") is None     # not a short post
    store.set_setting(PostingSites.SETTING, json.dumps({"sites": None, "direct": None,
                                                        "instance": None, "disclose": None}))
    assert sites.choices(store) == []
    assert post_api.posting_read(store)["sites"][0]["ticked"] is False
    unknown = new_draft(store, cub=FILER, service="later-site", run_uuid=None,
                        content={"site": "later-site", "text": "From a later Kranto."})
    s = post_api.draft_sheet(rt, unknown["id"])
    assert s["site_word"] == "later-site" and s["open"] is None

