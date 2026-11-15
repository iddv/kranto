"""The promotion gate (the owner's decisions of 2026-10-24): time never decides
stable. The candidate is facts and blocking health checks; the owner's press carries out a
promotion; promote --now releases a held stable. Also the guards a hotfix merges and cuts with,
and hotfix.sh's own rules. No network: gh, Kranto, git and ClickHouse are fakes or local."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
REL = ROOT / "scripts" / "release"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"rel_{name}", REL / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate, guards, notes = _load("gate"), _load("guards"), _load("notes")
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def iso(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def rel(tag: str, pre: bool, draft: bool = False, body: str = "", published: float = 1) -> dict:
    return {"tag_name": tag, "prerelease": pre, "draft": draft, "body": body,
            "published_at": iso(published)}


HELD_BODY = ("Kranto 0.6.0: ...\n\n**Held for stable:** stable installs get it when the "
             "maintainer releases it.\n\n## the server\n\n- The fix\n")
RELEASES = [rel("v0.6.0-dev3", True, published=2), rel("v0.6.0-dev2", True, published=30),
            rel("v0.6.0-dev1", True, published=50),
            rel("v0.5.28", True, published=60), rel("v0.5.27", False, published=70)]


class FakeGH:
    def __init__(self, releases=None, body=HELD_BODY, prs=None):
        self.repo, self.brb_repo = "iddv/kranto", "iddv/kranto"
        self.rels = RELEASES if releases is None else releases
        self.text, self.edits, self.notes = body, [], []
        self.prs = prs if prs is not None else {
            "iddv/kranto": [{"number": 360, "title": "Today: a calmer home",
                               "mergedAt": iso(40), "labels": [{"name": "big"}]},
                              {"number": 361, "title": "A fix", "mergedAt": iso(20),
                               "labels": []},
                              {"number": 362, "title": "After the build", "mergedAt": iso(1),
                               "labels": []}]}

    def releases(self):
        return self.rels

    def body(self, tag):
        return self.text

    def promote(self, tag, body):
        self.edits.append((tag, body))
        for r in self.rels:
            if r["tag_name"] == tag:
                r["prerelease"] = False

    def edit_notes(self, tag, body, *extra):
        self.notes.append((tag, body))

    def merged(self, repo, since):
        return [p for p in self.prs.get(repo, []) if p["mergedAt"] > since]


def fake_run(version="0.6.0.dev3", calls=None, cut=0, rc=0):
    """kranto --version answers ``version``; the cut and rc_check exit ``cut`` and ``rc``."""
    def run(cmd, timeout=120, env=None, cwd=None):
        if calls is not None:
            calls.append(cmd)
        if cmd[1:] == ["--version"]:
            return subprocess.CompletedProcess(cmd, 0, f"Kranto {version} (the server {version})\n",
                                               "")
        if cmd[1:3] == ["settings", "stable-defaults"]:
            return subprocess.CompletedProcess(cmd, 0, json.dumps(
                [{"key": "shell.layout", "default": "new", "default_stable": "classic"}]), "")
        if cmd[:2] == ["git", "clone"]:
            Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if any(str(c).endswith("cut_local.sh") for c in cmd):
            return subprocess.CompletedProcess(cmd, cut, "published v0.6.0\n",
                                               "" if not cut else "cut_local: not green\n")
        if any(str(c).endswith("rc_check.sh") for c in cmd):
            return subprocess.CompletedProcess(cmd, rc, "PASS 0. a fresh HOME\n" if not rc else
                                               "PASS 0. a fresh HOME\nFAIL 3. roll back\n", "")
        raise AssertionError(cmd)
    return run


def ok(name):
    return lambda build, installed: gate.Check(name, True, f"{name} clean")


def make(tmp_path, *, gh=None, run=None, query=None, odd=None, routes=None, hist=(),
         errors=()):
    home = tmp_path / "kb"
    (home / "update").mkdir(parents=True, exist_ok=True)
    (home / "data").mkdir(parents=True, exist_ok=True)
    (home / "update" / "history.jsonl").write_text("".join(json.dumps(r) + "\n" for r in hist))
    (home / "data" / "errors.jsonl").write_text("".join(json.dumps(e) + "\n" for e in errors))
    return gate.Gate(gh or FakeGH(), home, run=run or fake_run(), query=query,
                     now=lambda: NOW, state=tmp_path / "state", odd=odd or ok("odd installs"),
                     routes=routes or ok("pages"))


def done(to, hours_ago, state="done"):
    return {"state": state, "to": to, "finished": iso(hours_ago)}


# -- what is held, and the lines ---------------------------------------------------------------

def test_held_is_a_stable_tag_published_as_a_prerelease_newer_than_latest():
    rels = [rel("v0.5.24", True), rel("v0.5.24-rc1", True), rel("v0.5.23", True),
            rel("v0.5.22", False), rel("v0.5.21", True), rel("v0.5.25", True, draft=True),
            rel("v0.6.0-dev1", True)]
    waiting, latest = gate.held(rels)
    assert latest == "v0.5.22"
    assert [r["tag_name"] for r in waiting] == ["v0.5.24", "v0.5.23"]   # no rc, dev, draft


def test_the_updater_never_sees_a_held_release_on_either_line():
    """A held stable candidate is a prerelease (stable skips it) and no nightly build (nightly
    skips it): only the release to stable, the flag flipped, reaches anyone."""
    from kranto.update.sources import pick
    rels = [rel("v0.5.23", True), rel("v0.5.22", False)]
    assert pick(rels, "stable")["tag_name"] == "v0.5.22"
    assert pick(rels, "nightly") is None


def test_nightly_builds_ahead_of_stable_newest_first_and_never_withdrawn():
    rels = [*RELEASES, rel("v0.6.0-dev4", True, body="**Do not install:** rc_check failed")]
    assert [r["tag_name"] for r in gate.nightlies(rels, "v0.5.27")] == \
        ["v0.6.0-dev3", "v0.6.0-dev2", "v0.6.0-dev1"]
    assert gate.nightlies(rels, "v0.6.0") == []


# -- the candidate: facts, never time ----------------------------------------------------------

def test_the_candidate_is_the_build_the_owners_install_runs_with_the_facts(tmp_path):
    g = make(tmp_path, run=fake_run("0.6.0.dev2"),
             hist=[done("0.5.27", 80), done("0.6.0.dev1", 50), done("0.6.0.dev2", 30)])
    c = g.candidate()
    assert c["state"] == "candidate" and c["tag"] == "v0.6.0-dev2" and c["to"] == "v0.6.0"
    assert c["stable"] == "v0.5.27" and c["installed"] == "0.6.0.dev2"
    # the PRs since the last stable, up to the build (not #362, merged after dev2's build)
    assert [p["number"] for p in c["prs"]["kranto"]] == [360] and c["count"] == 1
    assert c["big"] == [{"repo": "kranto", "number": 360, "title": "Today: a calmer home"}]
    assert c["off_on_stable"] == [{"key": "shell.layout", "default": "new",
                                   "default_stable": "classic"}]
    assert c["nightly_since"] == iso(50)               # information only
    assert [ch["name"] for ch in c["checks"]] == ["rollback", "errors", "pages", "odd installs"]
    assert not c["blocking"]


def test_no_count_of_days_or_hours_anywhere_in_the_gate():
    """The owner, 2026-10-24: "Something cannot become stable after just time." The gate keeps
    no soak, no hours and no minimum: a build made a minute ago is a candidate like any."""
    code = (REL / "gate.py").read_text()
    for word in ("RELEASE_GATE_HOURS", "RELEASE_SOAK_DAYS", "SOAK", "HOURS ="):
        assert word not in code
    assert gate.main(["hours"]) == 0


def test_a_fresh_build_is_a_candidate_at_once(tmp_path):
    gh = FakeGH([rel("v0.6.0-dev1", True, published=0.01), rel("v0.5.27", False)])
    c = make(tmp_path, gh=gh, run=fake_run("0.6.0.dev1")).candidate()
    assert c["state"] == "candidate" and c["tag"] == "v0.6.0-dev1"


def test_no_candidate_when_nightly_is_not_ahead_of_stable(tmp_path):
    gh = FakeGH([rel("v0.6.0", False), rel("v0.6.0-dev3", True)])
    c = make(tmp_path, gh=gh).candidate()
    assert c["state"] == "none" and "not ahead of stable v0.6.0" in c["said"]


def test_a_rollback_of_the_build_blocks(tmp_path):
    g = make(tmp_path, hist=[done("0.6.0.dev3", 5, "rolled_back")])
    c = g.candidate()
    assert c["state"] == "blocked" and "rolled back on your install" in c["blocking"][0]
    # another install's rollback, from the daily reports
    q = lambda sql: [{"day": "2026-10-24", "n": 1}] if "updates_by_day" in sql else []  # noqa: E731
    c = make(tmp_path, query=q).candidate()
    assert c["state"] == "blocked" and "another install" in c["blocking"][0]


def test_a_new_error_that_still_occurs_blocks_and_known_lifts_it(tmp_path):
    errors = [{"signature": "aa11", "version": "0.5.26", "at": iso(30), "where": "toot"},  # old
              {"signature": "bb22", "version": "0.6.0.dev2", "at": iso(40), "where": "brief"},
              {"signature": "bb22", "version": "0.6.0.dev3", "at": iso(2), "where": "brief"},
              {"signature": "cc33", "version": "0.6.0.dev1", "at": iso(30), "where": "gone"}]
    g = make(tmp_path, errors=errors)
    c = g.candidate()
    err = next(ch for ch in c["checks"] if ch["name"] == "errors")
    assert c["state"] == "blocked" and err["ok"] is False
    # bb22: first seen on dev2, seen 2 h ago. aa11 predates nothing after 0.5.27? It was first
    # seen on 0.5.26, before the stable: not new. cc33 stopped 30 h ago: not still occurring.
    assert [f["signature"] for f in err["found"]] == ["bb22"]
    assert "first seen on 0.6.0.dev2" in err["said"]
    gate.mark_known(g.state, "bb22", "the brief's model was down; fixed upstream", say=lambda s: 0)
    assert g.candidate()["state"] == "candidate"


def test_blind_telemetry_is_said_and_does_not_block(tmp_path):
    def q(sql):
        if sql.startswith("SHOW TABLES"):
            return [{"name": "daily_reports"}, {"name": "errors_by_version"}]
        return []
    c = make(tmp_path, query=q).candidate()
    assert c["state"] == "candidate"
    assert any("error reports: not in the telemetry store yet" in b for b in c["blind"])

    def down(sql):
        raise gate.GateError("connection refused")
    c = make(tmp_path, query=down).candidate()
    assert c["state"] == "candidate" and any("blind (connection refused)" in b
                                             for b in c["blind"])


def test_the_error_reports_are_read_when_the_server_has_them(tmp_path):
    def q(sql):
        if sql.startswith("SHOW TABLES"):
            return [{"name": "errors_by_signature"}]
        if "errors_by_signature" in sql:
            # ClickHouse lets a SELECT alias replace the column of the same name in WHERE: the
            # the server answered 500 to "toString(last_seen) AS last_seen … WHERE last_seen >= …"
            assert "AS last_seen" not in sql
            return [{"signature": "dd44", "type": "KeyError", "route_or_job": "/api/today",
                     "first_version": "0.6.0", "seen": "2026-10-24 11:00:00"},
                    {"signature": "ee55", "type": "OSError", "route_or_job": "ingest",
                     "first_version": "0.5.20", "seen": "2026-10-24 11:00:00"}]
        return []
    c = make(tmp_path, query=q).candidate()
    err = next(ch for ch in c["checks"] if ch["name"] == "errors")
    assert err["ok"] is False and [f["signature"] for f in err["found"]] == ["dd44"]
    assert err["found"][0]["last"] == "2026-10-24 11:00:00"
    assert not any("not in the telemetry store" in b for b in c["blind"])


def test_a_refused_key_is_the_installs_setup_and_does_not_block(tmp_path):
    """live's gate said "blocked" from 2026-10-25 09:01 because the owner's
    OpenRouter key expired: four "new errors" that were the install's setup, filed as a release
    regression. The 401 class is said as the install's and does not block."""
    def q(sql):
        if sql.startswith("SHOW TABLES"):
            return [{"name": "errors_by_signature"}]
        if "errors_by_signature" in sql:
            # live's row (2026-10-27): the job's failure, its message scrubbed to a template
            return [{"signature": "420298f2ce06f955", "type": "JobFailed",
                     "route_or_job": "ingest", "message": "HTTP <n> from <x> <x> key <x>.",
                     "first_version": "0.6.0", "seen": "2026-10-24 11:00:00"}]
        return []
    errors = [{"signature": "ff66", "version": "0.6.0.dev2", "at": iso(2),
               "where": "activity:auth:openrouter", "message": "HTTP <n> from <x> <x> key <x>."},
              {"signature": "ab12", "version": "0.6.0.dev2", "at": iso(3),
               "where": "activity:ideas", "message": "HTTP <n> from <x> <x> key <x>."}]
    c = make(tmp_path, query=q, errors=errors).candidate()
    err = next(ch for ch in c["checks"] if ch["name"] == "errors")
    assert c["state"] == "candidate" and err["ok"] is True and not c["blocking"]
    assert "OpenRouter key is refused (not this release)" in err["said"]
    assert c["setup"] == ("your install's OpenRouter key is refused (not this release): renew it "
                          "in Settings › Watching, then the gate checks again")
    assert {f["signature"] for f in err["found"]} == {"420298f2ce06f955", "ff66", "ab12"}
    # a new error that is not the key, first seen on the nightly, still blocks, as before
    errors.append({"signature": "dd44", "version": "0.6.0.dev3", "at": iso(1),
                   "where": "/api/today", "message": "KeyError: <x>"})
    c = make(tmp_path, query=q, errors=errors).candidate()
    err = next(ch for ch in c["checks"] if ch["name"] == "errors")
    assert c["state"] == "blocked" and [f["signature"] for f in err["found"]] == ["dd44"]
    assert "(not this release)" in err["said"]


