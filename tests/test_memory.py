"""Memory bounds (MEM, 2026-10-20): a stranger's first read grew Kranto to 7.6 GB.

The cause was the embedder: one model run for a whole first backfill (40 texts of about 630
tokens), whose working memory grows with the batch times the square of its longest text, kept
by onnxruntime's CPU arena. These tests hold the embedder to small runs, one at a time, with the
arena and prepacking off, and hold the Python heap of a first backfill and of a day of ingest
runs to a budget. The real model's resident memory is measured by the slow test at the end.
"""

import json
import os
import random
import subprocess
import sys
import threading
import time
import tracemalloc
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from kranto import embed, library, memory, sources
from kranto.config import BudgetConfig, Config, IngestConfig, LookConfig, MapConfig
from kranto.embed import MAX_BATCH, MAX_TOKENS, NomicEmbedder, StubEmbedder
from kranto.scheduler import Job, Scheduler
from kranto.sources import Item
from kranto.tick import run_ingest

from .conftest import SCREEN_PASS, chat_response, is_screen, llm_config

CONTRIB = json.dumps({
    "kind": "beat", "summary": "a concrete thing", "why_it_matters": "because",
    "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9,
})
WORDS = ["local", "first", "sync", "engine", "crdt", "offline", "replica", "merge", "conflict",
         "device", "storage", "peer", "network", "schema", "migration"]


class FakeTokenizer:
    def __init__(self):
        self.truncation = None

    def enable_truncation(self, max_length):
        self.truncation = max_length


class FakeModel:
    """fastembed's TextEmbedding as the embedder uses it: records each run's texts, how many
    runs overlap, and the options it was made with."""

    def __init__(self, name, **kwargs):
        self.name, self.kwargs = name, kwargs
        self.model = type("Inner", (), {})()
        self.model.tokenizer = FakeTokenizer()
        self.runs: list[list[str]] = []
        self.active = self.most_active = 0
        self.pause = 0.0
        self._lock = threading.Lock()

    def embed(self, texts, batch_size=256):
        texts = list(texts)
        with self._lock:
            self.active += 1
            self.most_active = max(self.most_active, self.active)
        try:
            time.sleep(self.pause)
            for start in range(0, len(texts), batch_size):
                self.runs.append(texts[start:start + batch_size])
            stub = StubEmbedder(dim=768)
            yield from stub.embed_documents(texts)
        finally:
            with self._lock:
                self.active -= 1


def fake_nomic():
    made = []

    def factory(name, **kwargs):
        made.append(FakeModel(name, **kwargs))
        return made[-1]

    return NomicEmbedder(factory=factory), made


def text(n_chars, seed):
    """On the topic's words, otherwise its own: no two texts are near duplicates."""
    rng = random.Random(seed)
    words = list(WORDS[:4])
    while sum(len(w) + 1 for w in words) < n_chars:
        words.append(rng.choice(WORDS) if rng.random() < 0.2 else f"w{rng.randrange(20000)}")
    return " ".join(words)[:n_chars]


def test_the_embedder_runs_small_batches_without_the_arena_and_keeps_the_order():
    e, made = fake_nomic()
    texts = [text(200 + 97 * i % 1900, i) for i in range(40)]
    vecs = e.embed_documents(texts)
    model = made[0]
    assert model.kwargs["enable_cpu_mem_arena"] is False
    assert model.model.tokenizer.truncation == MAX_TOKENS
    assert len(model.runs) >= 10 and all(len(r) <= MAX_BATCH for r in model.runs)
    for run in model.runs:
        assert len(run) * max(len(t) for t in run) ** 2 <= embed.BATCH_BUDGET
    # each text's vector is its own, whatever run it was in
    full = StubEmbedder(dim=768).embed_documents([f"search_document: {t}" for t in texts])
    np.testing.assert_allclose(vecs, embed._normalise_rows(full[:, :384]))
    assert len(made) == 1                                       # loaded once
    e.embed_query("again")
    assert len(made) == 1


def test_an_idle_model_is_let_go_and_loaded_again_when_needed(monkeypatch):
    e, made = fake_nomic()
    assert not e.drop_if_idle(0)                                # nothing loaded yet
    e.embed_query("load")
    assert not e.drop_if_idle(3600)                             # just used
    with e._lock:
        assert not e.drop_if_idle(0)                            # an embed is running
    assert e.drop_if_idle(0) and e._model is None
    e.embed_query("again")
    assert len(made) == 2 and e._model is made[1]

    from kranto import cli
    released = []
    monkeypatch.setattr(memory, "release", lambda: released.append(1))
    rt = type("Rt", (), {"embedder": e})()
    e.embed_query("used just now")
    cli._idle_embedder(rt)
    assert e._model is not None and released == []                # not idle for 10 minutes
    monkeypatch.setattr(embed, "IDLE_SECONDS", 0)
    cli._idle_embedder(rt)
    assert e._model is None and released == [1]
    cli._idle_embedder(type("Rt", (), {"embedder": StubEmbedder()})())   # no model to drop
    assert released == [1]


