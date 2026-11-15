"""The shapes of the API's answers the page reads, as TypedDicts: the one source
the web UI's TypeScript types are generated from (``scripts/dev/gen_page_ts.py`` writes
``ui/web/src/api/types.gen.ts``; a test fails when it is stale), and checked against the real
answers on the fake app at test time (``tests/page/test_api_types.py``), so neither side can drift
without a red test.

``OPEN`` names the types whose answers may carry more keys than are written here (the rows
the page still reads untyped, until its page moves); every key written here must still be
there with its type. ``RETURNS`` maps the paths the page reads to what they answer.

Standard library only; nothing here runs on a request. (No ``from __future__ import
annotations``: TypedDict reads ``NotRequired`` only from evaluated annotations.)
"""
import types
import typing
from typing import Any, Literal, NotRequired, TypedDict

# -- the shell's reads -----------------------------------------------------------------------


class WhoAmI(TypedDict):
    """``/api/whoami``: who this browser is signed in as (``origin`` None: not signed in)."""
    origin: str | None
    via: str | None
    require_token: bool
    signin: str


class Header(TypedDict):
    """``api/header``: what a host's header shows."""
    api_version: int
    paused: bool
    running: int
    queued: int
    revising: int
    needs_you: int
    open_ideas: int
    onboarding: list[Any]


# -- agent traces: every string redacted on read -----------------------------

TraceState = Literal["running", "ok", "error", "stopped"]
SpanKind = Literal["run", "stage", "session", "turn", "tool", "subagent", "hook", "call", "event"]
SpanStatus = Literal["ok", "unset", "error", "running"]
UsdKind = Literal["exact", "share", "none"]


class TraceSummary(TypedDict):
    """One trace (``api/traces``' rows): its state, cost (exact only), counts, where it failed
    and its page. ``tokens``: ``in`` counts cached input too."""
    id: str
    source: str
    key: str
    n: int | None
    title: str
    state: TraceState
    outcome: str | None
    started: float | None
    ended: float | None
    wall_s: float | None
    usd: float | None
    usd_kind: UsdKind
    tokens: dict[str, int] | None
    sessions: int
    tools: int
    errors: int
    failed_at: str | None
    failed_label: str | None
    model: str | None
    spans: int | None
    href: str | None                 # None: a trace that no longer opens (the build loop's)
    calls: NotRequired[int]          # a Watching run's model calls (its work is not sessions)


class TraceList(TypedDict):
    """``api/traces``: newest first; ``next``: the cursor of the next page."""
    traces: list[TraceSummary]
    next: str | None


class SpanSummary(TypedDict):
    """A span's row in the tree (``pos``: its place in depth-first order; ``rev``: the read
    that last changed it). ``usd_kind`` share: an estimate, never summed."""
    id: str
    parent: str | None
    kind: SpanKind
    name: str
    stage: str | None
    start: float | None
    end: float | None
    status: SpanStatus
    preview: str
    usd: float | None
    usd_kind: UsdKind
    tokens: dict[str, int] | None
    children: int
    depth: int
    pos: int
    error: str | None
    tool: str | None
    denied: bool
    rev: int
    attrs: NotRequired[dict[str, Any]]


class TraceLink(TypedDict):
    """The outcome linked to its span: a held gate's check (``hold``) or a failed scenario
    (``check``); ``span`` None with a ``note`` when the trace does not hold its run."""
    kind: str
    ref: str | None
    span: str | None
    note: str | None
    detail: str | None
    file: NotRequired[str | None]


class TraceFile(TypedDict):
    rel: str
    bytes: int
    mtime: float
    offset: int | None
    pruned: bool


class TraceStop(TypedDict):
    """A running run's Stop: the id ``api/activity/stop`` takes."""
    id: str


class TraceDetail(TraceSummary):
    """``api/trace``: the summary, its stages, the outcome's links, its files and the cursor
    a live page reads on from. ``note``: why the trace is short or stops, in a sentence (a
    session that kept no transcript or went on outside, a run with no model calls), else None."""
    stages: list[SpanSummary]
    links: list[TraceLink]
    files: list[TraceFile]
    cursor: str
    running: bool
    note: str | None
    line: str | None              # a server run's plain head line, else None
    stop: TraceStop | None        # its Stop while it runs (``api/activity/stop``), else None