def test_the_public_gate_names_no_host():
    """the address comes from the gate's unit (ops/release)."""
    code = (REL / "gate.py").read_text()
    assert "example-host" not in code and "9031" not in code


def test_status_says_one_pr_not_one_prs(tmp_path):
    gh = FakeGH(prs={"iddv/kranto": [{"number": 360, "title": "x", "mergedAt": iso(40),
                                        "labels": []}]})
    said: list[str] = []
    gate.status(make(tmp_path, gh=gh, run=fake_run("0.6.0.dev2")), say=said.append)
    assert any("; 1 PR since v0.5.27;" in s for s in said), said


def test_failing_pages_or_odd_installs_block(tmp_path):
    bad = lambda build, installed: gate.Check("pages", False, "GET /api/topics/7: 500")  # noqa: E731
    c = make(tmp_path, routes=bad).candidate()
    assert c["state"] == "blocked" and c["blocking"] == ["GET /api/topics/7: 500"]
    c = make(tmp_path, run=fake_run("0.5.27")).candidate()      # the install runs no nightly
    assert c["tag"] == "v0.6.0-dev3"                             # the newest, still offered


def test_the_pages_check_runs_only_on_the_build_installed(tmp_path):
    c = gate.check_routes("kranto", "0.5.27", "v0.6.0-dev3", run=fake_run())
    assert c.ok is None and "read at the press" in c.said


