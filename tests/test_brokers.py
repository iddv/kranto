"""The broker adapters: Buttondown and Mastodon against fake services
(``httpx.MockTransport``; nothing leaves the machine), every operation through the host's
``broker.call``, every outcome of the owner's press (dry, done, refused per status, unknown),
the version header, the idempotency key, the frontmatter refusal, the rate windows and
``-32013``; the two connection providers; the money broker listed and never grantable.

Every key and token here is made at runtime (``secrets``); none is a literal.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import uuid
from urllib.parse import parse_qs

import httpx
import pytest

from kranto import library
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.connections import Connections, OAuthError
from kranto.core import registry, tickets
from kranto.core.cubs import brokers
from kranto.core.cubs import settings as cub_settings
from kranto.core.cubs.host import CubHost
from kranto.core.cubs.process import RpcError
from kranto.core.manifest import ManifestError
from kranto.runtime import open_runtime
from kranto.sources import HTTP
from kranto.sources.pacing import Hosts

from .conftest import chat_response, llm_config
from .cubhelp import install, needs_bwrap, runtime

UI = {"origin": "ui", "via": "cookie"}
INSTANCE = "masto.example"


class FakeButtondown:
    """api.buttondown.com: newsletters, subscribers, emails (draft, send by status)."""

    def __init__(self) -> None:
        self.key = secrets.token_hex(20)
        self.emails: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.reply = None                 # (status, json) or an exception, for every write

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Token {self.key}":
            return httpx.Response(401, json={"detail": "Invalid token."})
        if request.headers.get("x-api-version") != "2026-04-01":
            return httpx.Response(400, json={"code": "api_version_missing"})
        path = request.url.path
        if request.method in ("POST", "PATCH") and self.reply is not None:
            if isinstance(self.reply, Exception):
                raise self.reply
            return httpx.Response(self.reply[0], json=self.reply[1])
        if path == "/v1/newsletters":
            return httpx.Response(200, json={"results": [{"id": "n1", "name": "Kranto Weekly",
                                                          "username": "kranto"}], "count": 1})
        if path == "/v1/subscribers":
            return httpx.Response(200, json={"results": [], "count": 148})
        if path == "/v1/emails" and request.method == "POST":
            body = json.loads(request.content)
            eid = str(uuid.uuid4())
            self.emails[eid] = body
            return httpx.Response(201, json={"id": eid, **body,
                                             "absolute_url": f"https://buttondown.com/x/{eid}"})
        if path.startswith("/v1/emails/"):
            eid = path.rsplit("/", 1)[-1]
            if eid not in self.emails:
                return httpx.Response(404, json={"code": "not_found"})
            if request.method == "PATCH":
                self.emails[eid].update(json.loads(request.content))
            return httpx.Response(200, json={"id": eid, **self.emails[eid]})
        return httpx.Response(404, json={"code": "not_found"})

    def sends(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.method in ("POST", "PATCH")
                and b"about_to_send" in r.content]


class FakeInstance:
    """A Mastodon instance's posting side: verify_credentials, the instance, statuses."""

    def __init__(self) -> None:
        self.token = secrets.token_urlsafe(32)
        self.max_characters = 1000
        self.statuses: list[dict] = []
        self.requests: list[httpx.Request] = []
        self.reply = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.headers.get("authorization") != f"Bearer {self.token}":
            return httpx.Response(401, json={"error": "The access token is invalid"})
        path = request.url.path
        if path == "/api/v1/accounts/verify_credentials":
            return httpx.Response(200, json={"acct": "ian", "display_name": "Ian",
                                             "url": f"https://{INSTANCE}/@ian"})
        if path == "/api/v2/instance":
            return httpx.Response(200, json={"configuration": {"statuses": {
                "max_characters": self.max_characters}}})
        if path == "/api/v1/statuses" and request.method == "POST":
            if self.reply is not None:
                if isinstance(self.reply, Exception):
                    raise self.reply
                return httpx.Response(self.reply[0], json=self.reply[1])
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            self.statuses.append(form)
            n = len(self.statuses)
            return httpx.Response(200, json={"id": str(n), "url": f"https://{INSTANCE}/@ian/{n}"})
        return httpx.Response(404, json={"error": "Record not found"})


@pytest.fixture
def fakes():
    return FakeButtondown(), FakeInstance()


