"""X as a source: the six kinds, the requests they send (only what ingest
consumes), every read in ``api_spend`` and equal to what the fake returned, the search and
bookmark cadence, the X cap (none by default; reached, X waits for next month), spent credits,
Settings › Spend, and one run over a real loopback socket. Against ``tests/fake_x.py`` and the
hand-written fixtures in ``tests/fixtures/x``; nothing reaches X."""

import json
import secrets
import socket
import threading
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from kranto import doctor, source_health, spend
from kranto.config import (
    BudgetConfig,
    Config,
    IngestConfig,
    LookConfig,
    MapConfig,
    XConfig,
    parse_x,
)
from kranto.connections import Connections
from kranto.connections.x import reads_of
from kranto.runtime import open_runtime
from kranto.sources import HTTP, catalog
from kranto.sources.x import XSource, cadence_hours, limit_for, post_item, search_query
from kranto.store import Store
from kranto.tick import run_ingest
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client
from .fake_x import USER_ID, FakeX, fixture, post

CALLBACK = "http://127.0.0.1:8765/connections/x/callback"


# -- items, from the fixtures --------------------------------------------------------------


def _included(body):
    return {p["id"]: p for p in body.get("includes", {}).get("posts", [])}


def test_a_list_page_becomes_items_without_authors_reposts_resolved_quotes_joined():
    body = fixture("list_posts.json")
    inc = _included(body)
    repost, quote, long, reply = (post_item(p, inc) for p in body["data"])
    # a repost is the original, under the original's id, with its own link
    assert repost.id == "1849100000000000001"
    assert repost.url == "https://x.com/i/status/1849100000000000001"
    assert repost.link == "https://example.org/microgrids"
    assert "https://example.org/microgrids" in repost.body and "t.co" not in repost.body
    # a quote carries the quoted text; its link is the quoted post's article, not x.com
    assert "\n\nQuoting: How we built offline sync with CRDTs" in quote.body
    assert quote.link == "https://example.org/crdt-sync"
    assert quote.meta["x"] == {"likes": 140, "reposts": 12, "replies": 3, "quotes": 2,
                               "bookmarks": 30, "seen_ids": ["1849100000000000008"]}
    # a long post is read from note_post, its link unwound
    assert long.body.startswith("A long thread opener") and "ownership all point" in long.body
    assert long.link == "https://www.inkandswitch.com/local-first/"
    assert len(long.title) <= 144 and long.title.endswith(" ...")
    assert reply is not None
    for item in (repost, quote, long):
        assert "@someone" not in item.body and "someone" not in (item.url or "")
        assert item.published_at.tzinfo is not None


def test_what_a_reply_costs_by_price_line():
    assert reads_of("/2/lists/1/tweets", fixture("list_posts.json")) == {"post_read": 6}
    assert reads_of(f"/2/users/{USER_ID}/bookmarks", fixture("list_posts.json")) == \
        {"owned_read": 4, "post_read": 2}
    assert reads_of("/2/users/me", fixture("users_me.json")) == {"user_read": 1}
    assert reads_of("/2/lists/123", {"data": {"id": "123", "name": "B"}}) == {"list_read": 1}
    assert reads_of("/2/tweets/search/recent", {"meta": {"result_count": 0}}) == {}
    assert reads_of("/2/tweets", fixture("lookup_errors.json")) == {"post_read": 1}


def test_search_query_leaves_out_reposts_and_replies_and_stays_short():
    assert search_query("solar  mini-grids", "en") == "solar mini-grids -is:retweet -is:reply " \
                                                      "lang:en"
    assert len(search_query("x" * 900)) == 512


def test_limits_and_cadence_follow_the_defaults_and_x_minimums():
    x = XConfig()
    assert [limit_for({"what": w}, x) for w in ("list", "home", "profile", "search",
                                                 "bookmarks", "likes")] == [20, 20, 10, 10, 20, 20]
    assert cadence_hours({"what": "search"}, x) == 24 and cadence_hours({"what": "likes"}, x) == 24
    assert cadence_hours({"what": "list"}, x) == 0
    assert x.monthly_usd is None
    with pytest.raises(Exception, match="search_results"):
        parse_x({"search_results": 5})
    assert parse_x({"monthly_usd": 12}).monthly_usd == 12.0


# -- the rig: a connected X account on a fake X ---------------------------------------------


def judge_reply(body):
    if "first, quick look" in body["messages"][0]["content"]:
        return chat_response(json.dumps({"pass": True, "reason": "ok"}))
    return chat_response(json.dumps({
        "kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.9,
        "durability": 0.9, "opportunity": 0.9, "override": False, "tags": ["t"]}))


