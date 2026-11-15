"""Stop where the work can stop (the owner's D-7): a cooperative flag checked
between a run's steps. A fake ingest stops after the source in hand; the run ends stopped, its
runs row skipped (so the job is due again at its re-check, never lost). Nothing touches a model
or the network."""

from __future__ import annotations

from datetime import timedelta

import pytest

from kranto import activity, library
from kranto.scheduler import SKIP_RECHECK, Job, is_due
from kranto.store import utcnow

from .conftest import chat_response
from .test_tick import CONTRIB, FakeSource, add, cfg, ingest, items  # noqa: F401 - fixtures
from .test_web import rt  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def _writers_stopped():
    yield
    activity.shutdown()


@pytest.fixture(autouse=True)
def fake_kind(monkeypatch):
    from kranto import sources
    monkeypatch.setitem(sources.KINDS, "fake", FakeSource)
    FakeSource.feeds = {}


def ended(store, uuid):
    activity.settle(store, 5)
    return store.query_one("SELECT * FROM run_marks WHERE run_uuid = ? AND mark = 'ended'",
                           (uuid,))


def test_stop_ends_an_ingest_after_the_source_in_hand(cfg, store, make_client,  # noqa: F811
                                                      embedder):
    for n in "abcde":
        add(store, n, items(3, prefix=n))
    client = make_client(lambda body: chat_response(CONTRIB))

    class Stopper(FakeSource):
        def fetch(self):
            if self.name == "b":
                activity.current().request_stop()      # the owner pressed Stop now
            return super().fetch()

    from kranto import sources
    sources.KINDS["fake"] = Stopper
    with activity.run(store, "ingest", origin="press") as r:
        report = ingest(cfg, store, client, embedder)
    assert report.run_uuid == r.uuid
    assert report.status == "skipped" and report.error.startswith("stopped by you after source")
    reached = [s for s in report.sources if s.fetched]
    assert [s.label for s in reached] == ["fake:a", "fake:b"]   # b was in hand; c to e wait
    assert ended(store, r.uuid)["state"] == "stopped"
    row = store.query_one("SELECT status FROM runs WHERE run_uuid = ?", (r.uuid,))
    assert row["status"] == "skipped"
    # still due: at the skip's re-check, as any skipped run
    j = Job("ingest", 2, lambda: None)
    assert not is_due(store, j, utcnow())
    assert is_due(store, j, utcnow() + SKIP_RECHECK + timedelta(minutes=1))
    assert library.seen_item_ids(store, 3) == set()             # c's items are not consumed


def test_a_cub_host_refuses_the_next_call_of_a_stopped_run(rt):  # noqa: F811
    from types import SimpleNamespace

    from kranto.core.cubs.host import CubHost, RpcError
    runtime = SimpleNamespace(rt=rt, halted=lambda cub: None)
    with activity.run(rt.store, "toot.weekly") as r:
        host = CubHost(runtime, SimpleNamespace(id="toot"), run_uuid=r.uuid,
                       run_log=SimpleNamespace(host=lambda *a, **k: None))
        r.request_stop()
        with pytest.raises(RpcError, match="stopped by the owner"):
            host.dispatch("kv.get", {"key": "x"})
