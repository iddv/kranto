"""A feature's one declaration, and the data schema it round-trips to
(``cub.yaml``, schema 1, protocol ``cub/1``).

A first-party feature is a ``Feature`` in its package (``the server/features/<id>/``): a dataclass
of lists and dicts, with code attached as callables. ``Feature.to_manifest()`` turns it into
the data a cub ships as ``cub.yaml``: the same keys, code named by method, so
``GET /api/features`` lists features and cubs as one list and one validator (``validate``)
checks both. An installed cub becomes a ``Feature`` again (``Feature.from_manifest``) whose
callables forward over its pipe. The schema is a one-way door, so it is small and closed: a key
it does not know is refused, as ``capability.yaml``'s rule is; its rules are the JSON Schema
shipped beside this file (``cub.schema.json``), which ``validate`` interprets.

The permission vocabulary is the closed, scoped list, used by first-party features too so
the enforcement code is one (``core.context``):

- ``reads``: which v1 read families (``core.api.READ_FAMILIES``);
- ``model``: the tiers and purposes the metered client accepts for this feature, and its cap;
- ``search``: the live-search kinds it may run (no page fetching);
- ``http``: public hosts it may fetch without credentials (none for News or Invest);
- ``broker``: typed operations on a named service the core performs with the owner's credential;
- ``requests``: the core's high-trust actions it may *ask for* (tickets the owner confirms);
- ``storage``: ``own`` (its ``<id>_`` tables) or ``none``.

Nothing else is grantable: no shell, no files, no secrets, no other feature's tables.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from bears_cub import schema as _schema_mod
from bears_cub import widgets as _widgets_mod

SCHEMA = 1
API = "cub/1"
# The protocols this Kranto speaks (``hello`` and ``api`` in a cub.yaml are checked against it).
SPEAKS = ("cub/1",)
ID = re.compile(r"[a-z][a-z0-9_]{1,39}")
KIND = re.compile(r"[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*(@[0-9]+)?")
# Who a feature or a mod is: set by the core, carried on every event it publishes.
TRUST = ("core", "first-party", "owner", "reviewed", "listed", "unreviewed", "generated")
# Doors an action may be run from: never "mcp" or "agent" for anything high-trust.
DOORS = ("ui", "cli", "mcp", "agent")
CLICKS = ("click", "confirm", "house")       # house: the house confirm (a sensitive change)
# ``topics``: which of the owner's topics, a list of topic ids (none: every topic), drawn by the
# core's one topic picker on the generated Settings page, never a text box
SETTING_TYPES = ("bool", "int", "float", "usd", "enum", "str", "list", "topics")
STORAGE = ("own", "none")
TODAY_GROUPS = ("needs_you", "new")
CARD_FIELD_KINDS = ("text", "date", "money", "link", "ref", "number", "list")
# The seven generic surfaces: a cub gives data, the core gives pixels. What it
# does, in one word (the home's More cubs and the gallery group by it); its glyph from a closed
# set the core draws (never an image of its own); its tile's tone; a form field's kind; where an
# action's button sits (``head``: always visible on the page, first-party only in schema 1).
UI_KINDS = ("post", "send", "money", "book", "watch", "make", "other")
GLYPHS = ("mail", "pen", "up", "plane", "play", "target", "swap", "grid", "dot")
TILE_TONES = ("new", "wait", "quiet")
FORM_FIELD_KINDS = ("text", "markdown", "enum", "choice", "bool", "int", "usd")
PLACES = ("card", "head")
# a list group's tone: its rows' glyph colour and state word (wait: amber,
# "waits on you"; good: green; bad: red; new: blue; quiet: grey)
GROUP_TONES = ("new", "wait", "quiet", "good", "bad")
# how a card's object opens: the one sheet, or a page of its own (an object you read:)
CARD_OPENS = ("sheet", "page")
# The home's widgets: the kinds the core draws, the sizes on its six columns
WIDGET_KINDS = _widgets_mod.KINDS
WIDGET_SIZES = _widgets_mod.SIZES
# the home's built-in widgets: an id without a dot (``core.home``), so no cub may take one
HOME_WIDGETS = ("greeting", "status", "needs", "doors", "new", "cubs", "foot", "spend",
                "builds", "topic", "sources", "grades", "activity")


# One exception for the SDK's checks and the core's (``bears_cub.schema``).
ManifestError = _schema_mod.ManifestError


def trust_rank(trust: str) -> int:
    """Higher is more trusted: core > first-party > owner > reviewed > listed > unreviewed >
    generated. A subscription's ``min_trust`` keeps events at or above its rank."""
    return len(TRUST) - TRUST.index(trust)


# -- the blocks -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class Job:
    """A scheduled job. ``every_hours``: its interval; ``per="topic"`` asks the job
    for each enabled topic itself (the job decides due-ness per topic, as the hourly News
    job does); ``on``: event kinds that also start it; ``when``: a setting key (bool) that
    turns it off, shown "off" in Health rather than absent; ``purpose``: its spend line;
    ``at`` (``HH:MM``, local) with ``days``: due once a day, or on those days, at or after that
    time (a cub's weekly job), ``every_hours`` then the retry cap; ``method``: the handler's
    name when the job runs in a cub's process."""

    kind: str
    run: Callable
    every_hours: float
    says: str = ""
    per: str | None = None
    on: tuple[str, ...] = ()
    when: str | None = None
    purpose: str | None = None
    deadline_s: int = 600
    at: str | None = None
    days: tuple[str, ...] = ()
    method: str | None = None


@dataclass(frozen=True)
class FormField:
    """One input of a form or of an action that takes input (row 4), drawn by its kind:
    ``text`` a field, ``enum`` a select of ``choices``, ``choice`` chips (from ``choices``, or
    from ``read``, one of the feature's own reads answering ``{"choices": [{value, word}]}``),
    ``bool`` a switch, ``int`` a number, ``usd`` dollars."""

    key: str
    label: str
    kind: str = "text"
    choices: tuple = ()
    read: str | None = None
    hint: str = ""
    required: bool = False


@dataclass(frozen=True)
class Action:
    """A verb. ``doors``: who may run it; ``click``: its confirm class; ``run`` takes
    ``(ctx, fields)`` and returns a dict for the page. ``fields``: the input it takes, so an
    action with input is a form; ``placement`` (``place`` in the data): ``card`` (on the card
    and the row) or ``head`` (always visible in the page's head: Invest's Stop). ``when``: one of
    its true-or-false settings; the page offers the action only while it is on, so a head never
    holds a button that can only refuse (the radar's Run now while the radar is off; UIBUGS B1).
    A feature's only, like the head (a cub's schema 1 has no ``when``)."""

    kind: str
    title: str
    run: Callable
    doors: tuple[str, ...] = ("ui", "cli")
    click: str = "click"
    subjects: tuple[str, ...] = ()
    says: str = ""
    fields: tuple[FormField, ...] = ()
    placement: str = "card"
    method: str | None = None
    when: str | None = None
    # the ladder kind its verb takes (``core.verbs``): ``spend`` for an action that only costs
    # model calls (Invest's Ask); None: from ``click`` (a click is reversible, a confirm outward)
    ladder: str | None = None


