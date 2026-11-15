"""Polite fetching (the owner's ruling, 2026-10-09): pacing per host, Retry-After and backoff
on 429 and 503, timeouts retried, paced is never a failure, and a source failing run after
run backs off by itself and asks for you. Offline: fake HTTP replies, a recorded sleep."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from time_machine import travel

from kranto import library, source_health
from kranto.config import (
    BudgetConfig,
    Config,
    ConfigError,
    FetchConfig,
    IngestConfig,
    LookConfig,
    MapConfig,
    load,
)
from kranto.runtime import open_runtime
from kranto.sources import HTTP, SourceError, pacing
from kranto.tick import run_ingest
from kranto.web.app import create_app

from .conftest import FIXED_NOW, chat_response, llm_config, web_client

PUBLIC = ["93.184.216.34"]


def http_for(handler):
    return HTTP(transport=httpx.MockTransport(handler), resolver=lambda h: PUBLIC)


def replies(*answers):
    """A transport handler that answers with ``answers`` in turn (the last one repeats), and
    keeps every request in ``.seen``."""
    queue = list(answers)

    def handler(request):
        handler.seen.append(request)
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    handler.seen = []
    return handler


OK = httpx.Response(200, text="fine")


# -- Retry-After, backoff and timeouts, in one request -------------------------------------


def test_429_with_retry_after_seconds_waits_it_out_and_retries(no_host_pacing):
    site = replies(httpx.Response(429, headers={"Retry-After": "7"}), OK)
    assert http_for(site).get("https://export.arxiv.org/api/query").text == "fine"
    assert len(site.seen) == 2 and no_host_pacing.slept == [pytest.approx(7, abs=0.5)]


def test_503_with_a_retry_after_date_is_honoured_too(no_host_pacing):
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=12), usegmt=True)
    site = replies(httpx.Response(503, headers={"Retry-After": when}), OK)
    assert http_for(site).get("https://ex.com/feed").text == "fine"
    assert len(site.seen) == 2 and 9 <= no_host_pacing.slept[0] <= 13


def test_429_without_retry_after_backs_off_exponentially_with_jitter(no_host_pacing):
    site = replies(httpx.Response(429))
    with pytest.raises(SourceError) as err:
        http_for(site).get("https://ex.com/feed")
    # two retries (fetch.retries), each after a longer wait: 4 s then 8 s, plus up to half again
    assert len(site.seen) == 3
    first, second = no_host_pacing.slept
    assert 4 <= first <= 6 and 8 <= second <= 12
    assert err.value.transient and not err.value.needs_login
    # given up: the error says when the host may be asked again (after the third backoff)
    ahead = (err.value.retry_at - datetime.now(UTC)).total_seconds()
    assert 15 <= ahead <= 25


def test_429_with_an_x_rate_limit_reset_waits_for_the_window(no_host_pacing):
    # X answers a 429 with x-rate-limit-reset (epoch seconds) and no Retry-After
    reset = str(int(time.time()) + 9)
    site = replies(httpx.Response(429, headers={"x-rate-limit-reset": reset}), OK)
    assert http_for(site).get("https://api.x.com/2/users/me").text == "fine"
    assert len(site.seen) == 2 and 7 <= no_host_pacing.slept[0] <= 10


def test_a_far_x_rate_limit_reset_defers_the_source(no_host_pacing):
    reset = str(int(time.time()) + 900)
    site = replies(httpx.Response(429, headers={"x-rate-limit-reset": reset}), OK)
    with pytest.raises(SourceError) as err:
        http_for(site).get("https://api.x.com/2/lists/1/tweets")
    assert len(site.seen) == 1 and no_host_pacing.slept == []
    ahead = (err.value.retry_at - datetime.now(UTC)).total_seconds()
    assert 880 <= ahead <= 905


def test_reset_after_parsing():
    assert pacing.reset_after_seconds({"x-rate-limit-reset": "1060"}, now=1000.0) == 60
    assert pacing.reset_after_seconds({"x-rate-limit-reset": "900"}, now=1000.0) == 0
    assert pacing.reset_after_seconds({"x-rate-limit-reset": "soon"}, now=1000.0) is None
    assert pacing.reset_after_seconds({}, now=1000.0) is None
    far = pacing.reset_after_seconds({"x-rate-limit-reset": str(10**9)}, now=0.0)
    assert far == pacing.MAX_RETRY_AFTER_SECONDS


def test_a_long_retry_after_defers_instead_of_waiting(no_host_pacing):
    site = replies(httpx.Response(429, headers={"Retry-After": "600"}), OK)
    http = http_for(site)
    with pytest.raises(SourceError) as err:
        http.get("https://export.arxiv.org/api/query", params={"q": "a"})
    assert len(site.seen) == 1 and no_host_pacing.slept == []
    assert err.value.transient
    assert 590 <= (err.value.retry_at - datetime.now(UTC)).total_seconds() <= 600
    # every request to that host is now deferred without being sent
    with pytest.raises(SourceError, match="paced") as again:
        http.get("https://export.arxiv.org/api/query", params={"q": "b"})
    assert len(site.seen) == 1 and again.value.retry_at is not None
    # another host is not held up
    assert http.get("https://ex.com/feed").text == "fine"


def test_timeouts_are_retried_with_backoff(no_host_pacing):
    site = replies(httpx.ReadTimeout("slow"), httpx.ConnectTimeout("slower"), OK)
    assert http_for(site).get("https://export.arxiv.org/api/query").text == "fine"
    assert len(site.seen) == 3 and len(no_host_pacing.slept) == 2


def test_persistent_timeouts_end_paced_with_a_retry_time(no_host_pacing):
    site = replies(httpx.ReadTimeout("slow"))
    with pytest.raises(SourceError, match="ReadTimeout") as err:
        http_for(site).get("https://export.arxiv.org/api/query")
    assert len(site.seen) == 3 and err.value.transient and err.value.retry_at is not None


def test_a_request_with_its_own_deadline_is_not_retried(no_host_pacing):
    # gathering for one item is context: one try, then it moves on
    site = replies(httpx.Response(429), OK)
    with pytest.raises(SourceError):
        http_for(site).get("https://ex.com/page", deadline=10)
    assert len(site.seen) == 1


def test_a_404_is_not_retried_and_is_not_transient(no_host_pacing):
    site = replies(httpx.Response(404))
    with pytest.raises(SourceError) as err:
        http_for(site).get("https://www.youtube.com/feeds/videos.xml")
    assert len(site.seen) == 1 and not err.value.transient and err.value.retry_at is None


def test_retry_after_parsing():
    now = datetime(2026, 10, 9, 4, 0, tzinfo=UTC)
    assert pacing.retry_after_seconds("120") == 120
    assert pacing.retry_after_seconds("Fri, 09 Oct 2026 04:01:00 GMT", now=now) == 60
    assert pacing.retry_after_seconds("Fri, 09 Oct 2026 03:00:00 GMT", now=now) == 0
    assert pacing.retry_after_seconds("soon") is None and pacing.retry_after_seconds(None) is None
    assert pacing.retry_after_seconds("999999") == pacing.MAX_RETRY_AFTER_SECONDS


# -- pacing per host -------------------------------------------------------------------------


def test_requests_to_one_host_keep_its_gap_and_other_hosts_do_not_wait():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(round(s, 3))
        now[0] += s

    hosts = pacing.Hosts(default_gap=1.0, clock=lambda: now[0], sleep=sleep)
    order = []

    def site(request):
        order.append((request.url.host, now[0]))
        now[0] += 0.5                      # each reply takes half a second
        return OK

    http = HTTP(transport=httpx.MockTransport(site), resolver=lambda h: PUBLIC, hosts=hosts)
    for url in ("https://export.arxiv.org/a", "https://export.arxiv.org/b", "https://ex.com/c",
                "https://export.arxiv.org/d"):
        http.get(url)
    # arXiv: three seconds from the end of one request to the start of the next; ex.com: none
    assert order == [("export.arxiv.org", 0.0), ("export.arxiv.org", 3.5), ("ex.com", 4.0),
                     ("export.arxiv.org", 7.0)]
    assert slept == [3.0, 2.5]


def test_one_request_at_a_time_per_host():
    hosts = pacing.Hosts(default_gap=0.0, sleep=lambda s: None)
    inflight, most = {}, {}
    guard = threading.Lock()

    def site(request):
        host = request.url.host
        with guard:
            inflight[host] = inflight.get(host, 0) + 1
            most[host] = max(most.get(host, 0), inflight[host])
        time.sleep(0.02)
        with guard:
            inflight[host] -= 1
        return OK

    http = HTTP(transport=httpx.MockTransport(site), resolver=lambda h: PUBLIC, hosts=hosts)
    urls = [f"https://{h}/{i}" for i in range(4) for h in ("export.arxiv.org", "ex.com")]
    threads = [threading.Thread(target=http.get, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert most == {"export.arxiv.org": 1, "ex.com": 1}


def test_fetch_config_sets_gaps_and_limits(tmp_path):
    hosts = pacing.Hosts()
    hosts.configure(FetchConfig(min_gap_seconds=0.5, hosts={"api.example.org": 10},
                                retries=1, max_wait_seconds=5))
    assert hosts.gap("api.example.org") == 10 and hosts.gap("export.arxiv.org") == 3.0
    assert hosts.gap("other.org") == 0.5 and hosts.retries == 1 and hosts.max_wait == 5

    base = "llm:\n  base_url: https://x\n  api_key_env: K\n  models: {judge: a, reason: b}\n"
    (tmp_path / "kranto.yaml").write_text(base + "fetch:\n  hosts: {Api.Example.org: 2}\n"
                                            "  failing_after_runs: 2\n")
    cfg = load(tmp_path, dotenv=False)
    assert cfg.fetch.hosts == {"api.example.org": 2.0} and cfg.fetch.failing_after_runs == 2
    (tmp_path / "kranto.yaml").write_text(base + "fetch:\n  retries: -1\n")
    with pytest.raises(ConfigError, match="fetch.retries"):
        load(tmp_path, dotenv=False)
    (tmp_path / "kranto.yaml").write_text(base + "fetch:\n  failing_after_runs: 0\n")
    with pytest.raises(ConfigError, match="failing_after_runs"):
        load(tmp_path, dotenv=False)


# -- ingest: paced is not a failure; a failing streak backs off ------------------------------


def feed(*titles):
    items = "".join(f"<item><title>{t}</title><link>https://ex.com/{i}</link><guid>{t}</guid>"
                    f"<description>{t} details</description>"
                    f"<pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate></item>"
                    for i, t in enumerate(titles))
    return f"<rss><channel><title>Feed</title>{items}</channel></rss>".encode()


class Site:
    """Feeds by path; ``answers[path]`` overrides one with a reply (or a list, in turn)."""

    def __init__(self):
        self.answers, self.requests = {}, []

    def __call__(self, request):
        self.requests.append(request)
        answer = self.answers.get(request.url.path)
        if isinstance(answer, list):
            answer = answer.pop(0) if len(answer) > 1 else answer[0]
        if isinstance(answer, Exception):
            raise answer
        if answer is not None:
            return answer
        return httpx.Response(200, content=feed(f"solar microgrid {request.url.path}"))

    def hits(self, path):
        return sum(1 for r in self.requests if r.url.path == path)


@pytest.fixture
def site():
    return Site()


@pytest.fixture
def rt(tmp_path, store, embedder, make_client, site):
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(fetch_full_text=False, backfill_items=0),
                 map=MapConfig(), look=LookConfig(enabled=False))
    client = make_client(lambda body: chat_response(json.dumps({
        "kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.9,
        "durability": 0.9, "opportunity": 0.9, "override": False, "tags": []})))
    runtime = open_runtime(cfg, store=store, embedder=embedder, llm=client, http=http_for(site))
    library.add_topic(store, embedder, "solar", "solar microgrid battery storage")
    return runtime


def ingest(rt):
    return run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                      connections=rt.connections, lock_path=rt.cfg.root / "ingest.lock")


def arxiv(store, query):
    return library.add_source(store, "arxiv", {"query": query}, label=f"arXiv search: {query}")


def test_four_arxiv_searches_share_one_cooldown_and_the_run_stays_ok(rt, site):
    """The 2026-10-09 03:55 run: four searches on export.arxiv.org drew 429s and the run was
    marked degraded. Now the first 429's Retry-After holds the host for every search, none is
    sent again while it lasts, and the run is ok with the four sources paced."""
    ids = [arxiv(rt.store, q) for q in ("agent evaluation", "tool use", "serving", "fine tuning")]
    good = library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    site.answers["/api/query"] = httpx.Response(429, headers={"Retry-After": "900"})
    report = ingest(rt)
    assert report.status == "ok"
    assert site.hits("/api/query") == 1          # one 429; the rest deferred unsent
    by_id = {s.source_id: s for s in report.sources}
    assert all(by_id[i].fetch_state == "paced" and by_id[i].retry_at for i in ids)
    assert by_id[good].fetch_state == "ok"
    rows = {s["id"]: s for s in source_health.list_sources(rt.store, rt.cfg)}
    assert rows[ids[0]]["status"] == "paced" and rows[ids[0]]["retry_at"]
    assert rows[ids[0]]["detail"].startswith("retrying at 2026-")
    assert not rows[ids[0]]["needs_fixing"]


def test_a_paced_source_is_fetched_again_at_the_end_of_the_run(rt, site):
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/busy"}, label="Busy")
    library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    # three 429s use up the request's own retries; the end-of-run pass finds it open
    site.answers["/busy"] = [httpx.Response(429)] * 3 + [
        httpx.Response(200, content=feed("solar microgrid late"))]
    report = ingest(rt)
    rep = next(s for s in report.sources if s.source_id == src)
    assert report.status == "ok" and rep.retried and rep.fetch_state == "ok"
    assert rep.fetch_error is None and rep.fetched == 1 and site.hits("/busy") == 4
    states = [r["state"] for r in rt.store.query(
        "SELECT state FROM source_fetches WHERE source_id = ? ORDER BY id", (src,))]
    assert states == ["paced", "ok"]


def test_a_paced_source_waits_for_its_retry_time_across_runs(rt, site, no_host_pacing):
    src = arxiv(rt.store, "agents")
    site.answers["/api/query"] = httpx.Response(429, headers={"Retry-After": "3600"})
    assert ingest(rt).status == "ok"
    sent = site.hits("/api/query")
    # a new process (the next run) has no cooldown in memory: the stored retry time defers it
    no_host_pacing._hosts.clear()
    report = ingest(rt)
    rep = report.sources[0]
    assert report.status == "ok" and rep.waiting_until and site.hits("/api/query") == sent
    assert rt.store.query_one("SELECT COUNT(*) AS n FROM source_fetches WHERE source_id = ?",
                              (src,))["n"] == 2       # the first run's two tries; none since
    with travel(FIXED_NOW + timedelta(hours=2), tick=True):
        no_host_pacing._hosts.clear()
        site.answers["/api/query"] = httpx.Response(200, content=feed("solar microgrid paper"))
        later = ingest(rt)
    assert later.sources[0].fetch_state == "ok"


def test_a_404_streak_backs_off_degrades_once_and_needs_you(rt, site, monkeypatch):
    gone = library.add_source(rt.store, "rss", {"url": "https://ex.com/gone"}, label="Gone")
    library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    site.answers["/gone"] = httpx.Response(404)
    first, second, third = ingest(rt), ingest(rt), ingest(rt)
    # one or two 404s are not persistent; the third in a row is, and the run says so
    assert (first.status, second.status, third.status) == ("ok", "ok", "degraded")
    assert [r.sources[0].failing_runs for r in (first, second, third)] == [1, 2, 3]
    assert source_health.needs_fixing(rt.store, rt.cfg)[0]["id"] == gone
    row = next(s for s in source_health.list_sources(rt.store, rt.cfg) if s["id"] == gone)
    assert row["status"] == "failing" and row["needs_fixing"] and row["failing_runs"] == 3
    assert row["detail"].startswith("failing 3 runs in a row; left alone until")

    # backing off: not fetched, and the run is ok
    fourth = ingest(rt)
    assert fourth.status == "ok" and fourth.sources[0].waiting_until == row["backoff_until"]
    assert site.hits("/gone") == 3

    # a day later it is tried again; fixed meanwhile, the streak ends
    with travel(FIXED_NOW + timedelta(hours=25), tick=True):
        site.answers.pop("/gone")
        fifth = ingest(rt)
        assert fifth.sources[0].fetch_state == "ok" and site.hits("/gone") == 4
        assert source_health.needs_fixing(rt.store, rt.cfg) == []


def test_backoff_doubles_up_to_the_cap():
    cfg = FetchConfig(failing_after_runs=3, failing_backoff_hours=24, failing_backoff_max_hours=72)
    last = "2026-10-09T00:00:00Z"
    assert source_health.backoff_until(2, last, cfg) is None
    assert source_health.backoff_until(3, last, cfg) == "2026-10-10T00:00:00Z"
    assert source_health.backoff_until(4, last, cfg) == "2026-10-11T00:00:00Z"
    assert source_health.backoff_until(9, last, cfg) == "2026-10-12T00:00:00Z"


def test_paced_fetches_neither_break_nor_extend_a_streak():
    rows = [{"state": s, "trigger": t, "created_at": f"2026-10-0{i}T00:00:00Z"}
            for i, (s, t) in enumerate([("failing", "run"), ("paced", "run"),
                                        ("failing", "manual"), ("failing", "run"),
                                        ("ok", "run"), ("failing", "run")], start=1)]
    assert source_health.failing_streak(rows) == (2, "2026-10-01T00:00:00Z")


def test_needs_you_lists_a_persistently_failing_source(rt, site):
    gone = library.add_source(rt.store, "rss", {"url": "https://ex.com/gone"}, label="Gone feed")
    library.add_source(rt.store, "rss", {"url": "https://ex.com/good"}, label="Good")
    site.answers["/gone"] = httpx.Response(404)
    for _ in range(3):
        ingest(rt)
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        today = web.get("/api/today").json()
        [row] = today["sources_failing"]
        assert row["id"] == gone and row["label"] == "Gone feed" and row["failing_runs"] == 3
        assert "HTTP 404" in row["error"] and row["backoff_until"]
        one = web.get(f"/api/sources/{gone}").json()
        assert one["needs_fixing"] and one["status"] == "failing"
        # removed (retired): it leaves Needs you
        assert web.post(f"/api/sources/{gone}/status", json={"status": "retired"}).status_code \
            == 200
        assert web.get("/api/today").json()["sources_failing"] == []


def test_fetch_now_records_a_paced_retry_time(rt, site):
    src = arxiv(rt.store, "agents")
    site.answers["/api/query"] = httpx.Response(429, headers={"Retry-After": "120"})
    out = source_health.fetch_now(rt, src)
    assert out["state"] == "paced" and out["retry_at"]
    stored = rt.store.query_one("SELECT retry_at FROM source_fetches WHERE source_id = ?", (src,))
    assert stored["retry_at"] == out["retry_at"]
