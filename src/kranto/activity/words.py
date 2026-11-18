"""The words a run is said in: never a key, never a uuid.

Every kind has three forms, scheduled ("Reading your sources"), running ("Reading your
sources", the stage words after it) and done ("Read your sources"), and the verb a failed run
offers. A feature's or a cub's job without a row here is said from its feature's title
("Toot's weekly run"). The page draws the same words from the read; it keeps none of its own.
"""

from __future__ import annotations

import re
from typing import Any

from ..core.text import possessive

# kind: (scheduled, running, done, verb when it failed)
# the jobs of features that left Kranto (cut 2): their runs rows stay, said as one past
# run with no button, and never a Fix row or an incident (kranto archive holds what they made)
RETIRED_KINDS = frozenset({"radar.run", "radar.terms", "radar.chain", "invest.mark",
                           "invest.track", "invest.scan", "invest.cards", "invest.events",
                           "invest.fold", "deepdive"})
RETIRED_RUN: tuple[str, str, str, str | None] = (
    "A run of a feature that left Kranto", "A run of a feature that left Kranto",
    "A run of a feature that left Kranto", None)
KINDS: dict[str, tuple[str, str, str, str | None]] = {
    "ingest": ("Reading your sources", "Reading your sources", "Read your sources",
               "Run ingest now"),
    "snapshot": ("Drawing the map", "Drawing the map", "Drew the map", None),
    "compact": ("Compacting old observations", "Compacting old observations",
                "Compacted old observations", None),
    "ideas": ("Writing idea cards", "Writing idea cards", "Wrote idea cards", None),
    "xrecheck": ("Checking kept X posts", "Checking kept X posts", "Checked kept X posts", None),
    "heartbeat": ("The weekly heartbeat", "Writing the weekly heartbeat",
                  "Wrote the weekly heartbeat", None),
    "update": ("The update check", "Checking for updates", "Checked for updates", "Try again"),
    "telemetry": ("Usage reports", "Sending the usage report", "Sent the usage report", None),
    "cubs.gc": ("Tidying the features' files", "Tidying the features' files",
                "Tidied the features' files",
                None),
    "cubs.updates": ("Looking for the features' updates", "Looking for the features' updates",
                     "Looked for the features' updates", "Look again"),
    "cub.update": ("A feature's update", "Updating a feature", "Updated a feature", None),
    "cub.source": ("A feature's source", "A feature's source is gone",
                   "A feature's source is gone", None),
    "news.brief": ("The topics' briefs", "Writing the topics' briefs", "Wrote the topics' briefs",
                   "Brief now"),
    "news.write": ("A brief", "Writing a brief", "Wrote a brief", "Brief now"),
    "ideas.card": ("A card on a theme", "Writing a card on a theme", "Wrote a card on a theme",
                   "Card it now"),
    "scout": ("Scouting sources", "Scouting sources", "Scouted sources", "Scout again"),
    "explain": ("An explanation", "Explaining", "Explained", "Explain again"),
    "fromtext": ("Resolving the sources you pasted", "Resolving the sources you pasted",
                 "Resolved the sources you pasted", "Paste again"),
    "post": ("A post's draft", "Writing a post's draft", "Wrote a post's draft",
             "Write a post again"),
    # a verb an assistant ran or prepared (core.verbs); the run's title says which
    "verb": ("An assistant's action", "Doing what an assistant asked",
             "Did what an assistant asked", None),
    **{k: RETIRED_RUN for k in RETIRED_KINDS},
}

STATES = {
    "running": ("⟳", "running"), "waiting": ("▣", "waiting on you"), "ok": ("✓", "done"),
    "degraded": ("⚠", "done with problems"), "failed": ("✕", "failed"),
    "skipped": ("–", "skipped"), "stopped": ("■", "stopped"),
}

# a setting key or a snake_case name (``news.run_minutes``, ``not_due``); a host name has no
# underscore and is left alone
_KEYISH = re.compile(r"\b[a-z][a-z0-9]*(?:\.[a-z0-9]+)*_[a-z0-9_]+\b")


def humanize(kind: str, feature_title: str | None = None) -> str:
    """A kind without a row: "<Feature>'s <rest> run", or its words with the dots gone."""
    head, _, rest = kind.partition(".")
    rest = rest.replace("_", " ").replace(".", " ").strip()
    owner = feature_title or head.replace("_", " ").capitalize()
    return f"{possessive(owner)} {rest} run" if rest else owner


def forms(kind: str, feature_title: str | None = None) -> dict[str, Any]:
    """``{"scheduled", "running", "done", "verb"}`` for a kind."""
    row = KINDS.get(kind)
    if row is None:
        t = humanize(kind, feature_title)
        return {"scheduled": t, "running": t, "done": t, "verb": "Run again"}
    return {"scheduled": row[0], "running": row[1], "done": row[2], "verb": row[3]}


def title_of(kind: str, state: str = "done", feature_title: str | None = None,
             subject_name: str | None = None) -> str:
    """The title of a run in its state; a subject named where it reads better."""
    f = forms(kind, feature_title)
    t = f["running"] if state in ("running", "waiting") else (
        f["done"] if state in ("ok", "degraded") else f["scheduled"])
    if subject_name and kind in ("news.write", "scout"):
        t = f"{t}: {subject_name}"
    return str(t)


def plain(text: str | None) -> str | None:
    """Words that may be served: no setting key (``x.y_z``), no uuid."""
    if not text:
        return text
    text = re.sub(r"\b[0-9a-f]{32}\b", "a run", text)
    # a prepared item's words kept before 0.6.0.dev15 ("waits for your press on #/needs"): said
    # as they are said now (the owner never reads "press")
    text = re.sub(r"\b(your|the owner's) press\b", r"\1 approval", text)
    return _KEYISH.sub(lambda m: m.group(0).split(".")[-1].replace("_", " "), text)