@dataclass(frozen=True)
class Setting:
    type: str
    default: object = None
    choices: tuple = ()
    lo: float | None = None
    hi: float | None = None
    words: str = ""
    # written only by hand in kranto.yaml: the page and the API refuse it (the owner's explicit
    # setting, as invest.live.enabled is)
    by_hand: bool = False
    # where it sits on its Settings › <Feature> page: the group's
    # heading (empty: "<Feature>'s settings"), or under the page's Advanced fold
    group: str = ""
    advanced: bool = False
    # the default on the stable line, when it differs: a big change that is
    # not finished rides to stable switched off, keeping the old behaviour there, until the
    # owner turns it on in a later stable release. None: the same default on both lines. A
    # value written in kranto.yaml wins on both. Kranto's own features only (not in a cub's
    # manifest).
    default_stable: object = None


def placed(keys: dict[str, Setting], groups: dict[str, tuple[str, ...]] | None = None,
           advanced: tuple[str, ...] = ()) -> dict[str, Setting]:
    """The keys with their place on the feature's Settings page: each group's
    heading over its keys, and the keys under Advanced. A key named that is not declared is a
    mistake in the feature, refused at import."""
    from dataclasses import replace
    out = dict(keys)
    for word, ks in (groups or {}).items():
        for k in ks:
            out[k] = replace(keys[k], group=word)
    for k in advanced:
        out[k] = replace(out[k], advanced=True)
    return out


@dataclass(frozen=True)
class Settings:
    """The feature's keys in its own ``kranto.yaml`` section (``<id>:``), with their rules.
    ``sensitive``: keys behind the house confirm, written from the page only."""

    keys: dict[str, Setting] = field(default_factory=dict)
    sensitive: tuple[str, ...] = ()
    per_topic: tuple[str, ...] = ()


@dataclass(frozen=True)
class Model:
    tiers: tuple[str, ...] = ()
    purposes: tuple[str, ...] = ()
    monthly_usd: float | None = None      # None: uncapped (the owner's rule for Kranto's own work)


@dataclass(frozen=True)
class Permissions:
    reads: tuple[str, ...] = ()
    model: Model = Model()
    search: tuple[str, ...] = ()
    http_hosts: tuple[str, ...] = ()
    # ("cited",): ``ctx.fetch`` reads the page behind a URL a read or a search of the same
    # context handed it, never another; Kranto's own features only
    fetch: tuple[str, ...] = ()
    broker: dict[str, tuple[str, ...]] = field(default_factory=dict)
    requests: tuple[str, ...] = ()
    storage: str = "own"


@dataclass(frozen=True)
class Subscribe:
    kind: str
    min_trust: str = "unreviewed"
    handler: Callable | None = None       # None: read at the feature's own run, no push
    method: str | None = None             # the handler's name when it runs in a cub's process


@dataclass(frozen=True)
class Events:
    publishes: tuple[str, ...] = ()
    subscribes: tuple[Subscribe, ...] = ()


@dataclass(frozen=True)
class Nav:
    route: str
    word: str
    under: str                            # the navigator's heading today: Desk | Work (later)
    count: str | None = None              # a read name that answers {"count": n}


@dataclass(frozen=True)
class TodayRow:
    """A row on the home (row 2): ``read`` is one of the feature's reads answering
    ``{"rows": [object]}``; ``card`` names the card schema whose title and lines word the row;
    ``primary`` is ``open``, one of its actions, or one of its request kinds (the ticket's
    confirm, drawn by the core)."""

    kind: str
    read: str
    group: str = "new"
    primary: str = "open"
    card: str | None = None


@dataclass(frozen=True)
class Tile:
    """The home tile (row 1): one line of words, a count from one of the feature's reads
    (answering ``{"count": n}``) with the words after it, and the tone of the count."""

    line: str = ""
    count: str | None = None
    words: str = ""
    tone: str = "quiet"


@dataclass(frozen=True)
class Group:
    """A group of a list: the key of the list's read whose value is the group's objects, and its
    tone (GROUP_TONES: its rows' glyph and state word)."""

    key: str
    word: str
    tone: str = "quiet"


@dataclass(frozen=True)
class UIList:
    """A list with a detail sheet (row 3): one word in the page's subnav, the read that
    answers it, the card that draws each object, its groups, and the group whose size is the
    count beside the word."""

    id: str
    word: str
    read: str
    card: str
    groups: tuple[Group, ...] = ()
    count: str | None = None
    # what the list says with nothing in it: what will appear and when (empty: the core's words)
    empty: str = ""


@dataclass(frozen=True)
class Form:
    """A simple form (row 4): its fields, and the action it runs with them."""

    id: str
    word: str
    submit: str
    fields: tuple[FormField, ...] = ()
    cost: str = ""
    says: str = ""


@dataclass(frozen=True)
class Widget:
    """A widget for the home: data the core draws by ``kind`` from the answer
    of ``read`` (one of the feature's reads, called with ``{size}``); ``sizes`` the ones it
    supports (the first is the size it is added at); ``every_s`` how often the home reads it
    again (a minute at least); ``open`` one of its lists (the head opens it) or None: its page;
    ``empty`` its words when there is nothing to show. On the home as ``<feature>.<id>``, and
    never until the person adds it."""

    id: str
    title: str
    kind: str
    read: str
    says: str = ""
    sizes: tuple[str, ...] = ("M",)
    every_s: int = 300
    open: str | None = None
    empty: str = ""


@dataclass(frozen=True)
class UI:
    """The slots it fills. ``cards``: declarative renderers: a card
    is ``{title, lines, fields: [{key, label, kind}], actions: [kind], origin, image_ref}``
    (``origin``: the field holding the cites; ``image_ref``: a field naming an image the core
    serves); a key may be a dotted path into the object (``thesis.catalyst``). First-party pages
    are components in the page's ``src/features/<id>/``, named in ``pages``; a feature without
    pages is drawn by the core from ``kind``, ``glyph``, ``tile``, ``lists`` and ``forms``."""

    area: str | None = None
    nav: tuple[Nav, ...] = ()
    pages: tuple[str, ...] = ()
    today_rows: tuple[TodayRow, ...] = ()
    cards: dict[str, dict] = field(default_factory=dict)
    settings_group: tuple[str, str] | None = None
    keys: dict[str, str] = field(default_factory=dict)
    kind: str = "other"
    glyph: str = "dot"
    tile: Tile | None = None
    lists: tuple[UIList, ...] = ()
    forms: tuple[Form, ...] = ()
    widgets: tuple[Widget, ...] = ()
    # the page's one primary: one of its forms' ids, or an action with place
    # head; None: its first form
    primary: str | None = None


@dataclass(frozen=True)
class Spend:
    purposes: tuple[str, ...] = ()
    caps: dict[str, str] = field(default_factory=dict)   # setting key -> words on Spend


@dataclass(frozen=True)
class Telemetry:
    counters: dict[str, tuple[int, int]] = field(default_factory=dict)