@pytest.fixture
def brt(tmp_path, store, embedder, make_client, fakes, monkeypatch):
    """A runtime whose web goes to the two fakes, with connections on (a scratch vault)."""
    monkeypatch.setenv("KRANTO_CUBS_STOP", str(tmp_path / "cubs.STOP"))
    bd, inst = fakes

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.buttondown.com":
            return bd(request)
        if request.url.host == INSTANCE:
            return inst(request)
        return httpx.Response(404)

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
    install(rt, "poster")
    yield rt
    r.stop_all("host")


def host(rt) -> CubHost:
    return CubHost(rt.cubs, rt.cubs.installed["poster"], run_uuid=str(uuid.uuid4()),
                   run_log=None)


def call(rt, service: str, op: str, **args) -> dict:
    return host(rt).dispatch("broker.call", {"service": service, "op": op, "args": args})


def refused(rt, service: str, op: str, **args) -> RpcError:
    with pytest.raises(RpcError) as got:
        call(rt, service, op, **args)
    return got.value


def connect_buttondown(rt, fakes) -> dict:
    return rt.connections.paste("buttondown", {"key": fakes[0].key})


def connect_mastodon(rt, fakes) -> dict:
    return rt.connections.paste("mastodon_post", {"instance": INSTANCE, "token": fakes[1].token})


def live(rt, *kinds: str) -> None:
    rt.cfg = dataclasses.replace(rt.cfg, cubs=cub_settings.parse({"poster": {"live": list(kinds)}}))


def ticket(rt, kind: str, fields: dict) -> int:
    return tickets.file(rt.store, cub="poster", trust="owner",
                        granted=("send.buttondown", "post.mastodon"), kind=kind, fields=fields)


def press(rt, tid: int) -> dict:
    return tickets.confirm(rt.store, tid, identity=UI, confirm=True, context=rt)


def issue(rt, subject: str = "Week 1") -> tuple[dict, int]:
    d = call(rt, "buttondown", "emails.create_draft", subject=subject, body="Two items.")
    return d, ticket(rt, "send.buttondown", {"draft_ref": d["draft_ref"], "subject": subject,
                                              "audience": "all"})


def toot(rt, text: str = "A pick of the week.") -> tuple[dict, int]:
    d = call(rt, "mastodon", "statuses.draft", text=text)
    return d, ticket(rt, "post.mastodon", {"draft_ref": d["draft_ref"], "text": text,
                                            "visibility": "public", "language": "en"})


# -- the tables -------------------------------------------------------------------------------


def test_the_sdk_tables_are_the_adapters():
    """``FakeHost`` refuses what Kranto refuses: one table each side, held equal."""
    from bears_cub import kinds
    from kranto import newsletter
    legacy = set(newsletter.legacy_services())         # aliases Kranto honours for one release
    assert set(kinds.BROKER) == set(brokers.grantable()) - legacy
    # Kranto's own kinds (the short posts' Open and Bluesky send) are never a cub's to ask for
    own = {k for k, s in tickets.KINDS.items() if s.first_party_only}
    assert set(kinds.TICKETS) == set(tickets.kind_names()) - {"trade.instruct"} \
        - set(newsletter.legacy_kinds()) - own
    for service, ops in kinds.BROKER.items():
        adapter = brokers.ADAPTERS[service]
        assert set(ops) == brokers.grantable()[service]
        for name, spec in ops.items():
            op = adapter.ops[name]
            assert (op.side, op.needs_credential, op.args) == \
                (spec["side"], spec["needs_credential"], spec["args"])
            assert (op.per_day if op.side == "draft" else op.per_hour) == \
                spec.get("per_day" if op.side == "draft" else "per_hour")
    tickets.kind_names()
    for kind in ("send.newsletter", "send.buttondown", "post.mastodon", "post.bluesky",
                 "post.open"):
        assert tickets.KINDS[kind].perform is not None


def test_no_money_broker_is_left_and_a_cub_cannot_ask_for_one():
    # Invest's broker left Kranto (cut 2): a cub's manifest naming it is refused
    assert "money" not in brokers.ADAPTERS and "money" not in brokers.grantable()
    with pytest.raises(ManifestError, match="no money operations"):
        registry.validate_cub({"schema": 1, "api": "cub/1", "version": "1.0.0", "id": "trader",
                               "title": "Trader", "says": "Reads quotes.",
                               "broker": {"money": ["quote.get"]}, "storage": "none"})


def test_a_perform_or_unknown_op_is_not_grantable(brt):
    assert refused(brt, "buttondown", "send").code == -32001
    assert refused(brt, "money", "quote", conid=1).code == -32001


