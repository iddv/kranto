"""Explain what a neighbourhood or a cluster has in common.

Always an explicit request, never automatic. One tier-2 call, cached by the
exact inputs (the sorted observation ids, the prompt version and the model),
so asking the same question twice costs nothing. Observation text is
truncated and framed as data to bound prompt injection; the output is checked
for length and markup, and citations that do not resolve are removed.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass

from .. import library, prompts
from ..llm import LLMClient
from ..map import read as map_read
from ..search import Index, similar_to
from ..store import Store, iso, utcnow
from ..stored.cards import SynthesisInputIds

MAX_INPUTS = 10
INPUT_CHARS = 300
MIN_CHARS = 120
MAX_CHARS = 2000
_CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
_MARKUP = re.compile(r"```|<\/?[a-zA-Z][^>]*>")


class ExplainError(Exception):
    pass


@dataclass(frozen=True)
class Synthesis:
    id: int
    text: str
    input_ids: list[int]
    cached: bool
    subject: str


def clean_citations(text: str, n_inputs: int) -> str:
    def keep(match: re.Match) -> str:
        nums = [int(x) for x in re.split(r"\s*,\s*", match.group(1))]
        valid = [str(x) for x in nums if 1 <= x <= n_inputs]
        return f"[{', '.join(valid)}]" if valid else ""

    return re.sub(r"\s+([.,;])", r"\1", _CITATION.sub(keep, text)).strip()


def validate(text: str, n_inputs: int) -> str:
    text = " ".join((text or "").split())
    if _MARKUP.search(text):
        raise ExplainError("the model returned markup")
    if not MIN_CHARS <= len(text) <= MAX_CHARS:
        raise ExplainError(f"the model returned {len(text)} characters")
    return clean_citations(text, n_inputs)


def _render(rows: list) -> str:
    lines = []
    for i, r in enumerate(rows, 1):
        summary = " ".join(r["summary"].split())[:INPUT_CHARS]
        lines.append(f"[{i}] ({r['source_label'] or 'unknown source'}) {summary}")
    return "\n".join(lines)


def cached(store: Store, subject: str):
    return store.query_one(
        "SELECT * FROM syntheses WHERE subject = ? ORDER BY id DESC LIMIT 1", (subject,)
    )


def explain(store: Store, llm: LLMClient, *, kind: str, subject: str,
            ids: list[int], offline: bool = False) -> Synthesis | None:
    """The explanation of ``ids``: from the cache when the same inputs, prompt and model were
    explained before, else from one model call. ``offline``: never call the model (a request
    reads the cache this way; the call itself runs in the background, ``web/jobs.py``), and
    None when nothing is cached."""
    ids = ids[:MAX_INPUTS]
    by_id = library.observations_by_id(store, ids)
    rows = [by_id[i] for i in ids if i in by_id]
    if len(rows) < 2:
        raise ExplainError("need at least two observations to compare")
    prompt = prompts.load("explain")
    model = llm.model_for("reason")
    key = hashlib.sha256(
        json.dumps([kind, sorted(r["id"] for r in rows), prompt.version, model]).encode()
    ).hexdigest()
    hit = store.query_one("SELECT * FROM syntheses WHERE cache_key = ?", (key,))
    if hit:
        return Synthesis(hit["id"], hit["text"], SynthesisInputIds.load(hit["input_ids"]).items,
                         True, subject)
    if offline:
        return None

    completion = llm.complete(
        tier="reason", purpose="explain", prompt_version=prompt.version,
        messages=[{"role": "user", "content": prompt.render(observations=_render(rows))}],
        # 500 cut off 3 of 15 explanations mid-word; a truncated reply now
        # raises instead of being validated and cached.
        max_tokens=llm.max_tokens("explain"), temperature=0.3,
    )
    text = validate(completion.text, len(rows))
    input_ids = [r["id"] for r in rows]
    syn_id = store.insert("syntheses", {
        "cache_key": key, "kind": kind, "subject": subject,
        "input_ids": SynthesisInputIds.write(input_ids),
        "text": text, "llm_call_id": completion.call_id, "created_at": iso(utcnow()),
    })
    return Synthesis(syn_id, text, input_ids, False, subject)


def explain_neighbourhood(store: Store, llm: LLMClient, index: Index, observation_id: int,
                          k: int = 7, offline: bool = False) -> Synthesis | None:
    neighbours = [h.observation_id for h in similar_to(index, observation_id, k=k)]
    return explain(store, llm, kind="neighbourhood", subject=f"obs:{observation_id}",
                   ids=[observation_id, *neighbours], offline=offline)


def explain_cluster(store: Store, llm: LLMClient, snapshot_id: int, cluster: int,
                    offline: bool = False) -> Synthesis | None:
    rows = [c for c in map_read.clusters(store, snapshot_id) if c["cluster"] == cluster]
    if not rows:
        raise ExplainError(f"no cluster {cluster} in snapshot {snapshot_id}")
    reps = rows[0]["representatives"]
    top = [r["observation_id"] for r in store.query(
        "SELECT p.observation_id FROM snapshot_points p JOIN observations o "
        "ON o.id = p.observation_id WHERE p.snapshot_id = ? AND p.cluster = ? "
        "ORDER BY o.signal DESC LIMIT 10", (snapshot_id, cluster))]
    ids = list(dict.fromkeys([*reps, *top]))
    return explain(store, llm, kind="cluster",
                   subject=f"cluster:{rows[0]['lineage_id']}", ids=ids, offline=offline)
