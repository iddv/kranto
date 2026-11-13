"""Short posts posted directly to LinkedIn and Threads (the person's own apps): the requests
Kranto would send and how it reads each answer, against the documented shapes in
``tests/fixtures/social/``. Nothing is posted: every request goes to a fake ``send``."""

from __future__ import annotations

import json
import secrets
from pathlib import Path

import httpx
import pytest

from kranto.core import sites, tickets
from kranto.core.cubs.brokers import linkedin as li
from kranto.core.cubs.brokers import threads as th
from kranto.core.cubs.brokers.base import new_draft
from kranto.core.cubs.brokers.social import FILER

HERE = Path(__file__).parent / "fixtures" / "social"
LI = json.loads((HERE / "linkedin.json").read_text())
TH = json.loads((HERE / "threads.json").read_text())


class Ctx:
    def __init__(self, store, handler, connected=True):
        self.store, self.handler, self.sent = store, handler, []
        self.connected = connected
        self.connection = {"id": 1, "state": "connected"} if connected else None
        self.label, self.instance = "Alex Example", "api.linkedin.com"

    def send(self, method, url, *, json=None, data=None, headers=None, params=None):
        self.sent.append({"method": method, "url": url, "json": json, "data": data,
                          "headers": headers, "params": params})
        return self.handler(self.sent[-1])


def _ticket(store, site, kind, text, **extra):
    d = new_draft(store, cub=FILER, service=site, run_uuid=None, content={
        "site": site, "parts": [{"text": text}], "text": text, "link": "https://ex.com/a",
        "card": {"url": "https://ex.com/a", "title": "A page", "description": "Teaser"},
        **extra})
    tid = tickets.file(store, cub=FILER, trust="core", granted=(kind,), kind=kind,
                       fields={"draft_ref": d["ref"], "text": text}, capped=False)
    return tickets.get(store, tid)


# -- the registry ------------------------------------------------------------------------------

def test_linkedin_is_offered_only_as_post_directly_and_threads_opens_first():
    assert sites.SITES["linkedin"].ways() == ("direct",)
    assert sites.SITES["threads"].ways() == ("open", "direct")
    assert "linkedin" not in sites.NOT_OFFERED and "substack" in sites.NOT_OFFERED


# -- LinkedIn -------------------------------------------------------------------------------------

def test_little_text_escapes_every_reserved_character_and_keeps_tags():
    assert li.little("a (b) [c] @d *e* _f_ ~g~ <h> {i} | \\") == \
        "a \\(b\\) \\[c\\] \\@d \\*e\\* \\_f\\_ \\~g\\~ \\<h\\> \\{i\\} \\| \\\\"
    assert li.little("on #OpenSource today") == "on {hashtag|\\#|OpenSource} today"


def test_a_linkedin_post_goes_with_its_author_card_and_version(store):
    t = _ticket(store, "linkedin", "post.linkedin", "Kiosks lose batteries (daily). #Ledgers")

    def handler(req):
        if req["method"] == "GET":
            return httpx.Response(200, json=LI["userinfo"])
        return httpx.Response(201, headers={"x-restli-id": LI["created_id"]})
    ctx = Ctx(store, handler)
    out = li.LinkedInAdapter().perform("post.linkedin", t, "live", ctx)
    assert out == {"state": "done", "note": "posted: https://www.linkedin.com/feed/update/"
                                            "urn:li:share:6844785523593134080/"}
    who, post = ctx.sent
    assert who["url"] == "https://api.linkedin.com/v2/userinfo"
    assert post["url"] == "https://api.linkedin.com/rest/posts"
    assert post["headers"] == {"Linkedin-Version": "202610", "X-Restli-Protocol-Version": "2.0.0"}
    body = post["json"]
    assert body["author"] == "urn:li:person:782bbtaQ"
    assert body["commentary"] == "Kiosks lose batteries \\(daily\\). {hashtag|\\#|Ledgers}"
    assert body["content"]["article"] == {"source": "https://ex.com/a", "title": "A page",
                                          "description": "Teaser"}
    assert body["lifecycleState"] == "PUBLISHED" and body["visibility"] == "PUBLIC"


