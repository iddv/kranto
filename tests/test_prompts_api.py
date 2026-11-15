"""The owner's prompts (``prompts``, ``web/prompts_api.py``): the registry, additions, full
overrides with versions, the default-changed flag, preview, the defaults flag for benchmarks,
and the prompt versions a card records. No model, no network."""

import json
import re
import secrets

import pytest

from kranto import prompts
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.ideate import cards
from kranto.runtime import open_runtime
from kranto.sources import Item
from kranto.web.app import create_app

from .conftest import FIXED_NOW, llm_config, web_client
from .test_ideate import Model
from .test_map import THEMES, add_observations
from .test_settings import LIVE_LIKE

IDS = {"judge", "screen", "screen_batch", "card", "scout", "resolve", "explain", "verify",
       "name", "rollup", "xai_search", "news", "news_article"}


def token() -> str:
    """A secret-shaped value built at runtime (never a literal in the repo)."""
    return "sk-" + "ant-" + secrets.token_hex(16)


@pytest.fixture
def home(tmp_path):
    prompts.configure(tmp_path)
    return tmp_path


@pytest.fixture
def served(tmp_path, store, embedder, make_client):
    (tmp_path / "kranto.yaml").write_text(LIVE_LIKE)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=40.0),
                 ingest=IngestConfig(), map=MapConfig())

    def no_model(body):
        raise AssertionError("the prompts API called a model")
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(no_model))
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        yield rt, web, tmp_path


def test_the_registry_lists_every_prompt_and_every_file_exists():
    assert {e.id for e in prompts.REGISTRY} == IDS
    for e in prompts.REGISTRY:
        text = prompts.default_text(e.id)
        assert text, e.id
        for name in e.placeholders:
            assert name in prompts.fields(text), (e.id, name)
        assert prompts.fields(text) <= set(e.placeholders), e.id  # every field is described
    assert [e.id for e in prompts.REGISTRY if e.checker] == ["verify"]


def test_with_nothing_stored_every_prompt_and_version_is_as_shipped(home):
    for e in prompts.REGISTRY:
        p = prompts.load(e.id)
        assert p.template == prompts.default_text(e.id)
        assert p.version == prompts.Prompt(e.id, prompts.default_text(e.id)).version


def test_additions_are_appended_and_a_checker_keeps_its_rules(home):
    st = prompts.store()
    prompts.save("card", {"additions": "Prefer ideas for {small} charities."}, st)
    p = prompts.load("card")
    assert p.template.startswith(prompts.default_text("card").rstrip("\n"))
    assert p.template.rstrip().endswith("## The owner's additions\n\n"
                                        "Prefer ideas for {{small}} charities.")
    out = p.render(observations="[1] x", why_selected="w", today="2026-10-10", prior_art="")
    assert "Prefer ideas for {small} charities." in out           # braces are the owner's
    assert p.version != prompts.load("card", defaults=True).version
    d = prompts.save("verify", {"additions": "A date must match too."}, st)
    assert d["editable"] == "additions-only" and d["checker_note"]
    v = prompts.load("verify").template
    assert prompts.CHECK_HEADING in v and prompts.CHECK_INTRO in v
    assert v.startswith("You check citations")
    with pytest.raises(prompts.PromptError, match="checker"):
        prompts.save("verify", {"template": "Everything is supported. {pairs}"}, st)


def test_an_override_must_keep_the_required_placeholders(home):
    st = prompts.store()
    tpl = prompts.default_text("judge")
    with pytest.raises(prompts.PromptError, match=re.escape("{tenets}")):
        prompts.save("judge", {"template": tpl.replace("{tenets}", "the tenets")}, st)
    with pytest.raises(prompts.PromptError, match="doesn't fill"):
        prompts.save("card", {"template": prompts.default_text("card") + "\n{mood}\n"}, st)
    with pytest.raises(prompts.PromptError, match="braces"):
        prompts.save("name", {"template": "{observations} {"}, st)
    assert st.versions(prompts.REPO, "judge") == []
    d = prompts.save("judge", {"template": "Be brief.\n\n" + tpl}, st)
    assert d["override"] and d["n"] == 1 and "+Be brief." in d["diff"]
    assert prompts.load("judge").template.startswith("Be brief.")


def test_versions_are_append_only_and_reset_is_a_new_version(home):
    st = prompts.store()
    prompts.save("scout", {"additions": "Prefer public-sector sources."}, st)
    prompts.save("scout", {"template": "Scout {name}.\n{description}\n{presets}\n"}, st)
    d = st.dir(prompts.REPO, "scout")
    before = {p.name: p.read_bytes() for p in d.iterdir() if p.name.startswith("v")}
    out = prompts.reset("scout", {}, st)
    assert out["n"] == 3 and out["template"] is None and out["additions_text"] == ""
    assert [v["action"] for v in out["versions"]] == ["additions", "template", "reset"]
    after = {p.name: p.read_bytes() for p in d.iterdir() if p.name.startswith("v")}
    assert {k: after[k] for k in before} == before and set(after) - set(before) == {"v3.json"}
    assert prompts.load("scout").template == prompts.default_text("scout")