# -- Buttondown: the operations -------------------------------------------------------------------


def test_a_draft_not_connected_is_held_by_kranto(brt, fakes):
    d = call(brt, "buttondown", "emails.create_draft", subject="Week 1", body="Two items.")
    assert d["where"] == "kranto" and d["draft_ref"].startswith("draft:") and d["url"] is None
    row = brt.store.query_one("SELECT * FROM cub_drafts WHERE ref = ?", (d["draft_ref"],))
    assert row["cub"] == "poster" and row["id"] == int(d["draft_ref"].split(":")[1])
    assert json.loads(row["content"])["email_type"] == "public"
    assert fakes[0].requests == []                      # nothing left the machine
    calls = brt.store.query("SELECT service, op, status FROM cub_calls WHERE cub = 'poster'")
    assert [tuple(c) for c in calls] == [("buttondown", "emails.create_draft", "ok")]
    listed = call(brt, "buttondown", "drafts.list")
    assert listed == {"drafts": [{"draft_ref": d["draft_ref"], "subject": "Week 1",
                                  "created_at": d["created_at"]}]}
    got = call(brt, "buttondown", "emails.get", draft_ref=d["draft_ref"])
    assert got["status"] == "kranto" and got["where"] == "kranto"


def test_frontmatter_is_refused_before_anything_is_written(brt):
    err = refused(brt, "buttondown", "emails.create_draft", subject="x", body="---\na: b\n---\nhi")
    assert err.code == -32005 and "frontmatter" in err.message
    assert brt.store.query_one("SELECT COUNT(*) AS n FROM cub_drafts")["n"] == 0


def test_args_outside_the_schema_are_refused(brt):
    assert refused(brt, "buttondown", "emails.create_draft", subject="x").code == -32005
    assert refused(brt, "buttondown", "emails.create_draft", subject="x", body="y",
                   to="everyone").code == -32005
    assert refused(brt, "buttondown", "emails.create_draft", subject="x" * 201,
                   body="y").code == -32005
    assert refused(brt, "mastodon", "statuses.draft", text="hi",
                   visibility="direct").code == -32005


def test_a_credential_op_not_connected_is_32013(brt):
    assert refused(brt, "buttondown", "newsletter.get").code == -32013
    assert refused(brt, "mastodon", "account.get").code == -32013
    assert refused(brt, "mastodon", "instance.limits").code == -32013


def test_a_draft_connected_is_also_at_buttondown_with_the_version_header(brt, fakes):
    connect_buttondown(brt, fakes)
    d = call(brt, "buttondown", "emails.create_draft", subject="Week 1", body="Two items.")
    assert d["where"] == "buttondown" and d["draft_ref"].startswith("bd:")
    assert d["url"].startswith("https://buttondown.com/")
    [post] = [r for r in fakes[0].requests if r.method == "POST"]
    assert json.loads(post.content)["status"] == "draft"
    assert all(r.headers["x-api-version"] == "2026-04-01" for r in fakes[0].requests)
    assert call(brt, "buttondown", "emails.get", draft_ref=d["draft_ref"])["status"] == "draft"
    assert call(brt, "buttondown", "newsletter.get") == {"name": "Kranto Weekly",
                                                         "subscriber_count": 148}


def test_another_cubs_draft_is_not_readable(brt):
    d, _ = issue(brt)
    brt.store.insert("cub_drafts", {"cub": "other", "service": "buttondown", "ref": "draft:999",
                                    "content": "{}", "content_hash": "x",
                                    "created_at": "2026-10-19T00:00:00Z"})
    assert refused(brt, "buttondown", "emails.get", draft_ref="draft:999").code == -32005
    assert call(brt, "buttondown", "emails.get", draft_ref=d["draft_ref"])["subject"] == "Week 1"


def test_the_rate_windows(brt):
    for i in range(20):
        call(brt, "buttondown", "emails.create_draft", subject=f"s{i}", body="b")
    err = refused(brt, "buttondown", "emails.create_draft", subject="s21", body="b")
    assert err.code == -32004 and "20 drafts a day" in err.message
    call(brt, "mastodon", "statuses.draft", text="the other service's window is its own")
    for _ in range(60):
        call(brt, "buttondown", "drafts.list", limit=1)
    assert refused(brt, "buttondown", "drafts.list").code == -32004


# -- Buttondown: the press ------------------------------------------------------------------------


