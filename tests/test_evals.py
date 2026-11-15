"""The eval set, its free replay and the scorecards (`kranto eval`): a
set cut from a copy of a library's history, scrubbed and split, never rewritten; the
recorded replies replayed through the current code; a changed verdict and a changed prompt
told apart; the baseline, the noise floor and the flags. No model, no network."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from kranto import prompts
from kranto.evals import Refused, refuse_under_ci, replay, scorecard, sets
from kranto.evals import cli as evals_cli
from kranto.ideate.cards import RATINGS

FIX = Path(__file__).parent / "fixtures" / "evals"

# What each fixture's reply must give, written by hand (not by the code under test): a
# regenerated fixture cannot hide a change in a reader.
EXPECTED = {
    "screen": {"pass": True, "drop": False, "fenced-pass": True, "prose-drop": False,
               "string-false": False, "unreadable": True, "cut-short": True, "no": False,
               "pass-no-reason": True, "drop-no-reason": False},
    "judge": {"kept-sharp": "contributed", "kept-mild-fenced": "contributed",
              "skip": "skipped", "gated": "gated", "override-lifted": "contributed",
              "override-refused": "gated", "no-why": "parse_failed",
              "cut-short": "parse_failed", "unknown-kind": "contributed",
              "prose-then-json": "contributed"},
    "card": {"ok": "ok", "ok-fenced": "ok", "declined": "declined",
             "malformed-no-evidence": "malformed", "malformed-bad-rating": "malformed",
             "no-card-key": "malformed", "ok-v1-fields": "ok", "prose": "malformed",
             "ok-long-title": "ok", "card-string": "malformed"},
}


def test_the_fixtures_are_the_behaviours_the_readers_must_keep():
    for step, want in EXPECTED.items():
        items = sets.load_items(FIX, step)
        assert sorted(i["behaviour"] for i in items) == sorted(want)
        for it in items:
            now, then = replay.verdict(step, it, 0.03)
            got = now[0] if step == "card" else now
            assert got == want[it["behaviour"]], (step, it["behaviour"], got)
            assert now == then, f"{step} {it['behaviour']}: recorded {then}, now {now}"


def test_replay_of_the_fixtures_is_clean_and_the_prompts_assemble():
    rep = replay.run(FIX)
    assert rep["changed"] == 0 and rep["due"] == []
    for step in ("screen", "judge", "card"):
        assert rep["steps"][step]["prompt"]["assembly"] is True, step
    assert "verdicts changed: 0; real eval due for: nothing" in replay.words(rep)


def test_a_changed_reader_and_a_changed_prompt_are_told_apart(tmp_path):
    d = tmp_path / "set"
    shutil.copytree(FIX, d)
    p = d / "watching" / "screen.jsonl"
    items = [json.loads(line) for line in p.read_text().splitlines()]
    items[0]["recorded"]["passed"] = False               # as if the reader changed since
    for it in items:
        it["prompt_version"] = "screen-00000000"          # recorded with an older prompt
    p.write_text("".join(json.dumps(i) + "\n" for i in items))
    rep = replay.run(d)
    assert rep["changed"] == 1 and rep["steps"]["screen"]["parse"]["diffs"][0]["id"] == \
        "screen-pass"
    assert rep["due"] == ["screen"]
    assert evals_cli.main(["replay", "--set", str(d)], tmp_path, out=lambda *_: None) == 1


def test_template_fields_read_a_render_back():
    card = prompts.Prompt("card", prompts.default_text("card"))
    vals = {"observations": "[1] a\n[2] b", "why_selected": "two agree", "today": "2026-10-17",
            "prior_art": "No prior-art search ran (no live search)."}
    assert sets.template_fields(card.template, card.render(**vals)) == vals
    assert sets.template_fields(card.template, "something else") is None


# -- building a set from a copy of a library -----------------------------------------------------

SCHEMA = """
CREATE TABLE llm_calls (id INTEGER PRIMARY KEY, purpose TEXT, status TEXT, model TEXT,
  prompt_version TEXT, request TEXT, response TEXT, created_at TEXT, prompt_tokens INT,
  completion_tokens INT, cost_usd REAL, latency_ms INT);
