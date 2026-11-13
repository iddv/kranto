"""The newsletter is platform-neutral (the owner's ruling of 2026-10-21, MAIL; the same rule as
Invest's broker, ``test_broker_neutral``): no newsletter platform is named in Kranto's code,
words, docs or the reference cub, outside the platform's own module
(``src/kranto/newsletter/<id>.py``) and the newsletter guide (``docs/newsletter.md``). The
platform in use comes from config, and until the owner connects one, nothing a browser is served
names one: not the cubs, the newsletter cub's page, its ticket and read-back, the home or the
newsletter's own status (beyond the list the Connect dialog offers). This test fails the build
otherwise."""

from __future__ import annotations

import json
import re
from pathlib import Path

from kranto import newsletter
from kranto.core import tickets
from kranto.core.cubs.brokers.base import new_draft

from .conftest import web_client
from .test_examples_install import add, home  # noqa: F401 - fixture
from .test_web import rt  # noqa: F401 - fixture

ROOT = Path(__file__).resolve().parents[1]
TEXT = {".py", ".md", ".json", ".yaml", ".yml", ".txt", ".toml", ".html", ".js", ".css",
        ".sql", ".j2"}
GUIDE = "docs/newsletter.md"


def _names() -> re.Pattern:
    words = set()
    for p in newsletter.PLATFORMS.values():
        words |= {p.id, p.name}
    return re.compile(r"\b(" + "|".join(re.escape(w) for w in sorted(words)) + r")\b", re.I)


def _allowed() -> set[str]:
    return {f"src/kranto/newsletter/{p.id}.py" for p in newsletter.PLATFORMS.values()} \
        | {GUIDE}


def _files():
    for base in ("src", "prompts", "docs"):
        if not (ROOT / base).exists():
            continue
        for p in (ROOT / base).rglob("*"):
            # the page's installed node_modules are not the repository's
            if p.is_file() and p.suffix in TEXT and "__pycache__" not in p.parts \
                    and "node_modules" not in p.parts and "app" not in p.parts:
                yield p


def test_no_platform_is_named_outside_its_module_and_the_guide():
    names, allowed = _names(), _allowed()
    offenders = []
    for p in _files():
        rel = p.relative_to(ROOT).as_posix()
        if rel in allowed:
            continue
        for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(),
                                 1):
            if names.search(line):
                offenders.append(f"{rel}:{n}: {line.strip()[:100]}")
    assert offenders == [], "a newsletter platform named outside its module:\n" \
        + "\n".join(offenders)


def test_the_check_would_catch_one():
    assert _names().search("Connect Resend now") and _names().search("send.buttondown")
    assert not _names().search("Connect a newsletter platform")


def test_each_platform_has_its_module_its_connection_and_a_guide_section():
    guide = (ROOT / GUIDE).read_text()
    for p in newsletter.PLATFORMS.values():
        assert (ROOT / "src/kranto/newsletter" / f"{p.id}.py").is_file()
        assert p.connection is not None and p.info["key"] == p.id
        assert p.info["group"] == "newsletter" and p.info["writes"] is True
        assert f"## {p.name}" in guide and p.docs == f"{GUIDE}#{p.id}"


# -- the words a browser is served ------------------------------------------------------------


def _served(rt, tid: int) -> dict:  # noqa: F811
    from kranto.web.app import create_app
    with web_client(create_app(rt), "http://127.0.0.1:8765") as web:
        out = {p: web.get(p).text for p in ("/api/features", "/api/shell", "/api/cubs",
                                            "/api/cubs/newsletter", f"/api/tickets/{tid}",
                                            f"/api/tickets/{tid}/ask", "/api/asks",
                                            "/api/today")}
        status = web.get("/api/newsletter").json()
    status.pop("platforms")                    # the Connect dialog's list names what it offers
    out["/api/newsletter"] = json.dumps(status)
    return out


def _ticket(rt) -> int:  # noqa: F811
    d = new_draft(rt.store, cub="newsletter", service="newsletter",
                  content={"subject": "This week: solar", "body": "Two items."}, run_uuid=None)
    return tickets.file(rt.store, cub="newsletter", trust="owner",
                        granted=("send.newsletter",), kind="send.newsletter",
                        fields={"draft_ref": d["ref"], "subject": "This week: solar",
                                "audience": "all", "when": "now"})


def test_no_platform_is_named_until_one_is_connected(home):  # noqa: F811
    add(home, "newsletter")
    tid = _ticket(home)
    served = _served(home, tid)
    # An earlier release's kind stays served by its id for one release (an open ticket of it
    # still draws its confirm: the page looks its schema up by kind); the id is never shown,
    # its title is the neutral one.
    old = newsletter.legacy_kinds()
    schemas = json.loads(served["/api/features"])["request_schemas"]
    assert all(schemas[k]["title"] == "Send this issue" for k in old)
    for path, text in served.items():
        for k in old:
            text = text.replace(f'"{k}"', '"(alias)"')
        hit = _names().search(text)
        assert hit is None, f"{path} names {hit.group(0)!r} with no platform connected"
    st = json.loads(served["/api/newsletter"])
    assert st["platform"] is None and st["name"] is None
    assert st["missing"] == ["No newsletter platform is connected: Connect a provider"]
    rb = dict(json.loads(served[f"/api/tickets/{tid}"])["readback"])
    assert rb["Newsletter"] == "no newsletter platform is connected" and "Platform" not in rb


def test_the_platform_chosen_at_connect_is_named(home):  # noqa: F811
    add(home, "newsletter")
    p = next(iter(newsletter.PLATFORMS.values()))        # the default, first offered
    newsletter.keep_sender(home.store, p, {})
    tid = _ticket(home)
    served = _served(home, tid)
    assert json.loads(served["/api/newsletter"])["name"] == p.name
    rb = dict(json.loads(served[f"/api/tickets/{tid}"])["readback"])
    assert rb["Platform"] == p.name and rb["Newsletter"] == f"{p.name} is not connected"


def test_the_connect_dialog_offers_every_platform_first_the_default():
    offered = [p["id"] for p in newsletter.listing()]
    assert offered == list(newsletter.PLATFORMS) and len(offered) >= 2
    assert newsletter.PLATFORMS[offered[0]].can_schedule      # the owner's choice, first
