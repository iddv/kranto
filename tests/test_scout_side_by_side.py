"""The scout test-reads its places side by side (``scout.check_all``): different hosts at once,
one host still one request at a time, the embedding model run on the calling thread only, and
the same numbers as reading them one after another."""

import threading
import time
from collections import defaultdict
from datetime import UTC, datetime

import httpx

from kranto import library
from kranto.scout import Proposal, check_all, validate
from kranto.sources import HTTP
from kranto.sources.pacing import Hosts

from .test_scout import feed

NOW = datetime(2026, 9, 24, tzinfo=UTC)
HOLD = 0.15  # seconds each reply takes


class Watch:
    """A site that takes ``HOLD`` to answer and counts the requests in flight, per host."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.now: dict[str, int] = defaultdict(int)
        self.most: dict[str, int] = defaultdict(int)
        self.most_overall = 0

    def __call__(self, request: httpx.Request) -> httpx.Response:
        host = request.url.host
        with self.lock:
            self.now[host] += 1
            self.most[host] = max(self.most[host], self.now[host])
            self.most_overall = max(self.most_overall, sum(self.now.values()))
        try:
            time.sleep(HOLD)
            if request.url.path not in ("/good", "/off"):
                return httpx.Response(404)
            words = "solar microgrid battery" if request.url.path == "/good" else "knitting wool"
            return httpx.Response(200, content=feed(f"{words} one", f"{words} two"))
        finally:
            with self.lock:
                self.now[host] -= 1


def client(watch: Watch) -> HTTP:
    # gap 0 and no sleeping: the test never waits for pacing, but the per-host slot still holds
    return HTTP(transport=httpx.MockTransport(watch), resolver=lambda h: ["93.184.216.34"],
                hosts=Hosts(default_gap=0.0, sleep=lambda s: None))


class Counted:
    """The test embedder, recording which threads ran it and how often."""

    def __init__(self, inner) -> None:
        self.inner, self.threads, self.calls = inner, [], 0

    def embed_documents(self, texts):
        self.calls += 1
        self.threads.append(threading.current_thread())
        return self.inner.embed_documents(texts)


def topic_for(embedder):
    return library.Topic(1, "solar", "solar microgrid battery",
                         embedder.embed_query("solar microgrid battery"))


def test_different_hosts_are_read_at_once(embedder):
    watch = Watch()
    proposals = [Proposal("rss", f"https://h{i}.example.com/good", "") for i in range(6)]
    started = time.monotonic()
    out = check_all(proposals, client(watch), embedder, topic_for(embedder), now=NOW)
    took = time.monotonic() - started
    assert [v.status for v, *_ in out] == ["valid"] * 6
    assert watch.most_overall > 1
    assert took < 6 * HOLD * 0.75, took          # one after another would take 6 holds


def test_one_host_is_still_asked_one_request_at_a_time(embedder):
    watch = Watch()
    proposals = [Proposal("rss", f"https://one.example.com/good?n={i}", "") for i in range(4)]
    out = check_all(proposals, client(watch), embedder, topic_for(embedder), now=NOW)
    assert [v.status for v, *_ in out] == ["valid"] * 4
    assert watch.most["one.example.com"] == 1


def test_same_numbers_in_the_same_order_and_the_model_runs_on_this_thread_only(embedder):
    urls = ["https://a.example.com/good", "https://b.example.com/missing",
            "https://c.example.com/off", "https://d.example.com/good"]
    proposals = [Proposal("rss", u, "") for u in urls]
    topic = topic_for(embedder)
    one_by_one = [validate(p, client(Watch()), embedder, topic, now=NOW) for p in proposals]
    counted = Counted(embedder)
    side_by_side = check_all(proposals, client(Watch()), counted, topic, now=NOW)
    assert side_by_side == one_by_one
    assert [v.status for v, *_ in side_by_side] == ["valid", "invalid", "valid", "valid"]
    assert side_by_side[0][0].median_similarity > side_by_side[2][0].median_similarity
    assert counted.calls == 3                    # one per place read, none for the 404
    assert set(counted.threads) == {threading.current_thread()}


def test_without_a_topic_nothing_is_embedded(embedder):
    counted = Counted(embedder)
    out = check_all([Proposal("rss", "https://a.example.com/good", "")], client(Watch()),
                    counted, None, now=NOW)
    assert out[0][0].status == "valid" and out[0][0].median_similarity is None
    assert counted.calls == 0
    assert check_all([], client(Watch()), counted, None) == []
