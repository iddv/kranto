"""Feedback: where the issue goes and filing it as the person, through their own gh.

The fake gh (``scripts/dev/fake_gh.py``) runs as a real subprocess, as a scratch server runs
it on PATH: the login, the repository, its labels and the issue it files; nothing reaches
GitHub. Covered: the states the sheet words (ready, missing, signed out, no access,
offline), ``feedback.repo``, the second scrub refusing what the page did not show (a home
path, a token's shape), the labels the repository has, the page's caller only, and no
network when GitHub can't be reached."""
import json
import sys
from pathlib import Path

import pytest

from kranto.page import feedback as F
from kranto.page.gh import Gh
from kranto.page.ui import api

from .app_common import make_home

FAKE = Path(__file__).resolve().parents[2] / "scripts" / "dev" / "fake_gh.py"
UI = {"origin": "ui", "name": "ui", "actions": None}
MCP = {"origin": "mcp", "name": "mcp", "actions": None}
# a token's shape, made here so no secret-shaped literal sits in the repository
TOKEN = "gh" + "p_" + "Z9y8X7w6V5u4T3s2R1q0" * 2


class Cfg(dict):
    tasks_dir = Path("/nonexistent/tasks")
    home = Path("/nonexistent/loop")


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    F.forget()
    monkeypatch.setenv("FAKE_GH_DIR", str(tmp_path / "gh"))
    monkeypatch.delenv("FAKE_GH_STATE", raising=False)
    monkeypatch.setattr(F, "reachable", lambda *a, **k: True)
    yield
    F.forget()


def fake() -> Gh:
    return Gh(cmd=[sys.executable, str(FAKE)])


def filed(tmp_path) -> list[dict]:
    log = tmp_path / "gh" / "issues.jsonl"
    return [json.loads(x) for x in log.read_text().splitlines()] if log.exists() else []


def test_the_repo_is_a_setting_with_the_release_repo_by_default():
    assert F.repo_of(Cfg()) == "iddv/kranto"
    assert F.repo_of(Cfg(feedback={"repo": "someone/fork"})) == "someone/fork"
    assert F.repo_of(Cfg(feedback={"repo": "not a repo; rm -rf"})) == "iddv/kranto"
    assert F.repo_of(None) == "iddv/kranto"
    from kranto.page.settings.store import DEFAULTS
    assert DEFAULTS["feedback"] == {"repo": "iddv/kranto"}


@pytest.mark.parametrize("state,want,can", [("ready", "ready", True),
                                            ("signed_out", "signed_out", False),
                                            ("no_access", "no_access", False)])
def test_status_says_how_it_can_send(monkeypatch, state, want, can):
    if state != "ready":
        monkeypatch.setenv("FAKE_GH_STATE", state)
    monkeypatch.setenv("FAKE_GH_LOGIN", "someone")
    st = F.status(Cfg(), gh=fake())
    assert (st["gh"], st["can_file"], st["reachable"]) == (want, can, True)
    assert st["repo"] == "iddv/kranto"
    assert st["login"] == (None if state == "signed_out" else "someone")
    assert "iddv/kranto" in st["line"] or "gh" in st["line"]
    assert [k["id"] for k in st["kinds"]] == ["bug", "idea", "question"]


def test_without_gh_installed_it_opens_github_instead():
    st = F.status(Cfg(), gh=Gh(cmd=["/nonexistent/gh-is-not-here"]))
    assert (st["gh"], st["can_file"]) == ("missing", False)
    assert "Open on GitHub" in st["line"]


def test_no_network_says_github_cannot_be_reached_and_runs_no_gh(monkeypatch):
    ran = []
    st = F.status(Cfg(), gh=Gh(run=lambda a, c: ran.append(a) or (0, "x", "")),
                  reach=lambda: False)
    assert (st["reachable"], st["can_file"]) == (False, False)
    assert "can't be reached" in st["line"] and "draft is kept" in st["line"]
    assert ran == []


def test_gh_offline_is_no_network_too(monkeypatch):
    monkeypatch.setenv("FAKE_GH_STATE", "offline")
    st = F.status(Cfg(), gh=fake())
    assert (st["reachable"], st["can_file"]) == (False, False)


def test_status_is_cached_and_never_holds_a_token():
    calls = []

    def run(args, cwd):
        calls.append(args)
        return (0, "true" if args[1].startswith("repos/") else "someone", "")
    F.status(Cfg(), gh=Gh(run=run))
    F.status(Cfg(), gh=Gh(run=run))
    assert len(calls) == 2                       # the login and the repo, once
    st = F.status(Cfg(), gh=Gh(run=run), fresh=True)
    assert len(calls) == 4
    assert "token" not in json.dumps(st).lower().replace("a token", "")