class SpanPage(TypedDict):
    """``api/trace/spans``: a page in tree order (with the shown spans that changed since the
    cursor), or a branch (``parent=``), or a filter's spans with their ancestors (``matches``:
    the spans that matched)."""
    spans: list[SpanSummary]
    cursor: str
    more: bool
    total: int
    rev: int
    running: NotRequired[bool]
    matches: NotRequired[list[str]]


class TraceHit(TypedDict):
    """A span whose payload holds the words: which part, and the words around them, redacted."""
    span: str
    part: str
    preview: str


class TraceSearch(TypedDict):
    """``api/trace/search?trace=&q=``: every payload of the trace searched (its files, bounded
    to the trace), the hits in tree order, at most 500 (``more``: there were more);
    ``scanned``: the bytes read."""
    hits: list[TraceHit]
    more: bool
    scanned: int
    rev: int


class Redaction(TypedDict):
    kind: str
    n: int


class SpanDetail(SpanSummary):
    """``api/trace/span``: one span whole, without payload bodies (``inputs``/``outputs``:
    their sizes); ``path``: the file its line is in."""
    attributes: dict[str, Any]
    events: list[dict[str, Any]]
    links: list[dict[str, Any]]
    inputs: dict[str, Any] | None
    outputs: dict[str, Any] | None
    source: dict[str, Any]
    error_detail: dict[str, Any] | None
    path: str | None
    redactions: list[Redaction]


class PayloadField(TypedDict):
    key: str
    value: str


class ChatMessage(TypedDict):
    """One message of a session's conversation: ``you``, ``claude`` or ``tool``."""
    role: str
    kind: str
    text: str
    ts: str | None
    i: int
    span: NotRequired[str]
    tool: NotRequired[str]
    cut: NotRequired[bool]
    is_error: NotRequired[bool]


class DiffHunk(TypedDict):
    header: str
    lines: list[str]


class TracePayload(TypedDict):
    """``api/trace/payload``: one part of a span, redacted: ``text`` paged (``next``),
    ``fields`` (a tool's arguments), ``messages`` (the chat) or ``hunks`` (a diff)."""
    redactions: list[Redaction]
    text: NotRequired[str]
    offset: NotRequired[int]
    next: NotRequired[int | None]
    bytes: NotRequired[int]
    is_error: NotRequired[bool]
    running: NotRequired[bool]
    stderr: NotRequired[str]
    stderr_from: NotRequired[int]
    fields: NotRequired[list[PayloadField]]
    messages: NotRequired[list[ChatMessage]]
    total: NotRequired[int]
    focus: NotRequired[int | None]
    file_path: NotRequired[str]
    hunks: NotRequired[list[DiffHunk]]
    added: NotRequired[int | None]
    removed: NotRequired[int | None]
    new_file: NotRequired[bool]
    hidden: NotRequired[str]


# -- what Kranto is doing (/api/activity,) --------------------------------------

RunState = Literal["running", "waiting", "ok", "degraded", "failed", "skipped", "stopped"]


class RunTrigger(TypedDict):
    origin: str
    by: str | None
    at: str | None


class RunSubject(TypedDict):
    kind: str
    id: str | None
    name: str | None


class RunProgress(TypedDict):
    step: int | None
    steps: int | None


class RunNeeds(TypedDict):
    """Where a waiting run's press is: the verb and the route (``cub/toot?sel=o4``)."""
    verb: NotRequired[str]
    href: NotRequired[str]
    words: NotRequired[str]