# -- the press ---------------------------------------------------------------------------------

def press(g, tag="v0.6.0-dev3"):
    (g.home / "update" / "promote.json").write_text(json.dumps(
        {"tag": tag, "by": "octo-owner", "at": iso(0)}))


def test_the_hourly_tick_writes_the_candidate_and_promotes_nothing(tmp_path):
    calls = []
    g = make(tmp_path, run=fake_run(calls=calls))
    assert g.tick(say=lambda s: None) == 0
    cand = json.loads((g.home / "update" / "candidate.json").read_text())
    assert cand["state"] == "candidate" and cand["tag"] == "v0.6.0-dev3"
    assert not any("cut_local.sh" in " ".join(map(str, c)) for c in calls)
    assert not g.gh.edits


def test_the_press_cuts_checks_and_releases_the_promotion(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "log", lambda entry, path=None: None)
    calls = []
    gh = FakeGH([*RELEASES, rel("v0.6.0", True, published=0)])     # the cut publishes it held
    g = make(tmp_path, gh=gh, run=fake_run(calls=calls))
    press(g)
    assert g.tick(say=lambda s: None) == 0
    cmds = [" ".join(map(str, c)) for c in calls]
    cut = next(c for c in cmds if "cut_local.sh" in c)
    assert "--from-tag v0.6.0-dev3" in cut and "MemoryMax=3G" in cut
    assert any("rc_check.sh v0.6.0 v0.5.27" in c for c in cmds)    # against the latest stable
    (tag, body), = gh.edits
    assert tag == "v0.6.0" and "**Promoted to stable**" in body and "from nightly v0.6.0-dev3" \
        in body and "pressed" in body and "Held for stable" not in body
    cand = json.loads((g.home / "update" / "candidate.json").read_text())
    assert cand["state"] == "promoted" and cand["promoted"]["tag"] == "v0.6.0"
    assert not (g.home / "update" / "promote.json").exists()


