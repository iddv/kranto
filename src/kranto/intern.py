"""The Kranto's judgment on one item: screen, prompt, parse, rate.

The model returns three ratings; code multiplies them. A single self-reported
score collapsed onto a handful of values in Parallax (46% of observations at
exactly 0.62); the decomposed product spread them out. Skip is a first-class
answer, and ``override`` with a reason lets the model keep an item of a kind
the operator wants kept whose ratings fall short only because its text
describes something richer (an episode's audio, a project's code).

Override is backed in code: it lifts an item over the gate only when
every rating is at least ``OVERRIDE_MIN_RATING`` (a rating below that is the
judge saying the item is empty, unverifiable or of no consequence, which no
reason makes up for) and its signal is at least ``OVERRIDE_FLOOR`` of the
threshold. Below either, the override is refused and the item is gated, so
override cannot empty the gate.

Since #84 an item is looked at twice. ``screen`` is a short, lenient first
look (its own prompt, ``screen``): is the item potentially worth reading
further? ``judge`` is the careful one, and sees what was gathered one step from
the item (its discussion, linked pages, repositories). When it keeps the item it
may name gathered sources that hold up on their own; each comes back with its
own ratings, multiplied and gated in code like the item's.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from . import prompts
from .llm import Completion, LLMClient
from .scrub import scrub
from .sources import Item

KINDS = ("beat", "mild_signal", "sharp_signal")
BODY_CHARS = 6000
MAX_TAGS = 8
# What the screen reads: enough to tell junk from something worth a look.
SCREEN_BODY_CHARS = 1500
SCREEN_COMMENTS = 3
SCREEN_COMMENT_CHARS = 300
# Gathered sources the judge may keep as observations of their own, per item.
MAX_CHILDREN = 4
RATINGS = ("content_quality", "durability", "opportunity")
# Override lifts an item only within these bounds. On the #47 sample the
# three items the operator wanted kept by override had ratings of 0.3 and above
# and signals of 0.084 to 0.168 against a 0.20 threshold.
OVERRIDE_MIN_RATING = 0.3
OVERRIDE_FLOOR = 0.25


@dataclass(frozen=True)
class ChildVerdict:
    """What the judge said about one gathered source it named (``ref``)."""

    ref: int
    outcome: str  # "contributed" | "gated"
    fields: dict


@dataclass(frozen=True)
class Verdict:
    """What the model said about an item."""

    outcome: str  # "contributed" | "gated" | "skipped" | "parse_failed"
    completion: Completion
    fields: dict | None = None
    children: list[ChildVerdict] = field(default_factory=list)

    @property
    def signal(self) -> float:
        return self.fields["signal"] if self.fields else 0.0


@dataclass(frozen=True)
class Screen:
    """The screen's answer: whether the item goes on to be gathered for and judged."""

    passed: bool
    reason: str
    completion: Completion


def _strip_fence(text: str) -> str:
    stripped = (text or "").strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE)
        if stripped.endswith("```"):
            stripped = stripped[:-3]
    return stripped.strip()


def extract_json_object(text: str) -> dict | None:
    """The first balanced JSON object in ``text``, tolerating fences and prose.

    Models ignore "no markdown fences" often enough (a third of the time for
    Haiku in Parallax's exp 16) that strict parsing silently drops good output.
    """
    stripped = _strip_fence(text)
    start = stripped.find("{")
    while start >= 0:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(stripped)):
            c = stripped[i]
            if in_string:
                if escaped:
                    escaped = False
                elif c == "\\":
                    escaped = True
                elif c == '"':
                    in_string = False
            elif c == '"':
                in_string = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(stripped[start : i + 1])
                    except json.JSONDecodeError:
                        break
                    return obj if isinstance(obj, dict) else None
        start = stripped.find("{", start + 1)
    return None


def _rating(obj: dict, key: str) -> float | None:
    try:
        value = float(obj[key])
    except (KeyError, TypeError, ValueError):
        return None
    if value != value:  # NaN
        return None
    return max(0.0, min(1.0, value))