def test_a_long_text_runs_alone_and_short_ones_share_a_run():
    texts = ["x" * 10_000, "short", "also short", "x" * 2_000, "tiny"]
    runs = embed.batches(texts)
    assert sorted(i for r in runs for i in r) == list(range(5))
    assert [0] in runs                                          # the long one alone
    assert any(set(r) >= {1, 2, 4} for r in runs)               # the short ones together
    assert embed.batches([]) == []


def test_one_model_run_at_a_time_across_threads():
    """The server shares one embedder between its jobs and its requests: two at once would
    each hold a run's working memory."""
    e, made = fake_nomic()
    e.embed_query("load")
    made[0].pause = 0.05
    threads = [threading.Thread(target=e.embed_documents, args=([text(500, i)] * 6,))
               for i in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert made[0].most_active == 1


def test_the_model_loads_without_prepacking_and_the_hook_is_put_back():
    pytest.importorskip("fastembed")
    from fastembed.common.onnx_model import OnnxModel

    before = OnnxModel.__dict__["add_extra_session_options"]
    seen = {}

    class Options:
        enable_cpu_mem_arena = True

        def add_session_config_entry(self, key, value):
            seen[key] = value

    def factory(name, **kwargs):
        options = Options()
        OnnxModel.add_extra_session_options(options, {"enable_cpu_mem_arena": False})
        seen["arena"] = options.enable_cpu_mem_arena
        return FakeModel(name, **kwargs)

    NomicEmbedder(factory=factory).embed_query("x")
    assert seen == {"session.disable_prepacking": "1", "arena": False}
    assert OnnxModel.__dict__["add_extra_session_options"].__func__ is before.__func__


# -- the Python heap of a first backfill and of a day of runs ----------------------------------

class FeedSource:
    kind = "memfeed"
    feeds: dict[str, list[Item]] = {}

    def __init__(self, http, *, name):
        self.name = name

    @property
    def label(self):
        return f"memfeed:{self.name}"

    def fetch(self):
        return list(self.feeds[self.name])

    def enrich(self, item):
        return item


@pytest.fixture
def memfeed(monkeypatch):
    monkeypatch.setitem(sources.KINDS, "memfeed", FeedSource)
    FeedSource.feeds = {}
    return FeedSource.feeds


def feed_items(source, n, start, base):
    """``n`` items of about 2,000 characters (the prefilter's ceiling), on the topic."""
    return [Item(id=f"{source}-{i}", title=f"local first sync engine {source} {i}",
                 body=text(2000, f"{source}-{i}"), url=f"https://ex.com/{source}/{i}",
                 published_at=base + timedelta(minutes=i))
            for i in range(start, start + n)]


def walk_shape(tmp_path, store, embedder, memfeed, make_client):
    """the walk: one topic, eight sources with history, a first backfill of 40 a source."""
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=None),
                 ingest=IngestConfig(prefilter_min_similarity=0.0, exploration_fraction=0.0),
                 map=MapConfig(), look=LookConfig(enabled=False))
    tid = library.add_topic(store, embedder, "Local-first software",
                            "local first sync engine crdt offline replica")
    base = datetime(2026, 10, 19, tzinfo=UTC)
    for s in range(8):
        memfeed[f"s{s}"] = feed_items(f"s{s}", 120, 0, base)
        sid = library.add_source(store, "memfeed", {"name": f"s{s}"}, label=f"s{s}")
        store.insert("topic_sources", {"topic_id": tid, "source_id": sid,
                                       "created_at": "2026-10-19T00:00:00Z"})
    client = make_client(lambda body: chat_response(SCREEN_PASS if is_screen(body)
                                                    else CONTRIB), budget=None)
    return cfg, client, base


def heap_of(fn):
    """(result, peak MB, MB still held after) of the Python heap while ``fn`` runs."""
    tracemalloc.start()
    try:
        before = tracemalloc.get_traced_memory()[0]
        result = fn()
        current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, (peak - before) / 2 ** 20, (current - before) / 2 ** 20


def test_a_first_backfill_stays_in_its_budget(tmp_path, store, memfeed, make_client):
    """Eight sources, 40 items each through the embedder in runs of at most four: the model
    sees no bigger run, and the Python heap peaks under 64 MB (measured: about 11)."""
    embedder, made = fake_nomic()
    cfg, client, _ = walk_shape(tmp_path, store, embedder, memfeed, make_client)
    report, peak, held = heap_of(lambda: run_ingest(cfg, store, client, embedder,
                                                    sources.HTTP()))
    assert report.status == "ok" and report.contributed == 8 * 40
    assert max(len(r) for r in made[0].runs) <= MAX_BATCH
    assert peak < 64, f"first backfill peaked at {peak:.1f} MB of Python heap"
    assert held < 16, f"first backfill left {held:.1f} MB on the Python heap"