def test_a_press_for_a_build_that_is_no_longer_the_candidate_is_refused(tmp_path):
    g = make(tmp_path)
    press(g, "v0.6.0-dev1")
    g.tick(say=lambda s: None)
    cand = json.loads((g.home / "update" / "candidate.json").read_text())
    assert cand["state"] == "candidate" and "no longer the candidate" in cand["refused"]["why"]
    assert not g.gh.edits


def test_a_blocked_candidate_is_never_promoted_by_a_press(tmp_path):
    g = make(tmp_path, hist=[done("0.6.0.dev3", 5, "rolled_back")])
    press(g)
    g.tick(say=lambda s: None)
    cand = json.loads((g.home / "update" / "candidate.json").read_text())
    assert cand["state"] == "blocked" and "a health check blocks it" in cand["refused"]["why"]
    assert not g.gh.edits


def test_a_failed_rc_check_leaves_the_release_held_and_says_where(tmp_path, monkeypatch):
    monkeypatch.setattr(gate, "log", lambda entry, path=None: None)
    g = make(tmp_path, run=fake_run(rc=1))
    press(g)
    assert g.tick(say=lambda s: None) == 1
    cand = json.loads((g.home / "update" / "candidate.json").read_text())
    assert cand["state"] == "failed" and cand["step"] == "rc_check"
    assert cand["reason"] == "FAIL 3. roll back" and cand["log"].endswith("rc_check.log")
    assert not g.gh.edits                                          # nothing half-promoted


