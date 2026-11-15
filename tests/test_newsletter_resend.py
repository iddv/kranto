"""The newsletter through Resend (MAIL), against ``FakeResend`` (Resend's documented shapes;
nothing leaves the machine): Save and test only reads and says what is missing; a draft is a
draft broadcast; the press sends it once (no idempotency key exists for broadcasts, so Kranto
reads the status first), or schedules it; each answer has its outcome; the read-back carries
the whole body, the audience and its count; and the migration: a cub installed with the old
platform-named kind and service still drafts, files and sends, and a kind it turned live stays
live.

Every key here is made at runtime; none is a literal.
"""

from __future__ import annotations

import dataclasses
import json
import secrets
import uuid
from datetime import timedelta

import httpx
import pytest

from kranto import library, newsletter
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.connections import Connections, OAuthError
from kranto.core import tickets
from kranto.core.cubs import inspect
from kranto.core.cubs import settings as cub_settings
from kranto.core.cubs.host import CubHost
from kranto.newsletter import render
from kranto.newsletter.resend import FULL_ACCESS, UNSUBSCRIBE
from kranto.runtime import open_runtime
from kranto.sources import HTTP
from kranto.sources.pacing import Hosts
from kranto.store import iso, utcnow
from kranto.web import types as T

from .conftest import chat_response, llm_config, web_client
from .cubhelp import install, runtime
from .fake_resend import HOST, FakeResend
from .test_web_types import problems

UI = {"origin": "ui", "via": "cookie"}
FROM = "Kranto Weekly <letters@news.example.org>"


@pytest.fixture
def fake():
    return FakeResend()


@pytest.fixture
def nrt(tmp_path, store, embedder, make_client, fake, monkeypatch):
    """A runtime whose web goes to FakeResend, connections on (a scratch vault), and the
    neutral ``letter`` cub and the old-named ``poster`` cub installed."""
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
    install(rt, "letter")
    install(rt, "poster")
    yield rt
    r.stop_all("host")


def connect(rt, fake, *, key=None, audience="Newsletter", sender=FROM) -> dict:
    return rt.connections.paste("resend", {"key": key or fake.key, "audience": audience,
                                           "from": sender})


def call(rt, op: str, cub: str = "letter", service: str = "newsletter", **args) -> dict:
    host = CubHost(rt.cubs, rt.cubs.installed[cub], run_uuid=str(uuid.uuid4()), run_log=None)
    return host.dispatch("broker.call", {"service": service, "op": op, "args": args})


def live(rt, *kinds: str, cub: str = "letter") -> None:
    rt.cfg = dataclasses.replace(rt.cfg, cubs=cub_settings.parse({cub: {"live": list(kinds)}}))


def issue(rt, subject: str = "Week 1", body: str = "Two items.", when: str = "now"):
    d = call(rt, "emails.create_draft", subject=subject, body=body)
    tid = tickets.file(rt.store, cub="letter", trust="owner", granted=("send.newsletter",),
                       kind="send.newsletter", fields={"draft_ref": d["draft_ref"],
                                                       "subject": subject, "audience": "all",
                                                       "when": when})
    return d, tid


def press(rt, tid: int) -> dict:
    return tickets.confirm(rt.store, tid, identity=UI, confirm=True, context=rt)


# -- Save and test: reads only, and says what is missing ---------------------------------------


def test_a_sending_only_key_is_refused_in_plain_words_and_nothing_is_kept(nrt, fake):
    with pytest.raises(OAuthError) as got:
        connect(nrt, fake, key=fake.sending_key)
    assert str(got.value) == FULL_ACCESS and "Full access" in FULL_ACCESS
    assert nrt.connections.accounts() == [] and newsletter.named(nrt.store) is None
    assert all(r.method == "GET" for r in fake.requests)          # it only read


def test_save_and_test_reads_only_and_says_ready(nrt, fake):
    conn = connect(nrt, fake)
    assert conn["account"] == FROM and conn["provider"] == "resend"
    assert "The key has Full access." in conn["said"]
    assert "The domain news.example.org is verified." in conn["said"]
    assert "The audience Newsletter has 147 subscribers." in conn["said"]    # 3 unsubscribed
    assert all(r.method == "GET" for r in fake.requests)
    assert all(r.headers["user-agent"] for r in fake.requests)
    st = newsletter.status(nrt)
    assert st["name"] == "Resend" and st["ready"] and st["missing"] == []
    assert st["from_address"] == FROM and st["audience"] == "the audience Newsletter"


