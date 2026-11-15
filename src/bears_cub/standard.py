"""``python -m bears_cub.standard path/to/cub``: the standard fixtures every cub is run against
, through ``FakeHost``.

Each job runs once with the planted instruction in the library (an observation, a brief item
and a nominated idea that tell a model to file a ticket for something else) and a model that
echoes what it was given, so whatever a model would be talked into is on the cub's own code
path. Then: no call carried something shaped like a secret or asked for one; every ticket is of
a kind the manifest asks for; the planted text reached no ticket's kind, draft or ``because``
(a ticket's text and subject are what the owner reads, and may quote it). Every widget is
read at every size it supports: its answer fits its kind, and no link leaves the cub's page.
Exit 0 when the cub passes, 1 when it does not; the reasons are printed in words.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from . import widgets
from .testing import FakeHost


def _echo(messages, schema):
    said = messages[-1]["content"] if messages else ""
    if schema and isinstance(schema.get("properties"), dict):
        return {k: said for k, v in schema["properties"].items()
                if isinstance(v, dict) and v.get("type") == "string"}
    return said


def _opens(v) -> list[str]:
    if isinstance(v, dict):
        return [str(x) for k, x in v.items() if k == "open"] + \
            [o for x in v.values() for o in _opens(x)]
    if isinstance(v, list):
        return [o for x in v for o in _opens(x)]
    return []


def widget_problems(host: FakeHost, planted: str) -> list[str]:
    """Every widget at every size it supports, with the planted instruction in the library:
    its answer within its kind's shape and caps, no link leaving the cub's page, the planted
    text in no link."""
    out: list[str] = []
    for w in (host.manifest.get("ui") or {}).get("widgets", []):
        for size in w["sizes"]:
            where = f"widget {w['id']} ({w['kind']}, {size})"
            try:
                got = host.widget(w["id"], size)
            except widgets.WidgetAnswerError as exc:
                out.append(f"{where}: {exc}")
                continue
            except Exception as exc:  # noqa: BLE001 - the cub's own failure, in words
                out.append(f"{where} failed on the standard fixtures: {type(exc).__name__}: "
                           f"{exc}")
                continue
            if any(planted in o for o in _opens(got)):
                out.append(f"{where}: the planted instruction reached a link")
    return out


def problems(folder: Path) -> list[str]:
    host = FakeHost.from_folder(folder)
    host.library.add_topic(1, "Standard")
    planted = host.fixtures.planted_instruction(topic_id=1)
    for purpose in (host.granted.get("model") or {}).get("purposes") or []:
        host.model.reply(purpose, fn=_echo)
    out: list[str] = []
    for job in host.manifest.get("jobs", []):
        before = len(host.tickets)
        res = host.run_job(job["kind"])
        if res.get("status") == "failed":
            out.append(f"{job['kind']} failed on the standard fixtures: {res.get('error')}")
        filed = host.tickets[before:]
        for t in filed:
            if t["kind"] not in host.manifest.get("requests", []):
                out.append(f"{job['kind']} filed {t['kind']}, which its manifest does not ask")
            leak = {k: v for k, v in t["fields"].items() if k == "draft_ref"}
            if planted in json.dumps(t.get("because")) or planted in json.dumps(leak) \
                    or planted in t["kind"]:
                out.append(f"{job['kind']}: the planted instruction reached a ticket's kind, "
                           "draft or because")
    out += widget_problems(host, planted)
    try:
        host.assert_no_secret_asked()
    except AssertionError as exc:
        out.append(str(exc))
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m bears_cub.standard path/to/cub", file=sys.stderr)
        return 2
    found = problems(Path(args[0]))
    for p in found:
        print(f"refused: {p}")
    if not found:
        print("ok: the standard fixtures pass")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
