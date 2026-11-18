"""One bad row never takes a page down, on the page's side: in a list built
row by row (``rowsafe.each``), one row that raises is still listed, as "Couldn't read this
<thing>" with an error id, the rest as before, and the error is kept once by its id. Without
the server the ids are errtrace's, computed here, and kept in the loop home. The lists of the
factory (builds, projects, Changes, repositories, lessons, the loop's steps) left with it."""
import json

import pytest

from kranto.page import rowsafe
from kranto.page.ui import api

from .app_common import make_home


def raises(*_a, **_k):
    raise TypeError("unsupported format string passed to NoneType.__format__")


def check(row: dict, what: str, exc: str = "TypeError") -> str:
    u = row["unreadable"]
    assert u["what"] == what and u["words"] == f"Couldn't read this {what}"
    assert u["exception"] == exc and len(u["error_id"]) == 8
    int(u["error_id"], 16)
    return u["error_id"]


@pytest.fixture(autouse=True)
def _fresh(monkeypatch):
    monkeypatch.setattr(rowsafe, "_seen", {})


def test_the_self_checks_reads_are_every_page_and_nothing_that_leaves(tmp_path):
    """Kranto's post-update self-check reads these under /brb (host_api.selfcheck_paths):
    each GET that takes nothing, never what asks GitHub or runs a program."""
    from kranto.page import host_api
    app = api.App(None, "fake", make_home(tmp_path).home)
    paths = host_api.selfcheck_paths(app)
    for p in ("/api/header", "/api/activity"):
        assert p in paths, p
    for gone in api.SELFCHECK_EXCLUDED:
        assert gone not in paths
    assert not [p for p in paths if p.startswith(("/api/kranto", "/api/build", "/api/projects",
                                                  "/api/maintain", "/api/changes"))]
    for p in paths:
        path, _, q = p.partition("?")
        code, _, _ = api.handle("GET", path, q, app=app)
        assert code < 500 or code in (502, 503), p


def test_without_kranto_the_id_is_errtraces_and_the_file_is_the_loop_homes(tmp_path,
                                                                            monkeypatch):
    monkeypatch.setattr(rowsafe, "_afk", lambda: None)
    rowsafe.configure(tmp_path)
    try:
        out = rowsafe.each([{"id": n} for n in (1, 2, 3)],
                           lambda x: raises() if x["id"] == 2 else x, "build")
        assert [r["id"] for r in out] == [1, 2, 3]
        eid = check(out[1], "build")
        rec = json.loads((tmp_path / "errors.jsonl").read_text().splitlines()[0])
        assert rec["id"] == eid and rec["exception"] == "TypeError"
        assert rec["frames"] and all(f.startswith("kranto.page.") for f in rec["frames"])
        assert rec["signature"].startswith(eid) and len(rec["signature"]) == 16
    finally:
        rowsafe.configure(None)
