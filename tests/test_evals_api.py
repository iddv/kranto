"""GET /api/evals and /api/evals/{name}: Settings › System › Evaluation reads
the last ten scorecards and "Live this month"; the page is read-only."""

from __future__ import annotations

from kranto.evals import scorecard

from .test_web import rt, web  # noqa: F401 - fixtures


def card(n: int, **kw) -> dict:
    c = scorecard.new("watching", set_version="v1", model="m", split="all", budget_usd=1.0, **kw)
    c["metrics"] = [scorecard.metric("screen_agree", "screen agrees with the recorded verdict",
                                     n, 60, step="screen"),
                    scorecard.info("list_usd", "its replies at list prices", 0.13)]
    c["noise"] = {"screen": 0.9}
    c["items"] = {"screen": [{"id": "screen-1", "want": True, "got": True}]}
    c["cost_usd"] = 0.0
    return c


def test_the_list_the_one_and_live_this_month(rt, web):  # noqa: F811
    home = rt.cfg.root
    first = scorecard.finish(home, card(51))
    worse = scorecard.finish(home, card(30))
    d = web.get("/api/evals").json()
    assert [s["name"] for s in d["scorecards"]] == [worse["file"].removesuffix(".json"),
                                                    first["file"].removesuffix(".json")]
    top = d["scorecards"][0]
    assert top["headline"]["num"] == 30 and top["headline"]["baseline"] == 0.85
    assert top["flags"] == ["REGRESSION"] and top["list_usd"] == 0.13
    assert d["total"] == 2 and d["live"]["month"] and d["live"]["eval_calls"] == 0
    one = web.get(f"/api/evals/{top['name']}").json()
    assert one["name"] == top["name"] and "items" not in one
    assert one["metrics"][0]["flag"] == "REGRESSION"
    assert web.get("/api/evals/nope").status_code == 404
    assert web.get("/api/evals/..%2Fetc").status_code == 404


def test_no_scorecard_yet(web):  # noqa: F811
    d = web.get("/api/evals").json()
    assert d["scorecards"] == [] and d["total"] == 0 and "kranto eval" in d["run"]


def test_kranto_status_says_the_last_eval(tmp_path):
    from kranto.launcher import evals_line
    assert evals_line(tmp_path) is None
    scorecard.finish(tmp_path, card(51))
    assert evals_line(tmp_path) == ("last run " + card(1)["date"] + ": watching on set v1 with "
                                    "m, screen agrees with the recorded verdict 51/60; nothing "
                                    "flagged (1 scorecards)")
