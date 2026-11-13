"""The Sanity broker against a fake Sanity (``httpx.MockTransport``; nothing leaves
the machine): the connection's Save and test, every operation through the host's
``broker.call``, the read-back with the whole body, and every outcome of the owner's press
(dry, filed, filed again unchanged, refused when published, when the slug is taken, when edited
in Studio, on 409 and 403, unknown on a dropped line). Never a publish, never an id outside
``drafts.kranto-``.

Every token here is made at runtime (``secrets``); none is a literal.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import uuid

import httpx
import pytest

from kranto import library
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.connections import Connections, OAuthError
from kranto.core import tickets
from kranto.core.cubs import brokers
from kranto.core.cubs import settings as cub_settings
from kranto.core.cubs.brokers.sanity import META, written_hash
from kranto.core.cubs.host import CubHost
from kranto.core.cubs.process import RpcError
from kranto.runtime import open_runtime
from kranto.sources import HTTP
from kranto.sources.pacing import Hosts

from .conftest import chat_response, llm_config
from .cubhelp import install, runtime

UI = {"origin": "ui", "via": "cookie"}
PROJECT = "abcd1234"
HOST = f"{PROJECT}.api.sanity.io"
BODY = "Two items.\n\n## One\n\nThe first.\n\n## Two\n\nThe second."


class FakeSanity:
    """``<project>.api.sanity.io``: doc, query and mutate, with drafts visible to the token."""

    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(40)
        self.docs: dict[str, dict] = {}
        self.categories = {"category-d": "Dispatch"}
        self.requests: list[httpx.Request] = []
        self.reply = None                  # (status, json) or an exception, for a mutate
        self.rev = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "Unauthorized",
                                             "message": "Session not found"})
        path = request.url.path
        if path.startswith("/v2021-06-07/data/doc/production/"):
            ids = path.rsplit("/", 1)[-1].split(",")
            return httpx.Response(200, json={
                "documents": [self.docs[i] for i in ids if i in self.docs],
                "omitted": [{"id": i, "reason": "existence"} for i in ids if i not in self.docs]})
        if path == "/v2021-06-07/data/query/production":
            q = request.url.params["query"]
            if q.startswith("count("):
                return httpx.Response(200, json={"result": sum(
                    1 for i in self.docs if i.startswith("drafts."))})
            if "category" in q:
                titles = json.loads(request.url.params["$titles"])
                hit = next((i for i, t in self.categories.items() if t.lower() in titles), None)
                return httpx.Response(200, json={"result": hit})
            slug, ours = json.loads(request.url.params["$slug"]), \
                json.loads(request.url.params["$ours"])
            hit = next((i for i, d in self.docs.items() if i not in ours
                        and (d.get("slug") or {}).get("current") == slug), None)
            return httpx.Response(200, json={"result": hit})
        if path == "/v2021-06-07/data/mutate/production" and request.method == "POST":
            if self.reply is not None:
                if isinstance(self.reply, Exception):
                    raise self.reply
                return httpx.Response(self.reply[0], json=self.reply[1])
            results = []
            for m in json.loads(request.content)["mutations"]:
                (op, body), = m.items()
                assert op in ("create", "patch"), op
                if op == "create":
                    if body["_id"] in self.docs:
                        return httpx.Response(409, json={"error": {"type": "mutationError"}})
                    self.rev += 1
                    self.docs[body["_id"]] = {**body, "_rev": f"r{self.rev}"}
                    results.append({"id": body["_id"], "operation": "create"})
                else:
                    doc = self.docs[body["id"]]
                    if body.get("ifRevisionID") != doc["_rev"]:
                        return httpx.Response(409, json={"error": {"type": "mutationError"}})
                    self.rev += 1
                    doc.update(body["set"], _rev=f"r{self.rev}")
                    results.append({"id": body["id"], "operation": "update"})
            return httpx.Response(200, json={"transactionId": "t", "results": results})
        return httpx.Response(404, json={"error": "Not found"})

    def writes(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method != "GET"]


@pytest.fixture
def fake():
    return FakeSanity()


@pytest.fixture
def srt(tmp_path, store, embedder, make_client, fake, monkeypatch):
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))

    def route(request: httpx.Request) -> httpx.Response:
        return fake(request) if request.url.host == HOST else httpx.Response(404)

    machine = tmp_path / "machine-id"
    machine.write_text(secrets.token_hex(16) + "\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(signal_threshold=0.20), map=MapConfig())
    http = HTTP(transport=httpx.MockTransport(route), resolver=lambda h: ["93.184.216.34"],
                hosts=Hosts(default_gap=0, sleep=lambda s: None))
    conns = Connections(store, cfg.data_dir, http, machine_id=machine)
    rt = open_runtime(cfg, store=store, embedder=embedder,
                      llm=make_client(lambda body: chat_response("{}")), http=http,
                      connections=conns)
    library.add_topic(store, embedder, "energy", "solar and batteries")
    r = runtime(rt)
    install(rt, "filer")
    yield rt
    r.stop_all("host")


def call(rt, op: str, **args) -> dict:
    h = CubHost(rt.cubs, rt.cubs.installed["filer"], run_uuid=str(uuid.uuid4()), run_log=None)
    return h.dispatch("broker.call", {"service": "sanity", "op": op, "args": args})


def connect(rt, fake, **extra) -> dict:
    return rt.connections.paste("sanity", {"project": PROJECT, "dataset": "production",
                                           "token": fake.token, **extra})


def live(rt) -> None:
    rt.cfg = dataclasses.replace(rt.cfg, cubs=cub_settings.parse({"filer": {
        "live": ["draft.sanity"]}}))


def post(rt, doc: str = "brief-12", slug: str = "a-week", **extra) -> tuple[dict, int]:
    args = {"doc": doc, "title": "A week", "slug": slug, "body": BODY, "category": "dispatch",
            **extra}
    d = call(rt, "documents.draft", **args)
    tid = tickets.file(rt.store, cub="filer", trust="owner", granted=("draft.sanity",),
                       kind="draft.sanity", fields={"draft_ref": d["draft_ref"],
                                                    "title": args["title"], "slug": slug,
                                                    "category": "dispatch"})
    return d, tid


def press(rt, tid: int) -> dict:
    return tickets.confirm(rt.store, tid, identity=UI, confirm=True, context=rt)


# -- the tables and the connection ----------------------------------------------------------


def test_the_kind_and_the_ops():
    spec = tickets.KINDS["draft.sanity"]
    assert (spec.expires_hours, spec.per_day, spec.page_only) == (None, 3, True)
    assert list(spec.fields) == ["draft_ref", "title", "slug", "category"]
    assert brokers.grantable()["sanity"] == {"documents.draft", "documents.get", "drafts.list"}
    assert not any(o for o in brokers.ADAPTERS["sanity"].ops if "publish" in o
                   or "delete" in o)


def test_save_and_test_reads_and_names_the_connection(srt, fake):
    conn = connect(srt, fake, studio="https://example-blog.sanity.studio",
                   post_url="https://example.com/blog")
    assert conn["account"] == f"{PROJECT}/production" and conn["state"] == "connected"
    assert "0 drafts" in conn["said"] and not fake.writes()
    with pytest.raises(OAuthError, match="refused this token"):
        srt.connections.paste("sanity", {"project": PROJECT, "token": secrets.token_hex(8)})
    with pytest.raises(OAuthError, match="project id"):
        srt.connections.paste("sanity", {"project": "Not A Project", "token": fake.token})
    with pytest.raises(OAuthError, match="https://"):
        connect(srt, fake, studio="http://insecure.example")


# -- the operations ----------------------------------------------------------------------------


def test_a_draft_is_kranto_own_and_needs_no_connection(srt, fake):
    d = call(srt, "documents.draft", doc="brief-12", title="A week", slug="a-week", body=BODY,
             category="dispatch", tags="Kranto, AI agents, Kranto", origin="brief",
             cites="brief 12")
    assert d["where"] == "kranto" and d["sanity_id"] == "drafts.kranto-brief-12"
    assert not fake.requests
    listed = call(srt, "drafts.list")["drafts"]
    assert listed[0]["title"] == "A week"
    row = srt.store.query_one("SELECT content FROM cub_drafts WHERE ref = ?", (d["draft_ref"],))
    assert json.loads(row["content"])["tags"] == ["Kranto", "AI agents"]


@pytest.mark.parametrize("args, word", [
    ({"slug": "Not A Slug"}, "slug"), ({"doc": "../x"}, "doc"),
    ({"category": "notes"}, "category"), ({"body": "---\ntitle: x\n---\nhi"}, "frontmatter")])
def test_a_draft_out_of_shape_is_refused(srt, args, word):
    base = {"doc": "brief-12", "title": "A week", "slug": "a-week", "body": BODY,
            "category": "dispatch"}
    with pytest.raises(RpcError) as got:
        call(srt, "documents.draft", **{**base, **args})
    assert got.value.code == -32005 and word in got.value.message


def test_documents_get_needs_the_connection_and_says_where_it_is(srt, fake):
    d, _ = post(srt)
    with pytest.raises(RpcError) as got:
        call(srt, "documents.get", draft_ref=d["draft_ref"])
    assert got.value.code == -32013
    connect(srt, fake)
    got = call(srt, "documents.get", draft_ref=d["draft_ref"])
    assert got["in_sanity"] is False and got["published"] is False


# -- the read-back -----------------------------------------------------------------------------


def test_the_readback_shows_the_whole_body_and_where_it_goes(srt, fake):
    connect(srt, fake, studio="https://example-blog.sanity.studio",
            post_url="https://example.com/blog")
    _, tid = post(srt, email_teaser="Read this.", x_post="A claim https://example.com/x")
    lines = dict(tickets.get(srt.store, tid)["readback"])
    assert lines["Body"] == BODY
    assert lines["Files as"] == f"drafts.kranto-brief-12 in {PROJECT}/production"
    assert "https://example.com/blog/a-week" in lines["Slug"]
    assert lines["Email teaser"] == "Read this." and lines["LinkedIn post"] == "none"
    assert lines["Studio"].endswith("/intent/edit/id=kranto-brief-12;type=post")
    assert "never publishes" in lines["Publishing"]


# -- the press ---------------------------------------------------------------------------------


def test_dry_writes_nothing_and_says_what_live_would(srt, fake):
    connect(srt, fake)
    _, tid = post(srt)
    out = press(srt, tid)
    assert out["state"] == "dry" and "drafts.kranto-brief-12" in out["note"]
    assert not fake.writes()


def test_live_files_one_draft_with_its_hash_and_category(srt, fake):
    connect(srt, fake)
    live(srt)
    _, tid = post(srt, tags="kranto", email_teaser="Read this.")
    out = press(srt, tid)
    assert out["state"] == "done" and out["note"].startswith("filed: drafts.kranto-brief-12")
    doc = fake.docs["drafts.kranto-brief-12"]
    assert doc["_type"] == "post" and "publishedAt" not in doc
    assert doc["markdownBody"] == BODY and doc["emailTeaser"] == "Read this."
    assert doc["categories"][0]["_ref"] == "category-d"
    assert doc[META]["contentHash"] == written_hash(doc)
    assert [r.url.path for r in fake.writes()] == ["/v2021-06-07/data/mutate/production"]
    assert all(m.get("create", {}).get("_id", "drafts.kranto-").startswith("drafts.kranto-")
               for r in fake.writes() for m in json.loads(r.content)["mutations"])


def test_filing_again_unchanged_is_done_and_a_redraft_patches_with_the_revision(srt, fake):
    connect(srt, fake)
    live(srt)
    _, first = post(srt)
    press(srt, first)
    _, same = post(srt)
    out = press(srt, same)
    assert out["state"] == "done" and "unchanged" in out["note"] and len(fake.writes()) == 1
    _, again = post(srt, excerpt="A redraft's excerpt.")
    out = press(srt, again)
    assert out["state"] == "done" and fake.docs["drafts.kranto-brief-12"]["excerpt"] == \
        "A redraft's excerpt."
    patch = json.loads(fake.writes()[-1].content)["mutations"][0]["patch"]
    assert patch["ifRevisionID"] == "r1"


def test_a_draft_edited_in_studio_is_never_overwritten(srt, fake):
    connect(srt, fake)
    live(srt)
    _, first = post(srt)
    press(srt, first)
    fake.docs["drafts.kranto-brief-12"]["title"] = "The owner's own title"
    _, again = post(srt, excerpt="A redraft.")
    out = press(srt, again)
    assert out["state"] == "refused" and "edited in Studio" in out["note"]
    assert fake.docs["drafts.kranto-brief-12"]["title"] == "The owner's own title"


def test_a_published_post_or_a_taken_slug_is_refused(srt, fake):
    connect(srt, fake)
    live(srt)
    fake.docs["kranto-brief-12"] = {"_id": "kranto-brief-12", "_rev": "p1"}
    _, tid = post(srt)
    assert "published already" in press(srt, tid)["note"]
    fake.docs["other"] = {"_id": "other", "_rev": "o1", "slug": {"current": "taken"}}
    _, tid = post(srt, doc="brief-13", slug="taken")
    out = press(srt, tid)
    assert out["state"] == "refused" and "already has the slug taken" in out["note"]
    assert not fake.writes()


@pytest.mark.parametrize("reply, state, word", [
    ((409, {"error": {"type": "mutationError"}}), "refused", "changed in Sanity"),
    ((403, {"error": "Forbidden"}), "refused", "may not write"),
    ((400, {"error": {"type": "mutationError", "description": "a quoted body"}}), "refused",
     "mutationError"),
    (httpx.ReadError("dropped"), "unknown", "look at Sanity")])
def test_the_service_saying_no_or_nothing(srt, fake, reply, state, word):
    connect(srt, fake)
    live(srt)
    fake.reply = reply
    _, tid = post(srt)
    out = press(srt, tid)
    assert out["state"] == state and word in out["note"]
    assert "a quoted body" not in out["note"]


def test_live_without_a_connection_is_refused(srt, fake):
    live(srt)
    _, tid = post(srt)
    out = press(srt, tid)
    assert out["state"] == "refused" and "not connected" in out["note"] and not fake.requests


def test_a_ticket_that_is_not_its_draft_is_refused(srt, fake):
    connect(srt, fake)
    live(srt)
    d, _ = post(srt)
    tid = tickets.file(srt.store, cub="filer", trust="owner", granted=("draft.sanity",),
                       kind="draft.sanity", fields={"draft_ref": d["draft_ref"],
                                                    "title": "Another title", "slug": "a-week",
                                                    "category": "dispatch"})
    out = press(srt, tid)
    assert out["state"] == "refused" and "title" in out["note"] and not fake.writes()
