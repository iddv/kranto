"""the console answers "why is Kranto degraded?" in one call.

On live (2026-10-29) the owner saw Degraded on the status bar and the console could not say why: no
tool carried the reason, which was worked out in the browser alone. Now the server works out the
word and one line why (``health.py``), ``api/activity`` passes it on, and ``kranto_incidents``
says it first, with the run's trace. A model run is not a CI test; the headless check is in the
track's report.
"""
from __future__ import annotations

from kranto.page.mcp import tools as T

from .test_nyu_words import client

LIVE = {"word": "Degraded", "tone": "amber",
        "reason": "The last read of your sources failed at 12:42: a safety filter at OpenRouter declined one "
                  "item",
        "at": "2026-10-29T12:42:41Z", "run": "3ad8f80e82ef43f481c2aa8905c68e48",
        "trace": "#/afk/3ad8f80e82ef43f481c2aa8905c68e48/trace"}


def test_kranto_incidents_says_why_kranto_is_degraded_in_one_read():
    c, seen = client({"health": LIVE, "incidents": [], "failing": []})
    got = T.call(c, "kranto_incidents", {})
    assert seen == ["/api/activity"]                              # one read, no file
    assert got["said"].startswith(
        "Kranto is Degraded (the status bar's word): The last read of your sources failed at 12:42: a "
        "safety filter at OpenRouter declined one item. The run's trace: #/afk/")
    assert got["health"] == {k: LIVE[k] for k in ("word", "reason", "at", "trace")}
    assert "why is Kranto degraded" in T.READS["kranto_incidents"][1]


def test_healthy_says_so_and_that_nothing_is_wrong():
    ok = {**LIVE, "word": "Healthy", "tone": "green", "reason": None, "run": None, "trace": None}
    got = T.call(client({"health": ok, "incidents": [], "failing": []})[0], "kranto_incidents", {})
    assert got["said"] == ("Kranto is Healthy (the status bar's word). Nothing is wrong now: no "
                           "incident and no failing kind.")


def test_a_kranto_before_the_reason_answers_as_before():
    got = T.call(client({"incidents": [], "failing": []})[0], "kranto_incidents", {})
    assert got["said"] == "Nothing is wrong now: no incident and no failing kind."
    assert got["health"] is None


def test_the_merged_activity_passes_health_on(tmp_path):
    """``api/activity`` (the page's merge of the server's) keeps the server's ``health``, typed; a
    the server before it answers None."""
    from kranto.page.ui import api
    from kranto.page.ui import types as TY

    from .app_common import make_home

    def afk(answer):
        return lambda method, path, body=None, owner=False: answer

    base = {"seq": 3, "running": [], "waiting": [], "next": [], "recent": [], "folded": [],
            "failing": [], "incidents": [], "quiet": "Nothing is running.", "scheduler": True,
            "now": "2026-10-29T12:43:00Z"}
    app = api.App(None, "fake", make_home(tmp_path).home)
    app.afk = afk({**base, "health": LIVE})
    out = app.activity({})
    assert TY.problems(out, TY.Activity) == []
    assert out["health"] == LIVE
    old = api.App(None, "fake", make_home(tmp_path / "old").home)
    old.afk = afk(base)
    assert old.activity({})["health"] is None