@dataclass(frozen=True)
class Prompt:
    id: str
    title: str
    purpose: str
    where: str
    placeholders: dict = field(default_factory=dict)
    editable: str = "full"


@dataclass(frozen=True)
class Docs:
    page: str | None = None
    glossary: dict[str, str] = field(default_factory=dict)
    words: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Feature:
    id: str
    title: str
    says: str
    version: str
    trust: str = "first-party"
    jobs: tuple[Job, ...] = ()
    owns: tuple[str, ...] = ()                       # its tables, each prefixed ``<id>_``
    api: dict[str, Callable] = field(default_factory=dict)   # read name -> fn(ctx, params)
    actions: tuple[Action, ...] = ()
    settings: Settings = Settings()
    permissions: Permissions = Permissions()
    events: Events = Events()
    ui: UI = UI()
    spend: Spend = Spend()
    telemetry: Telemetry = Telemetry()
    prompts: tuple[Prompt, ...] = ()
    evals: tuple[str, ...] = ()
    docs: Docs = Docs()
    # what the owner may grade (the core's one grades table): target -> its "why" chips
    grades: dict[str, tuple[tuple[str, str], ...]] = field(default_factory=dict)
    # its commands: ``cli(subparsers)`` adds ``afk <id> ...`` (code, not part of the data form)
    cli: Callable | None = None
    # ``guard(ctx, key, value)``: a feature's own rule on a settings write; raises ValueError
    guard: Callable | None = None
    # ``mode(ctx)``: the word its tag shows while it is on (``paper``, ``dry run``, ``drafts
    # only``, ``live``); without one, a ``<id>.mode`` setting, else ``live`` (code, not data)
    mode: Callable | None = None
    # an installed cub's manifest as the owner approved it (defaults filled): its data form,
    # which ``to_manifest`` returns as it is (None for a first-party feature)
    data: dict | None = None

    def to_manifest(self) -> dict:
        """The data form (schema 1): what ``validate`` checks and ``manifest_hash`` pins."""
        if self.data is not None:
            return json.loads(json.dumps(self.data))
        p = self.permissions
        return {
            "schema": SCHEMA, "api": API, "id": self.id, "version": self.version,
            "title": self.title, "says": self.says, "trust": self.trust,
            "reads": list(p.reads),
            "events": {"publish": list(self.events.publishes),
                       "subscribe": [{"kind": s.kind, "min_trust": s.min_trust,
                                      **({"method": s.method or _method(s.handler)}
                                         if s.handler is not None else {})}
                                     for s in self.events.subscribes]},
            "jobs": [{"kind": j.kind, "method": j.method or _method(j.run),
                      "every_hours": j.every_hours, "at": j.at, "days": list(j.days),
                      "per": j.per, "on": list(j.on), "when": j.when, "purpose": j.purpose,
                      "deadline_s": j.deadline_s, "says": j.says} for j in self.jobs],
            "actions": [{"kind": a.kind, "title": a.title, "method": a.method or _method(a.run),
                         "doors": list(a.doors), "click": a.click, "subjects": list(a.subjects),
                         "says": a.says, "fields": [_field(x) for x in a.fields],
                         "place": a.placement, **({"when": a.when} if a.when else {})}
                        for a in self.actions],
            "provides": sorted(self.api),
            "requests": list(p.requests),
            "broker": {k: list(v) for k, v in sorted(p.broker.items())},
            "http": {"hosts": list(p.http_hosts)},
            **({"fetch": list(p.fetch)} if p.fetch else {}),
            "model": {"tiers": list(p.model.tiers), "purposes": list(p.model.purposes),
                      "monthly_usd": p.model.monthly_usd},
            "search": list(p.search),
            "storage": p.storage,
            "owns": list(self.owns),
            "settings": {"keys": {k: _setting(s) for k, s in self.settings.keys.items()},
                         "sensitive": list(self.settings.sensitive),
                         "per_topic": list(self.settings.per_topic)},
            "ui": {"area": self.ui.area,
                   "nav": [{"route": n.route, "word": n.word, "under": n.under,
                            "count": n.count} for n in self.ui.nav],
                   "pages": list(self.ui.pages),
                   "today_rows": [{"kind": r.kind, "read": r.read, "group": r.group,
                                   "primary": r.primary, "card": r.card}
                                  for r in self.ui.today_rows],
                   "cards": self.ui.cards,
                   "settings_group": list(self.ui.settings_group) if self.ui.settings_group
                   else None,
                   "keys": dict(self.ui.keys),
                   "kind": self.ui.kind, "glyph": self.ui.glyph,
                   "tile": {"line": self.ui.tile.line, "count": self.ui.tile.count,
                            "words": self.ui.tile.words, "tone": self.ui.tile.tone}
                   if self.ui.tile else None,
                   "lists": [{"id": x.id, "word": x.word, "read": x.read, "card": x.card,
                              "groups": [{"key": g.key, "word": g.word, "tone": g.tone}
                                         for g in x.groups],
                              "count": x.count, "empty": x.empty} for x in self.ui.lists],
                   "primary": self.ui.primary,
                   "forms": [{"id": x.id, "word": x.word, "submit": x.submit,
                              "fields": [_field(f) for f in x.fields], "cost": x.cost,
                              "says": x.says} for x in self.ui.forms],
                   "widgets": [_widget(w) for w in self.ui.widgets]},
            "spend": {"purposes": list(self.spend.purposes), "caps": dict(self.spend.caps)},
            "telemetry": {"counters": {k: list(v) for k, v in self.telemetry.counters.items()}},
            "prompts": [{"id": x.id, "title": x.title, "purpose": x.purpose, "where": x.where,
                         "editable": x.editable,
                         "placeholders": {k: list(v) for k, v in x.placeholders.items()}}
                        for x in self.prompts],
            "evals": list(self.evals),
            "grades": {k: [list(c) for c in v] for k, v in self.grades.items()},
            "docs": {"page": self.docs.page, "glossary": dict(self.docs.glossary),
                     "words": dict(self.docs.words)},
        }


    @classmethod
    def from_manifest(cls, m: dict, runner, *, trust: str, grants: dict | None = None
                      ) -> Feature:
        """An installed cub as a ``Feature``: ``m`` is its validated
        manifest (defaults filled), ``grants`` what the owner approved (narrower than the
        manifest when topics were narrowed at install), ``trust`` the registry's. Its code is
        ``runner``'s: ``runner.job(kind, method)``, ``runner.action(kind, method)``,
        ``runner.read(name)`` and ``runner.deliver(kind, method)`` return callables that
        forward over the cub's pipe; ``runner.mode(ctx)`` is the word on its tag."""
        g = grants if grants is not None else grants_of(m)
        subs = tuple(
            Subscribe(s["kind"], s.get("min_trust", "unreviewed"),
                      runner.deliver(s["kind"], s["method"]) if s.get("method") else None,
                      s.get("method"))
            for s in (g.get("events") or {}).get("subscribe", []))
        jobs = tuple(Job(j["kind"], runner.job(j["kind"], job_method(j)), j["every_hours"],
                         says=j.get("says", ""), per=j.get("per"), on=tuple(j.get("on", [])),
                         when=j.get("when"), purpose=j.get("purpose"),
                         deadline_s=int(j.get("deadline_s", 600)), at=j.get("at"),
                         days=tuple(j.get("days", [])), method=job_method(j))
                     for j in m.get("jobs", []))
        acts = tuple(Action(a["kind"], a["title"], runner.action(a["kind"], action_method(a)),
                            doors=tuple(a.get("doors", ("ui", "cli"))),
                            click=a.get("click", "click"), subjects=tuple(a.get("subjects", [])),
                            says=a.get("says", ""),
                            fields=tuple(_form_field(f) for f in a.get("fields", [])),
                            placement=a.get("place", "card"), method=action_method(a))
                     for a in m.get("actions", []))
        st = m.get("settings") or {}
        ui = m.get("ui") or {}
        tile = ui.get("tile")
        model = g.get("model") or {}
        return cls(
            id=m["id"], title=m["title"], says=m["says"], version=m["version"], trust=trust,
            jobs=jobs, api={name: runner.read(name) for name in m.get("provides", [])},
            actions=acts,
            settings=Settings(keys={k: _setting_of(v) for k, v in (st.get("keys") or {}).items()},
                              sensitive=tuple(st.get("sensitive", [])),
                              per_topic=tuple(st.get("per_topic", []))),
            permissions=Permissions(
                reads=tuple(g.get("reads", [])),
                model=Model(tiers=tuple(model.get("tiers", [])),
                            purposes=tuple(model.get("purposes", [])),
                            monthly_usd=model.get("monthly_usd")),
                search=tuple(g.get("search", [])),
                http_hosts=tuple((g.get("http") or {}).get("hosts", [])),
                fetch=tuple(m.get("fetch", [])),
                broker={k: tuple(v) for k, v in (g.get("broker") or {}).items()},
                requests=tuple(g.get("requests", [])), storage=g.get("storage", "own")),
            events=Events(publishes=tuple((g.get("events") or {}).get("publish", [])),
                          subscribes=subs),
            ui=UI(area=ui.get("area"),
                  nav=tuple(Nav(n["route"], n["word"], n["under"], n.get("count"))
                            for n in ui.get("nav", [])),
                  today_rows=tuple(TodayRow(r["kind"], r["read"], r.get("group", "new"),
                                            r.get("primary", "open"), r.get("card"))
                                   for r in ui.get("today_rows", [])),
                  cards=dict(ui.get("cards") or {}),
                  settings_group=tuple(ui["settings_group"]) if ui.get("settings_group")
                  else None,
                  kind=ui.get("kind", "other"), glyph=ui.get("glyph", "dot"),
                  tile=Tile(tile.get("line", ""), tile.get("count"), tile.get("words", ""),
                            tile.get("tone", "quiet")) if tile else None,
                  lists=tuple(UIList(x["id"], x["word"], x["read"], x["card"],
                                     tuple(Group(gr["key"], gr["word"], gr.get("tone", "quiet"))
                                           for gr in x.get("groups", [])), x.get("count"),
                                     x.get("empty", ""))
                              for x in ui.get("lists", [])),
                  primary=ui.get("primary"),
                  forms=tuple(Form(x["id"], x["word"], x["submit"],
                                   tuple(_form_field(f) for f in x.get("fields", [])),
                                   x.get("cost", ""), x.get("says", ""))
                              for x in ui.get("forms", [])),
                  widgets=tuple(widget_of(w) for w in ui.get("widgets", []))),
            spend=Spend(purposes=tuple((m.get("spend") or {}).get("purposes", [])),
                        caps=dict((m.get("spend") or {}).get("caps", {}))),
            telemetry=Telemetry(counters={k: tuple(v) for k, v in
                                          ((m.get("telemetry") or {}).get("counters")
                                           or {}).items()}),
            evals=tuple(m.get("evals", [])),
            docs=Docs(page=(m.get("docs") or {}).get("page"),
                      glossary=dict((m.get("docs") or {}).get("glossary") or {}),
                      words=dict((m.get("docs") or {}).get("words") or {})),
            grades={k: tuple(tuple(c) for c in v) for k, v in (m.get("grades") or {}).items()},
            mode=runner.mode,
            data={**m, "trust": trust})