def test_promote_without_now_is_refused_time_never_promotes():
    assert gate.main(["promote"]) == 1
    assert gate.main(["promote", "--tag", "v0.6.0"]) == 1


def test_promote_now_releases_a_held_stable_and_logs(tmp_path):
    gh = FakeGH([rel("v0.5.28", True), rel("v0.5.22", False)])
    said = []
    assert gate.promote(gh, tag="v0.5.28", now_reason="REL: the last 0.5.x", now=lambda: NOW,
                        log_to=tmp_path / "gate.jsonl", say=said.append) == 0
    (tag, body), = gh.edits
    assert tag == "v0.5.28" and "**Promoted to stable** 2026-10-24 12:00 UTC: by the operator " \
        "(REL: the last 0.5.x)." in body
    entry = json.loads((tmp_path / "gate.jsonl").read_text())
    assert entry["how"] == "now" and entry["reason"] == "REL: the last 0.5.x"
    assert gate.promote(gh, tag="v0.5.28", now_reason=" ", say=said.append) == 1
    assert gate.promote(gh, tag="v0.6.0-dev3", now_reason="x", say=said.append) == 1


def test_the_old_staged_rollout_line_is_replaced_too():
    old = "Kranto 0.5.27: ...\n\n**Staged rollout:** after 6 hours.\n\n- x\n"
    out = gate.new_body(old, gate.promoted_line("by the operator", NOW))
    assert "Staged rollout" not in out and out.count("**Promoted to stable**") == 1


def test_withdraw_marks_a_nightly_so_no_install_is_offered_it(tmp_path):
    from kranto.update.sources import pick
    gh = FakeGH(body="Kranto 0.6.0.dev4: ...\n")
    assert gate.withdraw(gh, "v0.6.0-dev4", "rc_check failed on step 3",
                         log_to=tmp_path / "g.jsonl", say=lambda s: None) == 0
    (tag, body), = gh.notes
    assert body.startswith("**Do not install:** rc_check failed on step 3")
    assert pick([rel("v0.6.0-dev4", True, body=body), rel("v0.6.0-dev3", True)],
                "nightly")["tag_name"] == "v0.6.0-dev3"
    assert gate.withdraw(gh, "v0.6.0", "x", say=lambda s: None) == 1


# -- the notes --------------------------------------------------------------------------------

def test_the_notes_open_with_the_line():
    commits = "## Commits\n\nkranto:\n\n```\n4b1f506 The fix\n```"
    text = notes.render("0.6.0.dev12", "v0.6.0-dev12", "iddv/kranto", "iddv/kranto",
                        [{"number": 332, "title": "The fix", "mergedAt": "x"}], [],
                        "2026-10-23", commits=commits, kind="nightly")
    assert "**Nightly build** 12 toward 0.6.0" in text and "Held" not in text
    assert text.index("## Merged") < text.index("## Commits") < text.index("## Pins")
    from kranto.update.sources import note_lines
    shown = note_lines(text)
    assert shown[:1] == ["- The fix (#332)"]
    promo = notes.render("0.6.0", "v0.6.0", "r", "b", [], [], "2026-10-23", kind="promotion",
                         from_tag="v0.6.0-dev12",
                         big=[{"number": 360, "title": "Today: a calmer home", "mergedAt": "x"}],
                         off=[{"key": "shell.layout", "default": "new",
                               "default_stable": "classic"}])
    assert promo.index(notes.HELD_LINE) < promo.index("## Big changes") < \
        promo.index("## Off on stable") < promo.index("## Merged")
    assert notes.HELD_LINE.startswith(gate.HELD_PREFIXES)
    assert "- Today: a calmer home" in promo and "`shell.layout`: stable keeps " \
        "`classic`" in promo and "from nightly build v0.6.0-dev12" in promo
    fix = notes.render("0.6.1", "v0.6.1", "r", "b", [], [], "2026-10-23", kind="fix")
    assert "**Fix for stable 0.6**" in fix and "release/0.6" in fix
    assert "no pull request since the previous stable is labelled big" in notes.render(
        "0.6.0", "v0.6.0", "r", "b", [], [], "x", kind="promotion")