def test_a_day_of_ingest_runs_does_not_grow(tmp_path, store, memfeed, make_client):
    """Eight runs three hours apart, ten new items a source each, through the scheduler as
    under kranto serve: what the heap holds after the last run is within a few MB of what it
    held after the second (nothing accumulates per run)."""
    embedder = StubEmbedder()
    cfg, client, base = walk_shape(tmp_path, store, embedder, memfeed, make_client)
    run_ingest(cfg, store, client, embedder, sources.HTTP())   # the backfill
    now = [datetime(2026, 10, 20, tzinfo=UTC)]

    def ingest():
        for s in range(8):
            memfeed[f"s{s}"] = feed_items(f"s{s}", 10, 1000 + len(held_after) * 10,
                                          base + timedelta(hours=len(held_after) * 3))
        report = run_ingest(cfg, store, client, embedder, sources.HTTP(), clock=lambda: now[0])
        assert report.status == "ok" and report.contributed == 80

    sched = Scheduler(store, [Job("ingest", 3, ingest)], clock=lambda: now[0])
    held_after: list[float] = []
    tracemalloc.start()
    try:
        for _ in range(8):
            assert sched.run_due() == ["ingest"]
            client.fake.requests.clear()  # the fake model's record is the test's, not Kranto's
            held_after.append(tracemalloc.get_traced_memory()[0] / 2**20)
            now[0] += timedelta(hours=3)
    finally:
        tracemalloc.stop()
    growth = held_after[-1] - held_after[1]
    assert growth < 4, f"the heap grew {growth:.1f} MB over six runs: {held_after}"


# -- the caps (memory.py) -------------------------------------------------------------------

GiB = 1 << 30


def test_the_default_caps_are_4_gib_or_half_the_machine():
    assert memory.default_caps(16 * GiB) == (3 * GiB, 4 * GiB)
    assert memory.default_caps(4 * GiB) == (1536 << 20, 2 * GiB)
    assert memory.default_caps()[1] <= 4 * GiB  # this machine's
    assert memory.unit_lines(16 * GiB) == "MemoryHigh=3072M\nMemoryMax=4096M\nOOMPolicy=continue\n"


def cgroup_tree(tmp_path, *, high="max", cap="max", parent_cap="max", current=GiB):
    root = tmp_path / "cg"
    svc = root / "user.slice" / "app.slice" / "kranto.service"
    svc.mkdir(parents=True)
    (svc / "memory.current").write_text(f"{current}\n")
    (svc / "memory.high").write_text(f"{high}\n")
    (svc / "memory.max").write_text(f"{cap}\n")
    (svc.parent / "memory.max").write_text(f"{parent_cap}\n")
    proc = tmp_path / "cgroup"
    proc.write_text("0::/user.slice/app.slice/kranto.service\n")
    return root, svc, proc


def test_the_caps_in_force_are_the_lowest_on_the_way_up(tmp_path):
    root, svc, proc = cgroup_tree(tmp_path, high=str(3 * GiB), cap="max", parent_cap=str(2 * GiB))
    assert memory.cgroup_dir(proc, root) == svc
    assert memory.caps_of(svc, root) == (3 * GiB, 2 * GiB)
    u = memory.use(svc, root)
    assert (u.current, u.limit, u.level, u.group) == (GiB, 2 * GiB, "ok", "kranto.service")
    assert memory.cgroup_dir(tmp_path / "missing", root) is None
    # its own cap counts for "already capped"; a cap shared by the whole slice does not
    assert memory.own_caps(svc)
    (svc / "memory.high").write_text("max\n")
    assert not memory.own_caps(svc) and not memory.own_caps(None)


def test_past_80_percent_is_high_and_said_once_each_way(tmp_path, caplog):
    root, svc, _ = cgroup_tree(tmp_path, high=str(3 * GiB), cap=str(4 * GiB))
    watch = memory.Watch(read=lambda: memory.use(svc, root))
    caplog.set_level("INFO", logger="kranto.memory")
    assert watch.check().level == "ok" and not caplog.records
    (svc / "memory.current").write_text(f"{int(2.7 * GiB)}\n")
    for _ in range(3):
        assert watch.check().level == "high"
    warned = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
    assert warned == [
        "memory: Kranto uses 2.7 GB of its 3.0 GB MemoryHigh (kranto.service); above it the "
        "system slows kranto down, at MemoryMax it ends the biggest process in Kranto's group. "
        "'kranto status' and Settings › System say more; a drop-in sets other caps "
        "(docs/memory.md)"
    ]
    (svc / "memory.current").write_text(f"{GiB}\n")
    watch.check()
    assert caplog.records[-1].getMessage().startswith("memory: back under 80% of the cap")
    d = watch.last.as_dict()
    assert d["level"] == "ok" and d["high_mb"] == 3072 and d["max_mb"] == 4096