def _fields(obj: dict) -> dict | None:
    """Rated fields from one object of the reply, or None when they are incomplete."""
    # The model's own words are scrubbed too, before they are stored.
    summary = scrub(str(obj.get("summary") or "").strip())
    why = scrub(str(obj.get("why_it_matters") or "").strip())
    ratings = {k: _rating(obj, k) for k in RATINGS}
    if not summary or not why or any(v is None for v in ratings.values()):
        return None
    override = obj.get("override") is True
    override_reason = scrub(str(obj.get("override_reason") or "").strip())
    if override and not override_reason:
        override = False
    kind = obj.get("kind") if obj.get("kind") in KINDS else "beat"
    tags = obj.get("tags") if isinstance(obj.get("tags"), list) else []
    signal = ratings["content_quality"] * ratings["durability"] * ratings["opportunity"]
    return {
        "kind": kind,
        "summary": summary,
        "why_it_matters": why,
        **ratings,
        "signal": signal,
        "override": override,
        "override_reason": override_reason if override else None,
        "tags": [str(t)[:40] for t in tags if isinstance(t, (str, int, float))][:MAX_TAGS],
    }


def override_effect(fields: dict, threshold: float) -> str | None:
    """What the judge's override did to an item: None when it was not set;
    ``unneeded`` when the signal keeps the item anyway; ``lifted`` when it keeps
    an item the gate would drop; ``refused`` when the item is too thin for it
    (a rating below ``OVERRIDE_MIN_RATING``, or a signal below ``OVERRIDE_FLOOR``
    of the threshold) and is gated."""
    if not fields["override"]:
        return None
    if fields["signal"] >= threshold:
        return "unneeded"
    if fields["signal"] >= threshold * OVERRIDE_FLOOR \
            and min(fields[k] for k in RATINGS) >= OVERRIDE_MIN_RATING:
        return "lifted"
    return "refused"


def override_lifted(row, threshold: float) -> bool:
    """Whether a stored observation was kept by the override: it was set, and the
    signal is below the gate. Pages show override only then; the judge sets it far more
    often than it is needed, and an unneeded one is noise. The row is not edited: the
    judge's reply stays in ``llm_calls`` and the run summaries keep their counts."""
    return bool(row["override"]) and row["signal"] is not None and row["signal"] < threshold


def _kept(fields: dict, threshold: float) -> bool:
    return fields["signal"] >= threshold or override_effect(fields, threshold) == "lifted"


def interpret(text: str, threshold: float) -> tuple[str, dict | None]:
    """Classify a model reply into an outcome and, if usable, its fields."""
    obj = extract_json_object(text)
    if obj is None:
        return "parse_failed", None
    if obj.get("skip") is True:
        return "skipped", None
    fields = _fields(obj)
    if fields is None:
        return "parse_failed", None
    return ("contributed" if _kept(fields, threshold) else "gated"), fields


def interpret_children(text: str, threshold: float, n_gathered: int) -> list[ChildVerdict]:
    """The gathered sources the judge named in ``children``, each rated on its own.

    An entry is used only when its ``ref`` names a gathered source (1-based) not
    already named and its fields are complete; anything else is dropped, never
    guessed at. At most ``MAX_CHILDREN``."""
    obj = extract_json_object(text) or {}
    entries = obj.get("children")
    if not isinstance(entries, list):
        return []
    out: list[ChildVerdict] = []
    seen: set[int] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref = entry.get("ref")
        if isinstance(ref, bool) or not isinstance(ref, int):
            continue
        if not 1 <= ref <= n_gathered or ref in seen:  # stored-shape: an int, checked above
            continue
        fields = _fields(entry)
        if fields is None:
            continue
        seen.add(ref)
        out.append(ChildVerdict(ref, "contributed" if _kept(fields, threshold) else "gated",
                                fields))
        if len(out) >= MAX_CHILDREN:
            break
    return out


MARKED = {"bookmarked": "the person running this bookmarked this post on X",
          "liked": "the person running this liked this post on X"}


def _stats(meta: dict) -> dict:
    """An item's counts as the judge reads them: an X post's engagement, without the ids
    Kranto keeps for itself or the person's own mark (said on its own); a page read in the
    browser, its score and comment count as the page showed them (the read itself is said on
    its own: ``read_by_you``)."""
    if isinstance(meta.get("browser"), dict):
        b = meta["browser"]
        shown = {k: b.get(k) for k in ("score", "comment_count") if b.get(k) is not None}
        rest = {k: v for k, v in meta.items() if k != "browser"}
        return {**rest, **({"page": shown} if shown else {})}
    if not isinstance(meta.get("x"), dict):
        return meta
    x = {k: v for k, v in meta["x"].items() if k not in ("seen_ids", "mine")}
    return {**meta, "x": x}