@pytest.mark.parametrize("status,fixture,word", [(401, "expired", "refused"),
                                                 (400, "too_long", "Reduce the length"),
                                                 (429, "throttled", "rate limited")])
def test_linkedin_refusals_in_words(store, status, fixture, word):
    from kranto.sources.base import SourceError
    t = _ticket(store, "linkedin", "post.linkedin", "Words.")

    def handler(req):
        if req["method"] == "GET":
            return httpx.Response(200, json=LI["userinfo"])
        if status in (401, 429):
            raise SourceError(f"HTTP {status}", needs_login=status == 401, status=status,
                              sent=True)
        return httpx.Response(status, json=LI[fixture])
    out = li.LinkedInAdapter().perform("post.linkedin", t, "live", Ctx(store, handler))
    assert out["state"] == "refused" and word.lower() in out["note"].lower()


def test_linkedin_not_connected_or_changed_is_refused_before_any_request(store):
    t = _ticket(store, "linkedin", "post.linkedin", "Words.")
    ctx = Ctx(store, None, connected=False)
    assert li.LinkedInAdapter().perform("post.linkedin", t, "live", ctx)["state"] == "refused"
    changed = {**t, "fields": {**t["fields"], "text": "Other."}}
    assert "changed" in li.LinkedInAdapter().perform("post.linkedin", changed, "live",
                                                     Ctx(store, None))["note"]
    assert ctx.sent == []


def test_the_linkedin_connection_checks_the_token_with_userinfo():
    from kranto.connections.linkedin_post import LinkedInPostProvider
    from kranto.connections.oauth import OAuthError
    from kranto.sources.base import HTTP
    good = secrets.token_urlsafe(24)

    def handler(request):
        assert request.url.path == "/v2/userinfo"
        if request.headers.get("authorization") != f"Bearer {good}":
            return httpx.Response(401, json=LI["expired"])
        return httpx.Response(200, json=LI["userinfo"])
    p = LinkedInPostProvider(HTTP(transport=httpx.MockTransport(handler),
                                  resolver=lambda h: ["93.184.216.34"]))
    g = p.paste({"token": good})
    assert g.account == "Alex Example" and g.secrets["sub"] == "782bbtaQ"
    assert g.secrets["expires_by"] - g.secrets["made_at"] == 60 * 86400
    with pytest.raises(OAuthError, match="refused this token"):
        p.paste({"token": secrets.token_urlsafe(24)})


# -- Threads --------------------------------------------------------------------------------------

def test_a_threads_post_waits_for_its_container_then_publishes(store):
    t = _ticket(store, "threads", "post.threads", "Kiosks lose batteries daily.",
                topic_tag="Batteries")
    states = iter([TH["in_progress"], TH["finished"]])

    def handler(req):
        if req["method"] == "POST" and req["url"].endswith("/me/threads"):
            return httpx.Response(200, json=TH["container"])
        if req["method"] == "GET" and req["params"] == {"fields": "status,error_message"}:
            return httpx.Response(200, json=next(states))
        if req["url"].endswith("/me/threads_publish"):
            return httpx.Response(200, json=TH["published"])
        return httpx.Response(200, json=TH["permalink"])
    a = th.ThreadsAdapter()
    slept = []
    a.sleep = slept.append
    ctx = Ctx(store, handler)
    out = a.perform("post.threads", t, "live", ctx)
    assert out == {"state": "done", "note": "posted: https://www.threads.com/"
                                            "@threadsapitestuser/post/abcdefg"}
    create = ctx.sent[0]
    assert create["url"] == "https://graph.threads.com/v1.0/me/threads"
    assert create["data"] == {"media_type": "TEXT", "text": "Kiosks lose batteries daily.",
                              "link_attachment": "https://ex.com/a", "topic_tag": "Batteries"}
    assert slept == [th.POLL_S]
    publish = next(s for s in ctx.sent if s["url"].endswith("threads_publish"))
    assert publish["data"] == {"creation_id": TH["container"]["id"]}


