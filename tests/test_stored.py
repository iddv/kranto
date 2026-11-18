"""The contracts for stored JSON: the
base every contract type derives from, its total parse, its one write, its odd values, and the
registry that says every JSON column the migrations declare has a contract."""
from __future__ import annotations

import dataclasses
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Literal

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kranto import stored
from kranto.stored import base
from kranto.stored.base import Iso, Stored
from kranto.stored.testing import column_text, json_values, strategy


# Types for these tests only: no COLUMN, so the registry is untouched.
@dataclass(frozen=True)
class Cost(Stored):
    check: float | None = None
    run: float | None = None


@dataclass(frozen=True)
class Measured(Stored):
    """The unmeasured column, in small: a similarity a writer may leave null."""

    JSON_NAMES = {"from_text": "from"}
    status: Literal["valid", "invalid", "unverified"] | None = None
    items: int = 0
    recent: int | None = None
    latest: Iso | None = None
    median_similarity: float | None = None
    role: Literal["core", "wildcard"] = "core"
    from_text: str | None = None
    fields: dict[str, str] = field(default_factory=dict)
    cites: list[dict[str, Any]] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    cost_usd: Cost | None = None
    history: list[Cost] = field(default_factory=list)
    flag: bool = False
    anything: Any = None
    extra: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def named_odd(cls) -> list[Measured]:
        return [cls(status="valid", median_similarity=None)]


@pytest.fixture(autouse=True)
def _fresh_problems():
    base.forget_problems()
    yield
    base.forget_problems()


# -- the unmeasured similarity, as a type --

def test_a_null_and_an_absent_key_both_read_as_none_and_never_as_the_default():
    """`.get(k, 0)` returned the stored None; the type says None for both, and nothing else."""
    assert Measured.parse('{"status": "valid", "median_similarity": null}').median_similarity \
        is None
    assert Measured.parse('{"status": "valid"}').median_similarity is None
    assert Measured.parse('{"median_similarity": 0.42}').median_similarity == 0.42
    assert Measured.parse('{"median_similarity": 1}').median_similarity == 1.0


def test_a_wrong_type_reads_as_the_default_and_is_noted_once(caplog):
    caplog.set_level(logging.WARNING, logger="kranto.stored.base")
    for _ in range(3):
        v = Measured.parse('{"median_similarity": "0.5", "items": true, "role": "boss"}')
        assert v is not None
        assert (v.median_similarity, v.items, v.role) == (None, 0, "core")
    keys = sorted(p.key for p in stored.problems_seen())
    assert keys == ["items", "median_similarity", "role"]
    assert len(caplog.records) == 3                        # once per signature, not per row
    assert "0.5" not in caplog.text                        # the value never reaches the log
    assert all(p.where == "Measured" for p in stored.problems_seen())


def test_null_empty_and_unreadable_text_are_none_to_parse_and_empty_to_load():
    for raw in (None, "", "  ", b"", "null"):
        assert Measured.parse(raw) is None
        assert Measured.load(raw) == Measured.empty()
    for raw in ("{not json", "[]", '"text"', "3"):
        assert Measured.parse(raw) is None
        assert Measured.load(raw) == Measured.empty()
    assert {p.expected for p in stored.problems_seen()} == {"JSON", "an object"}


def test_a_dict_a_writer_built_reads_the_same_as_its_text():
    d = {"status": "valid", "items": 3, "from": "a sentence", "cost_usd": {"check": 0.01}}
    assert Measured.from_dict(d) == Measured.parse(json.dumps(d))
    assert Measured.from_dict(None) == Measured.empty()
    v = Measured.from_dict(d)
    assert v.from_text == "a sentence" and v.cost_usd == Cost(check=0.01)


def test_lists_and_dicts_keep_what_reads_and_drop_what_does_not():
    v = Measured.load('{"tags": ["a", 3, "b", null], "fields": {"site": "x", "n": 2},'
                      ' "history": [{"check": 1}, "junk", {"run": "no"}]}')
    assert v.tags == ["a", "b"]
    assert v.fields == {"site": "x"}
    assert v.history == [Cost(check=1.0), Cost()]
    assert {p.key for p in stored.problems_seen()} >= {"tags[1]", "fields.n", "history[1]",
                                                        "history[2].run"}


def test_timestamps_are_kept_as_text_and_a_bad_one_reads_as_none():
    assert Measured.load('{"latest": "2026-10-23T16:44:10Z"}').latest == "2026-10-23T16:44:10Z"
    assert Measured.load('{"latest": "yesterday"}').latest is None


def test_a_bool_is_never_a_number_and_a_numeric_string_is_not_one():
    assert Measured.load('{"items": true, "recent": "4"}').items == 0
    assert Measured.load('{"recent": "4"}').recent is None
    assert Measured.load('{"items": 4.0}').items == 4


def test_unknown_keys_survive_a_rewrite():
    raw = '{"items": 2, "newer_key": {"a": 1}, "nulls": null}'
    v = Measured.load(raw)
    assert v.extra == {"newer_key": {"a": 1}, "nulls": None}
    assert json.loads(v.to_json()) == {"items": 2, "role": "core", "newer_key": {"a": 1},
                                       "nulls": None, "fields": {}, "cites": [], "tags": [],
                                       "history": [], "flag": False}