def test_a_dry_press_sends_nothing(brt, fakes):
    connect_buttondown(brt, fakes)
    d, tid = issue(brt)
    out = press(brt, tid)
    assert out["state"] == "dry" and out["mode"] == "dry"
    assert out["note"].startswith(
        "practice: nothing was sent; the draft stays at Buttondown")
    assert fakes[0].sends() == []
    row = brt.store.query_one("SELECT * FROM cub_calls WHERE ticket_id = ?", (tid,))
    assert (row["service"], row["op"], row["status"]) == ("buttondown", "send.buttondown", "dry")


def test_live_sends_a_buttondown_draft_once(brt, fakes):
    connect_buttondown(brt, fakes)
    live(brt, "send.buttondown")
    d, tid = issue(brt)
    out = press(brt, tid)
    assert out["state"] == "done" and out["mode"] == "live"
    assert "undo within minutes" in out["note"]
    [send] = fakes[0].sends()
    assert send.method == "PATCH" and send.url.path == f"/v1/emails/{d['draft_ref'][3:]}"
    with pytest.raises(tickets.TicketError):
        press(brt, tid)                                  # a ticket is confirmed once
    assert len(fakes[0].sends()) == 1


def test_live_sends_a_kranto_draft_with_the_direct_send_header(brt, fakes):
    live(brt, "send.buttondown")
    d, tid = issue(brt)                                  # drafted before connecting
    connect_buttondown(brt, fakes)
    out = press(brt, tid)
    assert out["state"] == "done"
    [send] = fakes[0].sends()
    assert send.method == "POST" and send.headers["x-buttondown-live-dangerously"] == "true"
    body = json.loads(send.content)
    assert body["subject"] == "Week 1" and body["body"] == "Two items."
    assert call(brt, "buttondown", "emails.get", draft_ref=d["draft_ref"])["status"] == "sent"


def test_live_not_connected_is_refused(brt):
    live(brt, "send.buttondown")
    _, tid = issue(brt)
    out = press(brt, tid)
    assert out["state"] == "refused" and "not connected" in out["note"]


def test_a_ticket_whose_subject_is_not_the_drafts_is_refused(brt, fakes):
    connect_buttondown(brt, fakes)
    live(brt, "send.buttondown")
    d = call(brt, "buttondown", "emails.create_draft", subject="Week 1", body="b")
    tid = ticket(brt, "send.buttondown", {"draft_ref": d["draft_ref"], "subject": "Other",
                                          "audience": "all"})
    out = press(brt, tid)
    assert out["state"] == "refused" and "the draft changed" in out["note"]
    assert fakes[0].sends() == []


@pytest.mark.parametrize("reply, state, words", [
    ((400, {"code": "body_contains_frontmatter", "detail": "x"}), "refused",
     "body_contains_frontmatter"),
    ((400, {"code": "sending_requires_confirmation"}), "refused", "sending_requires_confirmation"),
    ((429, {"detail": "slow down"}), "refused", "rate limited"),
    ((500, {}), "unknown", "look at Buttondown"),
    ((502, {}), "unknown", "look at Buttondown"),
    (httpx.ReadTimeout("slow"), "unknown", "no answer from Buttondown"),
])
def test_each_answer_of_buttondown_has_its_outcome(brt, fakes, reply, state, words):
    connect_buttondown(brt, fakes)
    live(brt, "send.buttondown")
    _, tid = issue(brt)
    fakes[0].reply = reply
    n = len(fakes[0].requests)
    out = press(brt, tid)
    assert out["state"] == state and words in out["note"]
    assert len(fakes[0].requests) == n + 1               # never sent twice


def test_a_refused_key_marks_the_connection_and_refuses(brt, fakes):
    conn = connect_buttondown(brt, fakes)
    live(brt, "send.buttondown")
    _, tid = issue(brt)
    fakes[0].key = secrets.token_hex(20)                 # rotated at Buttondown
    out = press(brt, tid)
    assert out["state"] == "refused" and "401" in out["note"]
    assert brt.connections.get(conn["id"])["state"] == "needs_login"
    assert refused(brt, "buttondown", "newsletter.get").code == -32013


def test_the_readback_is_the_cores(brt, fakes):
    connect_buttondown(brt, fakes)
    _, tid = issue(brt)
    rb = dict(tickets.get(brt.store, tid)["readback"])
    assert rb["Subject"] == "Week 1" and rb["Newsletter"] == "Kranto Weekly"
    assert rb["To"] == "all subscribers" and rb["Length"] == "2 words, 10 characters"
    assert rb["Body"] == "Two items."                   # what goes to subscribers, as text