def test_a_threads_container_that_never_finishes_publishes_nothing(store):
    t = _ticket(store, "threads", "post.threads", "Words.")

    def handler(req):
        if req["method"] == "POST":
            return httpx.Response(200, json=TH["container"])
        return httpx.Response(200, json=TH["error_status"])
    ctx = Ctx(store, handler)
    out = th.ThreadsAdapter().perform("post.threads", t, "live", ctx)
    assert out["state"] == "refused" and "nothing was published" in out["note"]
    assert not any(s["url"].endswith("threads_publish") for s in ctx.sent)


def test_threads_refusals_in_words(store):
    t = _ticket(store, "threads", "post.threads", "Words.")
    out = th.ThreadsAdapter().perform("post.threads", t, "live", Ctx(
        store, lambda req: httpx.Response(400, json=TH["links"])))
    assert out == {"state": "refused", "note": "refused: THREADS_API__LINK_LIMIT_EXCEEDED"}


def test_the_threads_connection_names_the_account_and_refreshes_after_a_day(monkeypatch):
    import time

    from kranto.connections.oauth import OAuthError
    from kranto.connections.threads_post import ThreadsPostProvider
    from kranto.sources.base import HTTP
    fresh = secrets.token_urlsafe(24)

    def handler(request):
        if request.url.path == "/refresh_access_token":
            assert request.url.params["grant_type"] == "th_refresh_token"
            return httpx.Response(200, json={**TH["refresh"], "access_token": fresh})
        return httpx.Response(200, json=TH["me"])
    p = ThreadsPostProvider(HTTP(transport=httpx.MockTransport(handler),
                                 resolver=lambda h: ["93.184.216.34"]))
    g = p.paste({"token": secrets.token_urlsafe(24)})
    assert g.account == "@threadsapitestuser"
    with pytest.raises(OAuthError, match="under a day old"):
        p.refresh("graph.threads.com", g.secrets)
    old = {**g.secrets, "made_at": time.time() - 2 * 86400}
    new = p.refresh("graph.threads.com", old)
    assert new["access_token"] == fresh and new["expires_at"] > time.time() + 59 * 86400


# -- the writer and the choices -------------------------------------------------------------------

def test_ticking_linkedin_means_post_directly_and_files_its_send(store, tmp_path):
    from types import SimpleNamespace

    from kranto import prose, social
    from kranto.stored.settings import PostingSites, set_blob
    set_blob(store, PostingSites.SETTING, PostingSites(sites=["linkedin", "threads"],
                                                       direct={"threads": True}))
    ch = {c.site.id: c for c in sites.choices(store)}
    assert ch["linkedin"].direct and ch["threads"].direct

    def model(messages, schema):
        if "parts" in json.dumps(schema):
            return {"structured": {"parts": ["Kiosks lose batteries daily. #Ledgers"]}}
        return {"structured": {"edits": []}}
    m = social.Material(title="Battery ledger", facts="[1] kiosks", link="https://ex.com/a",
                        card={"url": "https://ex.com/a", "title": "Battery ledger",
                              "description": ""})
    out = social.write_all(SimpleNamespace(store=store, embedder=None), list(ch.values()), m,
                           "a", about="card:9", complete=model, profile=prose.default())
    assert sorted(out["written"]) == ["linkedin", "threads"], out
    kinds = {r["kind"] for r in store.query("SELECT kind FROM cub_tickets WHERE cub = ?",
                                            (FILER,))}
    assert kinds == {"post.linkedin", "post.threads"}
