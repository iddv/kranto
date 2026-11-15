"""X search through Grok: off until XAI_API_KEY is set; one metered call
a day with x_search; the cost is the tokens plus $5 per 1,000 posts the tool fetched, in
llm_calls and the watcher's budget; items are Grok's own gists under handle-less post URLs,
never the posts' text; the key reaches no page, log, row or process. Against
``tests/fake_xai.py``; nothing reaches xAI."""

import io
import json
import logging
import secrets

import httpx
import pytest

from kranto import pricing, providers, source_health
from kranto.config import BudgetConfig, Config, IngestConfig, LookConfig, MapConfig
from kranto.llm import LLMClient
from kranto.providers.xai import reply_text
from kranto.runtime import open_runtime
from kranto.sources import HTTP, catalog
from kranto.sources.xai_search import NOTE, digest_items
from kranto.store import Store
from kranto.tick import run_ingest

from .conftest import chat_response, llm_config
from .fake_xai import FakeXAI


def judge_or_xai(xai):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.x.ai":
            return xai(request)
        body = json.loads(request.content)
        if "first, quick look" in body["messages"][0]["content"]:
            return chat_response(json.dumps({"pass": True, "reason": "ok"}))
        return chat_response(json.dumps({
            "kind": "beat", "summary": "s", "why_it_matters": "w", "content_quality": 0.9,
            "durability": 0.9, "opportunity": 0.9, "override": False, "tags": ["t"]}))
    return handler


@pytest.fixture
def rig(tmp_path, embedder, monkeypatch):
    key = "xai-" + secrets.token_hex(24)
    xai = FakeXAI(key)
    store = Store.open(tmp_path / "data" / "kranto.db")
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=None),
                 ingest=IngestConfig(fetch_full_text=False), map=MapConfig(),
                 look=LookConfig(enabled=False))
    llm = LLMClient(store, cfg.llm, cfg.budget, api_key="k",
                    transport=httpx.MockTransport(judge_or_xai(xai)))
    http = HTTP(transport=httpx.MockTransport(lambda r: httpx.Response(404)),
                resolver=lambda h: ["93.184.216.34"])
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=llm, http=http)
    yield rt, xai, key, monkeypatch
    rt.close()


def add(rt):
    sid, _ = source_health.add_from_preset(rt, "x.grok_search",
                                           {"query": "solar mini-grids"}, None)
    return sid


def test_without_a_key_the_source_needs_login_and_calls_nothing(rig):
    rt, xai, key, mp = rig
    mp.delenv("XAI_API_KEY", raising=False)
    add(rt)
    report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                        lock_path=rt.cfg.data_dir / "l.lock")
    assert report.sources[0].fetch_state == "needs_login"
    assert "no xAI key" in report.sources[0].fetch_error
    assert xai.requests == []


def test_one_metered_call_a_day_items_are_gists_and_the_tool_is_priced(rig, caplog):
    rt, xai, key, mp = rig
    caplog.set_level(logging.DEBUG)
    mp.setenv("XAI_API_KEY", key)
    add(rt)
    report = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                        lock_path=rt.cfg.data_dir / "l.lock")
    assert report.status == "ok" and report.sources[0].fetched == 3
    [req] = xai.requests
    body = json.loads(req.content)
    assert body["model"] == "grok-4.7" and body["tools"][0]["type"] == "x_search"
    assert "from_date" in body["tools"][0] and body["max_turns"] == 2
    call = rt.store.query_one("SELECT * FROM llm_calls WHERE purpose = 'xai_search'")
    assert call["provider"] == "xai"
    expected = pricing.xai_cost("grok-4.7", 9000, 600, posts=24)
    # 9,000 in at $2/M, 600 out at $6/M, 24 posts at $5 per 1,000
    assert call["cost_usd"] == pytest.approx(expected) and expected == pytest.approx(0.1416)
    assert rt.store.month_spend() >= expected            # in the watcher's budget
    rows = rt.store.query("SELECT item_id, source_url, source_excerpt FROM observations")
    assert {r["item_id"] for r in rows} == {"1849300000000000002", "1849300000000000001",
                                            "1849300000000000009"}
    assert all(r["source_url"].startswith("https://x.com/i/status/") for r in rows)
    assert all("gridco" not in (r["source_excerpt"] or "") for r in rows)
    # once a day: the next run waits
    again = run_ingest(rt.cfg, rt.store, rt.llm, rt.embedder, rt.http,
                       lock_path=rt.cfg.data_dir / "l.lock")
    assert again.sources[0].waiting_until and len(xai.requests) == 1
    # the key is nowhere it must not be
    rt.store.query("PRAGMA wal_checkpoint(FULL)")
    db = b"".join(p.read_bytes() for p in rt.cfg.data_dir.glob("kranto.db*"))
    out = io.StringIO()
    for table in rt.store.append_only_tables():
        rt.store.export_jsonl(table, out)
    assert key.encode() not in db and key not in out.getvalue()
    assert all(key not in r.getMessage() for r in caplog.records)


def test_a_digest_names_no_author_and_carries_its_note():
    payload = {"output": [{"type": "message", "content": [{
        "type": "output_text", "text": json.dumps({"posts": [
            {"url": "https://twitter.com/alice/status/123", "gist": "A tool for CRDT sync",
             "link": "https://example.org/crdt", "date": "2026-10-16"},
            {"url": "https://example.org/not-a-post", "gist": "skipped"}]}),
        "annotations": [{"type": "url_citation", "url": "https://x.com/bob/status/456",
                         "title": "2"}]}]}]}
    text, cites = reply_text(payload)
    items = digest_items(text, cites)
    assert [i.id for i in items] == ["123"]          # a citation titled by its number only
    item = items[0]
    assert item.url == "https://x.com/i/status/123" and item.capture_note == NOTE
    assert item.link == "https://example.org/crdt" and "alice" not in item.body


def test_the_key_is_tested_before_it_is_kept(tmp_path, monkeypatch):
    from kranto.config import init_workspace

    monkeypatch.delenv("XAI_API_KEY", raising=False)
    init_workspace(tmp_path)
    key = "xai-" + secrets.token_hex(24)
    fake = FakeXAI(key)
    bad = providers.xai_key(tmp_path, "xai-" + secrets.token_hex(24),
                            transport=httpx.MockTransport(fake))
    assert not bad["ok"] and not (tmp_path / ".env").exists()
    good = providers.xai_key(tmp_path, key, transport=httpx.MockTransport(fake))
    assert good == {"ok": True, "detail": "xAI accepted the key; grok-4.7 is offered",
                    "changed": True}
    env = tmp_path / ".env"
    assert (env.stat().st_mode & 0o777) == 0o600 and f"XAI_API_KEY={key}" in env.read_text()
    again = providers.xai_key(tmp_path, key, transport=httpx.MockTransport(fake))
    assert again["changed"] is False
    monkeypatch.delenv("XAI_API_KEY", raising=False)


def test_the_preset_and_its_shape():
    p = catalog.get("x.grok_search")
    assert p.access == "login" and p.needs == "xai" and not p.scout
    r = catalog.resolve("x.grok_search", {"query": " solar ", "handles": "@a, b_2"})
    assert (r.kind, r.params) == ("xai_search", {"query": "solar", "handles": "a b_2"})
    with pytest.raises(ValueError, match="usernames"):
        catalog.resolve("x.grok_search", {"query": "q", "handles": "not valid!"})
    assert catalog.provider_of("xai_search", {}) == "x"