def test_the_readback_carries_the_whole_body(brt, fakes):
    connect_buttondown(brt, fakes)
    body = "Para one <b>not html</b>.\n\n" + "word " * 30000
    d = call(brt, "buttondown", "emails.create_draft", subject="Long", body=body)
    tid = ticket(brt, "send.buttondown", {"draft_ref": d["draft_ref"], "subject": "Long",
                                          "audience": "all"})
    rb = dict(tickets.get(brt.store, tid)["readback"])
    assert rb["Body"] == body and rb["Length"] == f"30004 words, {len(body):,} characters"


def test_the_stop_file_makes_a_live_press_dry_without_a_request(brt, fakes, tmp_path):
    connect_buttondown(brt, fakes)
    live(brt, "send.buttondown")
    _, tid = issue(brt)
    (tmp_path / "cubs.STOP").touch()
    out = press(brt, tid)
    assert out["state"] == "dry" and "cubs.STOP" in out["note"]
    assert fakes[0].sends() == []


# -- Mastodon ---------------------------------------------------------------------------------


def test_a_post_draft_is_checked_against_the_limit(brt, fakes):
    err = refused(brt, "mastodon", "statuses.draft", text="x" * 501)
    assert err.code == -32005 and err.data == {"limit": 500, "got": 501}
    d = call(brt, "mastodon", "statuses.draft", text="hi")
    assert d == {"draft_ref": d["draft_ref"], "chars": 2, "limit": 500, "where": "kranto"}
    connect_mastodon(brt, fakes)
    assert call(brt, "mastodon", "statuses.draft", text="x" * 900)["limit"] == 1000
    assert call(brt, "mastodon", "instance.limits") == {"instance": INSTANCE,
                                                        "max_characters": 1000}
    acct = call(brt, "mastodon", "account.get")
    assert acct["acct"] == f"@ian@{INSTANCE}" and acct["url"] == f"https://{INSTANCE}/@ian"
    n = len(fakes[1].requests)
    call(brt, "mastodon", "instance.limits")
    call(brt, "mastodon", "account.get")
    assert len(fakes[1].requests) == n                   # cached


def test_a_dry_post_names_the_account_and_posts_nothing(brt, fakes):
    connect_mastodon(brt, fakes)
    _, tid = toot(brt)
    out = press(brt, tid)
    assert out["state"] == "dry" and out["note"] == \
        f"practice: nothing was posted. For real it would post as @ian@{INSTANCE}"
    assert fakes[1].statuses == []


def test_live_posts_once_with_the_idempotency_key(brt, fakes):
    connect_mastodon(brt, fakes)
    live(brt, "post.mastodon")
    _, tid = toot(brt)
    out = press(brt, tid)
    assert out["state"] == "done" and out["note"] == f"posted: https://{INSTANCE}/@ian/1"
    [post] = [r for r in fakes[1].requests if r.url.path == "/api/v1/statuses"]
    assert post.headers["idempotency-key"] == f"kranto-ticket-{tid}"
    assert fakes[1].statuses == [{"status": "A pick of the week.", "visibility": "public",
                                  "language": "en"}]


@pytest.mark.parametrize("reply, state, words", [
    ((422, {"error": "Validation failed: Text character limit of 500 exceeded"}), "refused",
     "Validation failed"),
    ((429, {"error": "Too many requests"}), "refused", "rate limited by the instance"),
    ((403, {"error": "This action is not allowed"}), "refused", "answered 403"),
    ((500, {}), "unknown", "look at the instance"),
    (httpx.ConnectTimeout("slow"), "unknown", "no answer from the instance"),
])
def test_each_answer_of_the_instance_has_its_outcome(brt, fakes, reply, state, words):
    connect_mastodon(brt, fakes)
    live(brt, "post.mastodon")
    _, tid = toot(brt)
    fakes[1].reply = reply
    out = press(brt, tid)
    assert out["state"] == state and words in out["note"]
    assert len([r for r in fakes[1].requests if r.url.path == "/api/v1/statuses"]) == 1


def test_a_refused_token_marks_the_posting_connection(brt, fakes):
    conn = connect_mastodon(brt, fakes)
    live(brt, "post.mastodon")
    call(brt, "mastodon", "instance.limits")             # the limit is cached first
    _, tid = toot(brt)
    fakes[1].token = secrets.token_urlsafe(32)
    out = press(brt, tid)
    assert out["state"] == "refused" and "401" in out["note"]
    assert brt.connections.get(conn["id"])["state"] == "needs_login"


