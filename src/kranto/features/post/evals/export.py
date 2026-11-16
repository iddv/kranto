"""The eval's prompts, exported for any model (a bake-off).

    python -m kranto.features.post.evals export --items brief-24-1,card-158 --out DIR \\
        [--sites blog,toot] [--angles angles.json]

For each item and site (and each angle, when ``--angles`` gives them), this writes the messages
Kranto's writer would send, built by ``compose`` exactly as the blog and toot writers build them:

- ``DIR/<name>.json``: ``{name, item, site, angle_kind, angle, title, messages, system,
  examples, user, schema}`` (``examples`` is the few-shot pair, empty with no samples);
- ``DIR/<name>.txt``: the same as one plain-text prompt any model's command line can take, which
  asks for the post alone in markdown (no JSON);
- ``DIR/index.json``: every name with its item, site, title and angle, which the read builder
  uses to label each post.

``<name>`` is ``<item>.<site>`` or ``<item>.<site>.<angle kind>``. Write each model's answer to
``DRAFTS/<writer>/<name>.md`` and build the blind page with ``read``. No model is called.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import writers

SITE_FILE = {"blog": "blog", "toot": "toot"}
PLAIN_FORMAT = {
    "blog": "Reply with the post only, in markdown: a first line '# ' and the title, then the "
            "body. No JSON, no notes before or after.",
    "toot": "Reply with the post's text only. No JSON, no quotes, no notes before or after.",
}


def _items(ids: list[str] | None) -> list[dict]:
    items = writers.items()
    if not ids:
        return items
    by = {it["id"]: it for it in items}
    missing = [i for i in ids if i not in by]
    if missing:
        raise SystemExit(f"no such item: {', '.join(missing)} (items.json has "
                         f"{', '.join(by)})")
    return [by[i] for i in ids]


def split(messages: list[dict]) -> tuple[str, list[dict], str]:
    """``(system, examples, user)`` of a composed prompt."""
    system = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
    rest = messages[1:] if system else list(messages)
    user = rest[-1]["content"] if rest else ""
    return system, rest[:-1], user


def plain(messages: list[dict], site: str) -> str:
    system, examples, user = split(messages)
    # the writers ask for JSON (their schema); a model's command line answers in plain text
    system = re.sub(r" Answer JSON with [a-z, ]+\.", "", system)
    parts = ["=== INSTRUCTIONS ===", system]
    if examples:
        parts += ["=== HOW I WRITE (examples: match how they read, never their facts) ===",
                  "\n\n".join(m["content"] for m in examples if m["role"] == "user")]
    parts += ["=== THE POST TO WRITE ===", user, "=== FORMAT ===", PLAIN_FORMAT[site]]
    return "\n\n".join(parts).strip() + "\n"


def entry(item: dict, site: str, angle_kind: str | None = None,
          angle: str | None = None) -> dict:
    """One exported prompt."""
    msgs = writers.prompt("new", site, item, angle=angle if angle_kind else None)
    system, examples, user = split(msgs)
    name = f"{item['id']}.{site}" + (f".{angle_kind}" if angle_kind else "")
    return {"name": name, "item": item["id"], "site": site, "angle_kind": angle_kind,
            "angle": angle if angle_kind else None, "title": item["title"],
            "messages": msgs, "system": system, "examples": examples, "user": user,
            "schema": writers.schema(site), "plain_format": PLAIN_FORMAT[site]}


def export(out: Path, ids: list[str] | None = None, sites: tuple[str, ...] = ("blog",),
           angles: dict[str, dict[str, str]] | None = None,
           site_of: dict[str, str] | None = None) -> list[dict]:
    """Write the prompts; the index's rows. ``angles``: item -> {kind: sentence} (the run's
    proposals); ``site_of``: item -> the one site to export it for (else every one of
    ``sites``)."""
    out.mkdir(parents=True, exist_ok=True)
    index = []
    for item in _items(ids):
        for site in ([site_of[item["id"]]] if site_of and item["id"] in site_of else sites):
            if site not in SITE_FILE:
                raise SystemExit(f"site is one of {', '.join(SITE_FILE)}")
            pairs: list[tuple[str | None, str | None]] = list(
                (angles or {}).get(item["id"], {}).items()) or [(None, None)]
            for kind, sentence in pairs:
                e = entry(item, site, kind, sentence)
                (out / f"{e['name']}.json").write_text(
                    json.dumps(e, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
                (out / f"{e['name']}.txt").write_text(plain(e["messages"], site),
                                                      encoding="utf-8")
                index.append({k: e[k] for k in ("name", "item", "site", "angle_kind", "angle",
                                                "title")})
    (out / "index.json").write_text(json.dumps({"prompts": index}, indent=1,
                                               ensure_ascii=False) + "\n", encoding="utf-8")
    return index
