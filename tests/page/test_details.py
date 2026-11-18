"""Details (the owner's D-9): the record behind a row or a dialog is
one read, ``GET /brb/api/details?sel=``, and the console's ``kranto_details`` answers that same
record, so the drawer and the tool never disagree. For a build, an idea, an idea card, a cub's
ask and an assistant's prepared item the drawer's read and the tool give the same record, in the
design's groups, ending with the call that reads it; a stored value of an unexpected shape (a
null, a list, a dict, a missing key) never breaks a record."""
from __future__ import annotations

import pytest

from kranto.page.mcp import tools as T
from kranto.page.ui import details as D
from kranto.page.ui.http import HttpError

BUILD = {"key": "sidedoor", "title": "sidedoor", "status": "held", "desc": "Delivered; the release gate would hold it",
         "reason": "safe_defaults: red: The README's quick-start commands fail.", "updated": 1792100000, "idea": "i01",
         "fail": None, "gate": {"verdict": "held", "checks": [{"name": "safe_defaults", "ok": False}]}, "tokens": {"in": 1000, "out": 20},
         "cost_usd": None, "repo": None}
PREPARED = {"uuid": "6dbbc192", "verb": "b.factory_issue", "title": "File a Kranto issue", "by_words": "by Claude Code",
            "page": "#/needs", "fields": {"issue": "The Send dialog asks about an expired draft", "labels": ["feature"], "area": None},
            "created_at": "2026-10-29T18:54:00Z", "state": "open", "says": "A new issue on iddv/kranto.", "locked": False}
ASK = {"question": "Send this week's issue?", "verb": "Send now", "readback": [["Subject", "This week"], ["To", "12 readers"]],
       "created_at": "2026-10-22T09:00:00Z", "expires_at": "2026-10-29T09:00:00Z", "cub": "newsletter", "mode": "practice",
       "history": [{"state": "waiting", "created_at": "2026-10-22T09:00:00Z", "note": None}], "open": True}
CARD = {"number": 7, "title": "Clinic schedules", "thesis": "Clinics keep schedules on paper.", "score": 0.31,
        "citations": [{"title": "A post", "url": "https://example.org/a"}, None, "plain"], "topics": [{"id": 2, "name": "Health"}],
        "tickets": [{"id": 41, "cub": "newsletter", "title": "Send this week's issue?", "state": "dry", "created_at": "2026-10-22T09:00:00Z"}, None]}
IDEA = {"id": "i01", "title": "Clinic schedules", "status": "open", "source": "kranto", "created": 1792100000, "card": {"number": 7}}


class FakeApp:
    """The page's App as details.record reads it: the builds, a loop idea, the server's JSON API"""

    def builds(self):
        return [BUILD, {"key": "other", "title": None, "status": None}]

    def loop_idea(self, iid):
        return IDEA if iid == "i01" else None

    def afk(self, method, path, body=None, owner=False):
        assert method == "GET", "Details only reads"
        answers = {"/api/prepared": {"prepared": [PREPARED, {"uuid": "x", "fields": None}]},
                   "/api/tickets/41/ask": ASK, "/api/ideas/7": CARD, "/api/sources/9": {"source": {"label": "HN", "status": "ok", "topics": None}}}
        if path not in answers:
            raise HttpError(404, "not found")
        return answers[path]


def client(app):
    """the console's client, answered by the same function the drawer's route calls"""
    def get(path, q=None):
        assert path == "/api/details", path
        try:
            return 200, D.record(app, q or {})
        except HttpError as e:
            return e.code, {"error": e.message if hasattr(e, "message") else str(e)}
    return T.Client(get=get, post=lambda p, b: (405, {}))


@pytest.mark.parametrize("sel,kind", [("card:7", "idea"), ("ask:41", "ask"),
                                      ("prep:6dbbc192", "prepared"), ("s9", "source")])
