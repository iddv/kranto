"""The strike gate, delivery, the weekly heartbeat and grades."""

import json
import sqlite3
import sys
import types
from datetime import timedelta

import httpx
import pytest

from kranto import cli, delivery, gate, grades, heartbeat, notify
from kranto import config as config_mod
from kranto.config import (
    BudgetConfig,
    Config,
    IngestConfig,
    MapConfig,
    NotifyConfig,
    StrikeConfig,
)
from kranto.embed import StubEmbedder
from kranto.ideate import cards
from kranto.map.snapshot import take_snapshot
from kranto.runtime import open_runtime
from kranto.scheduler import Job, Scheduler
from kranto.store import iso, utcnow
from kranto.web.app import create_app

from .conftest import FIXED_NOW, llm_config, old_grade, web_client
from .test_ideate import Model
from .test_map import THEMES, add_observations

NOW = FIXED_NOW


def make_cfg(tmp_path, *, strike=None, urls=(), ping=None) -> Config:
    return Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=5),
                  ingest=IngestConfig(), map=MapConfig(),
                  strike=strike or StrikeConfig(),
                  notify=NotifyConfig(urls=tuple(urls), heartbeat_ping_url=ping))


def add_snapshots(store, n, when=NOW - timedelta(days=3)):
    for i in range(n):
        store.insert("snapshots", {
            "fingerprint": f"fp{i}", "embedding_model": "m", "n": 0, "k": 0, "params": "{}",
            "quality": "{}", "density": "{}", "run_uuid": None, "created_at": iso(when)})


def candidate(store, origin="burst", subject="lineage:a", score=0.995, when=NOW, title="t"):
    return notify.record_candidate(store, origin=origin, subject_key=subject, score=score,
                                   title=title, body="b", evidence_ids=[1], now=when)


def decision(store, candidate_id):
    return store.query_one("SELECT * FROM strike_decisions WHERE candidate_id = ?",
                           (candidate_id,))


# -- the gate ----------------------------------------------------------------------------


def test_every_candidate_gets_one_recorded_decision_with_a_reason(store):
    add_snapshots(store, 2)
    cfg = StrikeConfig()
    ids = {
        "promoted": candidate(store, "burst", "lineage:a", 0.995),
        "below_threshold": candidate(store, "burst", "lineage:b", 0.97),
        "no_threshold": candidate(store, "mystery", "x:1", 5.0),
        "stale": candidate(store, "card", "lineage:s", 0.9, when=NOW - timedelta(days=8)),
    }
    decisions = gate.run_gate(store, cfg, now=NOW)
    assert len(decisions) == 4
    for reason, cid in ids.items():
        row = decision(store, cid)
        assert row["reason"] == reason
        assert row["promoted"] == (reason == "promoted")
        assert row["detail"]
    assert "below the burst threshold 0.990" in decision(store, ids["below_threshold"])["detail"]
    [strike] = notify.recent_messages(store, kind="strike")
    assert decision(store, ids["promoted"])["message_id"] == strike["id"]
    assert strike["dedup_key"] == f"strike:candidate:{ids['promoted']}"
    assert "against a threshold of 0.990" in strike["body"]
    # Decided once: a second pass decides nothing and sends nothing.
    assert gate.run_gate(store, cfg, now=NOW) == []
    assert len(notify.recent_messages(store, kind="strike")) == 1
    with pytest.raises(sqlite3.IntegrityError):
        store.query("UPDATE strike_decisions SET promoted = 1")
    with pytest.raises(sqlite3.IntegrityError):
        store.insert("strike_decisions", {"candidate_id": ids["stale"], "promoted": 1,
                                          "reason": "promoted", "detail": "again",
                                          "created_at": iso(NOW)})