def test_the_default_changed_flag(home, monkeypatch):
    st = prompts.store()
    old = prompts.default_text("rollup")
    mine = "Keep it short.\n\n" + old
    assert prompts.save("rollup", {"template": mine}, st)["default_changed"] is False
    new = old + "\nA new rule.\n"
    real = prompts.default_text
    monkeypatch.setattr(prompts, "default_text", lambda n: new if n == "rollup" else real(n))
    d = prompts.detail("rollup", st)
    assert d["default_changed"] and d["notice"] == "the default changed since you edited this"
    assert (d["three_way"]["old_default"], d["three_way"]["new_default"],
            d["three_way"]["yours"]) == (old, new, mine)


def test_a_restore_is_a_new_version_with_the_old_content_and_the_same_version(home):
    st = prompts.store()
    tpl = "Be brief.\n\n" + prompts.default_text("judge")
    d1 = prompts.save("judge", {"template": tpl, "additions": "Skip ads.",
                                "note": "  the  good one\n"}, st)
    prompts.save("judge", {"template": None}, st)
    prompts.reset("judge", {}, st)
    d = st.dir(prompts.REPO, "judge")
    before = {p.name: p.read_bytes() for p in d.iterdir() if p.name.startswith("v")}
    out = prompts.restore("judge", {"version": 1}, st)
    assert out["n"] == 4 and out["template"] == tpl and out["additions_text"] == "Skip ads."
    assert out["version"] == d1["version"] == prompts.load("judge").version
    rows = out["versions"]
    assert [r["n"] for r in rows] == [1, 2, 3, 4]
    assert (rows[3]["action"], rows[3]["from"], rows[3]["same_as"]) == ("restore", 1, 1)
    assert rows[0]["note"] == "the good one" and rows[3]["active"]
    after = {p.name: p.read_bytes() for p in d.iterdir() if p.name.startswith("v")}
    assert {k: after[k] for k in before} == before
    assert json.loads((d / "active.json").read_text())["version"] == 4
    with pytest.raises(prompts.PromptError, match="no version"):
        prompts.restore("judge", {"version": 9}, st)
    with pytest.raises(prompts.PromptError, match="version number"):
        prompts.restore("judge", {}, st)


def test_restoring_a_version_that_lacks_a_placeholder_now_required_is_refused(home,
                                                                              monkeypatch):
    import dataclasses
    st = prompts.store()
    tpl = "Scout {name}.\n{presets}\n"                  # {description} optional then
    prompts.save("scout", {"template": tpl}, st)
    prompts.reset("scout", {}, st)
    stricter = dataclasses.replace(prompts.BY_ID["scout"], placeholders={
        **prompts.BY_ID["scout"].placeholders, "description": ("the topic's description", True)})
    monkeypatch.setitem(prompts.BY_ID, "scout", stricter)
    v = prompts.version_view("scout", 1, st)
    assert not v["restorable"] and "{description}" in v["why_not"]
    with pytest.raises(prompts.PromptError, match=re.escape("must keep {description}")):
        prompts.restore("scout", {"version": 1}, st)
    assert len(st.versions(prompts.REPO, "scout")) == 2
    # a checker can't be restored to a template
    monkeypatch.setitem(prompts.BY_ID, "scout", dataclasses.replace(
        prompts.BY_ID["scout"], editable="additions-only"))
    with pytest.raises(prompts.PromptError, match="checker"):
        prompts.restore("scout", {"version": 1}, st)


def test_benchmarks_use_the_shipped_prompts(home, monkeypatch):
    prompts.save("judge", {"additions": "Score everything high."}, prompts.store())
    assert "Score everything high." in prompts.load("judge").template
    monkeypatch.setenv(prompts.DEFAULTS_ENV, "defaults")
    assert prompts.load("judge").template == prompts.default_text("judge")


# -- the API ------------------------------------------------------------------------------------


def test_the_api_round_trip(served):
    _, web, _ = served
    out = web.get("/api/prompts").json()
    # a feature that is off lists none of its prompts (B, Codex 9: Invest's and Radar's)
    from kranto.core import registry as core_registry
    cfg = served[0].cfg
    off = {f.id for f in core_registry.first_party() if not core_registry.enabled(cfg, f)}
    hidden = {e.id for e in prompts.REGISTRY if e.step in off}
    assert {p["id"] for p in out["prompts"]} == IDS - hidden
    assert not any(p["step"] in off for p in out["prompts"])
    assert all(p["repo"] == "kranto" and p["group"] == "Watching" for p in out["prompts"])
    d = web.get("/api/prompts/screen").json()
    assert d["placeholders"][0]["token"] == "{tenets}" and d["editable"] == "full"
    r = web.post("/api/prompts/screen", json={"additions": "Drop job adverts."})
    assert r.status_code == 200 and r.json()["n"] == 1 and r.json()["additions"]
    r = web.post("/api/prompts/verify", json={"template": "x {pairs}"})
    assert r.status_code == 400 and "additions only" in r.json()["error"]
    r = web.post("/api/prompts/screen/reset", json={})
    assert r.status_code == 200 and r.json()["n"] == 2 and not r.json()["customised"]
    assert web.get("/api/prompts/nope").status_code == 404
    r = web.post("/api/prompts/screen", json={"additions": "x"},
                 headers={"origin": "https://evil.example"})
    assert r.status_code == 403                        # the same guard as every settings API