def test_an_unverified_domain_names_its_dns_records(nrt, fake):
    fake.domains[0]["status"] = "pending"
    conn = connect(nrt, fake)
    assert "news.example.org isn't verified yet (pending)" in conn["said"]
    assert "MX send feedback-smtp.us-east-1.amazonses.com" in conn["said"]
    assert "resend._domainkey" not in conn["said"]               # that record is verified
    st = newsletter.status(nrt)                                   # the audience and from are kept,
    assert not st["ready"] and "isn't verified yet" in st["missing"][0]   # the page says why
    found = newsletter.check(nrt)
    assert not found.ok and "Verify DNS Records" in found.words()
    fake.domains[0]["status"] = "verified"                        # the owner added the records
    assert newsletter.check(nrt).ok and newsletter.status(nrt)["ready"]


def test_a_domain_not_in_resend_and_a_missing_audience_are_said(nrt, fake):
    conn = connect(nrt, fake, audience="Readers", sender="me@elsewhere.example")
    assert "Your domain elsewhere.example is not in Resend yet" in conn["said"]
    assert "There is no audience named “Readers” in Resend" in conn["said"]
    st = newsletter.status(nrt)
    assert not st["ready"] and "needs a from address and an audience" in st["missing"][0]


def test_create_the_audience_is_the_pages_press_only(nrt, fake):
    from kranto.web.app import create_app
    connect(nrt, fake, audience="Readers")
    app = create_app(nrt)
    with web_client(app, "http://127.0.0.1:8765", signed_in=False) as web:
        r = web.post("/api/newsletter/audience", json={"confirm": True, "name": "Readers"})
        assert r.status_code in (401, 403)
    with web_client(app, "http://127.0.0.1:8765") as web:
        assert web.post("/api/newsletter/audience", json={"name": "Readers"}).status_code == 400
        r = web.post("/api/newsletter/audience", json={"confirm": True, "name": "Readers"})
        assert r.status_code == 200, r.text
        assert r.json()["ready"] and "Made the audience Readers at Resend" in r.json()["message"]
        assert web.get("/api/newsletter").json()["audience"] == "the audience Readers"
        checked = web.post("/api/newsletter/check").json()
        assert checked["ok"] and "has 0 subscribers" in checked["message"]
        assert problems(web.get("/api/newsletter").json(), T.Newsletter) == []
    assert [r.method for r in fake.requests if r.url.path == "/segments"].count("POST") == 1


def test_the_newsletter_answers_its_type_before_any_platform(nrt):
    from kranto.web.app import create_app
    with web_client(create_app(nrt), "http://127.0.0.1:8765") as web:
        got = web.get("/api/newsletter").json()
    assert problems(got, T.Newsletter) == [] and got["platform"] is None


# -- the draft ----------------------------------------------------------------------------------


def test_a_draft_connected_is_a_draft_broadcast_to_the_audience(nrt, fake):
    connect(nrt, fake)
    d = call(nrt, "emails.create_draft", subject="Week 1",
             body="**Solar** kits <script>x</script> [read](https://example.com/a?b=1&c=2)")
    assert d["where"] == "resend" and d["draft_ref"].startswith("rs:")
    [post] = [r for r in fake.requests if r.method == "POST"]
    body = json.loads(post.content)
    assert "send" not in body and body["segment_id"] == fake.segments[0]["id"]
    assert body["from"] == FROM and body["subject"] == "Week 1"
    assert "<strong>Solar</strong>" in body["html"] and "<script>" not in body["html"]
    assert "&lt;script&gt;" in body["html"]
    assert '<a href="https://example.com/a?b=1&amp;c=2">read</a>' in body["html"]
    assert f'<a href="{UNSUBSCRIBE}">Unsubscribe</a>' in body["html"]
    assert body["text"].endswith(f"Unsubscribe: {UNSUBSCRIBE}")
    assert fake.broadcasts[d["draft_ref"][3:]]["status"] == "draft" and fake.sends() == []
    assert call(nrt, "emails.get", draft_ref=d["draft_ref"])["status"] == "draft"
    assert call(nrt, "newsletter.get") == {"name": "Newsletter", "subscriber_count": 147}