def test_thresholds_are_per_origin(store):
    add_snapshots(store, 2)
    cfg = StrikeConfig(max_per_week=10)
    # 0.2 is a strong card; 0.96 is a weak burst. A watch candidate left from before watches
    # were retired (WT) has no threshold now: decided once, never sent.
    card = candidate(store, "card", "lineage:c", 0.2)
    burst_weak = candidate(store, "burst", "lineage:d", 0.96)
    old_watch = candidate(store, "watch", "watch:2", 0.99)
    gate.run_gate(store, cfg, now=NOW)
    assert decision(store, card)["reason"] == "promoted"
    assert decision(store, card)["threshold"] == pytest.approx(0.15)
    assert decision(store, burst_weak)["reason"] == "below_threshold"
    assert decision(store, old_watch)["reason"] == "no_threshold"
    assert cfg.threshold("watch") is None


def test_refractory_suppresses_a_repeat_about_the_same_subject(store):
    add_snapshots(store, 2)
    cfg = StrikeConfig(refractory_days=7, max_per_week=10)
    first = candidate(store, subject="lineage:a", when=NOW)
    gate.run_gate(store, cfg, now=NOW)
    assert decision(store, first)["reason"] == "promoted"

    later = NOW + timedelta(days=3)
    repeat = candidate(store, subject="lineage:a", when=later)
    other = candidate(store, subject="lineage:b", when=later)
    gate.run_gate(store, cfg, now=later)
    row = decision(store, repeat)
    assert row["reason"] == "refractory" and not row["promoted"]
    assert "lineage:a" in row["detail"]
    assert decision(store, other)["reason"] == "promoted"

    after = NOW + timedelta(days=7, hours=1)
    again = candidate(store, subject="lineage:a", when=after)
    gate.run_gate(store, cfg, now=after)
    assert decision(store, again)["reason"] == "promoted"


def test_weekly_cap_is_enforced_over_a_rolling_week(store):
    add_snapshots(store, 2)
    cfg = StrikeConfig(max_per_week=2)
    ids = [candidate(store, subject=f"lineage:{i}", score=0.991 + i * 0.001) for i in range(3)]
    gate.run_gate(store, cfg, now=NOW)
    reasons = {cid: decision(store, cid)["reason"] for cid in ids}
    # Strongest first: the weakest candidate is the one the cap holds back.
    assert reasons == {ids[2]: "promoted", ids[1]: "promoted", ids[0]: "weekly_cap"}
    assert "2 strikes already sent" in decision(store, ids[0])["detail"]
    assert len(notify.recent_messages(store, kind="strike")) == 2

    still_capped = NOW + timedelta(days=6)
    held = candidate(store, subject="lineage:new", when=still_capped)
    gate.run_gate(store, cfg, now=still_capped)
    assert decision(store, held)["reason"] == "weekly_cap"

    week_later = NOW + timedelta(days=7, minutes=1)
    fresh = candidate(store, subject="lineage:newer", when=week_later)
    gate.run_gate(store, cfg, now=week_later)
    assert decision(store, fresh)["reason"] == "promoted"


def test_warmup_blocks_early_strikes(store):
    cfg = StrikeConfig(warmup_snapshots=2)
    add_snapshots(store, 1)
    early = candidate(store, subject="lineage:a")
    gate.run_gate(store, cfg, now=NOW)
    row = decision(store, early)
    assert row["reason"] == "warmup" and "1 of 2 map snapshots" in row["detail"]
    assert notify.recent_messages(store, kind="strike") == []

    add_snapshots(store, 1)
    warm = candidate(store, subject="lineage:a")
    gate.run_gate(store, cfg, now=NOW)
    assert decision(store, warm)["reason"] == "promoted"