CREATE TABLE sources (id INTEGER PRIMARY KEY, kind TEXT, label TEXT);
CREATE TABLE items_seen (source_id INT, item_id TEXT, outcome TEXT, llm_call_id INT,
  screen_call_id INT);
CREATE TABLE observations (id INTEGER PRIMARY KEY, llm_call_id INT, kind TEXT, signal REAL,
  override INT);
CREATE TABLE feedback (id INTEGER PRIMARY KEY, target TEXT, target_id TEXT, kind TEXT,
  value TEXT, reasons TEXT, created_at TEXT);
CREATE TABLE ideas (id INTEGER PRIMARY KEY, title TEXT, origin TEXT, status TEXT,
  input_ids TEXT, gen_call_id INT);
"""


def _call(c, i, purpose, system, user, reply, at="2026-10-10T10:00:00Z", version="v"):
    req = {"model": "m", "max_tokens": 900, "user": "user-7f3a9", "metadata": {"x": 1},
           "messages": [{"role": "system", "content": system},
                        {"role": "user", "content": user}]}
    if purpose == "card":
        req["messages"] = [{"role": "user", "content": user}]
    resp = {"choices": [{"message": {"content": reply}}]}
    c.execute("INSERT INTO llm_calls VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
              (i, purpose, "ok", "m", version, json.dumps(req), json.dumps(resp), at, 100, 20,
               0.0001, 900))


@pytest.fixture
def library(tmp_path):
    db = tmp_path / "kranto.db"
    c = sqlite3.connect(db)
    c.executescript(SCHEMA)
    c.execute("INSERT INTO sources VALUES (1, 'rss', 'a feed')")
    screen = prompts.load("screen", defaults=True)
    sys_screen = screen.render(tenets=prompts.tenets())
    for i in range(1, 9):
        _call(c, i, "screen", sys_screen, f"item {i}, write to ann@example.org",
              '{"pass": %s, "reason": "r"}' % ("true" if i % 2 else "false"),
              version=screen.version)
        c.execute("INSERT INTO items_seen VALUES (1, ?, ?, NULL, ?)",
                  (f"s{i}", "skipped" if i % 2 else "screened_out", i))
    kept = json.dumps({"kind": "mild_signal", "summary": "s", "why_it_matters": "w",
                       "content_quality": 0.9, "durability": 0.9, "opportunity": 0.9})
    for i in range(20, 26):
        _call(c, i, "judge", "judge prompt", f"judge item {i}", kept)
        c.execute("INSERT INTO items_seen VALUES (1, ?, 'contributed', ?, NULL)", (f"j{i}", i))
        c.execute("INSERT INTO observations VALUES (?, ?, 'mild_signal', 0.73, 0)", (i, i))
    c.execute("INSERT INTO feedback VALUES (1, 'observation', '20', 'grade', 'down', "
              "'[\"noise\"]', '2026-10-11T00:00:00Z')")
    c.execute("INSERT INTO feedback VALUES (2, 'observation', '21', 'grade', 'up', '[]', "
              "'2026-10-11T00:00:00Z')")
    c.execute("INSERT INTO feedback VALUES (3, 'observation', '21', 'grade', 'skip', '[]', "
              "'2026-10-12T00:00:00Z')")                  # cleared: no grade
    card = prompts.load("card", defaults=True)
    vals = {"observations": "[1] x\n[2] y", "why_selected": "w", "today": "2026-10-10",
            "prior_art": "Prior art: none."}
    _call(c, 40, "card", "", card.render(**vals),
          json.dumps({"card": {"title": "T", "evidence": [{"n": 1, "claim": "c"}],
                               "ratings": {k: [0.5, "r"] for k in RATINGS}}}),
          version=card.version)
    c.execute("INSERT INTO ideas VALUES (7, 'T', 'map', 'shown', '[1, 2]', 40)")
    c.execute("INSERT INTO feedback VALUES (4, 'idea', '7', 'grade', 'up', '[]', "
              "'2026-10-12T00:00:00Z')")
    c.commit()
    c.close()
    return db


def test_a_set_is_cut_scrubbed_split_and_never_rewritten(library, tmp_path):
    out = tmp_path / "sets" / "v1"
    m = sets.build(library, out, screens=6, judges=3, threshold=0.03)
    assert m["watching/screen"]["n"] == 6 and m["secret_shaped"] == 0
    # the newest judges plus every graded one; a cleared grade is no grade
    js = sets.load_items(out, "judge")
    assert sorted(i["id"] for i in js) == ["judge-20", "judge-23", "judge-24", "judge-25"]
    graded = next(i for i in js if i["id"] == "judge-20")
    assert graded["owner"]["value"] == "down" and graded["split"] == "held"
    assert next(i for i in js if i["id"] == "judge-21" or i["id"] == "judge-25")["owner"] is None
    sc = sets.load_items(out, "screen")
    text = (out / "watching" / "screen.jsonl").read_text()
    assert "ann@example.org" not in text and "[email]" in text
    assert "user-7f3a9" not in text and "metadata" not in text      # only the turns
    assert {i["split"] for i in sc} <= {"dev", "held"}
    assert sc[0]["inputs"] == {"user": sc[0]["messages"][1]["content"]}
    assert sc[0]["recorded"]["outcome"] in ("skipped", "screened_out")
    (cd,) = sets.load_items(out, "card")
    assert cd["id"] == "card-7" and cd["owner"]["value"] == "up" and cd["split"] == "held"
    assert cd["inputs"]["why_selected"] == "w" and cd["recorded"]["status"] == "ok"
    assert replay.run(out)["changed"] == 0
    with pytest.raises(sets.SetError, match="never rewritten"):
        sets.build(library, out, threshold=0.03)


def test_grow_keeps_the_old_items_holds_new_grades_and_rotates_old_held(library, tmp_path):
    from datetime import UTC, datetime
    v1 = tmp_path / "v1"
    sets.build(library, v1, screens=4, judges=2, threshold=0.03)
    c = sqlite3.connect(library)
    c.execute("INSERT INTO feedback VALUES (9, 'observation', '22', 'grade', 'up', '[]', "
              "'2027-03-01T00:00:00Z')")
    c.commit()
    c.close()
    m = sets.grow(v1, library, tmp_path / "v2", screens=4, judges=2,
                  now=datetime(2027, 3, 2, tzinfo=UTC))
    assert m["parent"] == "v1" and m["version"] == "v2"
    old = {i["id"] for s in sets.STEPS for i in sets.load_items(v1, s)}
    new = {i["id"]: i for s in sets.STEPS for i in sets.load_items(tmp_path / "v2", s)}
    assert old <= set(new)
    assert new["judge-22"]["owner"]["value"] == "up" and new["judge-22"]["split"] == "held"
    # held items from October, ungraded since, are past 90 days: dev now
    assert all(i["split"] == "dev" for i in new.values()
               if not i.get("owner") and i["id"].startswith("screen"))
    assert m["grown"]["rotated_to_dev"] >= 1


def test_the_secret_scan_fails_a_set(tmp_path):
    d = tmp_path / "s"
    (d / "watching").mkdir(parents=True)
    (d / "watching" / "screen.jsonl").write_text("sk-" + "ant-" + "x" * 30 + "\n")
    assert sets.secret_hits(d)


def test_the_live_file_is_read_through_a_copy(library):
    before = library.read_bytes()
    c = sets.open_backup(library)
    assert c.execute("SELECT count(*) FROM llm_calls").fetchone()[0] == 15
    c.close()
    assert library.read_bytes() == before


# -- scorecards ----------------------------------------------------------------------------------


def _card(value_num, noise=None, **kw):
    c = scorecard.new("watching", set_version="v1", model="m", split="all", budget_usd=1.0, **kw)
    c["metrics"] = [scorecard.metric("screen_agree", "screen agrees with the recorded verdict",
                                     value_num, 60, step="screen"),
                    scorecard.metric("owner_judge", "judge agrees with the owner", 6, 8,
                                     kind="owner", ids=["judge-1", "judge-2"]),
                    scorecard.info("cost_usd", "cost of the run", 0.06)]
    if noise:
        c["noise"] = noise
    c["prompts"] = {"screen": "screen-x"}
    return c


def test_baseline_noise_and_flags(tmp_path):
    first = scorecard.finish(tmp_path, _card(51, noise={"screen": 0.93}))
    assert first["baseline"] == "this run" and first["metrics"][0]["flag"] == ""
    within = scorecard.finish(tmp_path, _card(49))
    m = within["metrics"][0]
    assert (m["baseline"], m["last"], m["noise"], m["flag"]) == (0.85, 0.85, 0.93, "within noise")
    worse = scorecard.finish(tmp_path, _card(40))
    assert worse["metrics"][0]["flag"] == "REGRESSION" and worse["metrics"][0]["last"] == 0.817
    better = scorecard.finish(tmp_path, _card(60))
    assert better["metrics"][0]["flag"] == "better"
    c = _card(51)
    c["metrics"][1]["ids"] = ["judge-1"]
    assert scorecard.finish(tmp_path, c)["metrics"][1]["flag"] == "changed"
    md = (tmp_path / "evals" / "scorecards" / worse["file"]).with_suffix(".md").read_text()
    assert "| screen agrees with the recorded verdict | 40/60 0.67 | 0.82 | 0.85 | 0.93 | " \
           "REGRESSION |" in md
    board = (tmp_path / "evals" / "SCOREBOARD.md").read_text().splitlines()
    assert len([ln for ln in board if ln.startswith("| 20")]) == 5 and "REGRESSION" in board[4 + 2]
    pinned = scorecard.pin(tmp_path, worse["file"])
    assert pinned["_file"] == worse["file"]
    assert scorecard.finish(tmp_path, _card(40))["metrics"][0]["baseline"] == 0.667


def test_no_model_under_ci(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    with pytest.raises(Refused, match="never runs under CI"):
        refuse_under_ci()


def test_kranto_eval_set_and_scorecards(library, tmp_path, capsys):
    home = tmp_path / "home"
    lines = []
    assert evals_cli.main(["set", "build", "--from", str(library)], home,
                          out=lines.append) == 0
    assert lines[-1].startswith(f"set v1 written to {home / 'evals' / 'sets' / 'v1'}")
    assert evals_cli.main(["set", "show"], home, out=lines.append) == 0
    assert lines[-4].startswith("set v1, built ")
    assert evals_cli.main(["replay"], home, out=lines.append) == 0
    assert evals_cli.main(["scorecards"], home, out=lines.append) == 0 and lines[-1] == \
        "no scorecards yet"
    assert evals_cli.main(["set", "grow"], home, out=lines.append) == 2
    assert "give --from" in capsys.readouterr().err
    assert evals_cli.main(["set", "grow", "--from", str(library)], home, out=lines.append) == 0
    assert lines[-1].startswith("set v2 written")
    assert evals_cli.main(["replay", "--set", "nope"], home, out=lines.append) == 2


def test_kranto_eval_is_a_kranto_command(tmp_path, monkeypatch, capsys):
    from kranto import launcher
    monkeypatch.setenv("KRANTO_HOME", str(tmp_path))
    assert launcher.main(["eval", "scorecards"]) == 0
    assert capsys.readouterr().out.strip() == "no scorecards yet"


def test_kranto_eval_has_no_build_benchmark(monkeypatch, capsys):
    """CUT: the build benchmark left with builds; an old page's group is never asked."""
    from . import brbfake

    def add_eval_group(sub):
        raise AssertionError("the page's eval group was asked")
    brbfake.install(monkeypatch, add_eval_group=add_eval_group)
    with pytest.raises(SystemExit) as e:
        evals_cli.main(["builds", "--budget", "40"], Path("/nonexistent"))
    assert e.value.code == 2 and "invalid choice: 'builds'" in capsys.readouterr().err
