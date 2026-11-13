"""The span and the trace: MLflow's span model, which is OpenTelemetry's
with inputs and outputs first-class, and Kranto's kinds.

A **trace** is one run; its id names the source and the run (``build:beliefline/1``,
``session:<tid>``). Its state is ``running``, ``ok``, ``error`` or ``stopped`` (a budget,
turn or timeout stop, a killed session). A **span** is one step: ``run``, ``stage``,
``session``, ``turn`` (one API response), ``tool`` (a call and its result), ``subagent``,
``hook`` (a kranto-mod row), ``call`` (a one-shot model call: cost and tokens, no payload) or
``event`` (a moment: a retry, a denial, a question, a hold).

Ids are stable across reads and across a transcript's move from the workspace into
``transcripts/``: they hash the trace id with what the line itself names (the session id and
its init line's uuid, a message id, a tool_use id, a line's uuid), never a path.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

KINDS = ("run", "stage", "session", "turn", "tool", "subagent", "hook", "call", "event")
STATES = ("running", "ok", "error", "stopped")
PREVIEW = 240                 # characters of an input or output shown in a list or tree
USD_KINDS = ("exact", "share", "none")


def span_id(trace: str, key: str) -> str:
    """16 hex characters, stable for ``(trace, key)``."""
    return hashlib.sha1(f"{trace}|{key}".encode()).hexdigest()[:16]


def parse_trace_id(tid: str) -> tuple[str, str, int | None]:
    """``("build", "beliefline", 1)`` for ``build:beliefline/1`` (``maint:`` alike);
    ``("session", tid, None)`` for ``session:<tid>`` (``research:<stem>`` alike). ValueError for
    anything else."""
    src, sep, rest = str(tid or "").partition(":")
    if not sep or not rest or src not in ("build", "maint", "session", "research", "afk",
                                          "loop"):
        raise ValueError(f"not a trace id: {tid!r}")
    if src in ("session", "research", "afk", "loop"):
        return src, rest, None
    key, sep, n = rest.rpartition("/")
    if not sep or not key or not n.isdigit():
        raise ValueError(f"not a trace id: {tid!r}")
    return src, key, int(n)


def tokens(u: dict | None) -> dict | None:
    """A ``message.usage`` (or a ledger row) as ``{in, cache_read, cache_write, out}``; None
    when it has none. ``in`` is the uncached input only, as the API counts it."""
    if not isinstance(u, dict):
        return None
    keys = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens",
            "output_tokens")
    if not any(isinstance(u.get(k), int) for k in keys):
        return None
    return {"in": int(u.get("input_tokens") or 0),
            "cache_read": int(u.get("cache_read_input_tokens") or 0),
            "cache_write": int(u.get("cache_creation_input_tokens") or 0),
            "out": int(u.get("output_tokens") or 0)}


def add_tokens(a: dict | None, b: dict | None) -> dict | None:
    if not b:
        return a
    if not a:
        return dict(b)
    return {k: int(a.get(k) or 0) + int(b.get(k) or 0) for k in set(a) | set(b)}


def tokens_in(t: dict | None) -> int:
    """Every input token, cached or not (the trace head's "in")."""
    if not t:
        return 0
    return int(t.get("in") or 0) + int(t.get("cache_read") or 0) + int(t.get("cache_write") or 0)


@dataclass
class Span:
    id: str
    trace: str
    parent: str | None
    kind: str
    name: str
    stage: str | None = None
    start: float | None = None
    end: float | None = None
    status: str = "unset"               # ok · unset · error · running
    error: dict | None = None           # {type, message}
    preview: str = ""                   # the input's (or output's) first words, redacted later
    inputs: dict | None = None          # a payload reference: {file, from, to, part, bytes}
    outputs: dict | None = None
    attrs: dict = field(default_factory=dict)
    events: list = field(default_factory=list)
    links: list = field(default_factory=list)
    source: dict | None = None          # {file, line}: where the span's line is
    usd: float | None = None
    usd_kind: str = "none"
    tokens: dict | None = None
    seq: int = 0                        # the order spans were made in (ties on start)
    depth: int = 0
    children: int = 0
    pos: int = 0                        # the place in the tree's depth-first order

    def summary(self) -> dict:
        """The ``SpanSummary`` record, unredacted: the caller redacts."""
        return {"id": self.id, "parent": self.parent, "kind": self.kind, "name": self.name,
                "stage": self.stage, "start": self.start, "end": self.end,
                "status": self.status, "preview": self.preview, "usd": self.usd,
                "usd_kind": self.usd_kind, "tokens": self.tokens, "children": self.children,
                "depth": self.depth, "pos": self.pos,
                "error": (self.error or {}).get("message") if self.error else None,
                "tool": self.attrs.get("tool"), "denied": bool(self.attrs.get("denied"))}

    def full(self) -> dict:
        """The ``Span`` record: the summary with attributes, events, links and the payload
        references' sizes (never their bodies)."""
        out = self.summary()
        out.update(attributes=self.attrs, events=self.events, links=self.links,
                   inputs=_ref(self.inputs), outputs=_ref(self.outputs), source=self.source,
                   error_detail=self.error)
        return out


def _ref(r: dict | None) -> dict | None:
    if not r:
        return None
    return {"bytes": r.get("bytes"), "part": r.get("part")}
