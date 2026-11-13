"""The build loop's actions are verbs too: one door, one ladder, for every assistant.

the page's registry hands its actions to the host (``host_api.verb_rows``); the server lists them
as ``b.<kind>`` and runs them through ``api/act`` in this process, so the ladder, the prepared
presses and Activity are the same for a build as for a topic. An assistant's token (``mcp``,
``console``) may not post to ``api/act`` directly once the page has verbs; a named agent keeps
its own actions list there. ``mcp.actions: false`` (reads only) stops your own assistant, not
the console. Here the page is a stand-in that records who the host said was calling."""

import json

import pytest

from kranto import tokens
from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.core import verbs
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config, web_client
from .test_brb_mount import FakeApi

BASE = "http://127.0.0.1:8765"
BOTH = ["ui", "cli", "mcp", "console", "agent"]


def row(kind, title, ladder, subjects, click="click", fields=(), doors=BOTH, page=None):
    return {"kind": kind, "title": title, "says": f"{title}, in words.", "click": click,
            "ladder": ladder, "subject": "|".join(s for s in subjects if s != "new") or "new",
            "subjects": list(subjects), "doors": list(doors),
            "page": page or ("#/builds/{id}" if "build" in subjects else "#/ideas"),
            "mark": "build:{id}" if "build" in subjects else "",
            "fields": [{"name": f, "type": t, "says": "", "required": req, "choices": []}
                       for f, t, req in fields]}


class ActApi(FakeApi):
    """the page's mount with ``verb_rows``, an ``api/act`` that records its caller, and the
    loop's settings (``Config``: ``mcp.actions``)."""

    def __init__(self):
        super().__init__()
        self.mcp_actions = True
        self.checks = []
        api = self

        class Settings:
            def __init__(self, root=None, overrides=None):
                self.data = {"mcp": {"actions": api.mcp_actions}}
        self.Config = Settings

    def verb_rows(self):
        return [row("retry", "Retry", "spend", ("idea", "build"),
                    fields=(("note", "line", False),)),
                row("publish", "Publish", "outward", ("idea", "build"), click="confirm"),
                row("add_idea", "Add to Ideas", "reversible", ("new",),
                    fields=(("text", "text", True),)),
                row("github_app_key", "Replace key", "credential", ("loop",), click="confirm",
                    doors=("ui", "cli"), page="#/settings/github"),
                row("factory_issue", "File a Kranto issue", "outward", ("new", "idea", "build"),
                    fields=(("issue", "line", True), ("text", "text", True)),
                    page="#/needs")]

    def handle(self, method, path, query=None, body=None, identity=None):
        if path == "/api/act" and json.loads(body).get("check"):
            # the build loop's own check of a press's fields: nothing runs
            b = json.loads(body)
            self.checks.append(b)
            if (b.get("fields") or {}).get("issue") == "refused here":
                return 400, "application/json", json.dumps(
                    {"error": "the issue's title says nothing"}).encode()
            return 200, "application/json", json.dumps(
                {"ok": True, "checked": True, "why_not_now": None}).encode()
        if path == "/api/act":
            self.calls.append((method, path, query, json.loads(body), identity))
            if (json.loads(body).get("fields") or {}).get("issue") == "refused at the press":
                return 400, "application/json", json.dumps(
                    {"error": "the build loop said no"}).encode()
            return 200, "application/json", json.dumps(
                {"say": "done", "by": (identity or {}).get("origin")}).encode()
        return super().handle(method, path, query, body)


@pytest.fixture
def api(monkeypatch):
    return brbfake.install(monkeypatch, ActApi())


@pytest.fixture
def app(tmp_path, store, embedder, make_client, api):
    (tmp_path / "kranto.yaml").write_text("llm:\n  models:\n    judge: m\n    reason: m\n")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(),
                 builds=BuildsConfig(enabled=True),
                 brb=BrbConfig(enabled=True, root=str(tmp_path / "tasks")))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    return create_app(rt, port=8765)


def bearer(name):
    tokens.Store().ensure_doors()
    return {"authorization": "Bearer " + tokens.Store().value(name)}


def bare(app):
    return web_client(app, BASE, signed_in=False)


def acts(api):
    return [c for c in api.calls if len(c) == 5]


def test_the_build_loops_actions_are_verbs(app):
    with bare(app) as web:
        got = {v["kind"]: v for v in web.get("/api/verbs").json()["verbs"]}
    assert got["b.retry"]["ladder"] == "spend" and got["b.retry"]["choice"] == "do"
    assert got["b.retry"]["subjects"] == ["idea", "build"]
    assert got["b.publish"]["choice"] == "ask"
    key = got["b.github_app_key"]
    assert key["locked"] and key["choice"] == "never" and "mcp" not in key["doors"]
    assert not verbs.get("b.add_idea").needs_id() and verbs.get("b.retry").needs_id()


