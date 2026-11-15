import json
from pathlib import Path

import httpx
import numpy as np
import pytest
import yaml

from kranto import doctor, library
from kranto.bundle import export_bundle
from kranto.config import BudgetConfig, Config, IngestConfig, MapConfig
from kranto.map.snapshot import take_snapshot
from kranto.packs import load_pack
from kranto.sources import HTTP

from .conftest import llm_config
from .test_map import THEMES, add_observations

PACKS = Path(__file__).parents[1] / "examples" / "packs"


def feeds(request):
    if "missing" in str(request.url):
        return httpx.Response(404)
    return httpx.Response(200, content=b"<rss><channel><title>Feed</title><item><title>x"
                                       b"</title><guid>1</guid></item></channel></rss>")


def test_example_packs_are_well_formed(store, embedder):
    http = HTTP(transport=httpx.MockTransport(feeds), resolver=lambda h: ["93.184.216.34"])
    for pack in sorted(PACKS.glob("*.yaml")):
        load_pack(store, embedder, http, pack, check=False)
    names = {t.name for t in library.active_topics(store)}
    assert names == {"Local-first software", "Energy access", "Lab tools"}
    assert len(library.list_sources(store, "approved")) >= 15


def test_example_packs_ship_without_reddit_sources():
    # Reddit's Responsible Builder Policy; see RESPONSIBLE_USE.md.
    for pack in sorted(PACKS.glob("*.yaml")):
        data = yaml.safe_load(pack.read_text())
        found = list(data.get("sources") or [])
        for topic in data.get("topics") or []:
            found += topic.get("sources") or []
        assert found, pack.name
        assert all(s["kind"] != "reddit" for s in found), pack.name


def test_pack_skips_sources_that_fail_and_is_idempotent(store, embedder, tmp_path):
    pack = tmp_path / "p.yaml"
    pack.write_text("topics:\n  - name: T\n    description: d\n    sources:\n"
                    "      - {kind: rss, value: 'https://ex.com/ok'}\n"
                    "      - {kind: rss, value: 'https://ex.com/missing'}\n"
                    "      - {kind: twitter, value: '@x'}\n")
    http = HTTP(transport=httpx.MockTransport(feeds), resolver=lambda h: ["93.184.216.34"])
    report = load_pack(store, embedder, http, pack)
    assert report.added == ["Feed"]
    assert len(report.failed) == 2
    load_pack(store, embedder, http, pack)
    assert len(library.active_topics(store)) == 1
    assert len(library.list_sources(store)) == 1
    with pytest.raises(ValueError):
        bad = tmp_path / "bad.yaml"
        bad.write_text("nothing: here\n")
        load_pack(store, embedder, http, bad)


def cfg(tmp_path, **llm):
    return Config(root=tmp_path, llm=llm_config(base_url="https://openrouter.ai/api/v1", **llm),
                  budget=BudgetConfig(monthly_usd=5), ingest=IngestConfig(), map=MapConfig())


def provider(key_status=200, models=("judge-model", "reason-model")):
    def handler(request):
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": m} for m in models]})
        if request.url.path.endswith("/key"):
            return httpx.Response(key_status, json={"data": {"limit_remaining": 4.5}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def by_name(checks):
    return {c.name: c for c in checks}


def test_doctor_happy_path(tmp_path, store, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    checks = by_name(doctor.run(cfg(tmp_path), store, transport=provider(),
                                check_embedder=False))
    assert checks["api key"].status == doctor.OK and "4.50" in checks["api key"].detail
    assert checks["judge model"].status == doctor.OK
    assert checks["sources"].status == doctor.WARN


def test_doctor_catches_dead_key_and_unknown_model(tmp_path, store, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    checks = by_name(doctor.run(cfg(tmp_path), store, check_embedder=False,
                                transport=provider(key_status=401, models=("judge-model",))))
    assert checks["api key"].status == doctor.FAIL
    assert checks["reason model"].status == doctor.FAIL
    monkeypatch.delenv("TEST_KEY")
    checks = by_name(doctor.run(cfg(tmp_path), store, transport=provider(),
                                check_embedder=False))
    assert checks["api key"].status == doctor.FAIL


def test_doctor_flags_missing_prices(tmp_path, store, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "k")
    checks = by_name(doctor.run(cfg(tmp_path, cost_source="table"), store,
                                transport=provider(), check_embedder=False))
    assert checks["pricing"].status == doctor.FAIL


def test_bundle_export(store, embedder, tmp_path):
    with pytest.raises(ValueError):
        export_bundle(store, tmp_path / "none")
    for theme in THEMES:
        add_observations(store, embedder, theme, 12, f"{theme}-a")
    take_snapshot(store, embedder, None)
    manifest = export_bundle(store, tmp_path / "bundle")
    assert manifest["format"] == "kranto-bundle" and manifest["stability"] == "unstable"
    obs = json.loads((tmp_path / "bundle" / "observations.json").read_text())
    matrix = np.frombuffer((tmp_path / "bundle" / "embeddings.bin").read_bytes(),
                           dtype="<f4").reshape(len(obs), manifest["dim"])
    assert len(obs) == manifest["n"] == 36
    assert np.allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-5)
    clusters = json.loads((tmp_path / "bundle" / "clusters.json").read_text())
    assert sum(c["size"] for c in clusters) == 36
    assert "source_totals" not in manifest["quality"]
