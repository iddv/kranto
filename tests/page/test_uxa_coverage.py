"""the coverage matrix (INVENTORY.md; ui/web/coverage/uxa.json): nothing a
person can do today is lost in the doors. Here, read off the files: every row's route is one
nodes.json has, with a page for its node; every action's words are in the component the row
names; every part of the inventory has rows; what proposed to drop is still there. What the
routes do (an old route landing on the row's, the page drawing, its words on it, a sheet opening
with the doors on) is walked in Vitest: ui/web/src/lib/app/coverage.test.ts."""
import json
import re

import pytest

from .webui import SRC, WEB, nodes, src

MATRIX = json.loads((WEB / "coverage" / "uxa.json").read_text())
ROWS = MATRIX["rows"]
KINDS = {"page", "sheet", "action", "key", "setting", "api", "state"}
# "new": added since (track the layout setting, a cub installed later); "removed": the
# owner retired it (WT: watches), its old routes landing where the row says; "changed": kept in its
# place, drawn the one way (STD: the head, the row, the states)
FATES = {"kept", "merged", "moved", "default", "kept-not-dropped", "new", "removed", "changed"}


def registered() -> set[str]:
    """the nodes a page is registered under (pages/index.ts, features/index.ts)"""
    text = src("pages/index.ts") + src("features/index.ts")
    return set(re.findall(r'register\("([^"]+)"', text))


def route_of(path: str) -> dict | None:
    """the nodes.json entry a path matches (":x" is one segment), as router.ts's matchRoute"""
    parts = [p for p in path.split("/") if p]
    for n in nodes():
        pat = n["route"].split("/") if n["route"] else []
        if len(pat) == len(parts) and all(p.startswith(":") or p == parts[i] for i, p in enumerate(pat)):
            return n
    return None


def test_the_matrix_names_every_part_of_the_inventory_once():
    ids = [r["id"] for r in ROWS]
    assert len(ids) == len(set(ids))
    assert {r["inv"] for r in ROWS} >= {"A1", "A2", "A3", "A4", "A5", "A6", "A7", "B1", "B2", "B3", "B4",
                                         "B5", "B6", "C", "D", "E", "F"}
    for r in ROWS:
        assert r["kind"] in KINDS and r["fate"] in FATES and r["what"] and r["at"], r


def test_what_uxa_proposed_to_drop_stays_for_the_owner():
    # the tree and its layout commands were D-4's: the owner kept them as the classic layout
    # (2026-10-21), so they are kept, not waiting; the bulk bar and its keys the owner removed
    #, as News' ▲ ▼
    kept = sorted(r["id"] for r in ROWS if r["fate"] == "kept-not-dropped")
    assert kept == []
    assert {r["id"]: r["fate"] for r in ROWS if r["id"] in ("B3-bulk", "D-ticks", "B5-news-grade")} == \
        {"B3-bulk": "removed", "D-ticks": "removed", "B5-news-grade": "removed"}
    assert {r["id"]: r["fate"] for r in ROWS if r["id"] in ("B1-layout", "B1-tree")} == \
        {"B1-layout": "kept", "B1-tree": "kept"}


@pytest.mark.parametrize("row", ROWS, ids=[r["id"] for r in ROWS])
def test_every_row_is_a_route_with_a_page(row):
    path = row["at"].split("?")[0]
    n = route_of(path)
    assert n, f"{row['id']}: no route for #/{path}"
    assert not n.get("redirect") and not n.get("doors"), f"{row['id']}: #/{path} moves on with the doors on"
    node = n["node"]
    # a page of a topic (topics/:id/map) is registered by its parent's loop (pages/index.ts)
    assert node in registered() or re.sub(r"/[^/]+$", "/:id", node) in registered() \
        or re.sub(r"/[^/]+$", "", node) in registered() or node.split("/")[0] in registered(), \
        f"{row['id']}: no page registered for {node}"
    if row.get("old"):
        assert route_of(row["old"].split("?")[0]), f"{row['id']}: the old route #/{row['old']} is gone"


@pytest.mark.parametrize("row", [r for r in ROWS if r.get("in")], ids=[r["id"] for r in ROWS if r.get("in")])
def test_every_action_is_in_the_component_that_draws_it(row):
    f = SRC / row["in"]
    assert f.is_file(), f"{row['id']}: {row['in']} is gone"
    text = f.read_text()
    for w in row["has"]:
        assert w in text, f"{row['id']}: {w!r} is not in {row['in']}"
