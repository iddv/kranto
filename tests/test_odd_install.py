"""The odd install: every route the
page reads answers on a library generated from what the writers can store (every nullable field
null, every optional path taken), not only on one like the owner's. A 500, or a row contained as
unreadable, on the fixture is a failure: containment is the net for someone's real data, not a
pass here."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from kranto import config as config_mod
from kranto import library, source_health, stored
from kranto.embed import StubEmbedder
from kranto.runtime import open_runtime
from kranto.store import Store
from kranto.stored.sources import Validation
from kranto.web.app import create_app

from .conftest import web_client
from .test_web_types import T, _key, no_logins, problems  # noqa: F401  (no_logins: autouse)

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("odd_install",
                                               ROOT / "scripts" / "dev" / "odd_install.py")
odd_install = importlib.util.module_from_spec(_spec)
sys.modules["odd_install"] = odd_install          # its dataclasses look their module up
_spec.loader.exec_module(odd_install)

# The server-rendered pages; the API's reads are what the post-update self-check reads
# (``/api/selfcheck/paths``: every GET with no id, every topic's and source's page, each
# feature's reads), so the fixture and ``kranto doctor --routes`` read the same list.
PAGES = ["/", "/library", "/topics", "/health", "/ideas", "/rollups", "/map", "/clusters"]


@pytest.fixture(scope="module", params=odd_install.VARIANTS)
def home(request, tmp_path_factory):
    path = tmp_path_factory.mktemp(f"odd-{request.param}")
    manifest = odd_install.build(path, request.param)
    return path, manifest


@pytest.fixture
def client(home):
    path, _ = home
    cfg = config_mod.load(path, dotenv=False)         # the default config, as an install has
    rt = open_runtime(cfg, store=Store.open(cfg.db_path), embedder=StubEmbedder())
    with web_client(create_app(rt), "http://127.0.0.1:8765") as c:
        yield c
    rt.store.close()


def unreadable_rows(value, where="$") -> list[str]:
    """Where an answer holds a row contained as unreadable (SAFE's A3 marker)."""
    if isinstance(value, dict):
        out = [where] if "unreadable" in value else []
        for k, v in value.items():
            out += unreadable_rows(v, f"{where}.{k}")
        return out
    if isinstance(value, list):
        return [p for i, v in enumerate(value) for p in unreadable_rows(v, f"{where}[{i}]")]
    return []


def test_every_route_answers_on_the_odd_install(home, client):
    _, manifest = home
    listed = client.get("/api/selfcheck/paths").json()["paths"]
    paths = PAGES + [p for p in listed if not p.startswith("/brb")]
    assert len(paths) > 40 + len(manifest["sources"]) * (manifest["variant"] == "odd")
    for i in [*manifest["topics"].values(), *manifest["sources"].values()]:
        assert f"/api/topics/{i}" in paths or f"/api/sources/{i}" in paths
    failed = []
    for path in paths:
        r = client.get(path)
        if r.status_code >= 500:
            failed.append(f"{path}: {r.status_code} {r.text[:300]}")
        elif r.headers.get("content-type", "").startswith("application/json"):
            rows = unreadable_rows(r.json())
            if rows:
                failed.append(f"{path}: rows contained as unreadable at {', '.join(rows[:5])}")
    assert not failed, f"{manifest['variant']}:\n" + "\n".join(failed)


def test_the_odd_install_holds_the_unmeasured_row(home):
    path, manifest = home
    if manifest["variant"] != "odd":
        pytest.skip("only the odd variant has the unmeasured row")
    store = Store.open(path / "data" / "kranto.db")
    try:
        rows = {s.id: s for s in library.list_sources(store)}
        described = rows[manifest["sources"]["described"]]
        assert described.validation is not None
        assert described.validation.status == "valid"
        assert described.validation.median_similarity is None
        assert described.validation.topic_id is None
        assert rows[manifest["sources"]["imported"]].validation is None
        # the status line leaves the similarity out, never "sim None" or a raise
        status, detail = source_health._status(described, None)
        assert status == "proposed" and "sim" not in detail and "None" not in detail
    finally:
        store.close()


def test_every_odd_value_of_a_column_type_is_in_the_odd_install():
    """Each type the cases name has its derived odd values written: a field added to a type is
    in the next library with no edit to the generator."""
    named = {t for case in odd_install.CASES for t in case.types}
    assert Validation in named
    for t in named:
        assert any(issubclass(t, c) for c in (*stored.COLUMNS.values(),
                                              *stored.SETTINGS.values(),
                                              *stored.FILES.values())), t


def test_the_manifest_says_what_was_written(home):
    path, manifest = home
    on_disk = json.loads((path / "manifest.json").read_text())
    assert on_disk == manifest
    assert len(manifest["generator"]) == 16
    if manifest["variant"] == "odd":
        assert len(manifest["cases"]) == len(odd_install.CASES)
        assert manifest["counts"]["sources"] >= len(Validation.odd())
    elif manifest["variant"] == "projects":
        assert manifest["counts"]["topics"] == 2 and manifest["counts"]["sources"] == 3
    elif manifest["variant"] == "upgraded":
        # every version of the chain wrote its topic and its sources, and the last migration ran
        assert [s["tag"] for s in manifest["steps"]] == list(odd_install.CHAIN)
        assert manifest["counts"]["topics"] >= len(odd_install.CHAIN)
        assert all("topic" in s["wrote"] for s in manifest["steps"])
    else:
        assert manifest["counts"] == {"topics": 0, "sources": 0, "runs": 0}


def test_api_types_hold_on_odd_install(home, client):
    """``test_web_types``' TypedDict check on the fixture's answers: a number that comes back
    null on an odd row is a type lie the page would trip on."""
    _, manifest = home
    listed = client.get("/api/selfcheck/paths").json()["paths"]
    typed = [p for p in listed if _key(p) in T.RETURNS]
    assert len(typed) > 20
    failed = []
    for path in typed:
        r = client.get(path)
        if path == "/api/map" and r.status_code == 404:
            failed += problems(r.json(), T.MapNotYet, path)
        elif r.status_code == 200:      # a 4xx asks for a query: the route test reads 5xx
            failed += problems(r.json(), T.RETURNS[_key(path)], path)
    assert not failed, f"{manifest['variant']}:\n" + "\n".join(failed[:40])


def test_every_stored_type_has_an_odd_case():
    """Every registered contract (a column's, a setting's, a file's) is named by a case, so
    its odd values are in the odd install."""
    stored.load_all()
    named = {t for case in odd_install.CASES for t in case.types}
    registered = {*stored.COLUMNS.values(), *stored.SETTINGS.values(), *stored.FILES.values()}
    assert not {t.__name__ for t in registered - named}


def test_fixture_manifest_matches_generator():
    """The committed upgraded home was made by today's chain and per-version writer
    (odd_install.upgraded_hash: CHAIN and scripts/dev/odd_old.py). Changed either? Run
    ``scripts/dev/odd_install.py --upgrade --out tests/fixtures/odd_install/upgraded`` (the
    weekly fixtures job does it and keeps the result) and commit the copy. This tree's
    migrations and contracts need no new copy: the variant is opened by them."""
    manifest = json.loads((odd_install.UPGRADED / "manifest.json").read_text())
    assert manifest["generator"] == odd_install.upgraded_hash()
    assert manifest["chain"] == list(odd_install.CHAIN)