def test_idea_cards_become_candidates_and_go_through_the_gate(store, embedder, make_client,
                                                              tmp_path):
    for theme in THEMES:
        add_observations(store, embedder, theme, 15, f"{theme}-a")
        add_observations(store, embedder, theme, 10, f"{theme}-b")
    take_snapshot(store, embedder, None)
    report = cards.generate_ideas(store, make_client(Model()), max_cards=2)
    assert report.shown == 2
    rows = store.query("SELECT * FROM strike_candidates WHERE origin = 'card' ORDER BY id")
    assert len(rows) == 2
    ideas = {i["id"]: i for i in cards.list_ideas(store)}
    for row in rows:
        detail = json.loads(row["detail"])
        idea = ideas[detail["idea_id"]]
        assert row["score"] == pytest.approx(idea["score"])  # 0.5 ** 5
        assert row["subject_key"] == f"lineage:{idea['lineage_id']}"
        assert json.loads(row["evidence_ids"]) == idea["card"].cited_ids()
    assert all(i["strike"] == {"candidate_id": i["strike"]["candidate_id"], "decided": 0,
                               "promoted": None, "reason": None, "threshold": None,
                               "message_id": None} for i in ideas.values())

    gate.run_gate(store, StrikeConfig(warmup_snapshots=0), now=NOW)
    for i in cards.list_ideas(store):
        assert i["strike"]["reason"] == "below_threshold"  # 0.03 < 0.15: stays a candidate


# -- delivery ----------------------------------------------------------------------------


class FakeApprise:
    """Stands in for the apprise module. Behaviour is chosen per URL."""

    def __init__(self, behaviour):
        self.behaviour = behaviour  # url -> "ok" | "refuse" | "raise" | "reject_url"
        self.sent: list[tuple[str, str, str]] = []
        module = self

        class Apprise:
            def __init__(self):
                self.urls = []

            def add(self, url):
                if module.behaviour.get(url) == "reject_url":
                    return False
                self.urls.append(url)
                return True

            def notify(self, title, body):
                [url] = self.urls
                what = module.behaviour.get(url, "ok")
                if what == "raise":
                    raise ConnectionError(f"could not reach {url}")
                if what == "refuse":
                    return False
                module.sent.append((url, title, body))
                return True

        self.Apprise = Apprise


GOOD = "ntfy://ntfy.example/topic-secret"
BAD = "tgram://123456:SECRET-TOKEN/42"
ALSO_GOOD = "mailto://user:pass@mail.example"


def test_a_failing_target_is_recorded_and_does_not_block_the_others(store, tmp_path):
    cfg = make_cfg(tmp_path, urls=[BAD, GOOD, ALSO_GOOD])
    first = notify.emit(store, "alarm", "a run failed", "detail", dedup_key="a1",
                        origin="ingest", evidence_ids=[7], now=NOW)
    fake = FakeApprise({BAD: "raise"})
    report = delivery.deliver_pending(store, cfg, now=NOW, apprise_module=fake)
    assert (report.attempted, report.sent, report.failed) == (3, 2, 1)
    assert [u for u, _, _ in fake.sent] == [GOOD, ALSO_GOOD]
    _, title, body = fake.sent[0]
    assert title == "[the server alarm] a run failed"
    assert "http://127.0.0.1:8765/obs/7" in body

    rows = store.query("SELECT * FROM deliveries ORDER BY id")
    assert [r["status"] for r in rows] == ["failed", "sent", "sent"]
    assert rows[0]["target"] == delivery.target_label(BAD)
    assert "ConnectionError" in rows[0]["error"]
    # Tokens in target URLs are never stored.
    dump = json.dumps([dict(r) for r in rows])
    assert "SECRET" not in dump and "topic-secret" not in dump and "pass@" not in dump

    # Sent targets are not re-sent; the failed one is retried, up to MAX_ATTEMPTS in all.
    for _ in range(5):
        delivery.deliver_pending(store, cfg, now=NOW, apprise_module=fake)
    per_target = {r["target"]: r["n"] for r in store.query(
        "SELECT target, COUNT(*) AS n FROM deliveries WHERE message_id = ? GROUP BY target",
        (first,))}
    assert per_target[delivery.target_label(BAD)] == delivery.MAX_ATTEMPTS
    assert per_target[delivery.target_label(GOOD)] == 1

    # Refusals and unparseable URLs are failures too, and still do not block.
    notify.emit(store, "alarm", "second", "d", dedup_key="a2", origin="x", now=NOW)
    fake2 = FakeApprise({GOOD: "refuse", ALSO_GOOD: "reject_url", BAD: "ok"})
    report = delivery.deliver_pending(store, cfg, now=NOW, apprise_module=fake2)
    assert report.sent == 1 and report.failed == 2
    errors = {r["target"]: r["error"] for r in store.query(
        "SELECT target, error FROM deliveries WHERE status = 'failed' AND message_id != ?",
        (first,))}
    assert "not sent" in errors[delivery.target_label(GOOD)]
    assert "did not accept" in errors[delivery.target_label(ALSO_GOOD)]