def test_to_json_leaves_a_none_out_sorts_its_keys_and_names_fields_by_their_json_key():
    v = Measured(items=1, from_text="t", median_similarity=None)
    text = v.to_json()
    d = json.loads(text)
    assert "median_similarity" not in d and d["from"] == "t" and "from_text" not in d
    assert list(d) == sorted(d)
    assert text == Measured.load(text).to_json()


def test_api_has_only_the_keys_that_are_set():
    v = Measured(status="valid", items=2, cost_usd=Cost(run=0.5), extra={"secret_shape": 1})
    assert v.api() == {"status": "valid", "items": 2, "role": "core", "fields": {}, "cites": [],
                       "tags": [], "cost_usd": {"run": 0.5}, "history": [], "flag": False}


def test_every_field_needs_a_default():
    @dataclass(frozen=True)
    class NoDefault(Stored):
        n: int

    with pytest.raises(TypeError, match="has no default"):
        NoDefault.load("{}")


def test_a_type_with_a_column_registers_itself():
    @dataclass(frozen=True)
    class Registered(Stored):
        COLUMN = ("test_table", "test_column")
        n: int = 0

    try:
        assert stored.contract_for("test_table", "test_column") is Registered
        assert Registered.where() == "test_table.test_column"
    finally:
        del stored.COLUMNS[("test_table", "test_column")]


# -- odd values --

def test_odd_values_null_every_optional_field_empty_every_list_and_use_every_word():
    odd = Measured.odd()
    for f in dataclasses.fields(Measured):
        if f.name == "extra":
            continue
        values = [getattr(o, f.name) for o in odd]
        hint = Measured._fields()[[x.name for x in Measured._fields()].index(f.name)].tp
        if base._strip_optional(hint)[1]:
            assert None in values, f.name
            assert any(v is not None for v in values), f.name
        if isinstance(getattr(Measured.full(), f.name), (list, dict)):
            assert any(v in ([], {}) for v in values), f.name
    assert {o.status for o in odd} == {None, "valid", "invalid", "unverified"}
    assert {o.role for o in odd} == {"core", "wildcard"}
    assert {o.items for o in odd} >= {0, base.BIG_INT}
    assert Measured(status="valid", median_similarity=None) in odd     # the named case
    for o in odd:                                                       # each one round-trips
        assert Measured.load(o.to_json()) == o


# -- properties --

@settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
@given(strategy(Measured))
def test_parse_of_to_json_is_the_object(v):
    assert Measured.parse(v.to_json()) == v


@settings(max_examples=300)
@given(column_text)
def test_parse_never_raises_on_any_text(raw):
    got = Measured.parse(raw)
    assert got is None or isinstance(got, Measured)
    assert isinstance(Measured.load(raw), Measured)


@settings(max_examples=300)
@given(st.dictionaries(st.sampled_from(["status", "items", "recent", "latest",
                                        "median_similarity", "role", "from", "fields", "cites",
                                        "tags", "cost_usd", "history", "flag", "x"]),
                       json_values, max_size=8))
def test_parse_never_raises_on_any_value_under_any_key(d):
    got = Measured.parse(json.dumps(d))
    assert isinstance(got, Measured)


# -- every registered contract --

stored.load_all()
REGISTERED = sorted({*stored.COLUMNS.values(), *stored.SETTINGS.values(), *stored.FILES.values(),
                     *stored.runs.KINDS.values()},
                    key=lambda t: (t.where(), t.__name__))


@pytest.mark.parametrize("cls", REGISTERED, ids=lambda t: t.__name__)
def test_every_registered_contract_round_trips_and_never_raises(cls):
    @settings(max_examples=200, suppress_health_check=[HealthCheck.too_slow])
    @given(strategy(cls))
    def round_trip(v):
        assert cls.parse(v.to_json()) == v

    @settings(max_examples=200)
    @given(column_text)
    def total(raw):
        got = cls.parse(raw)
        assert got is None or isinstance(got, cls)

    round_trip()
    total()


@pytest.mark.parametrize("cls", REGISTERED, ids=lambda t: t.__name__)
def test_every_registered_contracts_odd_values_cover_its_fields(cls):
    odd = cls.odd()
    for f in cls._fields():
        values = [getattr(o, f.name) for o in odd]
        if base._strip_optional(f.tp)[1]:
            assert None in values and any(v is not None for v in values), f.name
    for o in odd:
        assert cls.load(o.to_json()) == o


# -- the registry --

def test_json_columns_reads_the_schema():
    cols = stored.json_columns()
    assert ("sources", "validation") in cols and ("runs", "summary") in cols
    assert ("runs", "error") not in cols                    # plain text, though its name is not
    # migrations only add. cub_calls.detail, cub_orders.detail and news_briefs.quiet hold text,
    # migration 30's frozen tables are left out, and so are the tables of the features that left
    # Kranto (kept, read by kranto archive only)
    assert len(cols) >= 50 and not stored.frozen_tables() & {t for t, _ in cols}
    assert ("news_briefs", "quiet") not in cols
    assert not [t for t, _ in cols if t.startswith(stored.RETIRED_TABLES)]


def test_every_json_column_has_a_contract():
    """A migration that adds a JSON column adds its contract: a type with its COLUMN in
    kranto.stored (a feature's in its stored.py), or an OPAQUE entry saying why not."""
    missing = [f"{t}.{c}" for t, c in stored.json_columns()
               if (t, c) not in stored.COLUMNS and (t, c) not in stored.OPAQUE]
    assert not missing, "JSON columns with no contract in kranto.stored: " + ", ".join(missing)