def job_method(j: dict) -> str:
    """A job's handler: its ``method``, else the second part of its kind."""
    return j.get("method") or str(j["kind"]).split(".", 1)[1]


def action_method(a: dict) -> str:
    """An action's handler: its ``method``, else the second part of its kind."""
    return a.get("method") or str(a["kind"]).split(".", 1)[1]


def _form_field(f: dict) -> FormField:
    return FormField(f["key"], f["label"], f.get("kind", "text"), tuple(f.get("choices", [])),
                     f.get("read"), f.get("hint", ""), bool(f.get("required", False)))


def widget_of(w: dict) -> Widget:
    return Widget(w["id"], w["title"], w["kind"], w["read"], w.get("says", ""),
                  tuple(w.get("sizes") or ("M",)), int(w.get("every_s", 300)), w.get("open"),
                  w.get("empty", ""))


def _widget(w: Widget) -> dict:
    return {"id": w.id, "title": w.title, "says": w.says, "kind": w.kind, "read": w.read,
            "sizes": list(w.sizes), "every_s": w.every_s, "open": w.open, "empty": w.empty}


def _setting_of(s: dict) -> Setting:
    return Setting(s["type"], s.get("default"), tuple(s.get("choices", [])), s.get("lo"),
                   s.get("hi"), s.get("words", ""), bool(s.get("by_hand", False)),
                   str(s.get("group") or ""), bool(s.get("advanced", False)))


# The grant blocks as Kranto stores and sends them: the SDK's own function, so the host's
# ``hello.granted`` and FakeHost's are built the same way.
GRANT_BLOCKS = _schema_mod.GRANT_BLOCKS
grants_of = _schema_mod.grants_of


def _method(fn: Callable | None) -> str:
    """A callable's name as the data form carries it (``__name__``: a nested or bound
    function's qualified name is not a method name)."""
    return getattr(fn, "__name__", None) or "call"


def _field(f: FormField) -> dict:
    return {"key": f.key, "label": f.label, "kind": f.kind, "choices": list(f.choices),
            "read": f.read, "hint": f.hint, "required": f.required}


def _setting(s: Setting) -> dict:
    return {"type": s.type, "default": s.default, "choices": list(s.choices), "lo": s.lo,
            "hi": s.hi, "words": s.words, "by_hand": s.by_hand, "group": s.group,
            "advanced": s.advanced}