def test_uncapped_says_so():
    u = memory.Use(rss=300 << 20, current=None, high=None, max=None, group=None)
    assert u.level == "uncapped" and u.used == 300 << 20
    assert u.words() == "Kranto uses 300 MB; no memory cap is set for it"


def test_a_run_outside_the_unit_gets_a_capped_scope_only_when_it_needs_and_can(monkeypatch):
    found = {"systemd-run": "/usr/bin/systemd-run"}
    ok = lambda head: True  # noqa: E731
    argv = memory.scope_argv(
        ["python", "afk", "run"], environ={}, which=found.get, probe=ok, capped=False
    )
    high, cap = memory.default_caps()
    assert argv == [
        "/usr/bin/systemd-run",
        "--user",
        "--scope",
        "--quiet",
        "-p",
        f"MemoryHigh={high >> 20}M",
        "-p",
        f"MemoryMax={cap >> 20}M",
        "--",
        "env",
        "KRANTO_SCOPED=1",
        "python",
        "afk",
        "run",
    ]
    for environ in ({"KRANTO_SCOPED": "1"}, {"KRANTO_NO_SCOPE": "1"}):
        assert (
            memory.scope_argv(["x"], environ=environ, which=found.get, probe=ok, capped=False)
            is None
        )
    assert memory.scope_argv(["x"], environ={}, which=found.get, probe=ok, capped=True) is None
    assert memory.scope_argv(["x"], environ={}, which={}.get, probe=ok, capped=False) is None
    assert (
        memory.scope_argv(["x"], environ={}, which=found.get, probe=lambda h: False, capped=False)
        is None
    )


def test_each_job_hands_its_memory_back(monkeypatch, store):
    """A map snapshot's working memory stayed with the server until glibc was asked for it."""
    from kranto import scheduler as sched_mod

    released = []
    monkeypatch.setattr(sched_mod, "release_memory", lambda: released.append(1))
    sched = Scheduler(store, [Job("a", 1, lambda: None), Job("b", 1, lambda: 1 / 0)])
    assert sched.run_due() == ["a", "b"]
    assert len(released) == 2  # after a job that raised, too
    memory.release()  # the real one: no error here


def test_a_services_process_never_moves_itself_into_a_scope(monkeypatch, tmp_path):
    """kranto.service before its update wrote caps: its process stays the unit's."""
    monkeypatch.setattr(memory, "cgroup_dir", lambda: tmp_path / "kranto.service")
    assert (
        memory.scope_argv(
            ["x"], environ={}, which=lambda n: "/usr/bin/systemd-run", probe=lambda h: True
        )
        is None
    )
    monkeypatch.setattr(memory, "cgroup_dir", lambda: tmp_path / "session-3.scope")
    assert (
        memory.scope_argv(
            ["x"], environ={}, which=lambda n: "/usr/bin/systemd-run", probe=lambda h: True
        )
        is not None
    )


def test_enter_scope_replaces_the_process_or_returns(monkeypatch):
    execs = []
    monkeypatch.setattr(memory.os, "execvp", lambda f, a: execs.append(a))
    monkeypatch.setattr(memory, "scope_argv", lambda argv: None)
    memory.enter_scope("python -m kranto run")
    assert execs == []
    monkeypatch.setattr(memory, "scope_argv", lambda argv: ["systemd-run", "--", *argv])
    memory.enter_scope("python -m kranto run")
    assert execs and execs[0][0] == "systemd-run" and execs[0][2] == sys.executable


# -- the real model -------------------------------------------------------------------------

PROBE = """
import resource, sys
from kranto.embed import NomicEmbedder
texts = [(" ".join(["local first sync engine crdt offline", str(i)] * 60))[:2000]
         for i in range(40)]
e = NomicEmbedder()
e.embed_query("load")
for _ in range(2):
    e.embed_documents(texts)
print(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024)
"""


@pytest.mark.slow
def test_the_real_model_embeds_a_first_backfill_in_a_bounded_peak():
    """A first backfill's 40 texts at the prefilter's ceiling, twice: the process peaks under
    1.4 GB (measured 1.07 GB: the model 0.63, a run 0.4); 0.4.10's embedder passed 3 GB."""
    out = subprocess.run(
        [sys.executable, "-c", PROBE],
        capture_output=True,
        text=True,
        env=os.environ,
        timeout=600,
        check=True,
    )
    peak_mb = int(out.stdout.strip().splitlines()[-1])
    assert peak_mb < 1400, f"peak {peak_mb} MB"
