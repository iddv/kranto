"""The frozen eval set: cut from a backup of a library's own history, scrubbed,
split, versioned, and never written by a run.

A set is a directory::

    manifest.json              counts, prompt versions, models, the split rule, where it came from
    watching/screen.jsonl      recorded screen calls
    watching/judge.jsonl       recorded judge calls (every one whose observation the owner graded)
    ideas/cards.jsonl          every card the writer wrote, with its inputs and the owner's grade

One item a line: ``{id, stage, step, split, model, prompt_version, at, source, messages,
reply, inputs, recorded, usage, owner}``. ``messages`` are what was sent (system and user),
``reply`` what came back, ``recorded`` what the code drew from the reply when it ran, ``owner``
the owner's latest grade on what the call produced (``{value, reasons, at}``) or null.
``inputs`` are the prompt's own fields read back out of the sent text when the recorded
version is the shipped one (so a candidate prompt can be rendered with them), else null.

**Split:** one in three items is held out by a hash of its stable id; every owner-graded item
is held (the grades are what a candidate must not be tuned to). **Rotation** (D5): when a set
grows, held items older than 90 days move to dev and the newly graded ones are held.
**Scrubbing:** every message and reply through ``kranto.scrub`` and a bearer-token mask;
then a scan of the written files for secret-shaped strings fails the build.

A set is read from a SQLite backup and the live database is never opened for writing: give
``--from`` a backup (``kranto backup``), or the live file, which is copied first with SQLite's
own backup from a read-only connection."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import string
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .. import prompts, scrub
from ..ideate.cards import parse_card
from ..intern import interpret, interpret_screen
from ..stored.cards import InputIds
from ..stored.misc import FeedbackReasons

HELD_SHARE = 3
ROTATE_DAYS = 90
STEPS = {"screen": "watching/screen.jsonl", "judge": "watching/judge.jsonl",
         "card": "ideas/cards.jsonl"}
STAGE_OF = {"screen": "watching", "judge": "watching", "card": "ideas"}
BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{8,}")
# A written set is scanned for these; any hit fails the build (the scrubber missed one).
SECRET_SHAPES = (r"\bsk-(?:or-v1-|ant-|proj-)?[A-Za-z0-9_-]{20,}", r"\bgh[pousr]_[A-Za-z0-9]{20,}",
                 r"\bgithub_pat_[A-Za-z0-9_]{40,}", r"\bxai-[A-Za-z0-9]{20,}",
                 r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}", r"\bAKIA[0-9A-Z]{16}\b")


class SetError(ValueError):
    """A set that can't be built, read or grown, with the reason."""


def split_of(stable_id: str) -> str:
    h = int(hashlib.sha256(stable_id.encode()).hexdigest()[:8], 16)
    return "held" if h % HELD_SHARE == 0 else "dev"


def clean(text: str | None) -> str:
    return BEARER.sub("[bearer]", scrub.scrub(text or ""))


def reply_text(response: str | None) -> str | None:
    """The model's text out of a recorded response, whichever provider sent it."""
    from ..providers.replay import _reply_text
    return _reply_text(response)


def messages_of(request: str | None) -> list[dict] | None:
    """A recorded request as ``[{role, content}]``, system first, scrubbed; only the turns
    (never the request's ``user``, ``metadata`` or header-like keys)."""
    from ..providers.replay import _messages
    try:
        req = json.loads(request or "")
    except ValueError:
        return None
    if not isinstance(req, dict):
        return None
    turns = _messages(req)
    if not turns:
        return None
    out = []
    for m in turns:
        c = m.get("content")
        if isinstance(c, list):
            c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
        out.append({"role": str(m.get("role") or "user"), "content": clean(str(c or ""))})
    return out


def max_tokens_of(request: str | None) -> int | None:
    try:
        v = json.loads(request or "").get("max_tokens")
    except (ValueError, AttributeError):
        return None
    return int(v) if isinstance(v, int | float) else None


def template_fields(template: str, text: str) -> dict | None:
    """The values ``template.format(**values)`` was given to produce ``text`` (literal parts
    must match exactly), or None when ``text`` was not rendered from ``template``."""
    parts, pattern, names = list(string.Formatter().parse(template)), "", []
    for literal, field, _spec, _conv in parts:
        pattern += re.escape(literal.replace("{{", "{").replace("}}", "}"))
        if field is not None:
            if field in names:
                pattern += f"(?P={field})"
            else:
                names.append(field)
                pattern += f"(?P<{field}>[\\s\\S]*?)"
    m = re.fullmatch(pattern, text)
    return dict(m.groupdict()) if m else None


