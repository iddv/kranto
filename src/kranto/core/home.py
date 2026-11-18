"""The home and, until wave 3, the widgets it was made of.

**The home** is one fixed order, answered by ``GET /api/home`` in one read (``today``): the date
and one sentence, today's brief (each topic's brief of the local day, three topics at most, three
items each), the five newest idea cards with how many are new since the last visit, and one quiet
line (topics, sources, the last read, the next result). After ``home.away_days`` days or more
without a visit, ``away`` carries While you were away: the three best cards written in the
absence (by ``taste.rank``, Ideas' own order) and the lead item of the two newest briefs, five
rows at most, chosen by rule from stored rows. The page draws the one thing from the asks and the
prepared items it already reads; ``waiting`` counts them for the sentence.

**The visit marker** is one ``settings`` row, ``home.visit`` (``{"at", "previous"}``), moved by
``POST /api/home/visit`` (``visit``): the ordinary home moves it each time it is drawn, While you
were away only when the owner opens one of its rows or chooses Show today. A visit more than
``SESSION`` after the last starts a new one (``previous`` becomes the last ``at``), so "new since
your last visit" holds still across reloads. Absent (an install from before this, one never
opened) reads as not away and "new" as the last 24 hours. Readers: this module and the page.

**The widgets** are still answered beside it for one wave, so a cub's
widget, ``kranto cub check`` and the SDK's FakeHost keep their contract; the page no longer draws
them, and a stored arrangement is read and ignored by the home. Wave 3 removes them with
``home.arrange``.

- **Built-ins** have an id without a dot (``needs``, ``topic``); the page draws them by hand. The
  first seven are the default home, in 0.5.10's order, so a ``kranto.yaml`` without
  ``shell.widgets`` draws today's home. **Manifest widgets** are ``<feature>.<widget>``, declared
  by a first-party feature or a cub (``ui.widgets``) and drawn by kind from their read's answer.
- **The read** (``read``): the arrangement resolved, the library, and ``slots``: each manifest
  widget's answer, checked and capped by ``bears_cub.widgets.clean``, and the cubs' rows for Needs
  you and New today. Reads run on a small pool with a budget (2 s): a read that has not answered
  by then is ``loading`` (or ``stale``, with the last good answer and when it was), goes on in the
  background (a cub's read under its runtime's own 10 s deadline and cache), and the page asks
  for that slot alone again (``?slot=<n>``). A slot's error is the slot's: ``error`` with words,
  ``off`` for a feature that is off; nothing else waits for it.
- **Nothing is added by an install or an update**: a manifest widget is on the home only when the
  person's list names it; the library lists what could be added.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any

from bears_cub import widgets as kinds

from .settings import SettingError

log = logging.getLogger("kranto.core.home")

BUDGET_S = 2.0
WIDGETS_MAX = 40
OPTIONS_MAX = 8
ROWS_ANSWERED = 20
STALE_S = 300
# who reads the cubs' rows of each group: the widget, and the greeting's sentence
ROW_READERS = {"needs_you": ("needs", "greeting"), "new": ("new", "greeting")}
WIDGET_ID = re.compile(r"[a-z][a-z0-9_]{1,39}(\.[a-z][a-z0-9_]{1,39})?")


@dataclass(frozen=True)
class Builtin:
    """A widget the page draws by hand. ``options``: name -> (type, lo, hi, required); a
    built-in whose facts are a shell key (Needs you's rows, the cubs' pins) keeps them there."""

    id: str
    title: str
    says: str
    sizes: tuple[str, ...]
    on: bool = False
    many: bool = False
    options: tuple[tuple[str, str, int, int, bool], ...] = ()


BUILTINS: tuple[Builtin, ...] = (
    Builtin("greeting", "Greeting", "The Kranto, the date and one sentence from the counts.",
            ("L",), on=True),
    Builtin("status", "Status", "Healthy or not, watching, the build running, tokens today.",
            ("L", "M"), on=True),
    Builtin("needs", "Needs you", "What waits for you: the first rows and how many more.",
            ("L", "M"), on=True),
    Builtin("doors", "Doors", "Watch, Ideas, Build and News with their counts.", ("L", "M"),
            on=True),
    Builtin("new", "New today", "What Kranto kept since your last visit.", ("L", "M"),
            on=True),
    Builtin("cubs", "Cubs", "Your pinned cubs' tiles, the rest under More cubs.", ("L",),
            on=True),
    Builtin("foot", "Foot", "Settings, Spend, Cubs, CLI and MCP, Help and the version.", ("L",),
            on=True),
    Builtin("spend", "Spend", "Watching this month against its cap, builds this week, tokens "
            "today.", ("S", "M")),
    Builtin("builds", "Builds", "The builds running, or the last one finished and its verdict.",
            ("M", "L")),
    Builtin("topic", "A topic", "One topic's newest kept observations and what is new since "
            "your visit.", ("S", "M", "L"), many=True,
            options=(("topic", "int", 1, 10**9, True), ("rows", "int", 1, 10, False))),
    Builtin("sources", "Sources", "Sources watched, failing, last read and next read.",
            ("S", "M")),
    # what Kranto is doing (off by default, the top bar says it
    # on every page); drawn by the page from the page's activity read, so it has no slot here
    Builtin("activity", "Activity", "What Kranto is doing: what runs, what waits on you, what "
            "comes next.", ("S", "M", "L")),
)
BY_ID = {b.id: b for b in BUILTINS}
# built-ins that went (D-8: "Your grades" read the empty grades table and always said 0;
# Settings › System › Your grades says what grades do): an arrangement naming one still loads
RETIRED = frozenset({"grades"})
DEFAULT = tuple(b.id for b in BUILTINS if b.on)


# -- shell.widgets ------------------------------------------------------------------------------


def check_widgets(value: object) -> list[dict[str, Any]] | None:
    """``shell.widgets`` normalised, or SettingError saying what it takes:
    null (the default home) or a list of at most 40 ``{id, size?, phone?, options?}``. An id is
    a built-in's or ``<feature>.<widget>``; a manifest widget's options are empty in schema 1; a
    built-in's options are its own. Which features are installed is not checked here: an entry
    for one that is gone is kept and skipped at draw."""
    if value is None:
        return None
    if not isinstance(value, list):
        raise SettingError("shell.widgets is a list of widgets, or null for the default home")
    if len(value) > WIDGETS_MAX:
        raise SettingError(f"shell.widgets holds at most {WIDGETS_MAX} widgets")
    out, seen = [], set()
    for i, w in enumerate(value):
        where = f"shell.widgets[{i}]"
        if not isinstance(w, dict) or not isinstance(w.get("id"), str):
            raise SettingError(f"{where} is {{id, size, phone, options}}")
        extra = sorted(set(w) - {"id", "size", "phone", "options"})
        if extra:
            raise SettingError(f"{where} takes no {', '.join(extra)}")
        wid = w["id"]
        if wid in RETIRED:          # a home arranged before it went: drawn without it
            continue
        if not WIDGET_ID.fullmatch(wid):
            raise SettingError(f"{where}: {wid[:60]!r} is not a widget id")
        b = BY_ID.get(wid)
        if "." not in wid and b is None:
            raise SettingError(f"{where}: no built-in widget {wid}")
        if wid in seen and not (b and b.many):
            raise SettingError(f"{where}: {wid} is on the home already")
        seen.add(wid)
        one: dict[str, Any] = {"id": wid}
        size = w.get("size")
        if size is not None:
            if size not in kinds.SIZES or (b and size not in b.sizes):
                sizes = b.sizes if b else kinds.SIZES
                raise SettingError(f"{where}.size is one of {', '.join(sizes)}")
            one["size"] = size
        if w.get("phone") is not None:
            if not isinstance(w["phone"], bool):
                raise SettingError(f"{where}.phone is true or false")
            if w["phone"] is False:
                one["phone"] = False
        opts = w.get("options")
        if opts:
            one["options"] = _options(where, b, opts)
        elif b is not None:
            missing = [o[0] for o in b.options if o[4]]
            if missing:
                raise SettingError(f"{where}: {wid} needs {', '.join(missing)}")
        out.append(one)
    return out


def _options(where: str, b: Builtin | None, opts: Any) -> dict[str, Any]:
    if not isinstance(opts, dict) or len(opts) > OPTIONS_MAX:
        raise SettingError(f"{where}.options is a mapping of at most {OPTIONS_MAX} keys")
    if b is None:
        raise SettingError(f"{where}: a cub's widget takes no options")
    spec = {o[0]: o for o in b.options}
    out = {}
    for k, v in opts.items():
        if k not in spec:
            raise SettingError(f"{where}.options: {b.id} takes no {k}")
        _, typ, lo, hi, _ = spec[k]
        if typ == "int" and (isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi):
            raise SettingError(f"{where}.options.{k} is a whole number from {lo} to {hi}")
        out[k] = v
    missing = [k for k, o in spec.items() if o[4] and k not in out]
    if missing:
        raise SettingError(f"{where}: {b.id} needs {', '.join(missing)}")
    return out


def declared(features: Any) -> dict[str, tuple[Any, ...]]:
    """Every manifest widget of the features given: ``<feature>.<widget>`` -> (feature,
    widget)."""
    return {f"{f.id}.{w.id}": (f, w) for f in features for w in f.ui.widgets}


def resolve(stored: Any, features: Any) -> list[dict[str, Any]]:
    """The home in order, each entry as the page draws it: its place ``n`` in the stored list,
    its id, size (its first when absent or no longer one of its sizes), ``phone``, options, and
    what it is. An entry the page cannot draw (a feature removed, a widget its update dropped)
    is ``known: false``: kept in the list, skipped at draw, so a cub added again finds its
    widgets where they were."""
    entries = [{"id": x} for x in DEFAULT] if stored is None else stored
    found = declared(features)
    out = []
    for n, e in enumerate(entries):
        b = BY_ID.get(e["id"])
        if b is not None:
            sizes = b.sizes
            row = {"title": b.title, "sizes": list(sizes), "builtin": True}
        elif e["id"] in found:
            f, w = found[e["id"]]
            sizes = w.sizes
            row = {"title": w.title, "sizes": list(sizes), "builtin": False, "feature": f.id,
                   "kind": w.kind, "every_s": max(kinds.EVERY_MIN_S, int(w.every_s)),
                   "open": w.open, "empty": w.empty, "trust": f.trust}
        else:
            out.append({"n": n, "id": e["id"], "known": False})
            continue
        size = e.get("size") if e.get("size") in sizes else sizes[0]
        out.append({"n": n, "id": e["id"], "known": True, "size": size,
                    "phone": e.get("phone", True), "options": dict(e.get("options") or {}),
                    **row})
    return out


def library(features: Any, stored: Any, enabled: Any) -> list[dict[str, Any]]:
    """The library sheet's groups: Kranto's own built-ins, then one group per
    installed feature that declares widgets, each widget with whether it is on the home. A
    feature that is off is not offered (.2: no tile for a feature that is off);
    ``enabled`` stays in each group for a page that reads it."""
    on = {e["id"] for e in ([{"id": x} for x in DEFAULT] if stored is None else stored)}
    out = [{"id": "kranto", "title": "kranto", "trust": "core", "enabled": True,
            "widgets": [{"id": b.id, "title": b.title, "says": b.says, "sizes": list(b.sizes),
                         "many": b.many, "on_home": b.id in on,
                         "options": [o[0] for o in b.options]} for b in BUILTINS]}]
    for f in features:
        if not f.ui.widgets or not enabled(f):
            continue
        out.append({"id": f.id, "title": f.title, "trust": f.trust, "enabled": True,
                    "widgets": [{"id": f"{f.id}.{w.id}", "title": w.title, "says": w.says,
                                 "sizes": list(w.sizes), "kind": w.kind, "many": False,
                                 "on_home": f"{f.id}.{w.id}" in on, "options": []}
                                for w in f.ui.widgets]})
    return out


# -- the reads, budgeted ------------------------------------------------------------------------

_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="home-read")
_LOCK = threading.Lock()
_INFLIGHT: dict[tuple[Any, ...], Future[Any]] = {}
_LAST: dict[tuple[Any, ...], tuple[float, str, object]] = {}     # key -> (monotonic, iso, answer)


def _ask(key: tuple[Any, ...], fn: Any) -> Future[Any]:
    """One read in flight per key: a home loaded again while a slow read runs waits on the
    same one, so a cub that sleeps never holds more than one of the pool's threads a read."""
    with _LOCK:
        f = _INFLIGHT.get(key)
        if f is None or f.done():
            f = _POOL.submit(fn)
            _INFLIGHT[key] = f
        return f