def test_strikes_carry_a_grade_link_and_old_messages_are_not_replayed(store, tmp_path):
    cfg = make_cfg(tmp_path, urls=[GOOD])
    notify.emit(store, "alarm", "old", "b", dedup_key="old", origin="x",
                now=NOW - timedelta(days=30))
    add_snapshots(store, 2)
    candidate(store)
    fake = FakeApprise({})
    decisions, report = delivery.after_job(cfg, store, now=NOW, apprise_module=fake)
    assert [d.reason for d in decisions] == ["promoted"]
    assert report.sent == 1
    [(_, title, body)] = fake.sent
    assert title.startswith("[the server strike]")
    strike_id = decisions[0].message_id
    assert f"http://127.0.0.1:8765/grade/message/{strike_id}" in body


def test_nothing_leaves_the_machine_without_targets(store, tmp_path, monkeypatch):
    notify.emit(store, "alarm", "a", "b", dedup_key="k", origin="x", now=NOW)
    fake = FakeApprise({})
    report = delivery.deliver_pending(store, make_cfg(tmp_path), now=NOW, apprise_module=fake)
    assert report.attempted == 0 and fake.sent == []
    assert store.query("SELECT * FROM deliveries") == []
    assert delivery.describe(make_cfg(tmp_path)).startswith("off:")


def test_missing_apprise_is_reported_not_raised(store, tmp_path, monkeypatch, caplog):
    monkeypatch.setitem(sys.modules, "apprise", None)  # import apprise -> ImportError
    cfg = make_cfg(tmp_path, urls=[GOOD])
    notify.emit(store, "alarm", "a", "b", dedup_key="k", origin="x", now=NOW)
    report = delivery.deliver_pending(store, cfg, now=NOW)
    assert report.attempted == 0
    assert "Apprise is not installed" in report.note and "kranto[notify]" in report.note
    assert "Apprise is not installed" in caplog.text
    assert store.query("SELECT * FROM deliveries") == []
    assert delivery.describe(cfg).startswith("not sending")
    decisions, after = delivery.after_job(cfg, store, now=NOW)
    assert "not installed" in after.note


def test_targets_come_from_config_and_environment(monkeypatch):
    monkeypatch.setenv("KRANTO_NOTIFY_URLS", f"{GOOD}, {BAD}\n{GOOD}")
    cfg = NotifyConfig(urls=(ALSO_GOOD,))
    assert cfg.targets() == [ALSO_GOOD, GOOD, BAD]


def test_heartbeat_ping_only_after_a_working_ingest(tmp_path):
    seen = []
    transport = httpx.MockTransport(lambda r: seen.append(str(r.url)) or httpx.Response(200))
    cfg = make_cfg(tmp_path, ping="https://hc.example/ping/abc")
    assert delivery.ping_heartbeat(cfg, "ok", transport=transport) is True
    assert delivery.ping_heartbeat(cfg, "failed", transport=transport) is None
    assert delivery.ping_heartbeat(cfg, "skipped", transport=transport) is None
    assert delivery.ping_heartbeat(make_cfg(tmp_path), "ok", transport=transport) is None
    assert seen == ["https://hc.example/ping/abc"]
    down = httpx.MockTransport(lambda r: httpx.Response(503))
    assert delivery.ping_heartbeat(cfg, "degraded", transport=down) is False

    def unreachable(request):
        raise httpx.ConnectError("no route")

    assert delivery.ping_heartbeat(cfg, "ok", transport=httpx.MockTransport(unreachable)) \
        is False


