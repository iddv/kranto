"""The owner's press, Promote to stable (the owner's decisions of
2026-10-24): the candidate the gate wrote, read totally; the press only on the maintainer's
install, only for an open candidate, written to update/promote.json for the gate's unit. No
network and no systemd: the unit's start is a fake."""
from __future__ import annotations

import json

import pytest

from kranto import config as config_mod
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.runtime import open_runtime
from kranto.stored.release import Candidate, PromoteAsk
from kranto.update import check
from kranto.web import update_api
from kranto.web.app import create_app

from .conftest import llm_config, web_client

CAND = {"schema": 1, "at": "2026-10-24T12:00:00Z", "state": "candidate", "stable": "v0.5.27",
        "tag": "v0.6.0-dev3", "version": "0.6.0.dev3", "to": "v0.6.0", "installed": "0.6.0.dev3",
        "prs": {"kranto": [{"number": 360, "title": "Today: a calmer home"}], "kranto.page": []},
        "count": 1, "big": [{"repo": "kranto", "number": 360, "title": "Today: a calmer home"}],
        "off_on_stable": [{"key": "shell.layout", "default": "new", "default_stable": "classic"}],
        "checks": [{"name": "rollback", "ok": True, "said": "no rollback"},
                   {"name": "errors", "ok": None, "said": "blind"}],
        "blocking": [], "blind": ["error reports: not on the server yet"],
        "nightly_since": "2026-10-24T05:35:04Z"}


def test_the_candidate_reads_totally():
    c = Candidate.parse(json.dumps(CAND))
    assert c.open and c.to == "v0.6.0" and c.big[0].number == 360
    assert c.off_on_stable[0].default_stable == "classic" and c.checks[1].ok is None
    for raw in (None, "", "null", "[]", "not json", json.dumps({"state": None})):
        got = Candidate.parse(raw)
        assert got is None or (got.state == "none" and not got.open)
    odd = Candidate.parse(json.dumps({**CAND, "state": "rethinking", "count": "many",
                                      "big": None, "checks": [{"ok": "yes"}]}))
    assert odd.state == "rethinking" and not odd.open and odd.count == 0 and odd.big == []
    assert Candidate.parse(json.dumps({**CAND, "blocking": ["1 new error"]})).open is False
    assert PromoteAsk.parse(json.dumps({"tag": "v0.6.0-dev3", "by": "ui"})).tag == "v0.6.0-dev3"


def test_maintainer_is_a_setting_set_by_hand():
    assert config_mod.parse_update({}).maintainer is False
    assert config_mod.parse_update({"maintainer": True}).maintainer is True
    with pytest.raises(config_mod.ConfigError, match="maintainer"):
        config_mod.parse_update({"maintainer": "yes"})
    assert "maintainer" not in update_api.SETTABLE           # no page sets it


@pytest.fixture
def web(tmp_path, store, embedder, make_client, monkeypatch):
    started = []
    monkeypatch.setattr(update_api, "_start_gate",
                        lambda: started.append(1) or (True, "started"))
    (tmp_path / "kranto.yaml").write_text("llm: {}\nupdate:\n  repo: iddv/kranto\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    with web_client(create_app(rt, None), "http://127.0.0.1:8765") as w:
        w.home, w.started = tmp_path, started
        yield w


def _maintainer(home, cand=CAND):
    (home / "kranto.yaml").write_text("llm: {}\nupdate:\n  repo: iddv/kranto\n"
                                     "  maintainer: true\n")
    (home / "update").mkdir(exist_ok=True)
    if cand is not None:
        (home / "update" / "candidate.json").write_text(json.dumps(cand))


def test_only_the_maintainers_install_sees_the_candidate_and_may_press(web):
    _maintainer(web.home)
    (web.home / "kranto.yaml").write_text("llm: {}\nupdate:\n  repo: iddv/kranto\n")
    view = web.get("/api/update").json()
    assert view["candidate"] is None and view["settings"]["maintainer"] is False
    r = web.post("/api/update/promote", json={"tag": "v0.6.0-dev3"})
    assert r.status_code == 403 and "maintainer" in r.json()["error"]
    assert not (web.home / "update" / "promote.json").exists() and not web.started


def test_the_press_writes_the_ask_and_starts_the_gate(web):
    _maintainer(web.home)
    view = web.get("/api/update").json()
    assert view["candidate"]["tag"] == "v0.6.0-dev3" and view["candidate"]["to"] == "v0.6.0"
    r = web.post("/api/update/promote", json={"tag": "v0.6.0-dev3"})
    assert r.status_code == 202, r.text
    ask = json.loads((web.home / "update" / "promote.json").read_text())
    assert ask["tag"] == "v0.6.0-dev3" and ask["at"] and web.started == [1]
    assert r.json()["promote"]["started"] is True


@pytest.mark.parametrize("cand, why", [
    (None, "no candidate"),
    ({**CAND, "state": "none", "tag": None}, "no candidate"),
    ({**CAND, "state": "promoting", "step": "cutting"}, "promoting"),
    ({**CAND, "state": "blocked", "blocking": ["1 new error still occurring"]}, "blocks it"),
])
def test_no_press_without_an_open_candidate(web, cand, why):
    _maintainer(web.home, cand)
    r = web.post("/api/update/promote", json={"tag": "v0.6.0-dev3"})
    assert r.status_code == 409 and why in r.json()["error"]
    assert not (web.home / "update" / "promote.json").exists()


def test_a_press_for_a_build_that_moved_on_is_refused(web):
    _maintainer(web.home)
    r = web.post("/api/update/promote", json={"tag": "v0.6.0-dev2"})
    assert r.status_code == 409 and "the candidate is v0.6.0-dev3" in r.json()["error"]
    assert web.post("/api/update/promote", json={}).status_code == 409


def test_a_candidate_written_by_the_gate_is_what_the_view_reads(tmp_path):
    """The gate (scripts/release/gate.py, standard library only) and the server agree on the
    file: the gate's own shape parses into the contract with nothing noted away."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "rel_gate", Path(__file__).resolve().parent.parent / "scripts" / "release" / "gate.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    c = Candidate.parse(json.dumps(CAND))
    assert set(CAND) <= {f for f in c.to_dict()} | {"schema"}
    assert hasattr(gate, "SCHEMA") and c.schema == gate.SCHEMA
    (tmp_path / "update").mkdir()
    (tmp_path / "update" / "candidate.json").write_text(json.dumps(CAND))
    assert check.candidate(tmp_path).tag == "v0.6.0-dev3"