class ActivityRun(TypedDict):
    """One run, in words: the server's (``afk:<uuid>``), the loop's (``loop:<id>``), a build
    (``build:<key>``), a detached job (``pid:<n>``), a session (``session:<tid>``)."""
    id: str
    uuid: str
    kind: str
    title: str
    words: str | None
    state: RunState
    trigger: RunTrigger
    subject: RunSubject | None
    feature: str
    started: str | None
    finished: str | None
    elapsed_s: float | None
    usd: float
    calls: int | None
    tokens: dict[str, int] | None
    progress: RunProgress | None
    trace: str | None
    stoppable: bool
    stopping: bool
    needs: RunNeeds | None
    error: str | None
    why: str | None
    verb: str | None
    glyph: NotRequired[str]


class ActivityLast(TypedDict):
    state: str
    at: str | None
    why: str | None


class ActivityNext(TypedDict):
    """A scheduled kind that is on: when it runs next, how often, its last run."""
    kind: str
    title: str
    at: str
    every_words: str
    last: ActivityLast | None
    failing_since: str | None
    failures_in_a_row: int


class ActivityFold(TypedDict):
    """The hourly skipped re-checks and the usage reports, one line a kind."""
    kind: str
    state: str
    n: int
    first: str | None
    last: str | None
    why: str | None
    title: str
    line: str


class ActivityTry(TypedDict):
    uuid: str
    at: str | None
    error: str | None
    trace: str


class ActivityFail(TypedDict):
    """A Fix row: a kind failing twice in a row or for two days, until its next good run."""
    id: str
    kind: str
    title: str
    since: str | None
    last: str | None
    tries: int
    error: str
    verb: str
    trace: str
    runs: list[ActivityTry]
    # the failure kept by its id (the server's rowsafe.note_failure): Send this error files it
    error_id: NotRequired[str]


class IncidentKind(TypedDict):
    kind: str
    title: str
    noun: str
    since: str | None
    tries: int


class ActivityIncident(TypedDict):
    """A blocking incident: a provider's model key refused, from its first
    failure, folding every kind it stops; the verb renews the key. The server 0.6.0.dev5+."""
    id: str
    provider: str
    name: str
    cause: str
    blocking: bool
    title: str
    words: str
    since: str | None
    last: str | None
    tries: int
    kinds: list[IncidentKind]
    error: str
    verb: str
    href: str
    trace: str
    error_id: NotRequired[str]
    # a feature's blocked states (the server): the top bar's own words and the band's tone
    # (amber: a feature stopped, not blocking); a key incident has neither
    short: NotRequired[str]
    tone: NotRequired[str]
    # whether it raises the band (the owner, 2026-10-28: the band is for Kranto itself):
    # Kranto's own (a refused model key, ``auth:``; Kranto's core, ``core:``) is the band's; a
    # feature's or a cub's (a cub stopped) is one Needs you row only. Absent
    # from a server before it: decided by the id's class (lib/activity.ts isBand)
    band: NotRequired[bool]
    # The server 0.6.0.dev15+: the owner may put any incident away (POST
    # api/activity/dismiss {incident}); what makes it go, in words; the failed runs that hold it
    # (a later good call to the provider or a passing key test clears it). Absent from an older
    # the server: no Dismiss, no words, no runs (each reader says nothing)
    dismiss: NotRequired[bool]
    clears: NotRequired[str]
    runs: NotRequired[list["IncidentRun"]]


class IncidentRun(TypedDict):
    uuid: str
    kind: str
    at: str | None
    error: str
    trace: str


class ActivityCounts(TypedDict):
    running: int
    waiting: int
    failed_recent: int
    failing: int
    building: int
    incidents: NotRequired[int]


class ActivityHealth(TypedDict):
    """Kranto's health word and one line why; ``trace`` opens the run it is about."""
    word: Literal["Healthy", "Degraded", "Paused", "Not set up yet", "Reading for the first time"]
    tone: Literal["green", "amber", "grey"]
    reason: str | None
    at: str | None
    run: str | None
    trace: str | None


class Activity(TypedDict):
    """``api/activity``: what runs, what waits on you, what comes next, what ran."""
    seq: int
    running: list[ActivityRun]
    waiting: list[ActivityRun]
    next: list[ActivityNext]
    recent: list[ActivityRun]
    folded: list[ActivityFold]
    failing: list[ActivityFail]
    # empty from a server before the incidents
    incidents: list[ActivityIncident]
    counts: ActivityCounts
    quiet: str | None
    scheduler: bool
    paused: bool
    afk_error: str | None
    now: str | None
    # the status bar's word and why (the server's health.py,); None from a server before it
    health: NotRequired[ActivityHealth | None]


