"""The parity test (rules 1 and 5; the page keeps rules 2 to 4): the verb
registry (``core.verbs``) and the app's routes cannot drift apart.

1. **No write route without a verb.** Every non-GET route the app serves is a verb's route (or
   an older route of one) or on ``ROUTE_ALLOW`` with its reason; a POST added without a verb
   fails here (the planted route below proves the check holds).
5. **The ladder is total and the locks hold.** Every verb has a ladder kind; a credential or
   broker verb is run by the owner only; a house confirm is the page's or locked to Ask; every
   ticket kind is confirmed on the page only.

And the table itself: every verb's route exists, kinds are unique, a page is a hash route.
"""

import pytest
from starlette.routing import Route

from kranto.config import (
    ApiConfig,
    BrbConfig,
    BudgetConfig,
    BuildsConfig,
    Config,
    IngestConfig,
    MapConfig,
)
from kranto.core import tickets, verbs
from kranto.runtime import open_runtime
from kranto.web.app import create_app

from . import brbfake
from .conftest import llm_config
from .test_brb_mount import FakeApi

READ_METHODS = {"GET", "HEAD"}


@pytest.fixture
def app(tmp_path, store, embedder, make_client, monkeypatch):
    brbfake.install(monkeypatch, FakeApi())
    cfg = Config(root=tmp_path, llm=llm_config(), budget=BudgetConfig(monthly_usd=10),
                 ingest=IngestConfig(), map=MapConfig(), api=ApiConfig(),
                 builds=BuildsConfig(enabled=True),
                 brb=BrbConfig(enabled=True, root=str(tmp_path / "tasks")))
    rt = open_runtime(cfg, store=store, embedder=embedder, llm=make_client(lambda b: None))
    return create_app(rt, port=8765)


def write_routes(app) -> set[tuple[str, str]]:
    out = set()
    for r in app.routes:
        if isinstance(r, Route):
            for m in (r.methods or set()) - READ_METHODS:
                out.add((m, r.path))
    return out


def unregistered(routes: set[tuple[str, str]]) -> list[tuple[str, str]]:
    """Rule 1: the write routes that are no verb's and not allowed with a reason."""
    known = {rp for v in verbs.CORE for rp in verbs.routes_of(v)}
    return sorted(r for r in routes if r not in known and r not in verbs.ROUTE_ALLOW)


def test_every_write_route_is_a_verb(app):
    missing = unregistered(write_routes(app))
    assert not missing, (
        "a write route without a verb: add it to core/verbs.py (CORE, with its ladder kind, "
        f"doors and page) or to ROUTE_ALLOW with why: {missing}")


def test_a_route_planted_without_a_verb_fails(app):
    async def sneaky(request):  # pragma: no cover - never called
        return None
    app.router.routes.append(Route("/api/sneaky", sneaky, methods=["POST"]))
    assert unregistered(write_routes(app)) == [("POST", "/api/sneaky")]


def test_every_verb_route_is_served(app):
    served = write_routes(app)
    gone = sorted((v.kind, m, p) for v in verbs.CORE for m, p in verbs.routes_of(v)
                  if (m, p) not in served)
    assert not gone, f"a verb whose route the app does not serve: {gone}"
    stale = sorted(r for r in verbs.ROUTE_ALLOW if r not in served)
    assert not stale, f"ROUTE_ALLOW names a route that is gone: {stale}"


def test_the_table_is_whole():
    kinds = [v.kind for v in verbs.CORE]
    assert len(kinds) == len(set(kinds)), "a verb kind twice"
    for v in verbs.CORE:
        assert v.ladder in verbs.LADDER_KINDS, v.kind
        assert v.page.startswith("#/"), v.kind
        assert set(v.doors) <= set(verbs.DOORS) and "ui" in v.doors, v.kind
        assert v.click in ("click", "confirm", "house"), v.kind
        assert v.body in ("json", "form", "fields"), v.kind
        assert v.title and v.says, v.kind
        assert all(f.type in verbs.FIELD_TYPES for f in v.fields), v.kind
        if v.undo:
            assert verbs.get(v.undo) is not None, f"{v.kind}'s undo {v.undo} is no verb"


def test_the_ladder_is_total_and_the_locks_hold():
    """Rule 5: the owner's three standing rules, as tests."""
    for v in verbs.all_verbs():
        assert v.ladder in verbs.LADDER_KINDS, v.kind
        if v.ladder in ("credential", "broker"):
            assert set(v.doors) <= set(verbs.OWNER_DOORS), \
                f"{v.kind}: a {v.ladder} verb is run by the owner only"
            c = verbs.choice_for(None, v)
            assert c.locked and c.choice == verbs.LOCKS[v.ladder][0], v.kind
        if v.click == "house":
            assert v.doors == verbs.PAGE_ONLY or v.lock == "ask", \
                f"{v.kind}: a house confirm is the page's, or locked to Ask"
    # the assistant never sets what it may do, nor makes a token
    for kind in ("assistant.ladder", "token.add", "token.change"):
        assert set(verbs.get(kind).doors) <= set(verbs.OWNER_DOORS), kind
    # Invest's orders are built by code: no verb writes an instruction's fields
    assert not [v for v in verbs.all_verbs() if "trade" in v.kind or "instruct" in v.kind]
    for name in tickets.kind_names():
        spec = tickets.KINDS[name]
        assert spec.page_only, f"ticket kind {name} must be confirmed on the page only"
    for kind in ("ticket.confirm", "ticket.decline"):
        assert verbs.get(kind).doors == verbs.PAGE_ONLY


def test_a_locked_row_cannot_be_turned():
    with pytest.raises(ValueError, match="cannot be changed"):
        verbs.check_ladder({"kinds": {"credential": "do"}})
    # the broker's kind left with Invest: a stored choice for it loads and is never read
    assert verbs.check_ladder({"kinds": {"broker": "do"}}) == {"kinds": {}, "verbs": {}}
    with pytest.raises(ValueError, match="cannot be changed"):
        verbs.check_ladder({"verbs": {"cub.live": "do"}})
    with pytest.raises(ValueError, match="not a kind"):
        verbs.check_ladder({"kinds": {"fun": "do"}})
    with pytest.raises(ValueError, match="not one of"):
        verbs.check_ladder({"kinds": {"spend": "maybe"}})
    assert verbs.check_ladder({"kinds": {"spend": "ask"}, "verbs": {"topic.add": "never"}}) == \
        {"kinds": {"spend": "ask"}, "verbs": {"topic.add": "never"}}