def test_the_previous_release_is_told_by_its_tag(monkeypatch):
    seen = []
    monkeypatch.setattr(notes, "gh_json", lambda *a: seen.append(a) or {"tag_name": a[-1]})
    assert notes.previous_release("r", "v0.6.0-dev11")
    assert seen[-1] == ("api", "repos/r/releases/tags/v0.6.0-dev11")


def test_guards_log_lists_each_repos_commits(tmp_path):
    def g(*a):
        subprocess.run(["git", "-C", str(tmp_path), *a], check=True, capture_output=True)
    g("init", "-q", "-b", "main")
    g("-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "--allow-empty",
      "-m", "first")
    g("tag", "v1")
    g("-c", "user.name=t", "-c", "user.email=t@e.invalid", "commit", "-q", "--allow-empty",
      "-m", "The fix")
    out = guards.log("v1", "HEAD", {"kranto": tmp_path, "kranto.page": tmp_path})
    assert out.count("1 commit(s)") == 2 and "The fix" in out
    md = guards.log("HEAD", "HEAD", {"kranto": tmp_path}, markdown=True)
    assert "## Commits" in md and "(no commits)" in md


def test_the_previous_release_on_each_line():
    tags = ["v0.5.27", "v0.5.28", "v0.5.27-rc1", "v0.6.0-dev1", "v0.6.0-dev2", "v0.6.0",
            "v0.7.0-dev1"]
    assert guards.previous("v0.6.0-dev3", tags) == "v0.6.0-dev2"
    assert guards.previous("v0.6.0-dev1", tags) == "v0.5.28"       # the first: the stable
    assert guards.previous("v0.6.1", tags) == "v0.6.0"
    assert guards.previous("v0.6.0", tags) == "v0.5.28"
    assert guards.previous("v0.1.0", tags) is None


# -- the jobs a hotfix merges with ------------------------------------------------------------

def test_a_hotfix_merges_with_the_repos_required_jobs():
    for files in (["src/kranto/source_health.py"], ["src/kranto/core/cubs/runtime.py"], ["x.py"]):
        assert guards.required_jobs("kranto", files) == \
            ["test", "fast", "slow", "browser", "frontend", "lint", "gitleaks", "sandbox"]


def test_must_include_names_a_repo_and_a_commit():
    assert guards.parse_must("iddv/kranto@4B1F506") == ("kranto", "4b1f506")
    for bad in ("kranto", "parallax@4b1f506", "kranto@main", "kranto@4b1f"):
        with pytest.raises(guards.GuardError):
            guards.parse_must(bad)


def test_the_wait_is_bounded_and_says_so(monkeypatch):
    said, t = [], [0.0]
    states = iter([(None, "not in main yet"), (None, "not in main yet"),
                   (None, "checks are not done"), (0, "green")])
    monkeypatch.setattr(guards, "where", lambda *a, **k: next(states))
    code, why = guards.wait("o/afk", ".", "abc1234", timeout=100, interval=10,
                            sleep=lambda s: t.__setitem__(0, t[0] + s), now=lambda: t[0],
                            say=said.append)
    assert code == 0 and len(said) == 2 and "up to 100s more" in said[0]
    states = iter([(None, "not in main yet")] * 5)
    t[0] = 0.0
    code, why = guards.wait("o/afk", ".", "abc1234", timeout=15, interval=10,
                            sleep=lambda s: t.__setitem__(0, t[0] + s), now=lambda: t[0],
                            say=said.append)
    assert code == guards.TIMED_OUT and "gave up after 15s" in why


def test_the_wait_reads_the_branch_it_is_given(tmp_path):
    seen = []

    def run(checkout, *args):
        seen.append(args)
        if args[0] == "rev-parse":
            return subprocess.CompletedProcess(args, 0, "a" * 40 + "\n", "")
        return subprocess.CompletedProcess(args, 0, "", "")
    code, why = guards.where("o/afk", ".", "abc1234", run=run, base="release/0.6",
                             green=lambda r, s: (0, "green"))
    assert code == 0 and "is in release/0.6 and green" in why
    assert seen[0][-1] == "+refs/heads/release/0.6:refs/remotes/origin/release/0.6"
    assert ("merge-base", "--is-ancestor", "a" * 40, "origin/release/0.6") in seen