def make_rig(tmp_path, embedder, machine_id, http_factory, *, xcfg=None, look=None,
             reply=None):
    from kranto.llm import LLMClient

    fake = FakeX()
    store = Store.open(tmp_path / "data" / "kranto.db")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=None),
                 ingest=IngestConfig(fetch_full_text=False), map=MapConfig(),
                 look=look or LookConfig(enabled=False), x=xcfg or XConfig())
    http = http_factory(fake)
    conns = Connections(store, cfg.data_dir, http, machine_id=machine_id)
    answer = reply or judge_reply
    llm = LLMClient(store, cfg.llm, cfg.budget, api_key="k",
                    transport=httpx.MockTransport(lambda r: answer(json.loads(r.content))))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=llm, http=http, connections=conns)
    conns.set_client("x", {"client_id": fake.client_id})
    url, state_id = conns.start("x", "", CALLBACK)
    query = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    fake.authorized_with(query, CALLBACK)
    conns.finish("x", str(state_id), {"state": query["state"], "code": fake.code})
    return rt, fake


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


def mock_http(fake):
    return HTTP(transport=httpx.MockTransport(fake), resolver=lambda h: ["93.184.216.34"])


@pytest.fixture
def rig(tmp_path, embedder, machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http)
    yield rt, fake
    rt.close()


def add(rt, preset, fields=None):
    source_id, _ = source_health.add_from_preset(rt, preset, fields or {}, None)
    return source_id


def ingest(rt):
    return run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http, connections=rt.connections,
                      lock_path=rt.cfg.data_dir / "l.lock")


def x_reads(fake, since=0):
    return [r for r in fake.requests[since:] if r.url.path.startswith("/2/")
            and "oauth2" not in r.url.path]


def ledger(rt):
    rows = rt.store.query("SELECT kind, SUM(count) AS n FROM api_spend GROUP BY kind")
    return {r["kind"]: r["n"] for r in rows}


def test_the_presets_resolve_with_the_account_and_label_without_authors(rig):
    rt, fake = rig
    listed = source_health.preview(rt, "x.list", {"list": "https://x.com/i/lists/42"}, None)
    assert listed["label"] == "X list: Builders" and listed["params"]["list_id"] == "42"
    assert listed["items"] == 3 and listed["newest"][0]["url"].startswith("https://x.com/i/status/")
    who = catalog.resolve("x.profile", {"handle": "@local_first"},
                          rt.connections.http_for("x", None, rt.http))
    assert who.params == {"what": "profile", "user_id": "783214", "handle": "local_first"}
    with pytest.raises(ValueError, match="not an X list"):
        catalog.resolve("x.list", {"list": "https://example.org/42"}, None)
    keys = [p["key"] for prov in catalog.catalog_json()["providers"] if prov["key"] == "x"
            for p in prov["presets"]]
    assert keys == ["x.list", "x.home", "x.profile", "x.search", "x.bookmarks", "x.likes",
                    "x.grok_search", "x.scrape"]
    scrape = catalog.get("x.scrape")
    assert scrape.access == "not_offered" and "terms" in scrape.reason
    assert all(not catalog.get(k).scout for k in keys)


def test_requests_ask_for_exactly_what_a_run_consumes_and_never_for_authors(rig):
    rt, fake = rig
    home = add(rt, "x.home")
    start = len(fake.requests)
    first = ingest(rt)
    [req] = x_reads(fake, start)
    q = dict(req.url.params)
    # the first run backfills (ingest.backfill_items, 40); X's own field names, no authors
    assert q["max_results"] == "40" and "since_id" not in q and q["exclude"] == "replies"
    assert q["post.fields"] == "created_at,conversation_id,entities,public_metrics,note_post"
    assert q["expansions"] == "referenced_posts" and "user.fields" not in q
    assert req.url.path == f"/2/users/{USER_ID}/timelines/reverse_chronological"
    assert first.sources[0].fetch_state == "ok" and first.contributed == 3
    # the next run: the cap, after the newest post consumed
    fake.timeline.insert(0, post(1849000000000000004, "A new post about battery storage"))
    start = len(fake.requests)
    second = ingest(rt)
    [req] = x_reads(fake, start)
    assert req.url.params["since_id"] == "1849000000000000003"
    assert req.url.params["max_results"] == "10"         # min(ingest cap 10, x 20)
    assert second.sources[0].fetched == 1 and second.contributed == 1
    assert rt.store.query_one("SELECT COUNT(*) n FROM api_spend WHERE source_id = ?",
                              (home,))["n"] == 2


