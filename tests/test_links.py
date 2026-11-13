"""Links back to the instance (phase 1f): delivered messages, the Atom feed and form
redirects point into the page (``/#/...``) when the page is mounted, and to
the server's own pages otherwise."""

from dataclasses import replace
from xml.etree import ElementTree

import pytest

from kranto import delivery, links, notify
from kranto.config import (
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.links import Links
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from .conftest import chat_response, llm_config, web_client
from .test_brb_mount import fake_api  # noqa: F401 - the fixture

BASE = "http://127.0.0.1:8765"
NS = {"a": "http://www.w3.org/2005/Atom"}


def message(kind="strike", mid=7):
    return {"id": mid, "kind": kind, "title": "t", "body": "b", "links": [],
            "evidence_ids": [3, 4]}


def test_link_table():
    kranto, own = Links(True, BASE + "/"), Links(False, BASE)
    assert kranto.observation(3) == f"{BASE}/#/library/o/3"
    assert own.observation(3) == f"{BASE}/obs/3"
    assert kranto.idea(2) == f"{BASE}/#/ideas/card:2"
    assert own.idea(2) == f"{BASE}/ideas#idea-2"
    assert kranto.message(7) == f"{BASE}/#/settings/health?message=7"
    assert own.message(7) == f"{BASE}/health#message-7"
    assert kranto.grade_message(7) == kranto.message(7)
    assert own.grade_message(7) == f"{BASE}/grade/message/7"
    assert Links(True).health("a b&c") == "/#/settings/health?msg=a+b%26c"
    assert Links(False).cluster(4, "no map") == "/clusters?msg=no+map#c4"
    assert Links(True).cluster(4) == "/#/library/clusters/4"
    assert Links(False).map() == "/map?started=1" and Links(True).map() == "/#/library/map"


@pytest.mark.parametrize("kranto, obs, grade, health", [
    (True, f"{BASE}/#/library/o/3", f"{BASE}/#/settings/health?message=7",
     f"{BASE}/#/settings/health?message=8"),
    (False, f"{BASE}/obs/3", f"{BASE}/grade/message/7", f"{BASE}/health#message-8"),
])
def test_delivered_messages_link_into_the_ui_that_is_served(kranto, obs, grade, health):
    _, body = delivery.compose(message(), BASE, kranto=kranto)
    assert obs in body and f"Grade it: {grade}" in body
    assert "/obs/" not in body if kranto else "/#/" not in body
    _, body = delivery.compose(message("alarm", 8), BASE, kranto=kranto)
    assert body.rstrip().endswith(health)


def test_kranto_mounted_needs_the_setting_and_the_package(monkeypatch):
    cfg = Config(root=".", llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig())
    found = {"kranto.page": object()}
    monkeypatch.setattr(links.importlib.util, "find_spec", lambda name: found.get(name))
    assert not links.kranto_mounted(cfg)
    on = replace(cfg, builds=BuildsConfig(enabled=True), brb=BrbConfig(enabled=True))
    assert links.kranto_mounted(on)
    found.clear()
    assert not links.kranto_mounted(on)


def test_deliveries_use_the_kranto_links_when_enabled(store, monkeypatch, tmp_path):
    sent = []

    class Apprise:
        def add(self, url):
            return True

        def notify(self, title, body):
            sent.append(body)
            return True

    module = type("apprise", (), {"Apprise": Apprise})
    notify.emit(store, "strike", "a strike", "body", dedup_key="s", origin="test",
                evidence_ids=[5])
    target = "json://127.0.0.1/" + "hook"
    monkeypatch.setenv("KRANTO_TEST_NOTIFY_URLS", target)
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                 ingest=IngestConfig(), map=MapConfig(), builds=BuildsConfig(enabled=True),
                 brb=BrbConfig(enabled=True))
    cfg = replace(cfg, notify=replace(cfg.notify, urls_env="KRANTO_TEST_NOTIFY_URLS",
                                      base_url=BASE))
    monkeypatch.setattr(links.importlib.util, "find_spec", lambda name: object())
    report = delivery.deliver_pending(store, cfg, apprise_module=module)
    assert report.sent == 1
    assert f"{BASE}/#/library/o/5" in sent[0] and "/obs/5" not in sent[0]


def _feed_hrefs(rt):
    with web_client(create_app(rt), BASE) as web:
        root = ElementTree.fromstring(web.get("/feed.xml").content)
    [entry] = root.findall("a:entry", NS)
    return {link.get("rel") + ":" + link.get("href") for link in entry.findall("a:link", NS)}


def test_atom_feed_links_into_the_kranto_ui_when_mounted(tmp_path, store, embedder,
                                                        make_client, fake_api):  # noqa: F811
    notify.emit(store, "alarm", "an alarm", "body", dedup_key="a", origin="test",
                evidence_ids=[5])
    llm = make_client(lambda b: chat_response("{}"))
    for enabled, want in ((True, {f"alternate:{BASE}/#/settings/health?message=1",
                                  f"related:{BASE}/#/library/o/5"}),
                          (False, {f"alternate:{BASE}/health#message-1",
                                   f"related:{BASE}/obs/5"})):
        cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=1),
                     ingest=IngestConfig(), map=MapConfig(),
                     builds=BuildsConfig(enabled=enabled),
                     brb=BrbConfig(enabled=enabled, root=str(tmp_path / "tasks")))
        rt = open_runtime(cfg, store=store, embedder=embedder, llm=llm)
        assert _feed_hrefs(rt) == want