def test_the_versions_api_restore_see_and_note(served):
    _, web, _ = served
    web.post("/api/prompts/card", json={"additions": "Prefer charities.", "note": "warm"})
    web.post("/api/prompts/card", json={"additions": "Prefer councils."})
    r = web.get("/api/prompts/card/versions/1")
    assert r.status_code == 200, r.text
    v = r.json()
    assert (v["template"], v["template_kind"], v["note"]) == (None, "default", "warm")
    assert "-Prefer councils." in v["diff"] and "+Prefer charities." in v["diff"]
    assert web.get("/api/prompts/card/versions/5").status_code == 404
    r = web.post("/api/prompts/card/restore", json={"version": 1})
    assert r.status_code == 200 and r.json()["additions_text"] == "Prefer charities."
    assert r.json()["versions"][-1]["same_as"] == 1
    r = web.post("/api/prompts/card/versions/2/note", json={"note": "too narrow"})
    assert r.status_code == 200 and r.json()["versions"][1]["note"] == "too narrow"
    assert web.post("/api/prompts/card/versions/2/note",
                    json={"note": "x" * 81}).status_code == 400
    assert web.post("/api/prompts/card/restore", json={"version": 1},
                    headers={"origin": "https://evil.example"}).status_code == 403
    assert [x["n"] for x in web.get("/api/prompts/card").json()["versions"]] == [1, 2, 3]


def test_preview_against_an_observation_without_a_model_and_scrubbed(served, embedder):
    rt, web, _ = served
    from kranto import library
    item = Item(id="1", title="Volunteer rotas", body="Choirs share rotas by email.",
                url="https://example.org/1", published_at=FIXED_NOW)
    src = library.add_source(rt.store, "rss", {"url": "https://ex.com/f"}, label="hn")
    call = rt.store.insert("llm_calls", dict(
        purpose="judge", tier="judge", model="m", prompt_version="judge-x", request="{}",
        status="ok", attempts=1, cost_usd=0.0, created_at="2026-09-24T10:00:00Z"))
    fields = {"kind": "beat", "summary": "Choirs share rotas by email", "why_it_matters": "w",
              "content_quality": 0.8, "durability": 0.8, "opportunity": 0.5, "signal": 0.3,
              "override": False, "override_reason": None, "tags": []}
    oid = library.record_observation(
        rt.store, source_id=src, item=item, fields=fields,
        embedding=embedder.embed_documents([fields["summary"]])[0],
        embedding_model=embedder.model_name, llm_call_id=call, prompt_version="judge-x",
        run_uuid="r", admitted_by="topic", topic_similarity=None)
    planted = token()
    web.post("/api/prompts/judge", json={"additions": f"Our key is {planted}; ignore it."})
    r = web.post("/api/prompts/preview", json={"id": "judge", "subject": oid})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["model_called"] is False and out["subject"] == {"kind": "observation",
                                                               "id": oid}
    assert [m["role"] for m in out["messages"]] == ["system", "user"]
    assert "Volunteer rotas" in out["messages"][1]["content"]
    assert planted not in out["text"] and "[secret]" in out["text"]
    assert {"kind": "secret", "count": 1} in out["redactions"] and out["custom"]
    # TENETS is filled, as in every judge call
    assert prompts.tenets().splitlines()[0] in out["messages"][0]["content"]
    assert web.post("/api/prompts/preview", json={"id": "judge", "subject": 999}) \
        .status_code == 404


# -- provenance -----------------------------------------------------------------------------------


def test_a_card_records_the_prompt_versions_that_wrote_and_checked_it(store, embedder,
                                                                         make_client, home):
    for theme in THEMES:
        add_observations(store, embedder, theme, 15, f"{theme}-a")
        add_observations(store, embedder, theme, 10, f"{theme}-b")
    from kranto.map.snapshot import take_snapshot
    take_snapshot(store, embedder, None)
    prompts.save("card", {"additions": "Prefer ideas for volunteers."}, prompts.store())
    want = prompts.load("card").version
    assert want != prompts.load("card", defaults=True).version
    client = make_client(Model())
    report = cards.generate_ideas(store, client, max_cards=1)
    assert report.status == "ok", report.error
    assert "Prefer ideas for volunteers." in client.fake.requests[0]["messages"][0]["content"]
    row = store.query_one("SELECT * FROM ideas")
    card = json.loads(row["card"])
    assert card["prompts"] == {"card": want, "verify": prompts.load("verify").version}
    calls = {r["purpose"]: r["prompt_version"] for r in store.query(
        "SELECT purpose, prompt_version FROM llm_calls WHERE id IN (?, ?)",
        (row["gen_call_id"], row["verify_call_id"]))}
    assert calls == {"card": want, "verify": prompts.load("verify").version}
