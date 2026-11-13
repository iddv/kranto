"""The scout and X: while X is connected and under its cap the scout may
propose X searches, accounts and the person's own lists; at most x.scout_max_proposals are
checked, with one fetch of 10 posts each; none is approved without a person; without X the
scout's catalog is what it was. Against ``tests/fake_x.py``; nothing reaches X."""

import json
import secrets

import pytest

from kranto import library, scout
from kranto.config import XConfig
from kranto.store import Store

from .conftest import chat_response
from .test_x_sources import judge_reply, make_rig, mock_http, x_reads

PROPOSALS = [
    {"preset": "x.search", "fields": {"query": "solar mini-grids"}, "why": "w"},
    {"preset": "x.profile", "fields": {"handle": "@gridbuilder"}, "why": "w"},
    {"preset": "x.list", "fields": {"list": "42"}, "why": "w"},
    {"preset": "x.search", "fields": {"query": "pay-as-you-go solar"}, "why": "w"},
    {"preset": "x.search", "fields": {"query": "productive use of energy"}, "why": "w"},
    {"preset": "x.search", "fields": {"query": "minigrid tariffs"}, "why": "w"},
]


@pytest.fixture
def machine_id(tmp_path):
    path = tmp_path / "machine-id"
    path.write_text(secrets.token_hex(16) + "\n")
    return path


def scout_reply(proposals):
    def reply(body):
        content = body["messages"][-1]["content"]
        if "Fields:" in content:
            reply.prompts.append(content)
            return chat_response(json.dumps({"sources": proposals}))
        return judge_reply(body)
    reply.prompts = []
    return reply


def run(rt, **kw):
    topic = library.active_topics(rt.store)[0]
    return scout.scout_topic(rt.store, rt.llm, rt.embedder, rt.http, topic,
                             connections=rt.connections, xcfg=rt.cfg.x, **kw)


def test_x_proposals_are_capped_checked_small_and_never_approved(tmp_path, embedder, machine_id):
    reply = scout_reply(PROPOSALS)
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http, reply=reply)
    try:
        library.add_topic(rt.store, rt.embedder, "Solar", "Solar mini-grids in Africa")
        start = len(fake.requests)
        results = run(rt, auto_approve_min_similarity=0.0)
        prompt = reply.prompts[0]
        assert "x.search" in prompt and "x.profile" in prompt and "x.list" in prompt
        assert "Builders (42)" in prompt and "propose at most 5" in prompt
        checked = [r for r in results if r.status != "invalid"]
        capped = [r for r in results if r.validation.error == "not fetched: X proposal cap"]
        assert len(checked) == 5 and len(capped) == 1
        assert all(r.status == "proposed" for r in checked)        # not auto-approved
        fetches = [r for r in x_reads(fake, start) if r.url.path.endswith(("/tweets",
                                                                           "/recent"))]
        assert len(fetches) == 5
        assert all(r.url.params["max_results"] in ("10",) for r in fetches)
        src = rt.store.query_one("SELECT validation FROM sources WHERE kind = 'x' LIMIT 1")
        record = json.loads(src["validation"])
        assert record["cost_usd"]["check"] == 0.05 and record["cost_usd"]["run"] > 0
    finally:
        rt.close()


def test_without_x_or_over_the_cap_the_catalog_is_unchanged(tmp_path, embedder, machine_id):
    reply = scout_reply(PROPOSALS[:1])
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http, reply=reply,
                        xcfg=XConfig(monthly_usd=0.0))
    try:
        library.add_topic(rt.store, rt.embedder, "Solar", "Solar mini-grids in Africa")
        results = run(rt)
        assert "x.search" not in reply.prompts[0]
        assert results == []                  # an X proposal is not even read without X
        assert scout.presets_text() == scout.presets_text(None)
        assert "x.search" not in scout.presets_text()
    finally:
        rt.close()


def test_x_scout_off_is_honoured(tmp_path, embedder, machine_id):
    rt, fake = make_rig(tmp_path, embedder, machine_id, mock_http,
                        xcfg=XConfig(scout=False))
    try:
        assert scout.x_scouting(rt.store, rt.connections, rt.cfg.x, rt.http) is None
    finally:
        rt.close()


def test_x_proposals_are_refused_when_x_is_not_offered_to_the_parser():
    text = json.dumps({"sources": PROPOSALS[:2]})
    assert scout.parse_proposals(text) == []
    assert [p.preset for p in scout.parse_proposals(text, x=True)] == ["x.search", "x.profile"]
    # the language is optional; the query is not
    bare = json.dumps({"sources": [{"preset": "x.search", "fields": {}}]})
    assert scout.parse_proposals(bare, x=True) == []


def test_no_connection_means_no_x_scouting(store):
    assert scout.x_scouting(store, None, XConfig(), None) is None
    assert isinstance(store, Store)
