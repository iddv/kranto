"""A cub reaches the right half of the spine: ``objects.get`` still knows the kinds
of before wave 3, but a trend is not found since the radar left Kranto (cut 2), and a
build, a product and a project are not found since builds left, nor for a cub narrowed to
some topics; an unknown kind names the kinds."""

import pytest

from kranto.core import api, registry
from kranto.features.news import FEATURE as NEWS
from kranto.stored.cubs import Grants

from . import brbfake
from .test_web import rt  # noqa: F401 - fixture


def ctx(rt):  # noqa: F811
    return registry.context(rt, NEWS)


def test_a_trend_is_not_found_since_the_radar_left(rt):  # noqa: F811
    with pytest.raises(api.ReadError, match="no trend radar here"):
        api.objects_get(ctx(rt), {"kind": "trend", "id": "agent-memory"})
    assert api.objects_trends(ctx(rt), {}) == {"trends": [], "note": "no trend radar here"}


def test_a_build_a_product_and_a_project_are_not_available(rt, monkeypatch):  # noqa: F811
    """CUT: builds left Kranto. A cub's v1 read of a build, a product or a project is answered
    "not found" (its none), and the page is never asked, even one that still has the read."""
    def record(kind, key, home):
        raise AssertionError("the page's object_record was asked")
    brbfake.install(monkeypatch, object_record=record)
    for kind in ("build", "product", "project"):
        with pytest.raises(api.ReadError, match=f"no {kind}.*not available") as got:
            api.objects_get(ctx(rt), {"kind": kind, "id": "i235df527"})
        assert got.value.code == 404
    with pytest.raises(api.ReadError, match="the loop's"):
        api.objects_get(ctx(rt), {"kind": "build", "id": ""})


def test_an_unknown_kind_names_the_kinds(rt):  # noqa: F811
    with pytest.raises(api.ReadError, match="trend, build, product, project"):
        api.objects_get(ctx(rt), {"kind": "repo", "id": "x"})


def test_the_sdk_fake_host_serves_them_too():
    from pathlib import Path

    from bears_cub import HostError
    from bears_cub.testing import FakeHost
    host = FakeHost.from_folder(Path(__file__).parent / "fixtures" / "cubs" / "reader")
    host.library.add_object("build", "i235df527", {"state": "public", "title": "Logs <<<<"})
    got = host.handle("reads.get", {"name": "objects.get",
                                    "params": {"kind": "build", "id": "i235df527"}})
    assert got["kind"] == "build" and got["object"]["state"] == "public"
    assert "<<<<" not in got["object"]["title"]
    with pytest.raises(HostError):
        host.handle("reads.get", {"name": "objects.get", "params": {"kind": "project", "id": "p1"}})
    with pytest.raises(ValueError):
        host.library.add_object("repo", "x", {})


def test_a_narrowed_cub_reads_none_of_them(rt):  # noqa: F811
    from kranto.core.cubs import narrow

    class Host:
        store = rt.store
        cub = type("C", (), {"grants": Grants(reads_topics=[1])})()

        def feature_context(self):
            return ctx(rt)
    for kind in ("trend", "build", "product", "project"):
        with pytest.raises(api.ReadError, match=f"no such {kind}"):
            narrow.read(Host(), "objects.get", {"kind": kind, "id": "x"})
