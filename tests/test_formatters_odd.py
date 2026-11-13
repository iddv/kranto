"""The formatters over every shape a stored value can take: strategies come from the contract types
(``stored.testing.strategy``), so a field added
to a type is generated on the next run. A formatter never raises and never shows ``None``,
``nan`` or a traceback; a status function always answers one of its words."""
from __future__ import annotations

import json
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from kranto import library, source_health
from kranto.activity import read as activity_read
from kranto.activity import words as W
from kranto.core import text
from kranto.stored.cards import Card, Dropped
from kranto.stored.runs import RunSummary
from kranto.stored.sources import Validation
from kranto.stored.testing import json_values, strategy
from kranto.web import ideas_api

SETTINGS = settings(max_examples=200, deadline=None,
                    suppress_health_check=[HealthCheck.too_slow])
SOURCE_STATUSES = (None, "proposed", "approved", "retired", "invalid", "imported", "unknown")
FETCH_STATES = ("ok", "paced", "failing", "needs_login")
WORDS = {"proposed", "retired", "invalid", "imported", "new", *FETCH_STATES}
WHEN = st.none() | st.just("2026-10-23T12:00:00Z") | st.text(max_size=20)


def clean(s: object) -> bool:
    """A line the page can show: text with no ``None``, ``nan`` or traceback in it."""
    return isinstance(s, str) and not any(w in s for w in ("None", "nan", "Traceback"))


rows = st.builds(library.SourceRow, id=st.integers(1, 10**6), kind=st.sampled_from(
    ("rss", "hackernews", "websearch", "x")), params=st.just({}), label=st.text(max_size=20),
    origin=st.sampled_from(("scout", "manual", "import")), status=st.sampled_from(
        SOURCE_STATUSES), validation=st.none() | strategy(Validation))
lasts = st.none() | st.fixed_dictionaries(
    {"state": st.sampled_from(FETCH_STATES), "fetched": st.integers(0, 500),
     "new": st.integers(0, 500)}, optional={"error": st.none() | st.text(max_size=40)})
plans = st.none() | st.fixed_dictionaries({}, optional={
    "retry_at": WHEN, "backoff_until": WHEN, "failing_runs": st.none() | st.integers(0, 9)})


@SETTINGS
@given(rows, lasts, plans)
def test_a_sources_status_line_is_one_of_its_words_and_never_says_none(row, last, plan):
    word, detail = source_health._status(row, last, plan)
    assert word in WORDS or word == row.status
    # an error's own words are the source's (scrubbed upstream): only ours are checked
    if not (last and last.get("error")) and not (row.validation and row.validation.error):
        assert clean(detail), (row, last, plan, detail)


@SETTINGS
@given(rows, st.lists(st.integers(1, 9), max_size=3))
def test_a_sources_group_is_a_word(row, linked):
    assert source_health._group(row, linked) in {
        "wildcard", "broad", *(s for s in SOURCE_STATUSES if s), "unknown"}


def _idea(card: Card, dropped: Dropped, i: int, origin: str | None) -> dict[str, Any]:
    return {"id": i, "title": card.title or "a card", "status": "shown", "score": 0.5,
            "created_at": "2026-10-23T12:00:00Z", "card": card, "origin": origin,
            "lineage_id": None, "dropped": dropped.items}


@SETTINGS
@given(strategy(Card), strategy(Dropped), st.integers(1, 10**6),
       st.sampled_from((None, "cluster", ideas_api.DISPATCH_ORIGIN)))
def test_a_card_record_is_built_from_any_card(card, dropped, i, origin):
    """``card_record`` over every card its type allows: no raise, JSON out (the API's answer),
    and the strings it shows from the card are never ``None``."""
    rec = ideas_api.card_record(_idea(card, dropped, i, origin), {}, None, None, {})
    json.dumps(rec)
    for k in ("one_liner", "smallest_v1", "thesis", "pattern", "where_now", "cheapest_test",
              "risks", "why_selected"):
        assert isinstance(rec[k], str), k


kinds = st.text(alphabet="abcdefghij._-", min_size=1, max_size=20)


@SETTINGS
@given(kinds, st.sampled_from(("done", "running", "failed", "waiting", "skipped", "x")),
       st.none() | st.text(max_size=20))
def test_activity_titles_are_text(kind, state, feature):
    assert clean(W.humanize(kind)) and clean(W.title_of(kind, state))
    assert isinstance(W.title_of(kind, state, feature), str)


@SETTINGS
@given(st.none() | st.text(max_size=200))
def test_plain_words_are_text_or_none(s):
    out = W.plain(s)
    assert out is None or isinstance(out, str)


@SETTINGS
@given(st.sampled_from(("ok", "degraded", "failed", "skipped")),
       st.none() | st.text(max_size=40) | json_values.map(json.dumps) | strategy(
           RunSummary).map(lambda v: v.to_json()),
       st.none() | st.text(max_size=40))
def test_why_a_run_stopped_reads_any_summary(status, raw, error):
    """``activity.read._summary`` then ``_why`` over any text a summary column can hold."""
    summary = activity_read._summary(raw)
    assert isinstance(summary, dict)
    why = activity_read._why(status, summary, error)
    assert why is None or isinstance(why, str)


@SETTINGS
@given(st.none() | st.text(max_size=200), st.text(min_size=1, max_size=20))
def test_text_helpers_never_raise(s, name):
    assert text.words(s) >= 0
    assert isinstance(text.possessive(name), str)