def test_scheduler_jobs_are_followed_by_the_gate_even_when_they_raise(store, tmp_path):
    add_snapshots(store, 2)
    cfg = make_cfg(tmp_path)

    def failing_job():
        candidate(store)
        raise RuntimeError("job broke")

    job = Job("ingest", 1, delivery.notifying(cfg, store, failing_job))
    Scheduler(store, [job]).run_due()
    assert [r["reason"] for r in store.query("SELECT reason FROM strike_decisions")] == \
        ["promoted"]


# -- heartbeat ---------------------------------------------------------------------------


def test_heartbeat_is_sent_with_zero_strikes_and_lists_the_closest_candidates(store,
                                                                            embedder,
                                                                            tmp_path):
    add_snapshots(store, 2)
    add_observations(store, embedder, "solar", 3, "solar-a")
    store.insert("runs", {"run_uuid": "r1", "kind": "ingest", "status": "ok",
                          "started_at": iso(NOW), "finished_at": iso(NOW - timedelta(days=1)),
                          "summary": json.dumps({"sources": [{"explored": 4}]}), "error": None})
    store.insert("runs", {"run_uuid": "r2", "kind": "ingest", "status": "failed",
                          "started_at": iso(NOW), "finished_at": iso(NOW - timedelta(days=2)),
                          "summary": "{}", "error": "401"})
    candidate(store, "burst", "lineage:a", 0.98, title="Burst: solar")
    candidate(store, "card", "lineage:e", 0.10, title="Idea: grid")
    candidate(store, "card", "lineage:c", 0.14, title="Idea: workshops")
    candidate(store, "card", "lineage:d", 0.01, title="Idea: faint")
    gate.run_gate(store, StrikeConfig(), now=NOW)
    assert notify.recent_messages(store, kind="strike") == []

    cfg = make_cfg(tmp_path)
    report = heartbeat.send_heartbeat(store, cfg, now=NOW)
    assert report.message_id is not None and not report.already_sent
    [beat] = notify.recent_messages(store, kind="heartbeat")
    assert beat["dedup_key"] == "heartbeat:2026-W39"
    assert beat["title"] == "This week: nothing urgent, 3 new items kept"
    body = beat["body"]
    assert "No strikes this week" in body
    assert "- ingest: 1 ok, 1 failed" in body
    closest = body.split("Closest to a strike:")[1].split("\n\n")[0]
    lines = [ln for ln in closest.splitlines() if ln.startswith("- ")]
    assert len(lines) == 3
    assert lines[0].startswith("- burst 0.980 against threshold 0.990 (below threshold)")
    assert lines[1].startswith("- card 0.140 against threshold 0.150")
    assert lines[2].startswith("- card 0.100 against threshold 0.150")
    assert "faint" not in body
    assert "Exploration yield" in body and "- topic: 3, mean signal 0.32" in body
    assert "- exploration: 0 kept of 4 judged (0%)" in body

    again = heartbeat.send_heartbeat(store, cfg, now=NOW + timedelta(hours=3))
    assert again.already_sent and again.message_id is None
    assert len(notify.recent_messages(store, kind="heartbeat")) == 1
    next_week = heartbeat.send_heartbeat(store, cfg, now=NOW + timedelta(days=7))
    assert next_week.message_id is not None
    runs = store.query("SELECT status FROM runs WHERE kind = 'heartbeat'")
    assert [r["status"] for r in runs] == ["ok", "ok", "ok"]


def test_heartbeat_on_an_empty_instance_says_nothing_ran(store, tmp_path):
    report = heartbeat.send_heartbeat(store, make_cfg(tmp_path), now=NOW)
    body = report.heartbeat.body
    assert "none. If the scheduler or cron is meant to be running, it is not." in body
    assert "no candidates were held back this week" in body


