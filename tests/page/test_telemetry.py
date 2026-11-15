"""The page's usage counters: its part of the allow-list is
nodes.json's pages and the origins; with no sink nothing is recorded. The registry's action and
build lines left with the factory (CUT)."""
import json
from pathlib import Path

from kranto.page import telemetry

ROOT = Path(__file__).resolve().parents[2]


def test_the_node_enum_is_nodes_json():
    nodes = json.loads((ROOT / "src/kranto/page/ui/web/src/lib/nodes.json").read_text())
    want = list(dict.fromkeys(n["node"] for n in nodes if n.get("node")))
    assert telemetry.schema()["enums"]["node"] == want


def test_the_factorys_lines_and_enums_are_gone():
    s = telemetry.schema()
    assert "action" not in s["lines"] and "build" not in s["lines"]
    assert not {"action", "check", "stage", "build_outcome"} & set(s["enums"])
    assert not hasattr(telemetry, "action")


def test_every_string_field_is_an_enum():
    s = telemetry.schema()
    for line, fields in s["lines"].items():
        for k, spec in fields.items():
            if spec["type"] == "str":
                assert spec["enum"] in s["enums"], (line, k)


def test_no_sink_records_nothing():
    telemetry.set_sink(None)
    telemetry.record("view", node="news")                  # nothing to call: no error


def test_a_sink_that_raises_is_ignored():
    def boom(name, **f):
        raise RuntimeError("x")
    telemetry.set_sink(boom)
    try:
        telemetry.record("view", node="news")
    finally:
        telemetry.set_sink(None)


def test_a_sink_gets_the_line():
    got = []
    telemetry.set_sink(lambda name, **f: got.append((name, f)))
    try:
        telemetry.record("view", node="news")
    finally:
        telemetry.set_sink(None)
    assert got == [("view", {"node": "news"})]
    assert telemetry.origin_of("agent:rc") == "agent" and telemetry.origin_of("ui") == "ui"


def test_facts_are_numbers_and_modes(tmp_path):
    assert telemetry.facts(tmp_path) == {}
    (tmp_path / "loop.yaml").write_text("term:\n  enabled: true\n")
    out = telemetry.facts(tmp_path)
    assert out == {"settings.term_enabled": True}
    assert all(isinstance(v, bool | int | str) for v in out.values())