def test_file_it_files_as_the_login_with_the_labels_the_repo_has(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GH_LABELS", "bug,question")
    body = "The brief's Run now did nothing.\n\n**Kind:** Bug\n"
    r = F.file(Cfg(), "Bug: the brief's Run now did nothing", body, "bug", gh=fake())
    assert r["repo"] == "iddv/kranto" and r["number"] == 4242
    assert r["url"] == "https://github.com/iddv/kranto/issues/4242"
    assert r["labels"] == ["bug"] and r["dropped"] == ["feedback"]
    [issue] = filed(tmp_path)
    assert issue == {"repo": "iddv/kranto", "number": 4242,
                     "title": "Bug: the brief's Run now did nothing", "body": body,
                     "labels": ["bug"]}


def test_file_it_goes_to_the_repo_the_setting_names(tmp_path):
    r = F.file(Cfg(feedback={"repo": "someone/fork"}), "Idea: more", "More, please.", "idea",
               gh=fake())
    assert r["url"] == "https://github.com/someone/fork/issues/4242"
    assert filed(tmp_path)[0]["repo"] == "someone/fork"


@pytest.mark.parametrize("extra", [TOKEN, "/home/someone/kranto-loop/loop.yaml"],
                         ids=["token", "home-path"])      # no token shape in a test's id
def test_what_the_page_did_not_scrub_is_never_filed(tmp_path, extra):
    with pytest.raises(F.FeedbackError) as e:
        F.file(Cfg(), "Bug: it broke", "It broke at " + extra + " today.", "bug", gh=fake())
    assert e.value.status == 409
    assert extra not in e.value.extra["body"]
    assert filed(tmp_path) == []
    # the scrubbed text the page shows in a new confirm files as it is
    r = F.file(Cfg(), "Bug: it broke", e.value.extra["body"], "bug", gh=fake())
    assert r["number"] == 4242 and extra not in filed(tmp_path)[0]["body"]


@pytest.mark.parametrize("title,body,kind", [("", "x", "bug"), ("t", "", "bug"),
                                             ("t", "x", "rant"), ("t" * 200, "x", "bug"),
                                             ("t", "x" * 70000, "idea")])
def test_a_bad_request_files_nothing(tmp_path, title, body, kind):
    with pytest.raises(F.FeedbackError) as e:
        F.file(Cfg(), title, body, kind, gh=fake())
    assert e.value.status == 400 and filed(tmp_path) == []


def test_offline_while_filing_keeps_the_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_GH_STATE", "offline")
    with pytest.raises(F.FeedbackError) as e:
        F.file(Cfg(), "Bug: x", "y", "bug", gh=fake())
    assert e.value.status == 503 and "draft is kept" in str(e.value)


@pytest.fixture
def app(tmp_path, monkeypatch):
    cfg = make_home(tmp_path)
    a = api.App(None, "fake", cfg.home)
    a.loop_cfg = lambda: cfg
    monkeypatch.setattr(F, "Gh", fake)
    return a


def call(app, method, body=None, who=None, query=None):
    code, _, data = api.handle(method, "/api/feedback/issue", query,
                               json.dumps(body).encode() if body is not None else None,
                               app=app, identity=who)
    return code, json.loads(data)


def test_the_routes_read_and_file(app, tmp_path):
    code, st = call(app, "GET")
    assert code == 200 and st["can_file"] and st["repo"] == "iddv/kranto"
    code, r = call(app, "POST", {"kind": "question", "title": "Question: how?",
                                 "body": "How do I pause?"}, UI)
    assert code == 200 and r["url"].endswith("/issues/4242")
    assert filed(tmp_path)[0]["title"] == "Question: how?"


def test_only_the_person_at_the_page_files(app, tmp_path):
    code, r = call(app, "POST", {"kind": "bug", "title": "Bug: x", "body": "y"}, MCP)
    assert code == 403 and filed(tmp_path) == []


def test_the_route_answers_a_scrub_refusal_with_what_it_would_file(app, tmp_path):
    code, r = call(app, "POST", {"kind": "bug", "title": "Bug: x", "body": "at " + TOKEN}, UI)
    assert code == 409 and TOKEN not in r["body"] and r["title"] == "Bug: x"
    assert filed(tmp_path) == []