def test_console_runs_a_build_loop_action_through_the_door(app, api):
    with bare(app) as web:
        r = web.post("/api/verbs/b.retry", headers=bearer("console"),
                     json={"subject": {"kind": "build", "id": "repo-recall"},
                           "fields": {"note": "once more"}, "client": "claude"})
        assert r.status_code == 200 and r.json()["ok"], r.text
        assert r.json()["page"] == "#/builds/repo-recall"
        assert r.json()["by"] == "console:claude"
        method, path, _, body, who = acts(api)[-1]
        assert (method, path) == ("POST", "/api/act")
        assert body == {"kind": "retry", "fields": {"note": "once more"},
                        "subject": {"kind": "build", "id": "repo-recall"}, "confirm": False}
        assert who["origin"] == "console" and who["verb"] == "b.retry"
        r = web.post("/api/verbs/b.retry", headers=bearer("console"),
                     json={"subject": {"kind": "topic", "id": "x"}})
        assert r.status_code == 400 and "not a topic" in r.json()["error"]
        r = web.post("/api/verbs/b.add_idea", headers=bearer("mcp"),
                     json={"fields": {"text": "a tide-clock app"}})
        assert r.status_code == 200, r.text
        assert acts(api)[-1][3]["subject"] == {"kind": "new", "id": None}


def test_publish_is_prepared_and_the_owner_presses_it(app, api):
    with bare(app) as web:
        r = web.post("/api/verbs/b.publish", headers=bearer("mcp"),
                     json={"subject": {"kind": "build", "id": "repo-recall"},
                           "client": "codex"})
    assert r.json()["prepared"] and not acts(api)
    with web_client(app, BASE) as page:
        r = page.post(f"/api/prepared/{r.json()['prepared']}/press", json={})
    assert r.status_code == 200, r.text
    _, _, _, body, who = acts(api)[-1]
    assert body["kind"] == "publish" and body["confirm"] is True
    assert body["subject"] == {"kind": "build", "id": "repo-recall"} and who["origin"] == "ui"


def test_an_assistant_cannot_skip_the_door(app, api):
    tokens.Store().add("agent:RC")
    body = {"kind": "publish", "subject": {"kind": "build", "id": "x"}, "confirm": True}
    with bare(app) as web:
        for who in ("mcp", "console"):
            r = web.post("/brb/api/act", headers=bearer(who), json=body)
            assert r.status_code == 403 and "/api/verbs/<kind>" in r.json()["error"], who
        # a named agent keeps its own actions list on api/act
        r = web.post("/brb/api/act", headers=bearer("agent:RC"), json=body)
        assert r.status_code == 200 and r.json()["by"] == "agent:RC"
    assert [c[4]["origin"] for c in acts(api)] == ["agent:RC"]


def test_reads_only_stops_your_own_assistant(app, api):
    api.mcp_actions = False
    with bare(app) as web:
        r = web.post("/api/verbs/topic.add", headers=bearer("mcp"),
                     json={"fields": {"name": "X", "description": "d."}})
        assert r.status_code == 403 and "reads only" in r.json()["error"]
        r = web.post("/api/verbs/source.preview", headers=bearer("mcp"),
                     json={"fields": {"preset": "rss"}})
        assert r.status_code != 403                       # a read still reads
        r = web.post("/api/verbs/topic.add", headers=bearer("console"),
                     json={"fields": {"name": "X", "description": "d."}})
        assert r.status_code == 200 and r.json()["ok"], r.text   # the console is in the page


def test_the_reads_are_listed(app):
    with bare(app) as web:
        reads = {r["path"]: r for r in web.get("/api/verbs").json()["reads"]}
    assert "/api/status" in reads and "/api/verbs" in reads
    assert not [p for p in reads if p.startswith(("/api/tokens", "/api/runs"))]


def test_kranto_mcp_takes_console_and_compact(monkeypatch):
    from kranto import launcher
    seen = {}

    def mcp_main(url, console=None, compact=False):
        seen.update(url=url, console=console, compact=compact)
        return 0
    brbfake.install(monkeypatch, mcp_main=mcp_main)
    args = launcher.build_parser().parse_args(
        ["mcp", "--url", "http://127.0.0.1:9", "--console", "codex", "--compact"])
    assert args.func(args, launcher.Host()) == 0
    assert seen == {"url": "http://127.0.0.1:9", "console": "codex", "compact": True}