# -- hotfix.sh's own rules --------------------------------------------------------------------

def test_hotfix_sets_its_path_never_uses_admin_and_merges_with_required_jobs():
    sh = (REL / "hotfix.sh").read_text()
    subprocess.run(["bash", "-n", str(REL / "hotfix.sh")], check=True, timeout=30)
    code = "\n".join(ln for ln in sh.splitlines() if not ln.lstrip().startswith("#"))
    assert "--admin" not in code
    assert 'export PATH="$HOME/.local/bin:' in code
    assert 'merge_when_green.sh" "$repo" "$pr" --require "$jobs"' in code
    assert "--must-include" in code and "rc_check.sh" in code and "--from-tag" not in code
    assert 'update --to "$TAG" --yes' in code and "promote --now" in code
    assert "MemoryMax=3G" in code and "--line stable" in code and "cherry-pick -x" in code
    assert "labelled big" in code and "withdraw" in code


def test_hotfix_refuses_what_it_cannot_name(tmp_path):
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin", "HOTFIX_WORK": str(tmp_path / "w")}
    for args in (["parallax", "1"], ["kranto", "x"], ["kranto"],
                 ["kranto", "1", "--promote-now"]):
        r = subprocess.run(["bash", str(REL / "hotfix.sh"), *args], capture_output=True,
                           text=True, timeout=30, env=env)
        assert r.returncode == 2, (args, r.stderr)


# -- big ---------------------------------------------------------------------

def _diff(path, removed=(), added=(), deleted=False):
    head = f"diff --git a/{path} b/{path}\n" + ("deleted file mode 100644\n" if deleted else "")
    body = "".join(f"-{ln}\n" for ln in removed) + "".join(f"+{ln}\n" for ln in added)
    return head + f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n" + body


@pytest.mark.parametrize("diff, hint", [
    (_diff("src/kranto/core/shell.py",
           ['    "shell.layout": Setting("enum", "classic", choices=LAYOUTS),'],
           ['    "shell.layout": Setting("enum", "new", choices=LAYOUTS),']),
     "the default of shell.layout changed"),
    (_diff("src/kranto/features/news/__init__.py",
           ['    "news.on": Setting("bool", False, words="x"),'],
           ['    "news.on": Setting("bool", False, default_stable=True, words="x"),']),
     "the default of news.on changed"),
    (_diff("src/kranto/config.py", ["    auto_update: bool = False"],
           ["    auto_update: bool = True"]),
     "the default of auto_update changed (False -> True)"),
    (_diff("src/kranto/web/watches_api.py", ['            Route("/api/watches", self.list),']),
     "the route /api/watches is removed"),
    (_diff("src/kranto/page/ui/web/src/pages/watches/Watches.svelte", ["<p>x</p>"], deleted=True),
     "a page is removed"),
    (_diff("src/kranto/store.py", [], ['    "DROP TABLE watches",']),
     "a migration that drops or renames"),
    (_diff("src/kranto/launcher.py", ['    s = sub.add_parser("watch", help="x")']),
     "the command watch is removed"),
    (_diff("src/kranto/page/ui/help.md", ["## Watches {#watches}"]),
     'the heading "Watches" is gone'),
])
def test_each_hint_trips_on_its_diff(diff, hint):
    hints = guards.big_hints(diff)
    assert any(hint in h for h in hints), hints
    code, said = guards.big_verdict(hints, [])
    assert code == guards.NEEDS_LABEL and "label it big" in said
    assert guards.big_verdict(hints, ["big"])[0] == 0
    assert guards.big_verdict(hints, ["not-big", "docs"])[0] == 0


def test_no_hint_on_an_ordinary_change():
    plain = (_diff("src/kranto/core/shell.py",
                   ['    "shell.layout": Setting("enum", "new", choices=LAYOUTS, words="a"),'],
                   ['    "shell.layout": Setting("enum", "new", choices=LAYOUTS, words="b"),'])
             + _diff("src/kranto/web/topics_api.py", [], ['            Route("/api/x", self.x),'])
             + _diff("src/kranto/store.py", [], ['    "ALTER TABLE ideas ADD COLUMN x TEXT",'])
             + _diff("src/kranto/page/ui/help.md", ["## Ideas {#ideas}"],
                     ["## Ideas {#ideas}", "more"]))
    assert guards.big_hints(plain) == []
    assert guards.big_verdict([], [])[0] == 0