def _remember(key: tuple[Any, ...], answer: Any) -> None:
    from ..store import iso, utcnow
    with _LOCK:
        _LAST[key] = (time.monotonic(), iso(utcnow()), answer)


def _last(key: tuple[Any, ...]) -> Any:
    with _LOCK:
        hit = _LAST.get(key)
    if hit and time.monotonic() - hit[0] < STALE_S:
        return hit
    return None


def _words(exc: BaseException) -> str:
    return " ".join(str(exc).split())[:200] or type(exc).__name__


def _error_id(exc: BaseException, where: str) -> str:
    """The error kept once by its id (``rowsafe``): the slot offers Send this error."""
    from .. import rowsafe
    return str(rowsafe.note(exc, where)["id"])


def _rows(got: Any) -> list[Any]:
    if not isinstance(got, dict) or not isinstance(got.get("rows"), list):
        raise kinds.WidgetAnswerError("its rows read did not answer {rows}")
    return [r for r in got["rows"][:ROWS_ANSWERED] if isinstance(r, dict)]


def read(rt: Any, *, budget_s: float = BUDGET_S, only: int | None = None,
         next_run: dict[str, Any] | None = None) -> dict[str, Any]:
    """``GET /api/home``: the arrangement resolved, the library and the slots, within the
    budget. ``only``: one entry's slot (the page asking again for a slot that was loading);
    ``next_run``: the scheduler's next due time by job kind (Sources says the next read)."""
    from . import registry
    from . import shell as shell_mod

    features = registry.features()
    v = shell_mod.values(rt.cfg)
    stored = v.get("shell.widgets")
    # a feature that is off draws no tile: its widgets stay in the list,
    # known: false, skipped at draw, and come back where they were when it is on again
    entries = resolve(stored, [f for f in features if _enabled(rt, registry, f)])
    arrangement = shell_mod.arrangement(rt.cfg, features)
    on = {f.id: _state(rt, registry, f) for f in features}
    jobs: dict[str, tuple[tuple[Any, ...], object, object]] = {}   # slot -> (key, fn, finish)
    by_id = {f.id: f for f in features}

    # the cubs' rows of Needs you and New: for those widgets and for the greeting, whose
    # sentence counts them, so a home without Needs you still says what needs you
    drawn = {e["id"] for e in entries if e["known"]}
    groups = [] if only is not None else \
        [g for g, ids in ROW_READERS.items() if drawn & set(ids)]
    for group in groups:
        for f in _row_features(features, arrangement, group, on):
            decl = next(r for r in f.ui.today_rows if r.group == group)
            key = (f.id, decl.read, "")
            jobs[f"rows:{group}:{f.id}"] = (key, _call(rt, registry, f, decl.read, {}), _rows)
    for e in entries:
        if not e["known"] or (only is not None and e["n"] != only):
            continue
        if not e["builtin"]:
            f = by_id[e["feature"]]
            if on[f.id] is not None:
                continue
            w = next(w for w in f.ui.widgets if f"{f.id}.{w.id}" == e["id"])
            key = (f.id, w.read, e["size"])
            hosts = tuple(f.permissions.http_hosts)
            first = not registry.is_cub(f)
            jobs[str(e["n"])] = (key, _call(rt, registry, f, w.read, {"size": e["size"]}),
                                 _cleaner(w.kind, e["size"], f.id, hosts, first))

    futures = {slot: _ask(key, fn) for slot, (key, fn, _) in jobs.items()}
    if futures:
        wait(list(futures.values()), timeout=budget_s)
    answers: dict[str, dict[str, Any]] = {}
    for slot, fut in futures.items():
        key, _, finish = jobs[slot]
        answers[slot] = _answer(key, fut, finish)

    slots: dict[str, dict[str, Any]] = {}
    for e in entries:
        if not e["known"] or (only is not None and e["n"] != only):
            continue
        n = str(e["n"])
        if e["id"] in BUILTIN:
            slots[n] = _builtin_slot(rt, e, {"next_run": next_run})
        elif not e["builtin"]:
            off = on[e["feature"]]
            slots[n] = {"state": off[0], "error": off[1]} if off else answers[n]
    out = {"slots": slots, "budget_s": budget_s}
    if only is None:
        out.update(today(rt, next_run=next_run))
        out.update(rows={g: {k.rsplit(":", 1)[1]: a for k, a in answers.items()
                             if k.startswith(f"rows:{g}:")} for g in groups},
                   widgets=entries, custom=stored is not None,
                   library=library(features, stored,
                                   lambda f: (st := on[f.id]) is None or st[0] != "off"),
                   default=list(DEFAULT))
    return out


