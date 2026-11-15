"""Every page a verb's answer names is a page the page has, never a dead end.

The second outside try opened what kranto mcp's answers named: ``#/settings/capabilities`` (it
only landed on the Settings overview), ``#/cub/blog`` (it only redirected to Post) and
``#/settings/assistant?sel=outside`` (read as an observation, "No observation utside"). Each
verb's page is matched against the page's own routes (``src/lib/nodes.json``).
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import kranto
from kranto.core import verbs

NODES = Path(kranto.__file__).parent / "page" / "ui" / "web" / "src" / "lib" / "nodes.json"


def _routes() -> list[dict]:
    return json.loads(NODES.read_text())


def _land(path: str, routes: list[dict]) -> dict | None:
    parts = path.split("/")
    for r in routes:
        rp = r["route"].split("/") if r["route"] else [""]
        if len(rp) == len(parts) and all(a.startswith(":") or a == b
                                         for a, b in zip(rp, parts, strict=True)):
            return r
    return None


def _check(kind: str, page: str, routes: list[dict]) -> None:
    path, _, query = page.removeprefix("#/").partition("?")
    hit = _land(path, routes)
    assert hit is not None, (kind, page)
    assert not hit.get("gone"), (kind, page)
    if hit.get("redirect") in ("settings", "home") and path not in ("settings", "home"):
        raise AssertionError(f"{kind}: {page} only lands on the {hit['redirect']} page")
    sel = dict(x.partition("=")[::2] for x in query.split("&") if x).get("sel")
    if sel and path.startswith("settings"):
        assert sel.startswith("e"), (kind, page)        # a setting's row, never an observation


def test_every_core_verbs_page_is_a_page():
    routes = _routes()
    for v in verbs.CORE:
        _check(v.kind, verbs.fill(v.page, "1", {"feature": "news", "pid": "judge"}), routes)


def test_a_feature_that_writes_posts_names_post_and_news_its_own_page():
    post = SimpleNamespace(ui=SimpleNamespace(kind="post"))
    other = SimpleNamespace(ui=SimpleNamespace(kind="other"))
    assert verbs._feature_page(post, "blog") == "#/post"
    assert verbs._feature_page(other, "toolbox") == "#/cub/toolbox"
    routes = _routes()
    for page in ("#/post", "#/cub/toolbox", "#/news"):
        _check("feature", page, routes)