def test_a_post_whose_text_is_not_the_drafts_is_refused(brt, fakes):
    connect_mastodon(brt, fakes)
    live(brt, "post.mastodon")
    d = call(brt, "mastodon", "statuses.draft", text="one text")
    tid = ticket(brt, "post.mastodon", {"draft_ref": d["draft_ref"], "text": "another text",
                                        "visibility": "public", "language": "en"})
    out = press(brt, tid)
    assert out["state"] == "refused" and "the draft changed" in out["note"]
    assert fakes[1].statuses == []


def test_the_post_readback(brt, fakes):
    connect_mastodon(brt, fakes)
    _, tid = toot(brt)
    rb = dict(tickets.get(brt.store, tid)["readback"])
    assert rb["Account"] == f"@ian@{INSTANCE}" and rb["Text"] == "A pick of the week."
    assert rb["Characters"].startswith("19 of ")
    assert rb["Content warning"] == "none"


def test_the_post_readback_shows_the_drafts_content_warning(brt, fakes):
    connect_mastodon(brt, fakes)
    d = call(brt, "mastodon", "statuses.draft", text="A pick.", spoiler_text="Spoilers ahead")
    tid = ticket(brt, "post.mastodon", {"draft_ref": d["draft_ref"], "text": "A pick.",
                                         "visibility": "public", "language": "en"})
    rb = dict(tickets.get(brt.store, tid)["readback"])
    assert rb["Content warning"] == "Spoilers ahead"


# -- the connections ------------------------------------------------------------------------------


def test_buttondown_connects_with_a_pasted_key(brt, fakes):
    conn = connect_buttondown(brt, fakes)
    assert conn["account"] == "Kranto Weekly" and conn["instance"] == "buttondown.com"
    assert json.loads(conn["scopes"]) == ["emails:draft", "emails:send"]
    [acct] = brt.connections.accounts()
    assert acct["writes"] is True and acct["sources"] == []
    assert brt.connections.test(conn["id"]) == {"ok": True, "message":
                                                "Signed in as Kranto Weekly, 2 scopes."}
    with pytest.raises(OAuthError, match="refused this key"):
        brt.connections.paste("buttondown", {"key": secrets.token_hex(20)})
    kept = [p for p in (brt.cfg.data_dir / "secrets").rglob("*") if p.is_file()]
    assert kept and not any(fakes[0].key.encode() in p.read_bytes() for p in kept)
    assert fakes[0].key not in json.dumps(brt.connections.accounts())


def test_one_posting_account_per_kranto(brt, fakes):
    first = connect_mastodon(brt, fakes)
    assert first["account"] == f"@ian@{INSTANCE}" and first["instance"] == INSTANCE
    second = brt.connections.paste("mastodon_post", {"instance": "MASTO.example",
                                                     "token": fakes[1].token})
    assert brt.connections.get(first["id"])["state"] == "disconnected"
    assert [a["id"] for a in brt.connections.accounts()] == [second["id"]]
    with pytest.raises(OAuthError, match="required"):
        brt.connections.paste("mastodon_post", {"token": fakes[1].token})


def test_the_posting_app_has_its_own_name_and_scopes():
    from kranto.connections.mastodon import SCOPES as READ_SCOPES
    from kranto.connections.mastodon_post import MastodonPostProvider
    p = MastodonPostProvider(HTTP(), None)
    assert p.client_name == "Kranto (posting)" and p.scopes == ("read:accounts", "write:statuses")
    assert "write:statuses" not in READ_SCOPES
    url = p.authorize_url(INSTANCE, {"client_id": "c"}, "http://127.0.0.1:1/cb", "s", "ch")
    assert "scope=read%3Aaccounts+write%3Astatuses" in url


# -- a cub's run, end to end ----------------------------------------------------------------------


@needs_bwrap
def test_a_cubs_run_drafts_and_files_and_the_press_is_dry(brt, fakes):
    out = brt.cubs.run_job("poster", "poster.draft", "draft")
    assert out["status"] == "ok"
    a, b = json.loads(brt.store.query_one(
        "SELECT summary FROM runs WHERE kind = 'poster.draft'")["summary"])["tickets"]
    assert press(brt, a)["state"] == "dry" and press(brt, b)["state"] == "dry"
    assert fakes[0].requests == [] and fakes[1].requests == []