def manifest_hash(manifest: dict) -> str:
    """The pin: sha256 of the manifest's canonical JSON. A cub's is taken over
    its ``cub.yaml`` as loaded, before the validator fills any default, so the SDK computes
    the same value from the same file."""
    text = json.dumps(manifest, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


# -- versions -------------------------------------------------------------------------------------

_VERSION = re.compile(r"(\d+)\.(\d+)(?:\.(\d+))?(.*)")
_RANGE = re.compile(r"(>=|<=|<|>|==)\s*(\d+\.\d+(?:\.\d+)?)")


def version_key(v: str) -> tuple:
    """A version as a comparable tuple: major, minor, patch, then 1 for a release and 0 for a
    pre-release (``0.5.0rc1``, ``0.5.0-rc.1``, ``0.5.1.dev3``) so a pre-release sorts below its
    release; a local part (``+g1a2b``) is ignored. No ``packaging`` dependency."""
    m = _VERSION.match(str(v).strip())
    if not m:
        return (0, 0, 0, 0)
    rest = (m.group(4) or "").split("+", 1)[0]
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), 0 if rest else 1)


def in_range(version: str, rng: str) -> bool:
    """Whether ``version`` satisfies a cub's ``kranto`` range (``">=0.5,<0.7"``)."""
    have = version_key(version)
    for op, want in _RANGE.findall(rng or ""):
        w = version_key(want)
        ok = {">=": have >= w, "<=": have <= w, ">": have > w, "<": have < w,
              "==": have[:3] == w[:3]}[op]
        if not ok:
            return False
    return True


# -- validation (the one validator for features and cubs,) ------------------------

SCHEMA_FILE = _schema_mod.SCHEMA_FILE       # shipped with the SDK: one schema, one reader
SEMVER = re.compile(r"\d+\.\d+\.\d+([-+][0-9A-Za-z.-]+)?")
MAX_MANIFEST_BYTES = 64 * 1024
# A cub id may not be one of these, nor a section of kranto.yaml, nor a first-party feature's id
#; ``reserved_ids()`` adds the computed ones.
RESERVED_WORDS = ("core", "kranto", "cub", "cubs", "host", "sdk", "test", "demo", "stage",
                  "stages", "shell", "telemetry", "anthropic", "claude_code",
                  # the ids AX names for features to come
                  "watch", "themes", "build", "maintain", "media", "term", "strikes")
# Settings' own pages: every feature and cub has Settings › <Feature> at
# #/settings/<id>, so no cub may take the name of a page already there.
SETTINGS_PAGE_IDS = ("overview", "features", "watching", "building", "publishing", "accounts",
                     "spend", "privacy", "system", "appearance", "prompts", "tools", "access",
                     "capabilities", "connections", "github", "health", "home", "keys",
                     "learning", "maintenance", "mcp", "models", "plugins", "projects", "rules",
                     "sources", "topics", "updates", "watches", "evaluation", "search")
# What ``fetch`` grants a feature: the pages behind the URLs its own reads and searches returned.
FETCH_GRANTS = ("cited",)
# The anchors of a build stage, in the order a build reaches them.
ANCHORS = ("after_brief", "after_build", "before_check", "before_publish")