def test_a_list_has_no_since_id_and_its_replies_are_dropped(rig):
    rt, fake = rig
    fake.timeline.append(post(1849000000000000000, "@a yes", conversation_id="1",
                              referenced_posts=[{"type": "replied_to", "id": "1"}]))
    add(rt, "x.list", {"list": "42"})
    ingest(rt)
    start = len(fake.requests)
    ingest(rt)
    [req] = x_reads(fake, start)
    assert "since_id" not in req.url.params and req.url.params["max_results"] == "10"
    assert rt.store.query_one("SELECT COUNT(*) n FROM items_seen WHERE item_id = "
                              "'1849000000000000000'")["n"] == 0


def test_every_read_is_in_the_ledger_and_equals_what_x_returned(rig):
    rt, fake = rig
    add(rt, "x.list", {"list": "42"})
    add(rt, "x.search", {"query": "microgrids", "lang": "en"})
    add(rt, "x.bookmarks")
    fake.includes = [post(1848000000000000001, "the quoted original")]
    fake.timeline[0]["referenced_posts"] = [{"type": "quoted", "id": "1848000000000000001"}]
    report = ingest(rt)
    assert report.status == "ok", report.error
    assert ledger(rt) == dict(fake.returned)
    # the sign-in's identity call and the list's name were reads too, with no source
    assert rt.store.query_one("SELECT COUNT(*) n FROM api_spend WHERE source_id IS NULL")["n"] == 2
    month = spend.month(rt.store, "x")
    expected = sum(n * {"post_read": 0.005, "owned_read": 0.001, "user_read": 0.01,
                        "list_read": 0.005}[k] for k, n in fake.returned.items())
    assert month["usd"] == pytest.approx(expected)
    rows = {r["id"]: r for r in source_health.list_sources(rt.store, rt.cfg)}
    bookmarks = next(r for r in rows.values() if r["label"] == "Your X bookmarks")
    assert bookmarks["spend"]["run_usd"] == pytest.approx(0.02)
    # three owned reads, and the quoted original one of them carries at the post price
    assert bookmarks["spend"]["reads"] == 4 and bookmarks["spend"]["usd"] == pytest.approx(0.008)


def test_a_search_runs_once_a_day_and_bookmarks_once_a_day(rig):
    rt, fake = rig
    search = add(rt, "x.search", {"query": "microgrids"})
    ingest(rt)
    start = len(fake.requests)
    again = ingest(rt)
    assert x_reads(fake, start) == []
    rep = next(s for s in again.sources if s.source_id == search)
    assert rep.waiting_until and not rep.fetch_error and again.status == "ok"
    later = datetime.fromisoformat(rep.waiting_until.replace("Z", "+00:00"))
    assert timedelta(hours=23) < later - datetime.now(UTC) <= timedelta(hours=24)


def test_the_cap_defers_x_sources_to_next_month_and_raising_it_lifts_that(tmp_path, embedder,
                                                                           machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http,
                        xcfg=XConfig(monthly_usd=0.05))
    try:
        home = add(rt, "x.home")
        ingest(rt)                                         # 3 posts + the sign-in: $0.025
        fake.timeline = [post(1849000000000000000 + i, f"post {i}") for i in range(30, 0, -1)]
        ingest(rt)
        start = len(fake.requests)
        held = ingest(rt)
        rep = held.sources[0]
        assert x_reads(fake, start) == []
        assert rep.fetch_state == "paced" and rep.fetch_error.startswith("X cap reached")
        first_of_next = spend.next_month(datetime.now(UTC))
        assert rep.retry_at == first_of_next.strftime("%Y-%m-%dT%H:%M:%SZ")
        assert held.status == "ok"                         # paced, never failing
        row = next(r for r in source_health.list_sources(rt.store, rt.cfg) if r["id"] == home)
        assert row["status"] == "paced"
        assert doctor._x_spend(rt.cfg, rt.store)[0].status == doctor.WARN
        from dataclasses import replace
        rt.cfg = replace(rt.cfg, x=replace(rt.cfg.x, monthly_usd=None))
        start = len(fake.requests)
        ingest(rt)
        assert len(x_reads(fake, start)) == 1
    finally:
        rt.close()


def test_spent_credits_pace_the_source_six_hours_and_say_so(rig):
    rt, fake = rig
    add(rt, "x.list", {"list": "42"})
    fake.credits = False
    report = ingest(rt)
    rep = report.sources[0]
    assert rep.fetch_state == "paced" and "X credits exhausted" in rep.fetch_error
    ahead = datetime.fromisoformat(rep.retry_at.replace("Z", "+00:00")) - datetime.now(UTC)
    assert timedelta(hours=5, minutes=50) < ahead <= timedelta(hours=6)
    assert report.status == "ok" and ledger(rt) == {"user_read": 1, "list_read": 1}
    [line] = doctor._x_spend(rt.cfg, rt.store)
    assert line.status == doctor.WARN and "credits exhausted" in line.detail


