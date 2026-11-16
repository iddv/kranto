"""Settings › Posting › How you write: a writer's own model, and the OpenAI key pasted on the
page. The key goes to the server once, is tested, is kept as the command line keeps it, and is
never shown, logged or sent back. No default model is chosen (P-11 is the owner's). Nothing
touches the network: OpenAI answers through a ``MockTransport``; the key is built at runtime."""

from __future__ import annotations

import json
import logging

import httpx
import pytest

from kranto import prose, providers
from kranto.prose import profile as profile_mod

from .test_web import rt  # noqa: F401 - fixture


def _key() -> str:
    return "".join(("sk", "-", "w" * 40))


def _openai(status: int, seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"data": [{"id": "gpt-x"}]} if status == 200 else
                              {"error": {"message": "Incorrect API key provided"}})
    return handler


@pytest.fixture
def openai_answers(monkeypatch):
    """OpenAI's key test answered by a mock: ``set_status(200 | 401)``; ``seen`` its requests."""
    seen: list = []
    state = {"status": 200}
    real = providers.openai_key

    def fake(root, key=None, **kw):
        return real(root, key, transport=httpx.MockTransport(_openai(state["status"], seen)))
    monkeypatch.setattr(providers, "openai_key", fake)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    return state, seen


def _client(rt):  # noqa: F811
    from kranto.web.app import create_app

    from .conftest import web_client
    return web_client(create_app(rt), "http://127.0.0.1:8765")


def test_the_key_is_tested_kept_and_never_sent_back(rt, openai_answers, caplog,  # noqa: F811
                                                    monkeypatch):
    state, seen = openai_answers
    key = _key()
    caplog.set_level(logging.DEBUG)
    with _client(rt) as client:
        assert client.get("/api/prose").json()["writer_key"] == {"set": False}
        state["status"] = 401
        bad = client.post("/api/prose/writer-key", json={"key": key})
        assert bad.status_code == 200 and bad.json()["ok"] is False
        assert not (rt.cfg.root / ".env").exists() or "OPENAI_API_KEY" not in (
            rt.cfg.root / ".env").read_text()
        state["status"] = 200
        good = client.post("/api/prose/writer-key", json={"key": key})
        assert good.status_code == 200 and good.json()["ok"] is True
        assert good.json()["set"] is True
        assert client.get("/api/prose").json()["writer_key"] == {"set": True}
        for r in (bad, good, client.get("/api/prose")):
            assert key not in r.text
    env = rt.cfg.root / ".env"
    assert "OPENAI_API_KEY=" in env.read_text() and oct(env.stat().st_mode)[-3:] == "600"
    assert key not in caplog.text
    assert seen and all(r.url.path.endswith("/models") for r in seen)   # tested, nothing spent
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)


def test_only_the_pages_own_session_may_paste_the_key(rt, openai_answers):  # noqa: F811
    from kranto.web import prose_api
    for door in (None, "cli", "ui-token", "agent", "mcp", "console"):
        with pytest.raises(prose_api.ProseError) as e:
            prose_api.writer_key(rt, {"key": _key()}, door)
        assert e.value.code == 403
    with pytest.raises(prose_api.ProseError, match="Paste the key"):
        prose_api.writer_key(rt, {"key": "  "}, "ui")
    from kranto.core import verbs
    v = verbs.get("prose.writer_key")
    assert v.doors == verbs.PAGE_ONLY and v.ladder == "credential"


def test_a_writers_model_is_chosen_per_writer_and_none_is_chosen_by_default(rt):  # noqa: F811
    p = prose.load(rt.cfg, rt.store)
    assert all(p.writer_model(w) is None for w in profile_mod.WRITER_SITE)   # P-11: no default
    with _client(rt) as client:
        got = client.get("/api/prose").json()
        assert got["writer_models"] == {w: None for w in profile_mod.WRITER_SITE}
        assert "openai" in got["writer_providers"]
        r = client.post("/api/prose/voice", json={"writer_model": {
            "social": {"provider": "openai", "model": "gpt-x"}}})
        assert r.status_code == 200
        assert client.get("/api/prose").json()["writer_models"]["social"] == {
            "provider": "openai", "model": "gpt-x"}
        r = client.post("/api/prose/voice", json={"writer_model": {"social": None}})
        assert client.get("/api/prose").json()["writer_models"]["social"] is None


def test_the_route_is_listed_for_usage_reports_and_the_privacy_page():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    schema = json.loads((root / "src" / "kranto" / "telemetry" / "schema.json").read_text())
    assert "/api/prose/writer-key" in json.dumps(schema)
    assert "/api/prose/writer-key" in (root / "docs" / "privacy" / "what-kranto-sends.md"
                                       ).read_text()