@functools.cache
def _schema(source: str) -> dict:
    """The JSON Schema ``validate`` interprets: ``cub.schema.json`` as shipped for a cub; for
    an in-tree feature the first-party-only keys widened (``owns``,
    ``ui.pages``, ``ui.keys``, ``prompts``, ``place: head``, the house confirm, the ``mcp`` and
    ``agent`` doors, method names that are Python names)."""
    s = _schema_mod.load()
    if source == "cub":
        return s
    p = s["properties"]
    p["owns"] = {"type": "array", "maxItems": 40, "items": {"type": "string"}, "default": []}
    p["prompts"] = {"type": "array", "maxItems": 40, "items": {"type": "object"}, "default": []}
    p["fetch"] = {"type": "array", "maxItems": len(FETCH_GRANTS),
                  "items": {"type": "string", "enum": list(FETCH_GRANTS)}, "default": []}
    ui = p["ui"]["properties"]
    ui["pages"] = {"type": "array", "maxItems": 20, "items": {"type": "string"}, "default": []}
    ui["keys"] = {"type": "object", "maxProperties": 20,
                  "additionalProperties": {"type": "string"}, "default": {}}
    act = p["actions"]["items"]["properties"]
    act["click"]["enum"] = list(CLICKS)
    act["doors"]["items"]["enum"] = list(DOORS)
    act["place"]["enum"] = list(PLACES)
    act["when"] = {"type": "string", "pattern": r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$"}
    s["$defs"]["method"] = {"type": "string", "pattern": r"^[A-Za-z_][A-Za-z0-9_.]{0,79}$"}
    # core.money's operations keep their names (``accounts``, ``quote``): a cub's are
    # ``<noun>.<verb>`` of a broker adapter
    for sub in p["broker"]["patternProperties"].values():
        sub["items"] = {"type": "string", "pattern": r"^[a-z][a-z0-9_.]{0,60}$"}
    # a feature may ask for any kind the core registers (its existence is checked after)
    p["requests"]["items"] = {"type": "string"}
    return s


def reserved_ids() -> set[str]:
    """Every id a cub may not take: the fixed words, every section of ``kranto.yaml``,
    the first-party features' ids, the ``cubs:`` section's own key names and Settings' pages."""
    from dataclasses import fields as dc_fields

    from ..config import Config
    from .cubs.settings import GLOBAL_NAMES
    out = set(RESERVED_WORDS) | set(GLOBAL_NAMES) | set(HOME_WIDGETS) | set(SETTINGS_PAGE_IDS)
    out |= {f.name for f in dc_fields(Config)} - {"root"}
    try:
        from ..features import FEATURES
        out |= {f.id for f in FEATURES}
    except ImportError:  # pragma: no cover - the package always has its features
        pass
    return out


def _inside(where: str, p, files: set[str] | None) -> None:
    """A path a manifest names: relative, inside the cub's folder, present when the tree is
    known (rule 5)."""
    if p is None:
        return
    parts = str(p).split("/")
    if str(p).startswith("/") or "\\" in str(p) or any(x in ("", ".", "..") for x in parts):
        raise ManifestError(f"{where}: {p!r} must be a path inside the cub's folder")
    if files is not None and p not in files:
        raise ManifestError(f"{where}: {p} is not in the cub's folder")


def _cub_prechecks(m: dict) -> None:
    """The first-party-only keys and values, refused in words before the schema runs (rules 2 and
    4)."""
    if m.get("schema") not in (None, SCHEMA):
        raise ManifestError(f"manifest schema {m.get('schema')!r} needs a newer Kranto (this one "
                            f"reads schema {SCHEMA})")
    if "api" in m and m["api"] not in SPEAKS:
        raise ManifestError(f"this cub speaks {m['api']}; this Kranto speaks "
                            f"{', '.join(SPEAKS)}: update Kranto")
    if m.get("trust") in ("first-party", "core"):
        raise ManifestError(f"trust: {m['trust']} is Kranto's own; a cub's trust is set by Kranto "
                            "when it is installed")
    for key, words in (("owns", "a cub owns no tables (its data is its key-value store)"),
                       ("fetch", "a cub fetches through http.hosts, the hosts it names"),
                       ("prompts", "a cub's prompts are its own files, never the core's")):
        if m.get(key):
            raise ManifestError(f"{key}: {words}")
    ui = m.get("ui") if isinstance(m.get("ui"), dict) else {}
    if ui.get("pages"):
        raise ManifestError("ui.pages: a cub ships no page code; the core draws its page")
    if ui.get("keys"):
        raise ManifestError("ui.keys: a cub asks for no keyboard key")
    for a in m.get("actions") or []:
        if not isinstance(a, dict):
            continue
        if a.get("place") == "head":
            raise ManifestError(f"actions: {a.get('kind')} asks for the page's head, which is "
                                "Kranto's own features' only")
        if a.get("click") == "house":
            raise ManifestError(f"actions: {a.get('kind')}: the house confirm is the core's")
        if set(a.get("doors") or []) & {"mcp", "agent"}:
            raise ManifestError(f"actions: {a.get('kind')}: a cub's action runs from the page "
                                "or the command line only (never mcp or an agent token)")


def validate(m: dict, *, read_families: tuple[str, ...], request_kinds: tuple[str, ...],
             core_kinds: tuple[str, ...] = (), search_kinds: tuple[str, ...] = (),
             tiers: tuple[str, ...] = ("judge", "reason"), source: str = "feature",
             broker_ops: dict[str, set[str]] | None = None, files: set[str] | None = None,
             published: dict[str, str] | None = None) -> dict:
    """Check a manifest against schema 1 and return it, its defaults filled in place ("defaults
    first"). Raises ``ManifestError`` naming the key; nothing is written.

    ``source``: ``feature`` (an in-tree ``Feature``'s ``to_manifest()``: the first-party-only
    keys allowed) or ``cub`` (a ``cub.yaml``). What the core can grant: ``read_families``,
    ``request_kinds``, ``search_kinds``, ``tiers`` and, for a cub, ``broker_ops`` (each
    service's read and draft operations; a perform operation is never grantable). ``files``:
    the cub's tree, when known (paths it names must be in it). ``published``: event kinds
    other installed features and cubs publish, to their publisher."""
    if source not in ("feature", "cub"):
        raise ValueError(f"source is feature or cub, not {source!r}")
    if not isinstance(m, dict):
        raise ManifestError("a manifest is a mapping of keys")
    cub = source == "cub"
    if cub:
        _cub_prechecks(m)
    elif "trust" in m and (m["trust"] not in TRUST or m["trust"] == "core"):
        raise ManifestError(f"trust must be one of {', '.join(TRUST[1:])}")
    if not cub and "trust" not in m:
        raise ManifestError("the manifest needs trust")
    root = _schema(source)
    _schema_mod.walk(m, root, [], root)
    fid = m["id"]
    if cub and fid in reserved_ids():
        raise ManifestError(f"id: {fid} is a reserved word in Kranto (a section of kranto.yaml, "
                            "a feature of Kranto's own, a page of Settings, or a word the core "
                            "keeps)")
    if not SEMVER.fullmatch(m["version"]):
        raise ManifestError("version must be semver (1.2.3)")
    _check_reads(m, read_families)
    _check_events(m, fid, core_kinds, published, cub)
    provides = set(m.get("provides", []))
    settings_keys = (m.get("settings") or {}).get("keys") or {}
    _check_settings(m, fid, cub)
    _check_model(m, fid, tiers, search_kinds)
    _check_jobs(m, fid, settings_keys, cub)
    action_kinds = _check_actions(m, fid, provides, cub, settings_keys)
    _check_requests(m, request_kinds, cub)
    _check_broker(m, broker_ops, cub)
    _check_http(m)
    _check_ui(m, provides, action_kinds)
    for t in m.get("owns", []):
        if not str(t).startswith(fid + "_"):
            raise ManifestError(f"owns: {t!r} must start with {fid}_")
    for target in m.get("grades", {}):
        if not str(target).startswith(fid + "_"):
            raise ManifestError(f"grades: {target!r} must start with {fid}_")
    if cub:
        for where, p in (("entry", m.get("entry")), ("requirements", m.get("requirements")),
                         ("docs.page", (m.get("docs") or {}).get("page"))):
            _inside(where, p, files)
        _check_stages(m, fid, request_kinds, settings_keys, files)
    return m


def _check_reads(m: dict, read_families: tuple[str, ...]) -> None:
    bad = [r for r in m.get("reads", []) if r not in read_families]
    if bad:
        raise ManifestError(f"reads: no such read family: {', '.join(bad)} "
                            f"(families: {', '.join(read_families)})")


# Names under which strangers publish their own sites: a grant of one of them is a grant of every
# site under it (``http.hosts`` allows subdomains). The common hosting suffixes and two-part
# country suffixes; not the whole public suffix list.
SHARED_SUFFIXES = frozenset({
    "github.io", "gitlab.io", "pages.dev", "workers.dev", "vercel.app", "netlify.app",
    "herokuapp.com", "fly.dev", "onrender.com", "web.app", "firebaseapp.com", "appspot.com",
    "azurewebsites.net", "cloudfront.net", "amazonaws.com", "blogspot.com", "wordpress.com",
    "substack.com", "glitch.me", "replit.app", "repl.co", "ngrok.io", "ngrok-free.app",
    "trycloudflare.com", "duckdns.org", "s3.amazonaws.com", "translate.goog",
    "co.uk", "org.uk", "ac.uk", "gov.uk", "com.au", "net.au", "org.au", "co.nz", "co.jp",
    "co.za", "com.br", "com.cn", "co.in", "co.kr", "com.mx", "com.tr", "com.sg",
})


def _check_http(m: dict) -> None:
    for h in (m.get("http") or {}).get("hosts", []):
        if str(h) in SHARED_SUFFIXES:
            raise ManifestError(f"http.hosts: {h} is shared by many sites (every name under it "
                                f"would be allowed); name the site itself, such as "
                                f"someone.{h}")


def _check_events(m: dict, fid: str, core_kinds, published, cub: bool) -> None:
    ev = m.get("events") or {}
    for kind in ev.get("publish", []):
        if not KIND.fullmatch(kind):
            raise ManifestError(f"events.publish: {kind!r} is not <noun>.<verb>")
        if kind in core_kinds:
            raise ManifestError(f"events.publish: {kind} is the core's")
        if cub and not kind.startswith(fid + "."):
            raise ManifestError(f"events.publish: a cub's kinds start with {fid}. ({kind})")
        if published and kind in published and published[kind] != fid:
            raise ManifestError(f"events.publish: {kind} is published by {published[kind]}")
    for sub in ev.get("subscribe", []):
        if not KIND.fullmatch(str(sub.get("kind"))):
            raise ManifestError(f"events.subscribe: {sub.get('kind')!r} is not <noun>.<verb>")


def _check_settings(m: dict, fid: str, cub: bool) -> None:
    from .settings import SettingError, check
    st = m.get("settings") or {}
    keys = st.get("keys") or {}
    for key, rule in keys.items():
        if not str(key).startswith(fid + "."):
            raise ManifestError(f"settings: {key!r} must start with {fid}.")
        if rule.get("type") == "enum" and not rule.get("choices"):
            raise ManifestError(f"settings.{key}: an enum needs its choices")
        if rule.get("default") is not None:
            try:
                check(key, _setting_of(rule), rule["default"])
            except SettingError as exc:
                raise ManifestError(f"settings.{key}: its default does not fit: {exc}") from None
            if cub and _secret_shaped(rule["default"]):
                raise ManifestError(f"settings.{key}: a default shaped like a key or a token; a "
                                    "cub never holds one (connect it under Connections)")
    for key in [*st.get("sensitive", []), *st.get("per_topic", [])]:
        if key not in keys:
            raise ManifestError(f"settings: {key} is listed but not declared")


def _secret_shaped(value) -> bool:
    from ..scrub import secret_shaped
    if isinstance(value, str):
        return secret_shaped(value)
    if isinstance(value, list | tuple):
        return any(_secret_shaped(x) for x in value)
    return False


def _check_model(m: dict, fid: str, tiers, search_kinds) -> None:
    model = m.get("model") or {}
    if any(t not in tiers for t in model.get("tiers", [])):
        raise ManifestError(f"model.tiers are some of {', '.join(tiers)}")
    for p in model.get("purposes", []):
        if not (p == fid or str(p).startswith(fid + "_")):
            raise ManifestError(f"model.purposes: {p!r} must be {fid} or start with {fid}_")
    if search_kinds and any(k not in search_kinds for k in m.get("search", [])):
        raise ManifestError(f"search kinds are some of {', '.join(search_kinds)}")


def _check_jobs(m: dict, fid: str, settings_keys: dict, cub: bool) -> None:
    purposes = set((m.get("model") or {}).get("purposes", []))
    subscribed = {s.get("kind") for s in (m.get("events") or {}).get("subscribe", [])}
    for job in m.get("jobs", []):
        kind = str(job.get("kind", ""))
        if not kind.startswith(fid + "."):
            raise ManifestError(f"jobs: {kind!r} must start with {fid}.")
        if job.get("days") and not job.get("at"):
            raise ManifestError(f"jobs.{kind}: days needs at (the time of day it runs)")
        when = job.get("when")
        if when is not None and (when not in settings_keys
                                 or settings_keys[when].get("type") != "bool"):
            raise ManifestError(f"jobs.{kind}: when names {when!r}, which is not one of its "
                                "true-or-false settings")
        if job.get("purpose") is not None and job["purpose"] not in purposes:
            raise ManifestError(f"jobs.{kind}: purpose {job['purpose']!r} is not one of its "
                                "model.purposes")
        if cub:
            missing = [k for k in job.get("on", []) if k not in subscribed]
            if missing:
                raise ManifestError(f"jobs.{kind}: on names {', '.join(missing)}, which it does "
                                    "not subscribe to")


def _check_fields(where: str, fields: list, provides: set[str]) -> None:
    seen = set()
    for f in fields:
        key = str(f.get("key"))
        if key in seen:
            raise ManifestError(f"{where}: {key!r} is not a new field key")
        seen.add(key)
        if f.get("kind") == "enum" and not f.get("choices"):
            raise ManifestError(f"{where}.{key}: an enum needs its choices")
        if f.get("read") is not None and f["read"] not in provides:
            raise ManifestError(f"{where}.{key}: {f['read']!r} is not one of its reads")
        if f.get("kind") == "choice" and not f.get("choices") and not f.get("read"):
            raise ManifestError(f"{where}.{key}: a choice needs its choices or a read")


def _check_actions(m: dict, fid: str, provides: set[str], cub: bool,
                   settings_keys: dict | None = None) -> set[str]:
    kinds = set()
    for act in m.get("actions", []):
        kind = str(act.get("kind", ""))
        if kind in kinds:
            raise ManifestError(f"actions: {kind} is declared twice")
        kinds.add(kind)
        when = act.get("when")
        if when is not None and (settings_keys is None or when not in settings_keys
                                 or settings_keys[when].get("type") != "bool"):
            raise ManifestError(f"actions.{kind}: when names {when!r}, which is not one of its "
                                "true-or-false settings")
        _check_fields(f"actions.{kind}", act.get("fields", []), provides)
        if act.get("place") == "head" and m["trust"] != "first-party":
            raise ManifestError(f"actions: {kind} asks for the page's head, which is "
                                "first-party only in this schema")
        if not kind.startswith(fid + "."):
            raise ManifestError(f"actions: {kind!r} must start with {fid}.")
        doors = act.get("doors", [])
        if act.get("click") == "house" and set(doors) - {"ui"}:
            raise ManifestError(f"actions: {kind} takes the house confirm, so its only door is "
                                "ui")
    return kinds


def _check_requests(m: dict, request_kinds, cub: bool) -> None:
    from . import tickets
    bad = [r for r in m.get("requests", []) if r not in request_kinds]
    if bad:
        raise ManifestError(f"requests: no such high-trust action: {', '.join(bad)}")
    if cub:
        own = [r for r in m.get("requests", []) if r in tickets.KINDS
               and not tickets.grantable_to(r, "owner")]
        if own:
            raise ManifestError(f"requests: {', '.join(own)} is Kranto's own: a cub may not ask "
                                "for it")


def _check_broker(m: dict, broker_ops: dict[str, set[str]] | None, cub: bool) -> None:
    broker = m.get("broker") or {}
    if not cub:
        return
    offered = broker_ops or {}
    for service, ops in broker.items():
        if service not in offered:
            raise ManifestError(f"broker: no {service} operations in this Kranto"
                                + (f" (services: {', '.join(sorted(offered))})" if offered
                                   else ""))
        bad = [o for o in ops if o not in offered[service]]
        if bad:
            raise ManifestError(f"broker.{service}: no such operation a cub may be granted: "
                                f"{', '.join(bad)}")


def _check_ui(m: dict, provides: set[str], action_kinds: set[str]) -> None:
    ui = m.get("ui") or {}
    cards = ui.get("cards") or {}
    requests_ = set(m.get("requests", []))
    for row in ui.get("today_rows", []):
        if row.get("read") not in provides:
            raise ManifestError(f"ui.today_rows: {row.get('read')!r} is not one of its reads")
        if row.get("card") is not None and row["card"] not in cards:
            raise ManifestError(f"ui.today_rows: no card {row['card']!r} in ui.cards")
        primary = row.get("primary", "open")
        if primary not in ("open", "confirm") and primary not in action_kinds \
                and primary not in requests_:
            raise ManifestError(f"ui.today_rows: primary {primary!r} is open, confirm, one of "
                                "its actions or one of its request kinds")
    for n in ui.get("nav", []):
        if n.get("count") is not None and n["count"] not in provides:
            raise ManifestError(f"ui.nav: count {n['count']!r} is not one of its reads")
    for name, card in cards.items():
        bad = [a for a in card.get("actions", []) if a not in action_kinds]
        if bad:
            raise ManifestError(f"ui.cards.{name}: no action {', '.join(bad)}")
        if card.get("open", "sheet") not in CARD_OPENS:
            raise ManifestError(f"ui.cards.{name}.open is one of {', '.join(CARD_OPENS)}")
        if card.get("open") == "page" and not card.get("body"):
            raise ManifestError(f"ui.cards.{name}: open: page needs body, the field drawn as the "
                                "page's text")
    tile = ui.get("tile")
    if tile is not None and tile.get("count") is not None and tile["count"] not in provides:
        raise ManifestError(f"ui.tile.count: {tile['count']!r} is not one of its reads")
    seen: set[str] = set()
    for x in ui.get("lists", []):
        if x["id"] in seen:
            raise ManifestError(f"ui.lists: {x['id']!r} is not a new list id")
        seen.add(x["id"])
        if x.get("read") not in provides:
            raise ManifestError(f"ui.lists.{x['id']}: {x.get('read')!r} is not one of its reads")
        if x.get("card") not in cards:
            raise ManifestError(f"ui.lists.{x['id']}: no card {x.get('card')!r} in ui.cards")
        keys = [g.get("key") for g in x.get("groups", [])]
        if x.get("count") is not None and x["count"] not in keys:
            raise ManifestError(f"ui.lists.{x['id']}.count names one of its groups")
    for x in ui.get("forms", []):
        if x["id"] in seen:
            raise ManifestError(f"ui.forms: {x['id']!r} is not a new id")
        seen.add(x["id"])
        if x.get("submit") not in action_kinds:
            raise ManifestError(f"ui.forms.{x['id']}: submit names one of its actions")
        _check_fields(f"ui.forms.{x['id']}", x.get("fields", []), provides)
    for x in ui.get("lists", []):
        for g in x.get("groups", []):
            if g.get("tone", "quiet") not in GROUP_TONES:
                raise ManifestError(f"ui.lists.{x['id']}: a group's tone is one of "
                                    f"{', '.join(GROUP_TONES)}")
    primary = ui.get("primary")
    if primary is not None:
        forms = {x["id"] for x in ui.get("forms", [])}
        heads = {a.get("kind") for a in m.get("actions", []) if a.get("place") == "head"}
        if primary not in forms and primary not in heads:
            raise ManifestError(f"ui.primary: {primary!r} is not one of its forms (ui.forms) "
                                "or an action in its page's head")
    _check_widgets(ui.get("widgets", []), provides,
                   {x["id"] for x in ui.get("lists", [])})


def _check_widgets(widgets: list, provides: set[str], lists: set[str]) -> None:
    """each widget's read is one of its reads, its ``open`` one of its
    lists, its id new; the schema holds the kinds, the sizes, the floor and the count."""
    seen: set[str] = set()
    for w in widgets:
        where = f"ui.widgets.{w['id']}"
        if w["id"] in seen:
            raise ManifestError(f"ui.widgets: {w['id']!r} is declared twice")
        seen.add(w["id"])
        if w.get("read") not in provides:
            raise ManifestError(f"{where}: its read {w.get('read')!r} is not one of its reads "
                                "(provides)")
        if w.get("open") is not None and w["open"] not in lists:
            raise ManifestError(f"{where}: open names one of its ui.lists, or is left out for "
                                "its page")


def _anchor_rank(at: str) -> int | None:
    return ANCHORS.index(at) if at in ANCHORS else None


def _check_stages(m: dict, fid: str, request_kinds, settings_keys: dict,
                  files: set[str] | None) -> None:
    """A cub's build stages."""
    stages = m.get("stages", [])
    by_id = {}
    cap = (m.get("model") or {}).get("monthly_usd")
    for st in stages:
        sid = st["id"]
        where = f"stages.{sid}"
        if sid in by_id:
            raise ManifestError(f"{where}: two stages are called {sid}")
        by_id[sid] = st
        if st.get("tree") == "rw" and st["at"] == "before_publish":
            raise ManifestError(f"{where}: a stage before publish reads the tree only (tree: "
                                "ro): nothing edits it after Check")
        if "patch" in st.get("gives", []) and st.get("tree") != "rw":
            raise ManifestError(f"{where}: gives a patch, so it needs tree: rw")
        if st.get("tree") == "rw" and not st.get("writes"):
            raise ManifestError(f"{where}: tree: rw needs writes (the paths it may change)")
        bad = [r for r in st.get("requests", []) if r not in request_kinds]
        if bad:
            raise ManifestError(f"{where}.requests: no such high-trust action: {', '.join(bad)}")
        if st["kind"] == "session" and not st.get("prompt"):
            raise ManifestError(f"{where}: a session stage needs its prompt file")
        if st["kind"] == "code" and not st.get("entry"):
            raise ManifestError(f"{where}: a code stage needs its entry file")
        _inside(f"{where}.entry", st.get("entry"), files)
        _inside(f"{where}.prompt", st.get("prompt"), files)
        model = st.get("model") or {}
        if model.get("max_usd") is not None and cap is not None and model["max_usd"] > cap:
            raise ManifestError(f"{where}: model.max_usd ${model['max_usd']} is over the cub's "
                                f"${cap} a month")
        if st.get("hold_at") is not None and st.get("on_fail") != "hold":
            raise ManifestError(f"{where}: hold_at needs on_fail: hold")
        if "findings" in st.get("reads", []) and st["at"] == "after_brief":
            raise ManifestError(f"{where}: there are no findings yet after the brief")
        bad = [k for k in st.get("settings", []) if k not in settings_keys]
        if bad:
            raise ManifestError(f"{where}.settings: {', '.join(bad)} is not one of its settings")
    for st in stages:
        mine = _anchor_rank(st["at"])
        for need in st.get("needs", []):
            other = by_id.get(need) or by_id.get(need.removeprefix(fid + "."))
            if other is None or mine is None:
                continue
            theirs = _anchor_rank(other["at"])
            if theirs is not None and theirs > mine:
                raise ManifestError(f"stages.{st['id']}: needs {need}, which runs later "
                                    f"({other['at']})")


REQUIREMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*==[A-Za-z0-9.+!-]+"
                         r"(\s+--hash=sha256:[0-9a-f]{64})+")
MAX_REQUIREMENTS = 50


def check_requirements(text: str) -> list[str]:
    """A cub's ``requirements.txt`` (rule 9): every line ``name==version`` with at least
    one ``--hash=sha256:…`` (a backslash continuation joins lines, comments and blank lines
    are skipped), at most 50 lines. Returns the requirement lines; ``uv pip install
    --require-hashes --only-binary :all:`` is still the install, so a sdist-only package or a
    wrong hash fails there in uv's words."""
    raw = text.replace("\\\n", " ").splitlines()
    if len(text.splitlines()) > MAX_REQUIREMENTS:
        raise ManifestError(f"requirements: at most {MAX_REQUIREMENTS} lines")
    out = []
    for n, line in enumerate(raw, 1):
        line = " ".join(line.split("#", 1)[0].split())     # a sha256 has no "#"
        if not line:
            continue
        if not REQUIREMENT.fullmatch(line):
            raise ManifestError(f"requirements: line {n} is not name==version with "
                                f"--hash=sha256:… ({line[:60]!r}): no ranges, URLs, paths or "
                                "editables")
        out.append(line)
    return out