def read_by_you(meta: dict) -> str | None:
    """The browser extension's provenance, in words: "read by you on 27 Oct
    2026 at 21:14 in Chrome (3 of 213 comments)", or "saved by you …". The comments the judge
    is given are the ones that were on the person's screen: a sample, and it is told so."""
    b = meta.get("browser") if isinstance(meta, dict) else None
    if not isinstance(b, dict):
        return None
    from datetime import datetime
    try:
        at = datetime.fromisoformat(str(b.get("read_at") or "").replace("Z", "+00:00"))
        when = f" on {at.day} {at:%b %Y} at {at:%H:%M} UTC"
    except ValueError:
        when = ""
    how = f" in {b['browser']}" if isinstance(b.get("browser"), str) and b["browser"] else ""
    seen, total = b.get("visible_comments"), b.get("comment_count")
    if isinstance(seen, int) and isinstance(total, int) and total > 0:
        of = f" ({seen} of {total} comments, the ones on their screen)"
    elif isinstance(seen, int) and seen > 0:
        of = f" ({seen} comments, the ones on their screen)"
    else:
        of = ""
    verb = "saved" if b.get("mode") == "save" else "read"
    return f"{verb} by the person running this{when}{how}{of}; authors are not kept"


def _item_payload(item: Item, body_chars: int, comments: list[str]) -> dict:
    mine = (item.meta.get("x") or {}).get("mine") if isinstance(item.meta, dict) else None
    stats = _stats(item.meta) if item.meta else {}
    return {
        "title": item.title,
        "body": item.body[:body_chars],
        **({"capture_note": f"no content captured: the body was {item.capture_note}"}
           if item.capture_note else {}),
        "url": item.url,
        "links_to": item.link,
        "published_at": item.published_at.isoformat() if item.published_at else None,
        **({"marked": MARKED[mine]} if mine in MARKED else {}),
        **({"read_by_you": read} if (read := read_by_you(item.meta or {})) else {}),
        **({"stats": stats} if stats else {}),
        **({"top_comments": comments} if comments else {}),
    }


def render_gathered(gathered: list, chars: int) -> list[dict]:
    """Gathered sources as the judge sees them, numbered from 1 (``ref``)."""
    out = []
    for i, g in enumerate(gathered, 1):
        item = g.item
        out.append({
            "ref": i,
            "relation": g.relation,
            "title": item.title,
            "url": item.url,
            "text": item.body[:chars],
            **({"stats": item.meta} if item.meta else {}),
        })
    return out


def render_item(item: Item, source_label: str, topics: list[str], *,
                gathered: list | None = None, gathered_chars: int = 2000) -> str:
    payload = {
        "source": source_label,
        "topics_this_source_is_watched_for": topics,
        "item": _item_payload(item, BODY_CHARS, list(item.comments)),
    }
    if item.reached_from:
        payload["reached_from"] = item.reached_from
    if gathered:
        payload["gathered"] = render_gathered(gathered, gathered_chars)
    return json.dumps(payload, ensure_ascii=False, indent=1)


def render_screen_item(item: Item, source_label: str, topics: list[str]) -> str:
    comments = [c[:SCREEN_COMMENT_CHARS] for c in item.comments[:SCREEN_COMMENTS]]
    return json.dumps({
        "source": source_label,
        "topics_this_source_is_watched_for": topics,
        "item": _item_payload(item, SCREEN_BODY_CHARS, comments),
    }, ensure_ascii=False, indent=1)


def judge(
    llm: LLMClient,
    item: Item,
    *,
    source_label: str,
    topics: list[str],
    threshold: float,
    run_uuid: str | None = None,
    purpose: str = "judge",
    gathered: list | None = None,
    gathered_chars: int = 2000,
) -> Verdict:
    """Ask the tier-1 model about one item. LLM errors propagate to the caller.

    ``gathered`` (``sources.gather.Gathered``) is what was read one step from the
    item; the verdict's ``children`` are those the judge kept as observations of
    their own, only ever when it kept the item. ``purpose`` labels the recorded
    call: ``deep_dive`` for items a deep dive reached, so their spend can be held
    to its own daily slice."""
    prompt = prompts.load("judge")
    system = prompt.render(tenets=prompts.tenets())
    completion = llm.complete(
        tier="judge",
        purpose=purpose,
        prompt_version=prompt.version,
        run_uuid=run_uuid,
        # Room for the item and the children it may name; a reply cut off is asked again
        # with twice the room before it counts as an error.
        max_tokens=llm.max_tokens("judge_gathered" if gathered else "judge"),
        retry_truncated=True,
        schema=prompts.schema("judge"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": render_item(item, source_label, topics,
                                                    gathered=gathered,
                                                    gathered_chars=gathered_chars)},
        ],
    )
    outcome, fields = interpret(completion.text, threshold)
    children = (interpret_children(completion.text, threshold, len(gathered))
                if outcome == "contributed" and gathered else [])
    return Verdict(outcome, completion, fields, children)


