"""A theme carded on request (L11, the owner's D-1 of 2026-10-22): one card on the
theme the owner names, outside the daily selection, one card call and its check; the same
evidence is not carded twice; a theme that is not on the map is refused; the daily run is not
skipped because of it; the page's route starts it in the background."""

import time

from kranto.ideate import cards

from .conftest import web_client
from .test_ideate import Model, mapped  # noqa: F401 - fixture


def lineage(store):
    return store.query_one("SELECT lineage_id FROM clusters "
                           "ORDER BY snapshot_id DESC, cluster LIMIT 1")["lineage_id"]


def test_one_card_on_the_theme_asked_for(mapped, make_client):  # noqa: F811
    client = make_client(Model(card=None))
    lin = lineage(mapped)
    report = cards.card_theme(mapped, client, lin)
    assert report.status == "ok" and report.shown == 1, report.error
    [idea] = cards.list_ideas(mapped)
    assert idea["lineage_id"] == lin and idea["origin"] == cards.ASKED
    assert "the owner asked for a card on this theme" in (idea["card"].why_selected or "")
    assert [r["purpose"] for r in mapped.query(
        "SELECT purpose FROM llm_calls WHERE purpose != 'judge' ORDER BY id")] == ["card", "verify"]
    # the same evidence again: not carded twice, no call
    calls = len(client.fake.requests)
    again = cards.card_theme(mapped, client, lin)
    assert again.already_carded == 1 and len(client.fake.requests) == calls
    # the daily run decides as it would have: a first run on this map runs, a second does not
    assert cards.generate_ideas(mapped, client, max_cards=1).status != "skipped"
    cards.card_theme(mapped, client, lin)
    later = cards.generate_ideas(mapped, client, max_cards=1)
    assert later.status == "skipped" and "has not changed" in later.error


def test_a_theme_not_on_the_map_is_refused(mapped, make_client):  # noqa: F811
    client = make_client(Model())
    report = cards.card_theme(mapped, client, "no-such-lineage")
    assert report.status == "skipped" and "no theme" in report.error
    assert client.fake.requests == []
    run = mapped.query_one("SELECT summary, error FROM runs WHERE kind = 'ideas' "
                           "ORDER BY finished_at DESC LIMIT 1")
    assert "no-such-lineage" in run["summary"] and "no theme" in run["error"]


def test_the_page_starts_it_in_the_background(mapped, make_client, tmp_path):  # noqa: F811
    from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
    from kranto.runtime import open_runtime
    from kranto.web.app import create_app

    from .conftest import llm_config
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig())
    rt = open_runtime(cfg, store=mapped, llm=make_client(Model()))
    web = web_client(create_app(rt))
    lin = lineage(mapped)
    r = web.post(f"/api/themes/{lin}/card", json={})
    assert r.status_code == 202 and r.json() == {"started": True, "lineage": lin}
    for _ in range(100):
        if cards.list_ideas(mapped):
            break
        time.sleep(0.05)
    assert cards.list_ideas(mapped)[0]["lineage_id"] == lin
    assert web.post("/api/themes/bad%20id!/card", json={}).status_code == 400
