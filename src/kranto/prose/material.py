"""What a writer is given about an idea card (round 3).

The owner read four posts written from idea cards and posted none: each described a tool one
could build. An idea card's evidence says something about the reader's world (a change the
sources converged on); the idea is one thing a builder might do about it. So the material leads
with the change and its meaning, and labels the idea as background, which the writer's task line
says the post is not about.

The same words are built in three places, kept equal by a test: here (Write a post's angles and
short posts, the eval), and in the blog cub's ``card_material`` (a cub imports only the SDK).
"""

from __future__ import annotations

from typing import Any

CHANGE = "What the sources show (the post is about this and what it means): "
MEANS = "What they suggest: "
IDEA = "The idea a builder might act on (background only, not the post's subject): "


def card_about(card: dict[str, Any]) -> str:
    """The ``about`` text of a card: its title first (Post's row reads the first line), then the
    change, what it suggests, and the idea, labelled."""
    lines = [str(card.get("title") or "").strip()]
    if card.get("one_liner"):
        lines.append(CHANGE + str(card["one_liner"]).strip())
    if card.get("insight"):
        lines.append(MEANS + str(card["insight"]).strip())
    if card.get("thesis"):
        lines.append(IDEA + str(card["thesis"]).strip())
    return "\n".join(x for x in lines if x)


def card_facts(sources: list[dict[str, Any]]) -> str:
    return "\n".join(f"[{s['n']}] {s.get('source') or ''}: {s.get('claim') or ''}"
                     for s in sources) or "(no sources)"


def card(card: dict[str, Any], sources: list[dict[str, Any]] | None = None) -> dict[str, str]:
    """``{title, facts}`` of an idea card, as every writer is given it."""
    srcs = (card.get("sources") or []) if sources is None else sources
    return {"title": card_about(card), "facts": card_facts(srcs)}