def interpret_screen(text: str) -> tuple[bool, str]:
    """Whether the screen passed the item, and its reason.

    Only an explicit ``"pass": false`` drops an item. A reply that cannot be read
    passes it on: the screen exists for recall, and the judge decides."""
    obj = extract_json_object(text)
    if obj is None:
        return True, "screen reply unreadable; passed on to the judge"
    verdict = obj.get("pass")
    reason = scrub(" ".join(str(obj.get("reason") or "").split()))[:200]
    if verdict is False or (isinstance(verdict, str) and verdict.strip().lower() in
                            ("false", "no")):
        return False, reason or "dropped"
    return True, reason or "passed"


def screen(
    llm: LLMClient,
    item: Item,
    *,
    source_label: str,
    topics: list[str],
    run_uuid: str | None = None,
) -> Screen:
    """A short, lenient first look at one item. LLM errors propagate."""
    prompt = prompts.load("screen")
    completion = llm.complete(
        tier="judge",
        purpose="screen",
        prompt_version=prompt.version,
        run_uuid=run_uuid,
        max_tokens=llm.max_tokens("screen"),
        retry_truncated=True,
        schema=prompts.schema("screen"),
        messages=[
            {"role": "system", "content": prompt.render(tenets=prompts.tenets())},
            {"role": "user", "content": render_screen_item(item, source_label, topics)},
        ],
    )
    passed, reason = interpret_screen(completion.text)
    return Screen(passed, reason, completion)


# Short posts screened together: from these kinds, a body this short with no
# comments.
SHORT_POST_KINDS = frozenset({"x", "bluesky", "mastodon"})
SHORT_POST_CHARS = 600


def short_post(item: Item) -> bool:
    return len(item.body or "") < SHORT_POST_CHARS and not item.comments


def render_screen_batch(items: list[Item], source_label: str, topics: list[str]) -> str:
    return json.dumps({
        "source": source_label,
        "topics_this_source_is_watched_for": topics,
        "posts": [{"ref": i, **_item_payload(item, SCREEN_BODY_CHARS, [])}
                  for i, item in enumerate(items, 1)],
    }, ensure_ascii=False, indent=1)


def interpret_screen_batch(text: str, n: int) -> list[tuple[bool, str]]:
    """One (passed, reason) per post, in ref order. Only an explicit ``"pass": false`` for a
    ref drops its post; a ref the reply leaves out, or a reply that cannot be read, passes
    (the screen exists for recall)."""
    out = [(True, "not in the screen's reply; passed on to the judge")] * n
    obj = extract_json_object(text)
    verdicts = obj.get("verdicts") if isinstance(obj, dict) else None
    if not isinstance(verdicts, list):
        return [(True, "screen reply unreadable; passed on to the judge")] * n
    for v in verdicts:
        if not isinstance(v, dict):
            continue
        try:
            ref = int(v.get("ref"))
        except (TypeError, ValueError):
            continue
        if 1 <= ref <= n:
            out[ref - 1] = interpret_screen(json.dumps({"pass": v.get("pass"),
                                                         "reason": v.get("reason")}))
    return out


def screen_batch(
    llm: LLMClient,
    items: list[Item],
    *,
    source_label: str,
    topics: list[str],
    run_uuid: str | None = None,
) -> list[Screen]:
    """The first look for several short posts in one call; every Screen shares its
    completion (and so its call id). LLM errors propagate."""
    prompt = prompts.load("screen_batch")
    completion = llm.complete(
        tier="judge",
        purpose="screen",
        prompt_version=prompt.version,
        run_uuid=run_uuid,
        # each verdict is about 30 tokens; the screen's own ceiling for one, and room per post
        max_tokens=llm.max_tokens("screen") + 60 * len(items),
        retry_truncated=True,
        schema=prompts.schema("screen_batch"),
        messages=[
            {"role": "system", "content": prompt.render(tenets=prompts.tenets())},
            {"role": "user", "content": render_screen_batch(items, source_label, topics)},
        ],
    )
    return [Screen(p, r, completion)
            for p, r in interpret_screen_batch(completion.text, len(items))]