def inputs_of(step: str, prompt_version: str, messages: list[dict]) -> dict | None:
    """The shipped prompt's fields read back out of what was sent, when the recorded call used
    the shipped prompt (its version); None otherwise."""
    name = "card" if step == "card" else step
    shipped = prompts.Prompt(name, prompts.default_text(name))
    if prompt_version != shipped.version:
        return None
    if step == "card":
        user = next((m["content"] for m in messages if m["role"] == "user"), None)
        return template_fields(shipped.template, user) if user is not None else None
    system = next((m["content"] for m in messages if m["role"] == "system"), None)
    if system is None:
        return None
    vals = template_fields(shipped.template, system)
    return {"user": next((m["content"] for m in messages if m["role"] == "user"), "")} \
        if vals is not None else None


# -- reading a backup ---------------------------------------------------------------------------


def open_backup(path: Path) -> sqlite3.Connection:
    """A read-only connection to a copy of the database at ``path`` (an in-memory copy made
    with SQLite's backup from a read-only connection: the file is never written)."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise SetError(f"no database at {path}")
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        mem = sqlite3.connect(":memory:")
        src.backup(mem)
    finally:
        src.close()
    mem.row_factory = sqlite3.Row
    return mem


def grades(c: sqlite3.Connection) -> dict[tuple[str, str], dict]:
    """The latest grade per ``(target, id)``; a cleared grade (skip) counts as none."""
    out: dict[tuple[str, str], dict] = {}
    for r in c.execute("SELECT target, target_id, value, reasons, created_at FROM feedback "
                       "WHERE kind = 'grade' ORDER BY id"):
        try:
            reasons = FeedbackReasons.load(r["reasons"]).items
        except ValueError:
            reasons = []
        out[(r["target"], str(r["target_id"]))] = {"value": r["value"], "reasons": reasons,
                                                    "at": r["created_at"]}
    return {k: v for k, v in out.items() if v["value"] != "skip"}


def _usage(r) -> dict:
    return {"in": r["prompt_tokens"], "out": r["completion_tokens"], "usd": r["cost_usd"],
            "ms": r["latency_ms"]}


def _base(r, step: str, messages: list[dict], text: str, split: str, owner) -> dict:
    return {"id": f"{step}-{r['id']}", "stage": STAGE_OF[step], "step": step, "split": split,
            "model": r["model"], "prompt_version": r["prompt_version"], "at": r["created_at"],
            "messages": messages, "reply": clean(text),
            "inputs": inputs_of(step, r["prompt_version"], messages),
            "max_tokens": max_tokens_of(r["request"]), "usage": _usage(r), "owner": owner}


CALL_COLS = ("l.id, l.model, l.prompt_version, l.request, l.response, l.created_at, "
             "l.prompt_tokens, l.completion_tokens, l.cost_usd, l.latency_ms")


def build_screens(c, n: int, since: str | None = None) -> list[dict]:
    rows = c.execute(
        f"SELECT {CALL_COLS}, i.outcome, i.source_id, i.item_id, s.kind AS source_kind, "
        "s.label AS source_label FROM llm_calls l "
        "LEFT JOIN items_seen i ON i.screen_call_id = l.id "
        "LEFT JOIN sources s ON s.id = i.source_id "
        "WHERE l.purpose = 'screen' AND l.status = 'ok' AND l.created_at >= ? "
        "ORDER BY l.id DESC LIMIT ?", (since or "", n * 2)).fetchall()
    out = []
    for r in rows:
        msgs, text = messages_of(r["request"]), reply_text(r["response"])
        if not msgs or text is None:
            continue
        passed, reason = interpret_screen(text)
        it = _base(r, "screen", msgs, text, split_of(f"screen-{r['source_id']}-{r['item_id']}"),
                   None)
        it["source"] = {"kind": r["source_kind"], "label": r["source_label"]}
        it["recorded"] = {"passed": passed, "reason": reason, "outcome": r["outcome"]}
        out.append(it)
        if len(out) >= n:
            break
    return out


def build_judges(c, n: int, gr: dict, threshold: float, since: str | None = None) -> list[dict]:
    graded = sorted({int(k[1]) for k in gr if k[0] == "observation" and k[1].isdigit()})
    base = (f"SELECT {CALL_COLS}, i.outcome, i.source_id, i.item_id, s.kind AS source_kind, "
            "s.label AS source_label, o.id AS obs_id, o.kind AS obs_kind, o.signal AS obs_signal, "
            "o.override FROM llm_calls l LEFT JOIN items_seen i ON i.llm_call_id = l.id "
            "LEFT JOIN sources s ON s.id = i.source_id "
            "LEFT JOIN observations o ON o.llm_call_id = l.id "
            "WHERE l.purpose = 'judge' AND l.status = 'ok' ")
    rows = list(c.execute(base + f"AND o.id IN ({','.join('?' * len(graded))})", graded)) \
        if graded else []
    seen = {r["id"] for r in rows}
    newest = 0
    for r in c.execute(base + "AND l.created_at >= ? ORDER BY l.id DESC LIMIT ?",
                       (since or "", n * 2)):
        if newest >= n:
            break
        if r["id"] not in seen:
            rows.append(r)
            seen.add(r["id"])
            newest += 1
    out = []
    for r in rows:
        msgs, text = messages_of(r["request"]), reply_text(r["response"])
        if not msgs or text is None:
            continue
        outcome, fields = interpret(text, threshold)
        owner = gr.get(("observation", str(r["obs_id"]))) if r["obs_id"] else None
        it = _base(r, "judge", msgs, text, "held" if owner else
                   split_of(f"judge-{r['source_id']}-{r['item_id']}"), owner)
        it["source"] = {"kind": r["source_kind"], "label": r["source_label"]}
        it["recorded"] = {"outcome": outcome, "items_seen": r["outcome"],
                          "kind": (fields or {}).get("kind"),
                          "observation": ({"id": r["obs_id"], "kind": r["obs_kind"],
                                           "signal": r["obs_signal"], "override": r["override"]}
                                          if r["obs_id"] else None)}
        out.append(it)
    return out


def build_cards(c, gr: dict, since: str | None = None) -> list[dict]:
    out = []
    for r in c.execute(
            f"SELECT {CALL_COLS}, i.id AS idea_id, i.title, i.origin, i.status, i.input_ids "
            "FROM ideas i JOIN llm_calls l ON l.id = i.gen_call_id WHERE l.created_at >= ? "
            "ORDER BY i.id", (since or "",)):
        msgs, text = messages_of(r["request"]), reply_text(r["response"])
        if not msgs or text is None:
            continue
        n_inputs = len(InputIds.load(r["input_ids"]).items)
        status, card = parse_card(text, n_inputs)
        owner = gr.get(("idea", str(r["idea_id"])))
        it = _base(r, "card", msgs, text, "held" if owner else split_of(f"card-{r['idea_id']}"),
                   owner)
        it["id"] = f"card-{r['idea_id']}"
        it.update(origin=r["origin"], n_inputs=n_inputs,
                  recorded={"status": status, "title": (card or {}).get("title"),
                            "stored_status": r["status"], "stored_title": r["title"]})
        out.append(it)
    return out


# -- writing and reading a set ------------------------------------------------------------------


def write_items(path: Path, items: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False, sort_keys=True) + "\n")


def load_items(set_dir: Path, step: str) -> list[dict]:
    p = Path(set_dir) / STEPS[step]
    if not p.is_file():
        return []
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def load_manifest(set_dir: Path) -> dict:
    p = Path(set_dir) / "manifest.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        raise SetError(f"{set_dir} is not an eval set (no manifest.json)") from None


def secret_hits(set_dir: Path) -> list[str]:
    hits = []
    for p in sorted(Path(set_dir).rglob("*.jsonl")):
        text = p.read_text()
        for pat in SECRET_SHAPES:
            n = len(re.findall(pat, text))
            if n:
                hits.append(f"{p.relative_to(set_dir)}: {n} match(es) of {pat}")
    return hits


def summary(items: list[dict]) -> dict:
    return {"n": len(items), "held": sum(i["split"] == "held" for i in items),
            "owner_graded": sum(1 for i in items if i.get("owner")),
            "prompt_versions": sorted({i["prompt_version"] for i in items if i["prompt_version"]}),
            "models": sorted({i["model"] for i in items if i["model"]})}


def _write_set(out: Path, items: dict[str, list[dict]], meta: dict) -> dict:
    out = Path(out)
    if (out / "manifest.json").exists():
        raise SetError(f"{out} already holds a set: a set is never rewritten (grow makes the "
                       "next version)")
    for step, path in STEPS.items():
        write_items(out / path, items.get(step) or [])
    manifest = {**meta, "version": out.name,
                "built_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "scrubbed": "kranto.scrub on every message and reply; bearer tokens masked; "
                            "only the request's turns kept",
                "split": f"held when sha256(stable id) % {HELD_SHARE} == 0; owner-graded items "
                         "are always held",
                **{STEPS[s].removesuffix(".jsonl"): summary(items.get(s) or []) for s in STEPS}}
    hits = secret_hits(out)
    manifest["secret_shaped"] = len(hits)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    if hits:
        raise SetError("secret-shaped strings left in the set (it must not be used): "
                       + "; ".join(hits[:5]))
    return manifest


def build(db: Path, out: Path, *, screens: int = 60, judges: int = 40, threshold: float,
          since: str | None = None, source: str | None = None) -> dict:
    """``kranto eval set build``: a new set at ``out`` from the database at ``db``."""
    c = open_backup(db)
    try:
        gr = grades(c)
        items = {"screen": build_screens(c, screens, since),
                 "judge": build_judges(c, judges, gr, threshold, since),
                 "card": build_cards(c, gr, since)}
    finally:
        c.close()
    return _write_set(out, items, {"from": source or f"a read-only copy of {Path(db).name}",
                                   "judge_threshold": threshold, "parent": None})


def grow(prev: Path, db: Path, out: Path, *, screens: int = 60, judges: int = 40,
         threshold: float | None = None, now: datetime | None = None) -> dict:
    """``kranto eval set grow``: the next version, ``out``, from ``prev`` and the database: every
    item of ``prev``; every new owner grade's item, held; the newest ungraded calls up to the
    size of ``prev``'s steps; held items older than 90 days rotated to dev (D5)."""
    pm = load_manifest(prev)
    thr = float(threshold if threshold is not None else pm.get("judge_threshold", 0.03))
    c = open_backup(db)
    try:
        gr = grades(c)
        fresh = {"screen": build_screens(c, screens), "judge": build_judges(c, judges, gr, thr),
                 "card": build_cards(c, gr)}
    finally:
        c.close()
    cutoff = ((now or datetime.now(UTC)) - timedelta(days=ROTATE_DAYS)).strftime("%Y-%m-%d")
    items: dict[str, list[dict]] = {}
    rotated = added = 0
    for step in STEPS:
        old = load_items(prev, step)
        have = {i["id"] for i in old}
        for it in old:
            if it["split"] == "held" and (it.get("at") or "") < cutoff \
                    and not (it.get("owner") and (it["owner"].get("at") or "") >= cutoff):
                it["split"] = "dev"
                rotated += 1
        cap = max(len(old), {"screen": screens, "judge": judges}.get(step, len(old)))
        new = [i for i in fresh[step] if i["id"] not in have]
        graded = [i for i in new if i.get("owner")]
        rest = [i for i in new if not i.get("owner")][:max(0, cap - len(old) - len(graded))]
        added += len(graded) + len(rest)
        # an older item graded since: its grade is the point (held)
        by_id = {i["id"]: i for i in fresh[step] if i.get("owner")}
        for it in old:
            if it["id"] in by_id and it.get("owner") != by_id[it["id"]]["owner"]:
                it["owner"], it["split"] = by_id[it["id"]]["owner"], "held"
        items[step] = old + graded + rest
    return _write_set(out, items, {"from": pm.get("from"), "parent": pm.get("version"),
                                   "judge_threshold": thr,
                                   "grown": {"added": added, "rotated_to_dev": rotated}})


def show(set_dir: Path) -> dict:
    m = load_manifest(set_dir)
    return {"version": m.get("version"), "built_at": m.get("built_at"), "from": m.get("from"),
            "parent": m.get("parent"),
            "steps": {s: summary(load_items(set_dir, s)) for s in STEPS}}