# -- grades ------------------------------------------------------------------------------


def test_grades_are_append_only_and_the_latest_wins(store, embedder):
    add_observations(store, embedder, "solar", 2, "solar-a")
    message = notify.emit(store, "strike", "s", "b", dedup_key="s1", origin="burst")
    # a message is not graded any more; its older grades are history, still read
    with pytest.raises(ValueError, match="kept on ideas and evidence only"):
        grades.add_grade(store, "message", message, "worth_waking")
    old_grade(store, "message", message, "worth_waking", at=FIXED_NOW - timedelta(hours=1))
    store.insert("grades", {"target": "message", "target_id": message, "grade": "not_worth_it",
                            "note": "it was old news", "created_at": iso(utcnow())})
    latest = grades.latest(store, "message", [message])[str(message)]
    assert latest["grade"] == "not_worth_it" and latest["note"] == "it was old news"
    assert len(grades.history(store, "message", message)) == 2

    grades.add_grade(store, "observation", 1, "not_useful")
    assert grades.latest(store, "observation", [1, 2]).keys() == {"1"}
    assert grades.latest(store, "observation", [1])["1"]["grade"] == "not_useful"

    # every grade is a feedback row now, append-only like the table before it
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.query("UPDATE feedback SET value = 'useful'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        store.query("DELETE FROM feedback")
    with pytest.raises(ValueError, match="one of"):
        grades.add_grade(store, "observation", 1, "missed")
    with pytest.raises(ValueError, match="no observation 999"):
        grades.add_grade(store, "observation", 999, "useful")
    with pytest.raises(ValueError, match="kept on ideas and evidence only"):
        grades.add_grade(store, "topic", 1, "useful")


def test_an_older_cluster_grade_is_kept_and_counted_nowhere(store, embedder):
    for theme in THEMES:
        add_observations(store, embedder, theme, 15, f"{theme}-a")
    take_snapshot(store, embedder, None)
    row = store.query_one("SELECT lineage_id, snapshot_id, cluster FROM clusters LIMIT 1")
    with pytest.raises(ValueError, match="kept on ideas and evidence only"):
        grades.add_grade(store, "cluster", row["lineage_id"], "missed")
    old_grade(store, "cluster", row["lineage_id"], "missed",
              context={"snapshot_id": row["snapshot_id"]})
    # a theme's grade was the build loop's (`feedback.target` = cluster): the row
    # stays as stored and no reader counts it (CUT)
    assert grades.history(store, "cluster", row["lineage_id"]) == []
    assert grades.latest(store, "cluster", [row["lineage_id"]]) == {}


def test_the_grade_form_is_gone_and_health_keeps_its_labels(store, embedder, make_client,
                                                             tmp_path):
    """POST /grade (the old pages' form) is retired with the message grades;
    Health still says what an older grade meant."""
    for theme in THEMES:
        add_observations(store, embedder, theme, 15, f"{theme}-a")
    take_snapshot(store, embedder, None)
    candidate(store, when=utcnow())
    strike = StrikeConfig(warmup_snapshots=1, warmup_days=0)
    delivery.after_job(make_cfg(tmp_path, strike=strike), store)
    [strike] = notify.recent_messages(store, kind="strike")
    rt = open_runtime(make_cfg(tmp_path), store=store, embedder=embedder,
                      llm=make_client(Model()))
    with web_client(create_app(rt)) as web:
        health = web.get("/api/health").json()
        assert health["decisions"] and health["grade_labels"]["worth_waking"] == "worth waking me"
        assert "no notify targets" in str(health["delivery_status"])
        assert "message_grades" not in health
        r = web.post("/grade", data={"target": "message", "target_id": strike["id"],
                                     "grade": "worth_waking", "next": "/health"},
                     follow_redirects=False)
        assert r.status_code in (404, 405)
    assert store.query_one("SELECT COUNT(*) AS n FROM feedback")["n"] == 0


# -- configuration and CLI ---------------------------------------------------------------


def test_default_config_documents_and_parses_strike_and_notify(tmp_path):
    config_mod.init_workspace(tmp_path)
    cfg = config_mod.load(tmp_path)
    assert cfg.strike == StrikeConfig()
    assert (cfg.strike.min_card_score, cfg.strike.min_burst_score) == (0.15, 0.99)
    assert (cfg.strike.refractory_days, cfg.strike.max_per_week,
            cfg.strike.warmup_snapshots) == (7, 2, 2)
    assert cfg.notify.urls == () and cfg.notify.targets() == []
    assert cfg.notify.heartbeat_every_hours == 168
    text = (tmp_path / config_mod.CONFIG_FILENAME).read_text()
    assert "different scales" in text or "own scale" in text

    path = tmp_path / config_mod.CONFIG_FILENAME
    # an older kranto.yaml still loads with the key watches left (WT), which nothing reads
    path.write_text(text.replace("  min_burst_score: 0.99",
                                 "  min_burst_score: 0.99\n  min_watch_score: 0.7"))
    assert config_mod.load(tmp_path).strike.threshold("watch") is None
    path.write_text(text.replace("  urls: []", '  urls: ["ntfy://x/y"]')
                    .replace("base_url: http://127.0.0.1:8765", "base_url: https://afk.example/"))
    cfg = config_mod.load(tmp_path)
    assert cfg.notify.targets() == ["ntfy://x/y"]
    assert cfg.notify.base_url == "https://afk.example"
    path.write_text(text.replace("  urls: []", '  urls: "ntfy://x/y"'))
    with pytest.raises(config_mod.ConfigError, match="notify.urls"):
        config_mod.load(tmp_path)
    path.write_text(text.replace("max_per_week: 2", "max_per_week: -1"))
    with pytest.raises(config_mod.ConfigError):
        config_mod.load(tmp_path)


def test_cli_strikes_heartbeat_and_grade(tmp_path, capsys, embedder):
    kb = tmp_path / "kb"
    assert cli.main(["init", str(kb)]) == 0
    cfg = config_mod.load(kb)
    rt = open_runtime(cfg, embedder=StubEmbedder())
    add_observations(rt.store, embedder, "solar", 2, "solar-a")
    candidate(rt.store, when=utcnow())
    rt.close()
    run = ["-w", str(kb)]
    capsys.readouterr()

    assert cli.main([*run, "strikes", "--run", "-v"]) == 0
    out = capsys.readouterr().out
    assert "1 candidates decided, 0 promoted" in out
    assert "warmup" in out and "0 of 2 map snapshots" in out
    assert "delivery off" in out

    assert cli.main([*run, "heartbeat", "--now"]) == 0
    out = capsys.readouterr().out
    assert "This week:" in out and "Closest to a strike" in out
    assert cli.main([*run, "heartbeat"]) == 0
    assert "not due yet" in capsys.readouterr().out
    assert cli.main([*run, "heartbeat", "--now"]) == 0
    assert "already sent" in capsys.readouterr().out

    assert cli.main([*run, "grade", "observation", "1", "not_useful", "--note", "big"]) == 0
    assert "observation 1: not_useful" in capsys.readouterr().out
    assert cli.main([*run, "grade", "observation", "77", "useful"]) == 2
    assert "no observation 77" in capsys.readouterr().err
    assert cli.main([*run, "grade", "message", "1", "useful"]) == 2
    assert "kept on ideas and evidence only" in capsys.readouterr().err
    assert cli.main([*run, "messages", "--kind", "heartbeat"]) == 0
    assert "heartbeat This week:" in capsys.readouterr().out


def test_fake_apprise_matches_the_interface_used(monkeypatch, store, tmp_path):
    """deliver_pending imports apprise itself when no module is passed."""
    fake = FakeApprise({})
    module = types.ModuleType("apprise")
    module.Apprise = fake.Apprise
    monkeypatch.setitem(sys.modules, "apprise", module)
    notify.emit(store, "alarm", "a", "b", dedup_key="k", origin="x", now=NOW)
    report = delivery.deliver_pending(store, make_cfg(tmp_path, urls=[GOOD]), now=NOW)
    assert report.sent == 1 and len(fake.sent) == 1


def test_scheduler_backs_off_a_job_that_raises(store):
    """#39: a job that raised left no runs row, stayed due, and ran every tick."""
    from datetime import UTC, datetime

    from kranto import scheduler as sched_mod

    t0 = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
    now = [t0]
    attempts = []

    def run():
        attempts.append(now[0])
        if len(attempts) < 3:
            raise sqlite3.OperationalError("database or disk is full")

    s = sched_mod.Scheduler(store, [sched_mod.Job("ingest", 3, run)], clock=lambda: now[0])
    for minutes in (0, 1, 4):  # first failure: retry after 5 minutes
        now[0] = t0 + timedelta(minutes=minutes)
        s.run_due()
    assert attempts == [t0]
    for minutes in (5, 10, 14):  # second failure at 5: next after 10 more minutes
        now[0] = t0 + timedelta(minutes=minutes)
        s.run_due()
    assert len(attempts) == 2
    now[0] = t0 + timedelta(minutes=15)
    s.run_due()  # third attempt succeeds and clears the backoff
    assert len(attempts) == 3 and not s._retry_at


def test_scheduler_stop_waits_for_a_running_job(store):
    """#44: shutdown waited 5 s, then the store was closed under a running ingest."""
    import threading
    import time

    from kranto import scheduler as sched_mod

    started, finished = threading.Event(), threading.Event()

    def slow():
        started.set()
        time.sleep(0.3)
        finished.set()

    s = sched_mod.Scheduler(store, [sched_mod.Job("ingest", 3, slow)])
    assert s.trigger("ingest") and started.wait(2)
    assert s.stop(timeout=2) and finished.is_set()

    started.clear()
    s2 = sched_mod.Scheduler(store, [sched_mod.Job("ingest", 3, slow)])
    assert s2.trigger("ingest") and started.wait(2)
    assert s2.stop(timeout=0.05) is False
    assert finished.wait(5)                     # the job still ends on its own
    assert s2.wait(5)                           # and its thread with it, before the store closes


def test_scheduler_stop_waits_at_most_its_timeout_in_all(store):
    """The 0.4.9 update: a stop during an ingest, with a lane still ticking, waited the
    timeout once for the scheduler's thread, again for the lane and again for the job (up to
    180 s), and systemd killed the server at 90 s with nothing logged. The waits now share one
    deadline."""
    import threading
    import time

    from kranto import scheduler as sched_mod

    started, release = threading.Event(), threading.Event()

    def stuck():
        started.set()
        release.wait(10)

    class StuckLane:
        name = "stuck"

        def run(self, stop):
            release.wait(10)            # ignores the stop until released

        def request_stop(self):
            pass

        def status(self):
            return {}

    s = sched_mod.Scheduler(store, [sched_mod.Job("ingest", 3, stuck)], lanes=[StuckLane()])
    s.start()
    s.trigger("ingest")                  # due at once: the loop may have started it
    assert started.wait(2)
    t0 = time.monotonic()
    assert s.stop(timeout=0.6) is False
    assert time.monotonic() - t0 < 1.2        # one budget, not one per wait
    release.set()
    assert s.wait(5)                          # every thread ends before the store closes


def test_warmup_also_needs_the_first_map_to_be_old_enough(store):
    """#42: two snapshots minutes apart met the snapshot count, and a new library
    struck within the hour of its creation."""
    add_snapshots(store, 2, when=NOW - timedelta(hours=1))
    early = candidate(store, subject="lineage:a")
    gate.run_gate(store, StrikeConfig(warmup_snapshots=2, warmup_days=3), now=NOW)
    row = decision(store, early)
    assert row["reason"] == "warmup" and "3 days old" in row["detail"]