def _enabled(rt: Any, registry: Any, f: Any) -> bool:
    """Whether feature ``f`` is on; one the registry cannot read is on (it says so in its slot)."""
    try:
        return bool(registry.enabled(rt.cfg, f))
    except Exception:  # noqa: BLE001
        return True


def _state(rt: Any, registry: Any, f: Any) -> tuple[str, str] | None:
    """None when the feature's reads may be asked; else the slot's state and its words."""
    if not registry.enabled(rt.cfg, f):
        return ("off", f"{f.title} is off: turn it on on its page")
    why = registry.refused(rt.store, f)
    if why:
        return ("error", f"{f.title}: {why}")
    return None


# -- the built-ins off by default: each one query, drawn by the page ----------

TOPIC_ROWS = {"S": 3, "M": 5, "L": 8}


def _spend(rt: Any, e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Watching this month against its cap, and tokens today; the builds' half (this week, today)
    is the loop's, from the snapshot the page holds."""
    from ..store import utcnow
    now = utcnow()
    return {"month_usd": round(rt.store.month_spend(now), 4),
            "cap_usd": rt.cfg.budget.monthly_usd,
            "tokens_today": rt.store.tokens_since(now.replace(hour=0, minute=0, second=0,
                                                              microsecond=0))}


def _topic(rt: Any, e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """One topic's newest kept observations (title, source, when) and how many are new since
    the person's last visit (the home's own marker, as New today counts)."""
    from .. import library
    from ..web.today_api import resolve_since
    tid = int((e.get("options") or {}).get("topic") or 0)
    t = next((t for t, _, _ in library.topics_with_status(rt.store) if t.id == tid), None)
    if t is None:
        raise ValueError("its topic is gone: pick another under ⋯")
    n = int((e.get("options") or {}).get("rows") or TOPIC_ROWS[e["size"]])
    rows, total = library.find_observations(rt.store, library.ObservationFilter(topic_id=tid),
                                            sort="new", limit=n)
    since, _ = resolve_since(rt.store, None)
    _, fresh = library.find_observations(rt.store, library.ObservationFilter(topic_id=tid,
                                                                             since=since),
                                         limit=1)
    return {"topic": {"id": t.id, "name": t.name}, "total": total, "new": fresh,
            "rows": [{"id": r["id"], "title": r["title"], "source": r["source_label"],
                      "at": r["created_at"]} for r in rows]}


def _sources(rt: Any, e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Sources watched, the ones failing run after run (named), the last read and the next."""
    from .. import library, source_health
    last = rt.store.query_one("SELECT finished_at, status FROM runs WHERE kind = 'ingest' AND "
                              "status != 'skipped' ORDER BY finished_at DESC LIMIT 1")
    failing = source_health.needs_fixing(rt.store, rt.cfg)
    return {"watched": len(library.list_sources(rt.store, status="approved")),
            "failing": [{"id": s["id"], "label": s["label"]} for s in failing[:5]],
            "failing_n": len(failing),
            "last_read": last["finished_at"] if last else None,
            "next_read": (ctx.get("next_run") or {}).get("ingest")}


BUILTIN = {"spend": _spend, "topic": _topic, "sources": _sources}


def _builtin_slot(rt: Any, e: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    try:
        return {"state": "ok", "data": BUILTIN[e["id"]](rt, e, ctx)}
    except ValueError as exc:  # the slot's own words (its topic is gone): not a bug
        return {"state": "error", "error": _words(exc)}
    except Exception as exc:  # noqa: BLE001 - a slot's failure is the slot's, in words
        # kept and logged once by its id: the slot offers Send this error
        return {"state": "error", "error": _words(exc),
                "error_id": _error_id(exc, f"home:{e['id']}")}


def _row_features(features: Any, arrangement: dict[str, Any], group: str,
                  on: dict[str, Any]) -> list[Any]:
    """The features whose rows join Needs you or New today, as the page chose them in 0.5.10
    (``rowCubs``): on, a row of the group declared, and for a cub not hidden and allowed; News
    (a door, not a cub) adds its New rows while it is on."""
    from .shell import DOOR_FEATURES
    places = {c["id"]: c for c in arrangement["cubs"]}
    out = []
    for f in features:
        if on[f.id] is not None or not any(r.group == group for r in f.ui.today_rows):
            continue
        if f.id in DOOR_FEATURES:
            if group == "new":
                out.append(f)
            continue
        p = places.get(f.id)
        if p is None or p["hidden"] or not p["needs_you" if group == "needs_you" else "new"]:
            continue
        out.append(f)
    return out


def _call(rt: Any, registry: Any, f: Any, name: str, params: dict[str, Any]) -> Any:
    def run() -> Any:
        return f.api[name](registry.context(rt, f), dict(params))
    return run


def _cleaner(kind: str, size: str, cid: str, hosts: tuple[str, ...], first_party: bool) -> Any:
    def finish(got: Any) -> dict[str, Any]:
        data, changes = kinds.clean(kind, size, got, cub=cid, hosts=hosts,
                                    first_party=first_party)
        if changes:
            log.info("%s widget answer changed to draw: %s", cid, "; ".join(changes)[:300])
        return data
    return finish


def _answer(key: tuple[Any, ...], fut: Future[Any], finish: Any) -> dict[str, Any]:
    """A slot from its read: ``ok`` with its data; ``stale`` (the last good answer and when) or
    ``loading`` while the read goes on; ``error`` in words, with the last good answer when
    there is one."""
    if not fut.done():
        hit = _last(key)
        if hit:
            return {"state": "stale", "data": hit[2], "as_of": hit[1]}
        return {"state": "loading"}
    try:
        got = fut.result()
        stale = isinstance(got, dict) and got.get("stale") is True
        data = finish(got)
    except Exception as exc:  # noqa: BLE001 - a slot's failure is the slot's, in words
        hit = _last(key)
        out = {"state": "error", "error": _words(exc),
               "error_id": _error_id(exc, f"home:{key[0]}.{key[1]}")}
        if hit:
            out.update(data=hit[2], as_of=hit[1])
        return out
    if not stale:
        _remember(key, data)
        return {"state": "ok", "data": data}
    hit = _last(key)
    return {"state": "stale", "data": data, "as_of": hit[1] if hit else None}


# -- the home: one fixed order, one read ---------------------------------------

VISIT_KEY = "home.visit"
SESSION_S = 6 * 3600            # a visit this long after the last one is a new visit
BRIEF_TOPICS = 3                # today's brief: three topics at most, then "and N more"
BRIEF_ITEMS = 3                 # ... each with its first three items
IDEAS_SHOWN = 5                 # the five newest cards
AWAY_ROWS = 5                   # While you were away: five rows at most
AWAY_CARDS = 3                  # ... the three best cards, then the lead item of two briefs
AWAY_BRIEFS = 2
# the next result the quiet line names: the job's kind and its words
NEXT_JOBS = {"ideas": "ideas", "snapshot": "the map", "news": "the brief"}
LOCAL_TZ: Any = None            # the machine's zone (tests set one), as News reads its day
_NUMBERS = ("no", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine")


def _parse(value: Any) -> Any:
    from datetime import UTC, datetime
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _local(dt: Any) -> Any:
    return dt.astimezone(LOCAL_TZ) if LOCAL_TZ is not None else dt.astimezone()


def _number(n: int) -> str:
    return _NUMBERS[n] if 0 <= n < len(_NUMBERS) else str(n)


def _plural(n: int, word: str) -> str:
    return f"{_number(n)} {word}{'' if n == 1 else 's'}"


def visit_of(store: Any) -> dict[str, Any] | None:
    """The stored marker, ``{"at", "previous"}``, or None (never set, or not readable: a row
    written by hand that is not the marker's shape reads as never set)."""
    import json
    raw = store.get_setting(VISIT_KEY)
    if not raw:
        return None
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(v, dict) or _parse(v.get("at")) is None:
        return None
    prev = v.get("previous")
    return {"at": v["at"], "previous": prev if _parse(prev) is not None else None}


def visit(store: Any, now: Any = None) -> dict[str, Any]:
    """``POST /api/home/visit``: the home was seen now. A new visit (none yet, or the last one
    ``SESSION_S`` or more ago) keeps the last as ``previous``; within a visit only ``at`` moves.
    Answers the marker as stored."""
    import json

    from ..store import iso, utcnow
    now = now or utcnow()
    last = visit_of(store)
    if last is None:
        out = {"at": iso(now), "previous": None}
    elif (now - _parse(last["at"])).total_seconds() >= SESSION_S:
        out = {"at": iso(now), "previous": last["at"]}
    else:
        out = {"at": iso(now), "previous": last["previous"]}
    store.set_setting(VISIT_KEY, json.dumps(out), now=now)
    return out


def _since(v: dict[str, Any] | None, now: Any) -> str | None:
    """Where "new since your last visit" starts: the last visit before this one, None for the
    last 24 hours (no marker, or this is the first visit)."""
    if v is None:
        return None
    at, previous = str(v["at"]), v.get("previous")
    if (now - _parse(at)).total_seconds() >= SESSION_S:
        return at
    return str(previous) if previous else None


def _briefs(store: Any, now: Any) -> dict[str, Any]:
    """Today's brief: each active topic's newest good brief of the local day, newest first,
    three topics at most and three items each."""
    from datetime import timedelta

    from .. import library
    from ..store import iso
    names = {t.id: t.name for t in library.active_topics(store) if t.kind == "user"}
    day = _local(now).date()
    seen: set[int] = set()
    topics: list[dict[str, Any]] = []
    for r in store.query("SELECT id, topic_id, items, created_at FROM news_briefs WHERE status = "
                         "'ok' AND created_at >= ? ORDER BY id DESC",
                         (iso(now - timedelta(days=2)),)):
        at = _parse(r["created_at"])
        if r["topic_id"] not in names or r["topic_id"] in seen or at is None or \
                _local(at).date() != day:
            continue
        seen.add(r["topic_id"])
        items = _items(r["items"])
        topics.append({"topic": {"id": r["topic_id"], "name": names[r["topic_id"]]},
                       "brief": r["id"], "at": r["created_at"],
                       "items": [{"n": n, "title": it["headline"], "source": _source(it)}
                                 for n, it in items[:BRIEF_ITEMS]],
                       "more": max(0, len(items) - BRIEF_ITEMS)})
    # the topic of the newest brief of any day (the console's first starter asks
    # about it when today has no brief yet), None before the first
    newest = next(({"id": r["topic_id"], "name": names[r["topic_id"]], "at": r["created_at"]}
                   for r in store.query("SELECT topic_id, created_at FROM news_briefs WHERE "
                                        "status = 'ok' ORDER BY id DESC LIMIT 50")
                   if r["topic_id"] in names), None)
    return {"topics": topics[:BRIEF_TOPICS], "more": max(0, len(topics) - BRIEF_TOPICS),
            "newest": newest}


def _items(raw: Any) -> list[tuple[int, dict[str, Any]]]:
    """A brief's items with their numbers (as its page counts them), those with a headline."""
    import json
    try:
        got = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    got = got.get("items") if isinstance(got, dict) else got
    return [(n, it) for n, it in enumerate(got if isinstance(got, list) else [])
            if isinstance(it, dict) and isinstance(it.get("headline"), str) and it["headline"]]


def _source(item: dict[str, Any]) -> str | None:
    """The item's first source in words: the site kranto read it on, else the found page's."""
    from urllib.parse import urlparse
    for s in item.get("sources") or []:
        if not isinstance(s, dict):
            continue
        site = s.get("source")
        if s.get("kind") == "obs" and isinstance(site, str) and site:
            return site.removeprefix("www.")
        if isinstance(s.get("url"), str):
            host = urlparse(s["url"]).hostname or ""
            if host:
                return host.removeprefix("www.")
    return None


def _cards(rt: Any, now: Any) -> tuple[list[Any], dict[int, Any]]:
    """The cards Ideas lists as Waiting (newest first) and their ranks: the same rows as
    ``GET /api/ideas`` without filters (every status, the dispatch cards left out: where
    counting every ``shown`` row said "All 143" beside Ideas' 39 waiting)."""
    from .. import taste
    from ..ideate.dispatches import ORIGIN as DISPATCH_ORIGIN

    rows = list(
        rt.store.query(
            "SELECT id, title, created_at FROM ideas WHERE origin IS NOT ? ORDER BY id DESC",
            (DISPATCH_ORIGIN,),
        )
    )
    try:
        ranks = taste.rank(rt.store, now, getattr(rt.cfg, "grading", None))
    except Exception as exc:  # noqa: BLE001 - the newest first is still an order
        log.warning("the home's cards are newest first: %s", _words(exc))
        ranks = {}
    # a card graded not useful or wrong is passed: Ideas puts it last; the home leaves it out.
    # So is one put off with Later, or posted (H1: the home shows what is Waiting on Ideas,
    # by the server's own state, ``ideas_api.card_state``)
    from .. import outcomes
    from ..web.ideas_api import card_state, drafts_of

    ids = [r["id"] for r in rows]
    kinds, drafts = outcomes.by_kind(rt.store, ids), drafts_of(rt.store, ids)
    keep = {
        i
        for i in ids
        if card_state(ranks[i].own if i in ranks else None, kinds.get(i), drafts.get(i), now)
        == "waiting"
    }
    return [r for r in rows if r["id"] in keep], ranks


def _order(rows: list[Any], ranks: dict[int, Any]) -> list[Any]:
    """Ideas' own order (``taste.rank``'s key); a card without a rank goes last, newest first."""
    return sorted(
        rows, key=lambda r: ranks[r["id"]].key if r["id"] in ranks else (9, 0, 0, 0, 0, -r["id"])
    )


def _card_row(r: Any, ranks: dict[int, Any]) -> dict[str, Any]:
    # the owner's own grade (useful, not_useful, wrong) or null: the row's ▲ ▼ show it pressed
    own = ranks[r["id"]].own if r["id"] in ranks else None
    return {"id": r["id"], "title": r["title"], "at": r["created_at"], "grade": own}


def _ideas(rows: list[Any], ranks: dict[int, Any], since: str | None, now: Any) -> dict[str, Any]:
    """The five newest cards in Ideas' own order, and how many are new since the last visit."""
    from datetime import timedelta

    from ..store import iso

    start = since or iso(now - timedelta(hours=24))
    return {
        "rows": [_card_row(r, ranks) for r in _order(rows[:IDEAS_SHOWN], ranks)],
        "new": sum(1 for r in rows if r["created_at"] > start),
        "since": since,
        "total": len(rows),
    }


def _away(rt: Any, rows: list[Any], ranks: dict[int, Any], at: str, now: Any) -> dict[str, Any]:
    """While you were away: the three best cards written since ``at``, then the lead item of
    the two newest briefs since then; fewer briefs give more cards, fewer things fewer rows."""
    from .. import library

    names = {t.id: t.name for t in library.active_topics(rt.store) if t.kind == "user"}
    briefs = [
        b
        for b in rt.store.query(
            "SELECT id, topic_id, items, created_at FROM news_briefs WHERE status = 'ok' AND "
            "created_at > ? ORDER BY id DESC",
            (at,),
        )
        if b["topic_id"] in names
    ]
    cards = _order([r for r in rows if r["created_at"] > at], ranks)
    leads: list[dict[str, Any]] = []
    for b in briefs:
        items = _items(b["items"])
        if items:
            n, it = items[0]
            leads.append(
                {
                    "kind": "brief",
                    "brief": b["id"],
                    "n": n,
                    "title": it["headline"],
                    "topic": names[b["topic_id"]],
                    "source": _source(it),
                    "at": b["created_at"],
                }
            )
        if len(leads) == AWAY_BRIEFS:
            break
    n_cards = max(AWAY_CARDS, AWAY_ROWS - len(leads))
    picked = [{"kind": "card", **_card_row(r, ranks)} for r in cards[:n_cards]]
    picked += leads[: AWAY_ROWS - len(picked)]
    days = max(1, int((now - _parse(at)).total_seconds() // 86400))
    gone = f"You were away for {days} day{'' if days == 1 else 's'}."
    wrote = " and ".join(
        x
        for x in (
            f"{len(briefs)} brief{'' if len(briefs) == 1 else 's'}" if briefs else "",
            f"{len(cards)} idea{'' if len(cards) == 1 else 's'}" if cards else "",
        )
        if x
    )
    if not picked:
        said = f"{gone} Nothing new was written."
    else:
        best = (
            "This is the best."
            if len(picked) == 1
            else f"These {_number(len(picked))} are the best."
        )
        said = f"{gone} Kranto wrote {wrote}. {best}"
    return {
        "since": at,
        "days": days,
        "rows": picked,
        "ideas": len(cards),
        "briefs": len(briefs),
        "sentence": said,
    }


def _waiting(store: Any, now: Any) -> dict[str, int]:
    """What waits for the owner's yes, counted for the sentence: the drafts a posting cub asks
    to send (an open ask, or the newest draft of one that may be offered again: the rows Needs you
    and the one thing draw, ``asks.latest``), and the items an assistant prepared. A post the
    owner scheduled already has their yes (``social.hours``): it is not counted."""
    from ..social import hours
    from ..store import iso
    from . import asks

    drafts = sum(1 for t in asks.latest(store) if hours.held_of(store, t.get("id")) is None)
    prepared = store.query_one(
        "SELECT COUNT(*) AS n FROM prepared p WHERE p.id IN (SELECT MAX(id) FROM prepared "
        "GROUP BY prepared_uuid) AND p.state = 'open' AND (p.expires_at IS NULL OR "
        "p.expires_at > ?)",
        (iso(now),),
    )
    return {"drafts": drafts, "prepared": int(prepared["n"]) if prepared else 0}


def _sentence(briefs: dict[str, Any], waiting: dict[str, int]) -> str:
    """ "Today's brief is ready, and one draft waits for you." """
    first = "Today's brief is ready" if briefs["topics"] else "No brief yet today"
    d, p = waiting["drafts"], waiting["prepared"]
    things = [
        x for x in (_plural(d, "draft") if d else "", _plural(p, "prepared item") if p else "") if x
    ]
    if not things:
        return f"{first}, and nothing waits for you."
    verb = "waits" if len(things) == 1 and (d or p) == 1 else "wait"
    return f"{first}, and {' and '.join(things)} {verb} for you."


def _quiet(rt: Any, next_run: dict[str, Any] | None) -> dict[str, Any]:
    """The quiet line: topics and sources watched, the last read, whether a read runs now
    (``reading``: a home whose first read is still going says so, not "not read yet"), the next
    result."""
    from .. import library
    from ..tick import current_progress

    last = rt.store.query_one(
        "SELECT finished_at FROM runs WHERE kind = 'ingest' AND status "
        "NOT IN ('skipped', 'running') AND finished_at IS NOT NULL "
        "ORDER BY finished_at DESC LIMIT 1"
    )
    nxt = sorted(
        (
            (at, kind)
            for kind, at in (next_run or {}).items()
            if kind in NEXT_JOBS and isinstance(at, str)
        ),
        key=lambda x: x[0],
    )
    # the owner's topics: a project's (held while builds are off) is not one of them
    return {
        "topics": sum(1 for t in library.active_topics(rt.store) if t.kind == "user"),
        "sources": len(library.list_sources(rt.store, status="approved")),
        "read_at": last["finished_at"] if last else None,
        "reading": current_progress() is not None,
        "next": {"kind": nxt[0][1], "words": NEXT_JOBS[nxt[0][1]], "at": nxt[0][0]}
        if nxt
        else None,
    }


def _first(rt: Any, next_run: dict[str, Any] | None, now: Any) -> dict[str, Any] | None:
    """The first hour (mock ``first``): while the owner's newest topic that
    watches a place has no first brief yet, its four rows (``progress.topic_start``), the read as
    it goes (``read``: source n of m and that topic's kept and read so far, None between reads)
    and ``brief_minutes``, the page's estimate of the first brief (None once it is written, or
    when nothing can be said). None once the topic has its first brief, and on a home with
    nothing watched. Reads only."""
    from .. import library
    from ..features.news import brief as news_brief
    from ..progress import read_counts, topic_start
    from ..tick import current_progress

    store = rt.store
    watched = {s.id for s in library.list_sources(store, status="approved")}
    topics = [t for t in library.active_topics(store) if t.kind == "user"]
    topic = None
    for t in sorted(topics, key=lambda t: -t.id):
        linked = {
            r["source_id"]
            for r in store.query("SELECT source_id FROM topic_links WHERE topic_id = ?", (t.id,))
        }
        if linked & watched:
            topic = t
            break
    if topic is None:
        return None
    had = store.query_one(
        "SELECT id FROM news_briefs WHERE topic_id = ? AND status IN ('ok', 'quiet') LIMIT 1",
        (topic.id,),
    )
    if had is not None:
        return None
    row = store.query_one(
        "SELECT enabled FROM news_topics WHERE topic_id = ? ORDER BY id DESC LIMIT 1", (topic.id,)
    )
    news_on = bool(row and row["enabled"])
    reading = current_progress()
    no_key = not getattr(getattr(rt, "llm", None), "has_key", True)
    start = topic_start(
        store,
        topic.id,
        next_runs=next_run,
        news_on=news_on,
        reading=reading,
        brief_running=news_brief.running(topic.id),
        no_key=no_key,
    )
    read = None
    if reading is not None:
        got = read_counts(store, str(reading.get("run_uuid") or "")).get(topic.id) or {}
        read = {
            "source_index": max(1, int(reading.get("source_index") or 1)),
            "sources": int(reading.get("sources") or 0),
            "kept": int(got.get("kept", 0)),
            "judged": int(got.get("judged", 0)),
            "started_at": reading.get("started_at"),
        }
    return {
        "topic": {"id": topic.id, "name": topic.name},
        "rows": start["rows"],
        "quiet": start["quiet"],
        "read": read,
        "news_on": news_on,
        "no_key": no_key,
        "brief_minutes": brief_minutes(read, now) if news_on and not no_key else None,
        "early_kept": news_brief.EARLY_KEPT,
    }


FIRST_RATE = 0.25  # items kept of those read, before a read has said its own
FIRST_SECONDS = 3.5  # seconds an item, before a read has said its own


def brief_minutes(read: dict[str, Any] | None, now: Any) -> int | None:
    """Minutes until the first brief, as the first hour says it ("in about 4 minutes"): the
    items still to keep before ``EARLY_KEPT``, at this read's own rate and pace once it has read
    some, else the walks'. Before the read starts: about five. None once
    enough are kept (the brief is being written)."""
    from ..features.news.brief import EARLY_KEPT

    if read is None:
        return 5
    kept, judged = int(read.get("kept") or 0), int(read.get("judged") or 0)
    if kept >= EARLY_KEPT:
        return None
    rate = kept / judged if judged >= 10 and kept else FIRST_RATE
    pace = FIRST_SECONDS
    begun = _parse(read.get("started_at"))
    if begun is not None and judged >= 10:
        pace = max(0.5, (now - begun).total_seconds() / judged)
    seconds = (EARLY_KEPT - kept) / rate * pace + 60  # and about a minute to write it
    return max(1, round(seconds / 60))


def _block(name: str, fn: Any) -> Any:
    """One block of the home; a block that fails is that block's, in words, never the home's."""
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001
        return {"error": _words(exc), "error_id": _error_id(exc, f"home:{name}")}


def today(rt: Any, *, next_run: dict[str, Any] | None = None, now: Any = None) -> dict[str, Any]:
    """The home as one read: ``date`` (the local day), ``sentence``,
    ``waiting``, ``briefs``, ``ideas``, ``quiet``, ``visit`` (the marker as stored),
    ``away_days`` and ``away`` (While you were away, or None). Nothing is written."""
    from ..store import iso, utcnow

    now = now or utcnow()
    store = rt.store
    v = visit_of(store)
    away_days = getattr(getattr(rt.cfg, "home", None), "away_days", 3)
    gone = v is not None and (now - _parse(v["at"])).total_seconds() >= away_days * 86400
    briefs = _block("briefs", lambda: _briefs(store, now))
    waiting = _block("waiting", lambda: _waiting(store, now))
    got = _block("cards", lambda: _cards(rt, now))
    rows, ranks = got if isinstance(got, tuple) else ([], {})
    ideas = (
        _block("ideas", lambda: _ideas(rows, ranks, _since(v, now), now))
        if isinstance(got, tuple)
        else got
    )
    left = str(v["at"]) if v is not None else ""
    away = _block("away", lambda: _away(rt, rows, ranks, left, now)) if gone else None
    if isinstance(away, dict) and "error" in away:
        log.warning("While you were away could not be read: %s", away["error"])
        away = None
    ok = "error" not in briefs and "error" not in waiting
    said = away["sentence"] if away else _sentence(briefs, waiting) if ok else None
    return {
        "date": _local(now).date().isoformat(),
        "now": iso(now),
        "sentence": said,
        "waiting": waiting,
        "briefs": briefs,
        "ideas": ideas,
        "quiet": _block("quiet", lambda: _quiet(rt, next_run)),
        "first": _block("first", lambda: _first(rt, next_run, now)),
        "visit": v,
        "away_days": away_days,
        "away": away,
    }