def test_a_revoked_token_is_needs_login_and_the_run_goes_on(rig):
    rt, fake = rig
    add(rt, "x.home")
    fake.revoked.add(fake.access)
    report = ingest(rt)
    # the only source could not be read, so the run is failed (ingest's rule for any kind)
    assert report.sources[0].fetch_state == "needs_login" and report.status == "failed"
    assert rt.connections.accounts()[0]["state"] == "needs_login"


def test_settings_spend_shows_the_x_line_and_takes_its_cap(rig, tmp_path):
    rt, fake = rig
    path = tmp_path / "kranto.yaml"
    from kranto.config import DEFAULT_CONFIG_YAML
    # an install from before X: no x section at all
    path.write_text(DEFAULT_CONFIG_YAML.split("\nx:\n")[0] + "\n" + "telemetry:"
                    + DEFAULT_CONFIG_YAML.split("\ntelemetry:", 1)[1])
    add(rt, "x.home")
    ingest(rt)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        got = web.get("/api/settings/spend").json()["x"]
        assert got["monthly_usd"] is None and got["connected"] is True and not got["capped"]
        assert got["reads"] == 4 and got["spent_usd"] == pytest.approx(0.025)
        set_ = web.post("/api/settings/spend", json={"x_monthly_usd": 30})
        assert set_.status_code == 200, set_.text
        assert set_.json()["x"]["monthly_usd"] == 30.0 and rt.cfg.x.monthly_usd == 30.0
        assert web.post("/api/settings/spend", json={"x_monthly_usd": -1}).status_code == 400
        assert web.post("/api/settings/spend", json={"x_monthly_usd": None}).json()["x"][
            "monthly_usd"] is None
    from kranto.config import load
    assert load(tmp_path, dotenv=False).x.monthly_usd is None
    detail = source_health.source_detail(rt.store, rt.cfg, 1)
    assert "max_results=20" in detail["how"]["request"] and "$0.10" in detail["how"]["terms"]


def test_x_posts_are_kept_30_days_by_default(rig):
    rt, _ = rig
    assert rt.cfg.retention.days_for_kind("x") == 30
    from kranto.config import _parse_retention
    assert _parse_retention({"by_kind": {"x": 60}}).days_for_kind("x") == 60


def test_an_x_source_needs_a_valid_shape():
    with pytest.raises(ValueError, match="list's number"):
        XSource(None, what="list", list_id="abc")
    with pytest.raises(ValueError, match="needs a query"):
        XSource(None, what="search")
    with pytest.raises(ValueError, match="unknown X source"):
        XSource(None, what="mentions")


# -- once over a real socket ------------------------------------------------------------------


def _loopback_port() -> int:
    """A free port in 9070-9079 (the range this track may use)."""
    for port in range(9070, 9080):
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
            return port
    pytest.skip("no free port in 9070-9079")


class _ToLoopback(httpx.BaseTransport):
    """api.x.com and x.com, sent to the fake on 127.0.0.1 over a real socket; the request's
    own Host header and path are kept."""

    def __init__(self, port: int) -> None:
        self.port, self.inner = port, httpx.HTTPTransport()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        headers = dict(request.headers)
        sent = httpx.Request(request.method, url, headers=headers, content=request.content)
        return self.inner.handle_request(sent)


def test_one_run_end_to_end_over_a_loopback_socket(tmp_path, embedder, machine_id):
    port = _loopback_port()
    holder = {}

    class Handler(BaseHTTPRequestHandler):
        def _serve(self):
            length = int(self.headers.get("content-length") or 0)
            body = self.rfile.read(length) if length else b""
            host = self.headers.get("host", "api.x.com").split(":")[0]
            req = httpx.Request(self.command, f"https://{host}{self.path}",
                                headers=dict(self.headers), content=body)
            reply = holder["fake"](req)
            self.send_response(reply.status_code)
            for k, v in reply.headers.items():
                if k.lower() not in ("content-length", "transfer-encoding", "connection"):
                    self.send_header(k, v)
            self.send_header("content-length", str(len(reply.content)))
            self.end_headers()
            self.wfile.write(reply.content)

        do_GET = do_POST = _serve

        def log_message(self, *args):
            return None

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def real_http(fake):
        holder["fake"] = fake
        return HTTP(transport=_ToLoopback(port), resolver=lambda h: ["93.184.216.34"])

    try:
        rt, fake = make_rig(tmp_path, embedder, machine_id, real_http)
        try:
            add(rt, "x.list", {"list": "42"})
            report = ingest(rt)
            assert report.status == "ok" and report.contributed == 3
            reads = x_reads(fake)
            assert reads[-1].headers["authorization"] == f"Bearer {fake.access}"
            assert reads[-1].headers["host"] == "api.x.com"
            assert ledger(rt) == dict(fake.returned)
        finally:
            rt.close()
    finally:
        server.shutdown()
        server.server_close()