def test_the_drawer_and_the_console_read_the_same_record(sel, kind):
    app = FakeApp()
    drawer = D.record(app, {"sel": sel})
    tool = T.kranto_details(client(app), sel)
    said = tool.pop("said")
    assert tool == drawer
    assert drawer["kind"] == kind and drawer["sel"] == sel and drawer["tool"] == f"kranto_details {sel}"
    assert drawer["title"] and said.startswith(drawer["title"])
    # the design's groups, in its order, each a list of [label, value] in words
    order = [g["h"] for g in drawer["groups"]]
    assert order == [h for h in D.ORDER if h in order] and order
    for g in drawer["groups"]:
        assert all(isinstance(k, str) and isinstance(v, str) and v for k, v in g["rows"])
        assert all(v != "None" and "null" not in v for _, v in g["rows"])


def test_a_build_or_a_loop_idea_is_gone_in_words():
    """The factory left: a build's or the loop's own idea's sel answers 404, in words."""
    for sel in ("bsidedoor", "i01"):
        with pytest.raises(HttpError) as e:
            D.record(FakeApp(), {"sel": sel})
        assert e.value.code == 404


def test_an_idea_card_says_what_cubs_asked_on_it_in_the_owners_words():
    rec = D.record(FakeApp(), {"sel": "card:7"})
    asked = {g["h"]: g["rows"] for g in rec["groups"]}["Asked of you"]
    assert [v for _, v in asked] == ["newsletter: Send this week's issue? (practiced: not sent)"]


def test_a_cards_details_hold_its_claims_with_their_sources_its_risks_and_its_cheapest_test():
    """ 11 (Codex 5): Details showed bare URLs and observation ids, and no risk or test;
    MCP's read had them."""
    card = {**CARD, "citations": [{"observation_id": 11594, "url": "https://dev.to/a", "source": "dev.to",
                                   "claim": "Anthropic removed the 5-hour limit for Ultra."}, None],
            "risks": "The usage meter may not be readable.", "cheapest_test": "Run one task daily for three weeks."}

    class App(FakeApp):
        def afk(self, method, path, body=None, owner=False):
            return card if path == "/api/ideas/7" else super().afk(method, path, body, owner)
    groups = {g["h"]: g["rows"] for g in D.record(App(), {"sel": "card:7"})["groups"]}
    assert groups["Evidence"] == [["1. dev.to", "Anthropic removed the 5-hour limit for Ultra."], ["", "https://dev.to/a"]]
    assert groups["What could go wrong"] == [["risks", "The usage meter may not be readable."]]
    assert groups["The cheapest test"] == [["test", "Run one task daily for three weeks."]]


def test_a_prepared_item_says_what_it_does_and_who_prepared_it():
    rec = D.record(FakeApp(), {"sel": "prep:6dbbc192"})
    groups = {g["h"]: dict(g["rows"]) for g in rec["groups"]}
    assert groups["What"]["action"] == "File a Kranto issue (b.factory_issue)"
    assert groups["What"]["labels"] == "feature" and "area" not in groups["What"]   # a null says nothing
    assert groups["Who, when"]["by words"] == "by Claude Code"


def test_a_shape_it_did_not_expect_says_less_never_fails():
    class Odd(FakeApp):
        def afk(self, method, path, body=None, owner=False):
            if path == "/api/ideas/7":
                return {"title": None, "citations": "not a list", "tickets": [None, "x"], "risks": [None]}
            return super().afk(method, path, body, owner)
    rec = D.record(Odd(), {"sel": "card:7"})
    assert rec["title"] == "card:7"
    assert D._value(None) is None and D._value([]) is None and D._value({"a": None}) is None
    assert D._value([None, {"title": "x"}, 3]) == "x; 3"


def test_an_unknown_object_is_a_404_in_words():
    with pytest.raises(HttpError):
        D.record(FakeApp(), {"sel": "bnope"})
    with pytest.raises(HttpError):
        D.record(FakeApp(), {"sel": "zzz"})
    with pytest.raises(HttpError):                 # an object of a feature that left Kranto
        D.record(FakeApp(), {"sel": "o5"})
    with pytest.raises(T.ToolError):
        T.kranto_details(client(FakeApp()), "")


def test_kranto_details_is_one_tool_the_console_reads():
    names = [t["name"] for t in T.tools()]
    assert names.count("kranto_details") == 1
    d = next(t for t in T.tools() if t["name"] == "kranto_details")
    assert d["read_only"] is True and "sel" in d["schema"]["properties"]