# -- the event stream (/api/stream,): invalidations, never payloads ----------------------

# what ui/live.py's watcher names: the sessions' records, the server's runs and an assistant's
# verbs (its mirrors), and a followed trace's files (the factory's kinds left with it, CUT)
ChangeKind = Literal["activity", "term", "trace", "verb"]


class TraceFollow(TypedDict):
    """``api/trace/follow``: the trace's files are watched until ``until`` (seconds from now);
    a ``change`` of kind ``trace`` says they grew. ``cursor``: where the page reads on from."""
    cursor: str
    running: bool
    until: float


class StreamChange(TypedDict):
    """``event: change``: refetch what these kinds show (``keys``: which, when known)."""
    kinds: list[ChangeKind]
    keys: list[str]
    seq: int


class StreamHost(TypedDict):
    """``event: host``: the server's version; a new one means reload."""
    version: str


OPEN: frozenset[str] = frozenset()

# what the page reads, by the path it asks for (the page's own relative, the server's absolute)
RETURNS: dict[str, type] = {
    "api/header": Header,
    "api/traces": TraceList,
    "api/trace": TraceDetail,
    "api/trace/spans": SpanPage,
    "api/trace/search": TraceSearch,
    "api/trace/span": SpanDetail,
    "api/trace/payload": TracePayload,
    "api/trace/follow": TraceFollow,
    "api/activity": Activity,
    "/api/whoami": WhoAmI,
}


# -- the check ---------------------------------------------------------------------------------

def problems(value: Any, tp: Any, where: str = "$") -> list[str]:
    """Where ``value`` (a decoded JSON answer) does not have the shape ``tp`` says, in words;
    empty when it does."""
    origin, args = typing.get_origin(tp), typing.get_args(tp)
    if tp is Any:
        return []
    if tp is None or tp is type(None):
        return [] if value is None else [f"{where}: {value!r:.40} is not null"]
    if origin is Literal:
        return [] if value in args else [f"{where}: {value!r:.40} is not one of {args}"]
    if origin in (typing.Union, types.UnionType):
        tried = [problems(value, a, where) for a in args]
        return [] if any(not t for t in tried) else min(tried, key=len)
    if origin is list:
        if not isinstance(value, list):
            return [f"{where}: {type(value).__name__} is not a list"]
        return [p for i, v in enumerate(value) for p in problems(v, args[0], f"{where}[{i}]")]
    if origin is dict:
        if not isinstance(value, dict):
            return [f"{where}: {type(value).__name__} is not an object"]
        return [p for k, v in value.items() for p in problems(v, args[1], f"{where}.{k}")]
    if typing.is_typeddict(tp):
        if not isinstance(value, dict):
            return [f"{where}: {type(value).__name__} is not an object ({tp.__name__})"]
        out = [f"{where}: no {k!r} ({tp.__name__})" for k in sorted(tp.__required_keys__)
               if k not in value]
        hints = typing.get_type_hints(tp)
        for k, v in value.items():
            if k in hints:
                out += problems(v, hints[k], f"{where}.{k}")
            elif tp.__name__ not in OPEN:
                out.append(f"{where}: {k!r} is not in {tp.__name__}")
        return out
    if tp is bool:
        return [] if isinstance(value, bool) else [f"{where}: {value!r:.40} is not a boolean"]
    if tp is int:
        ok = isinstance(value, int) and not isinstance(value, bool)
        return [] if ok else [f"{where}: {value!r:.40} is not an integer"]
    if tp is float:
        ok = isinstance(value, int | float) and not isinstance(value, bool)
        return [] if ok else [f"{where}: {value!r:.40} is not a number"]
    if tp is str:
        return [] if isinstance(value, str) else [f"{where}: {value!r:.40} is not a string"]
    raise TypeError(f"problems: no rule for {tp!r} at {where}")