def test_not_connected_the_draft_is_held_by_kranto_and_names_nothing(nrt, fake):
    d = call(nrt, "emails.create_draft", subject="Week 1", body="Two items.")
    assert d["where"] == "kranto" and d["draft_ref"].startswith("draft:")
    assert fake.requests == []


# -- the press ----------------------------------------------------------------------------------


def test_a_dry_press_sends_nothing(nrt, fake):
    connect(nrt, fake)
    _, tid = issue(nrt)
    out = press(nrt, tid)
    assert out["state"] == "dry" and out["note"].startswith(
        "practice: nothing was sent; the draft stays at Resend")
    assert "the audience Newsletter, 147 subscribers when drafted" in out["note"]
    assert fake.sends() == []


def test_live_reads_the_draft_then_sends_it_once(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    d, tid = issue(nrt)
    bid = d["draft_ref"][3:]
    n = len(fake.requests)
    out = press(nrt, tid)
    assert out["state"] == "done" and out["mode"] == "live", out
    assert out["note"].startswith(f"sent: {bid} (queued)")
    assert [(r.method, r.url.path) for r in fake.requests[n:]] == [
        ("GET", f"/broadcasts/{bid}"), ("POST", f"/broadcasts/{bid}/send"),
        ("GET", f"/broadcasts/{bid}")]
    with pytest.raises(tickets.TicketError):
        press(nrt, tid)                                    # a ticket is confirmed once
    assert len(fake.sends()) == 1
    assert call(nrt, "emails.get", draft_ref=d["draft_ref"])["status"] == "queued"


def test_a_broadcast_that_is_no_longer_a_draft_is_never_sent_again(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    d, tid = issue(nrt)
    fake.broadcasts[d["draft_ref"][3:]]["status"] = "sent"           # sent at Resend by hand
    out = press(nrt, tid)
    assert out["state"] == "refused" and "is sent at Resend" in out["note"]
    assert fake.sends() == []


def test_a_scheduled_send_says_how_to_cancel(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    when = iso(utcnow() + timedelta(days=1))[:19] + "Z"
    d, tid = issue(nrt, when=when)
    out = press(nrt, tid)
    assert out["state"] == "done" and out["note"].startswith("scheduled:")
    assert "cancel it at Resend (Broadcasts) before then" in out["note"]
    [send] = fake.sends()
    assert json.loads(send.content) == {"scheduled_at": when}
    rb = dict(tickets.get(nrt.store, tid)["readback"])
    assert rb["When"].startswith(f"scheduled for {when}")


def test_a_time_already_passed_is_refused(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    _, tid = issue(nrt, when="2026-01-01T09:00:00Z")
    out = press(nrt, tid)
    assert out["state"] == "refused" and "has passed" in out["note"] and fake.sends() == []


def test_a_draft_held_by_kranto_is_created_and_sent_in_one_request(nrt, fake):
    live(nrt, "send.newsletter")
    d, tid = issue(nrt)                                    # before any platform is connected
    connect(nrt, fake)
    n = len(fake.requests)
    out = press(nrt, tid)
    assert out["state"] == "done", out
    sends = [r for r in fake.requests[n:] if r.method == "POST"]
    assert len(sends) == 1 and sends[0].url.path == "/broadcasts"
    body = json.loads(sends[0].content)
    assert body["send"] is True and body["subject"] == "Week 1" and "Two items." in body["text"]
    assert call(nrt, "emails.get", draft_ref=d["draft_ref"])["status"] == "sent"


@pytest.mark.parametrize("reply, state, words", [
    ((422, {"name": "validation_error", "statusCode": 422}), "refused", "validation_error"),
    ((403, {"name": "validation_error", "statusCode": 403}), "refused", "Resend answered 403"),
    ((429, {"name": "daily_quota_exceeded", "statusCode": 429}), "refused", "rate limited"),
    ((500, {"name": "application_error"}), "unknown", "look at Resend"),
    ((503, {}), "unknown", "look at Resend"),
    (httpx.ReadTimeout("slow"), "unknown", "no answer from Resend"),
])
def test_each_answer_of_resend_has_its_outcome_and_is_never_repeated(nrt, fake, reply, state,
                                                                      words):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    d, tid = issue(nrt)
    fake.reply = reply
    n = len(fake.requests)
    out = press(nrt, tid)
    assert out["state"] == state and words in out["note"], out
    sent = [r for r in fake.requests[n:] if r.method == "POST"]
    assert len(sent) == 1                                  # one send, never retried


def test_the_audience_changed_since_the_draft_refuses(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.newsletter")
    _, tid = issue(nrt)
    fake.segments.append({"id": str(uuid.uuid4()), "name": "Others", "created_at": "x"})
    connect(nrt, fake, audience="Others")
    out = press(nrt, tid)
    assert out["state"] == "refused" and "the audience changed" in out["note"]
    assert fake.sends() == []


def test_the_readback_is_the_whole_issue_and_its_audience(nrt, fake):
    connect(nrt, fake)
    body = "Para one.\n\n" + "word " * 1000
    _, tid = issue(nrt, body=body)
    rb = dict(tickets.get(nrt.store, tid)["readback"])
    assert rb["Body"] == body and rb["From"] == FROM and rb["Platform"] == "Resend"
    assert rb["To"] == "the audience Newsletter, 147 subscribers when drafted"
    assert rb["Footer"].startswith("An unsubscribe link for each reader")
    assert rb["Draft"].endswith("at Resend") and rb["Newsletter"] == FROM


# -- the migration: an installed cub with the old names ------------------------------------------


def test_a_cub_with_the_old_names_drafts_and_sends_through_the_platform_in_use(nrt, fake):
    connect(nrt, fake)
    live(nrt, "send.buttondown", cub="poster")             # turned live before the rename
    d = call(nrt, "emails.create_draft", cub="poster", service="buttondown", subject="Week 1",
             body="Two items.")
    assert d["draft_ref"].startswith("rs:")
    tid = tickets.file(nrt.store, cub="poster", trust="owner",
                       granted=("send.buttondown", "post.mastodon"), kind="send.buttondown",
                       fields={"draft_ref": d["draft_ref"], "subject": "Week 1",
                               "audience": "all"})
    out = press(nrt, tid)
    assert out["state"] == "done" and out["mode"] == "live", out
    assert len(fake.sends()) == 1


def test_a_kind_live_under_its_old_name_is_live_under_the_new_and_back(nrt):
    live(nrt, "send.buttondown")
    assert "send.newsletter" in cub_settings.live_kinds(nrt.cfg, "letter")
    live(nrt, "send.newsletter")
    assert "send.buttondown" in cub_settings.live_kinds(nrt.cfg, "letter")


def test_an_open_ticket_of_the_old_kind_stays_and_reads_as_before(nrt):
    from kranto.core.cubs.brokers.base import new_draft
    d = new_draft(nrt.store, cub="poster", service="buttondown",
                  content={"subject": "Week 1", "body": "Two items.", "email_type": "public"},
                  run_uuid=None)
    tid = tickets.file(nrt.store, cub="poster", trust="owner", granted=("send.buttondown",),
                       kind="send.buttondown", fields={"draft_ref": d["ref"],
                                                       "subject": "Week 1", "audience": "all"})
    t = tickets.get(nrt.store, tid)
    assert t["kind"] == "send.buttondown" and t["performs"] and t["title"] == "Send this issue"
    assert dict(t["readback"])["Body"] == "Two items."
    assert press(nrt, tid)["state"] == "dry"


def test_renaming_to_the_neutral_names_is_not_a_new_permission():
    old = {"requests": ["send.buttondown"],
           "broker": {"buttondown": ["emails.create_draft", "emails.get", "drafts.list"]}}
    new = {"requests": ["send.newsletter"],
           "broker": {"newsletter": ["emails.create_draft", "emails.get", "drafts.list"]}}
    d = inspect.delta(old, new)
    assert d["same"] and not d["grown"]
    assert inspect.delta(old, {**new, "requests": ["send.newsletter", "post.mastodon"]})["grown"]


# -- the renderer ----------------------------------------------------------------------------


def test_the_renderer_makes_no_markup_from_the_text():
    html = render.to_html('<img src=x onerror=alert(1)> **b** [x](javascript:alert(1)) '
                          '[y](https://e.example/"onmouseover=x)')
    assert "<img" not in html and "&lt;img" in html
    assert html.count("<a ") == 0                          # neither address becomes a link
    assert "[x](javascript:alert(1))" in html and "[y](https://e.example/&quot;" in html
    assert "<strong>b</strong>" in html
