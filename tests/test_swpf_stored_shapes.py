"""the sweep: each stored shape a writer can produce, as the writer stores
it, then the read that broke on it. The pages answer 200 and say what they can."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kranto import source_health
from kranto.store import iso, utcnow
from kranto.stored.runs import IngestSummary, summary_of
from kranto.stored.sources import Validation
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

# -- F2: a run whose summary is not a JSON object --------------------------------------------------


@pytest.mark.parametrize("summary", ["not json", "[]", "null", '"text"'])
def test_a_run_summary_that_is_not_an_object_reads_as_empty(rt, summary):  # noqa: F811
    now = iso(utcnow())
    for kind in ("ingest", "compact", "ideas"):
        rt.store.insert("runs", {"run_uuid": f"odd-{kind}", "kind": kind, "status": "ok",
                                 "started_at": now, "finished_at": now, "summary": summary})
    assert summary_of("compact", summary).to_dict() == {}
    assert summary_of("ingest", summary) == IngestSummary.empty()
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        for path in ("/api/health", "/api/today"):
            r = web.get(path)
            assert r.status_code == 200, (path, r.text)
        assert web.get("/api/today").json()["ingest"]["last"]["contributed"] is None


def test_run_summary_keeps_a_dict():
    assert summary_of("ingest", '{"contributed": 3}').contributed == 3
    assert summary_of("compact", '{"contributed": 3}').to_dict() == {"contributed": 3}
    assert summary_of("compact", None).to_dict() == {}
    assert summary_of("compact", {"a": 1}).to_dict() == {"a": 1}


# -- F8: a source added by hand, set back to proposed ----------------------------------------------


def test_a_hand_added_proposal_says_it_was_not_test_fetched():
    row = SimpleNamespace(status="proposed",
                          validation=Validation.from_dict({"items": 3, "checked": "manual"}))
    assert source_health._status(row, None) == ("proposed", "added by hand; not test-fetched")
    row.validation = Validation.from_dict({"items": 3, "preset": "x", "fields": {},
                                           "checked": "preview"})
    assert source_health._status(row, None) == ("proposed",
                                                "added from the catalog; not test-fetched")
    row.validation = Validation.from_dict({"status": "invalid", "error": "HTTP 404"})
    assert source_health._status(row, None) == ("proposed", "HTTP 404")
    row.validation = None
    assert source_health._status(row, None) == ("proposed", "test fetch did not finish")


# -- F3: a source's "how it is read" with params a reader did not expect ---------------------------


def test_describe_survives_an_arxiv_source_with_no_query_and_x_params_it_does_not_take():
    assert "search_query=" in source_health.describe("arxiv", {})["request"]
    how = source_health.describe("x", {"what": "home", "gone_key": 1})
    assert how["request"].startswith("https://api.x.com/2/users/<you>/")