def test_a_diff_over_300_files_is_read_from_the_files_api(monkeypatch):
    """GitHub refuses `gh pr diff` past 300 files (REPO B2 deletes 308): the big check reads the
    paged files API instead, and its hints still trip."""
    files = [
        {
            "filename": "src/kranto/page/ui/web/src/pages/watches/Watches.svelte",
            "status": "removed",
            "patch": "@@ -1 +0,0 @@\n-<p>x</p>",
        },
        {
            "filename": "src/kranto/page/ui/help.md",
            "status": "modified",
            "patch": "@@ -1 +1 @@\n-## Watches {#watches}\n+## Lists {#lists}",
        },
        {"filename": "docs/new.md", "previous_filename": "docs/old.md", "status": "renamed"},
    ]
    calls = []

    def run(cmd, **kw):
        calls.append(cmd[:3])
        if cmd[:3] == ["gh", "pr", "diff"]:
            return subprocess.CompletedProcess(
                cmd,
                1,
                "",
                "could not find pull request diff: "
                "HTTP 406: Sorry, the diff exceeded the maximum "
                "number of files (300).",
            )
        return subprocess.CompletedProcess(cmd, 0, "".join(json.dumps(f) + "\n" for f in files), "")

    monkeypatch.setattr(guards.subprocess, "run", run)
    hints = guards.big_hints(guards.pr_diff("o/r", "7"))
    assert calls == [["gh", "pr", "diff"], ["gh", "api", "--paginate"]]
    assert any("a page is removed" in h for h in hints), hints
    assert any('the heading "Watches" is gone' in h for h in hints), hints
    # any other refusal is still an error, never an empty diff
    monkeypatch.setattr(
        guards.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "HTTP 404: Not Found"),
    )
    with pytest.raises(guards.GuardError):
        guards.pr_diff("o/r", "7")


# -- a nightly checked before it is offered ----------------------------------------


def test_a_nightly_rc_check_must_check_is_published_unoffered_until_it_passed(tmp_path):
    """v0.6.0-dev3 was published, and offered to every nightly install, before its rc_check
    ran (it carried a runaway loop rc_check did not see). cut_local now publishes such a
    nightly with notes.py's checking line first: pick() never offers it; gate.py offer takes
    the line out only after rc_check.sh passed on it here."""
    from kranto.update.sources import pick

    body = notes.checking("Kranto 0.6.0.dev5: ...\n\n## the server\n\n- A fix\n", "v0.6.0-dev5")
    assert body.startswith(gate.CHECKING)
    rels = [rel("v0.6.0-dev5", True, body=body), rel("v0.6.0-dev4", True)]
    assert pick(rels, "nightly")["tag_name"] == "v0.6.0-dev4"  # not offered
    gh = FakeGH(rels, body=body)
    said: list[str] = []
    passed = tmp_path / "passed"
    # rc_check failed (no pass here): it stays unoffered, nothing is edited
    assert gate.offer(gh, "v0.6.0-dev5", passed, tmp_path / "log", say=said.append) == 1
    assert gh.notes == [] and "has not passed" in said[-1]
    # rc_check passed: the line goes, and the next check offers it
    passed.mkdir()
    (passed / "v0.6.0-dev5").write_text("2026-10-27T19:00:00Z\n")
    assert gate.offer(gh, "v0.6.0-dev5", passed, tmp_path / "log", say=said.append) == 0
    [(tag, new)] = gh.notes
    assert (
        tag == "v0.6.0-dev5" and new.startswith("Kranto 0.6.0.dev5") and gate.WITHDRAWN not in new
    )
    rels[0]["body"] = new
    assert pick(rels, "nightly")["tag_name"] == "v0.6.0-dev5"
    # a withdrawn nightly is never offered this way; an offered one is left alone
    gh = FakeGH(rels, body=f"{gate.WITHDRAWN} rc_check failed\n\nbody")
    assert gate.offer(gh, "v0.6.0-dev5", passed, tmp_path / "log", say=said.append) == 1
    assert (
        gate.offer(
            FakeGH(rels, body="body"), "v0.6.0-dev5", passed, tmp_path / "log", say=said.append
        )
        == 0
    )
    assert gate.offer(gh, "v0.6.0", passed, say=said.append) == 1


def test_cut_local_publishes_checked_nightlies_unoffered_and_rc_check_leaves_its_pass():
    cut = (REL / "cut_local.sh").read_text()
    assert '[ "$KIND" = nightly ] && [ "$RC_CHECK" = 1 ] && extra+=(--checking)' in cut
    assert "scripts/release/gate.py offer $TAG" in cut
    rc = (REL / "rc_check.sh").read_text()
    assert 'passed}/$RC"' in rc
