"""Topic-first configuration: propose sources for a topic, then check them.

The scout (a tier-2 model call) proposes candidate sources from a topic's
plain-language description. Its proposals are untrusted: every one is
fetched before a person sees it. A proposal that cannot be fetched or has no
items is recorded as ``invalid`` and never shown as a candidate. One that
fetches is ``proposed`` with the numbers a person needs to decide: how many
items, how recent, and how similar its items are to the topic.

Most proposals are ``core``: sources about the topic. Up to ``MAX_WILDCARDS``
are ``wildcard``: sources unrelated to the topic that are likely to carry the
same patterns in another vocabulary. Wildcards are the aperture the topic
would otherwise close, so they are handled differently: they are never
auto-approved (their items are by design dissimilar to the topic), and they
are not linked to the topic, so once a person approves one its items reach
the judge without the topic prefilter, like any other broad source. The role
is kept in the source's validation record.

The scout speaks in presets (``sources.catalog``, section 2): it
proposes ``{"preset": ..., "fields": {...}}`` from the public presets the catalog
marks for it, so what it proposes is what a person could add by hand, and a
proposal is reviewed on the same page. It never proposes a login preset, and no
Reddit: Reddit's feeds stop on 13 Nov 2026. For a topic that watches Reddit
sources, the prompt lists them and asks for replacements, each marked with what it
``replaces``.

A proposed feed URL that fails for good on a publication's own host is often the
right publication with the wrong path: the site's feed is looked up from its
homepage and checked in its place. An arXiv listing with no items is ``unverified``,
not ``invalid``: arXiv announces nothing on weekends and holidays.

Proposals written the older way, ``{"kind": ..., "value": ...}``, are still
accepted for ``rss``, ``hackernews``, ``arxiv`` and ``site`` (a homepage whose feed
is found during validation, ``sources.discover``).

**Grounded in live search** (5, the owner's rule of 2026-10-17: what exists and
what is new comes from the web, not the model's memory). Before the call, ``ground`` runs a
search per angle (blogs, newsletters, podcasts, forums, researchers and projects through the
web backend; repositories created in the last year through GitHub; stories through Hacker
News; papers through arXiv) and the prompt gets the dated results: proposals come FROM THESE
RESULTS and name them in ``from``; a source no result names may come only in ``from_memory``,
at most ``MAX_FROM_MEMORY``. Each proposal's record keeps the hits it cites (``cites``, the
reply's ``from`` checked against the block: a label the block does not have loses its
grounding, never the proposal), its ``grounding`` (``results``, ``cites nothing`` or
``memory``) and the run's ``search`` (backends, date, the sentence). (``from`` in a record is
describe-sources' pasted line, so the scout's citations have their own key.) With no live
search the prompt says so, every proposal is
``memory`` and the sentence "no live search: results are from model memory and may be stale"
travels with the run. A site found by search that has no feed is proposed as a source watched
through live search (``websearch``, one search a run, restricted to the site), never
approved by the scout, and reported as ``no_feed``. Wildcards come from results too: two of the
strongest dated results are searched for sites like them (``Searcher.similar``,),
and the block says which results those are.
"""

from __future__ import annotations

import statistics
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urlparse

from . import library, prompts, sources, websearch
from .embed import Embedder
from .intern import extract_json_object
from .llm import LLMClient
from .sources import catalog
from .sources.discover import discover_feed
from .store import Store, iso, utcnow
from .stored import sources as stored_sources

if TYPE_CHECKING:
    from .sources.x import XSource

MAX_PROPOSALS = 20
SIMILARITY_SAMPLE = 30
RECENT_DAYS = 30
MAX_WILDCARDS = 3
MAX_FROM_MEMORY = 3
NO_FEED = "no_feed"
WILDCARD_SEEDS = 2      # dated results searched for sites like them (the wildcards' results)
# The angles the scout searches before it proposes: (what, kind, backends, how many, recency).
# The web backend's six are the US measurement's; GitHub finds repositories created this year
# (the only way the measurement found young ones), Hacker News stories, arXiv papers.
GROUNDING = (
    ("blogs and personal sites that regularly publish substantive posts about {topic}",
     "web", None, 8, "12mo"),
    ("newsletters covering {topic}", "web", None, 8, "12mo"),
    ("podcasts about {topic} with recent episodes", "web", None, 8, "12mo"),
    ("forums, communities and discussion boards where practitioners discuss {topic}",
     "web", None, 8, None),
    ("researchers and labs publishing on {topic}: their homepages", "web", None, 8, None),
    ("open-source projects about {topic} with recent releases", "web", None, 8, "12mo"),
    ("{topic}", "code", ("github",), 12, "12mo"),
    ("{topic}", "discussion", ("hackernews",), 10, "12mo"),
    ("{topic}", "papers", ("arxiv",), 5, "12mo"),
)
ROLES = ("core", "wildcard")
SITE = "site"  # a homepage whose feed is found during validation
PRESET = "preset"  # a proposal made as a catalog preset with fields
PROPOSAL_KINDS = frozenset({"rss", "hackernews", "arxiv", SITE})
SCOUT_PRESETS = {k: p for k, p in catalog.PRESETS.items() if p.scout}
# Never proposed, not even as a plain feed URL or a homepage (see ``_refuse_excluded``).
EXCLUDED_HOSTS = {"reddit.com": "Reddit", "redd.it": "Reddit", "lobste.rs": "Lobsters"}


@dataclass(frozen=True)
class Proposal:
    kind: str
    value: str
    why: str
    role: str = "core"
    preset: str | None = None
    fields: dict[str, Any] = field(default_factory=dict, hash=False, compare=False)
    replaces: str | None = None
    cites: tuple[str, ...] = ()
    from_memory: bool = False


# X presets the scout may propose while X is connected and under its cap:
# each costs money per post read, so they are proposed, checked with one small fetch, and
# never approved by themselves.
X_SCOUT_PRESETS = ("x.search", "x.profile", "x.list")
X_CHECK_POSTS = 10
MAX_X_LISTS = 50


@dataclass(frozen=True)
class XScouting:
    """X for one scout run: the account's HTTP, the person's own lists (name, id), how many
    X proposals may be checked."""

    http: sources.HTTP
    connections: object
    lists: tuple[tuple[str, str], ...] = ()
    max_proposals: int = 5


def x_scouting(store: Store, connections: Any, xcfg: Any,
               http: sources.HTTP) -> XScouting | None:
    """Whether this scout run may propose X, and with what: X connected, ``x.scout`` on, the
    month's X reads under ``x.monthly_usd``. The person's owned lists are read once ($0.005 a
    list, at most 50) so the scout can name one by its title."""
    from . import spend
    from .sources.x import API

    if connections is None or xcfg is None or not xcfg.scout or xcfg.scout_max_proposals <= 0:
        return None
    if spend.capped(store, xcfg.monthly_usd) is not None:
        return None
    try:
        authed = connections.http_for("x", None, http)
        me = authed.auth_account
        lists: list[tuple[str, str]] = []
        if me:
            data = authed.get_json(f"{API}/users/{me}/owned_lists",
                                   params={"max_results": MAX_X_LISTS})
            for row in (data.get("data") or []) if isinstance(data, dict) else []:
                if isinstance(row, dict) and str(row.get("id") or "").isdigit():
                    lists.append((" ".join(str(row.get("name") or "").split())[:80],
                                  str(row["id"])))
    except sources.SourceError:
        return None
    return XScouting(authed, connections, tuple(lists), xcfg.scout_max_proposals)


def presets_text(x: XScouting | None = None) -> str:
    """The catalog as the scout reads it: one line per preset it may propose, and the X
    presets with the person's own lists when this run may propose X."""
    lines = []
    for key, p in SCOUT_PRESETS.items():
        fields = ", ".join(f'"{f.key}" ({f.label.lower()}, e.g. {f.placeholder})'
                           for f in p.fields) or "no fields"
        lines.append(f"    {key:<22} {catalog.PROVIDERS[p.provider]}: {p.name}. {p.blurb} "
                     f"Fields: {fields}.")
    if x is not None:
        for key in X_SCOUT_PRESETS:
            p = catalog.PRESETS[key]
            if key == "x.list" and not x.lists:
                continue
            fields = ", ".join(f'"{f.key}" ({f.label.lower()}, e.g. {f.placeholder})'
                               for f in p.fields if not f.label.endswith("(optional)")) \
                or "no fields"
            lines.append(f"    {key:<22} {catalog.PROVIDERS[p.provider]}: {p.name}. {p.blurb} "
                         f"Fields: {fields}.")
        if x.lists:
            lines.append("    The person's own X lists (for x.list, give the number): "
                         + "; ".join(f"{name or 'untitled'} ({lid})" for name, lid in x.lists))
        lines.append(f"    X presets are paid per post read: propose at most {x.max_proposals}, "
                     "only where X is where the topic's conversation happens.")
    return "\n".join(lines)


def _replacements_text(reddit_labels: list[str]) -> str:
    if not reddit_labels:
        return ""
    return ("\nThis topic watches Reddit sources whose feeds stop on 13 Nov 2026: "
            + ", ".join(reddit_labels) + ". Among your core sources, propose one or two "
            "replacements for each (an HN search, a Mastodon hashtag, a Bluesky feed or list, "
            "a forum's or a publication's feed covering the same ground), and set "
            "\"replaces\" to the Reddit source it replaces. Never propose Reddit.\n")


@dataclass(frozen=True)
class Validation:
    status: str  # "valid" | "invalid" | "unverified"
    items: int = 0
    recent: int = 0
    latest: str | None = None
    median_similarity: float | None = None
    error: str | None = None
    discovered_from: str | None = None


@dataclass(frozen=True)
class ScoutResult:
    source_id: int | None
    label: str
    proposal: Proposal
    validation: Validation
    status: str
    search: dict[str, Any] | None = None     # the run's live search: backends, date, the sentence


def ground(searcher: websearch.Searcher | None, topic: library.Topic) -> websearch.Results:
    """The live search results the scout proposes from: one search per ``GROUNDING`` angle,
    combined into one numbered block. Without a searcher, the "no live search" sentence."""
    if searcher is None:
        return websearch.Results(topic.name, (), None, iso(utcnow()), note=websearch.NO_SEARCH)
    name = " ".join(topic.name.split())[:120]
    runs = []
    if searcher.off_reason() is None:
        for what, kind, backends, n, recency in GROUNDING:
            if (backends and not searcher.route(kind, backends)) \
                    or (not backends and searcher.web is None):
                continue
            runs.append(searcher.search(what.format(topic=name), kind=kind, backends=backends,
                                        n=n, recency=recency))
    if not runs:
        return searcher.search(name)      # the off switch's or no backend's sentence
    core = websearch.combine(*runs)
    dated = sorted((h for h in core.hits if h.date and h.backend not in websearch.FREE_BACKENDS),
                   key=lambda h: h.date or "", reverse=True)
    seeds = list({h.url: h for h in reversed(dated)}.values())[::-1][:WILDCARD_SEEDS]
    if seeds and searcher.web is not None:
        runs += [searcher.similar(h.url, h.title, n=5) for h in seeds]
    return websearch.combine(*runs)


def grounding_text(results: websearch.Results, weeks: int = 12) -> str:
    """What the prompt's ``{results}`` says: the dated block and how to use it, or that there
    is no live search."""
    day = results.searched_at[:10]
    if not results.live:
        return ("No live search ran for this topic (" + (results.note or websearch.NO_SEARCH)
                + "), so there are no results: what you propose comes from your memory and may "
                "be stale. Put every proposal in \"sources\" with \"from\": [] and begin every "
                "\"why\" with \"From memory:\".")
    return (f"Below are live search results, each dated (searched on {day}). Propose sources "
            "FROM THESE RESULTS: every proposal names the results it comes from in \"from\" "
            "(their labels, such as \"exa 3\") and its \"why\" says what those results show "
            f"and when. Prefer sources whose results are dated in the last {weeks} weeks, and "
            "say when a source was first active recently (a repository's creation date, a "
            "newsletter's first issue). A source you know but no result names may be proposed "
            f"only in \"from_memory\", at most {MAX_FROM_MEMORY}, and only where the results "
            "miss something important. A result about a source is not the source: propose the "
            "publication, project or community the result shows. The last results are sites "
            "like two of the strongest results: choose the wildcards from them where one "
            "carries the topic's patterns in another field.\n\n" + results.block(
                "Live search results"))


def parse_proposals(text: str, *, x: bool = False) -> list[Proposal]:
    """``x``: the X presets may be proposed too (``x_scouting``). Proposals in
    ``from_memory`` (at most ``MAX_FROM_MEMORY``) come after the grounded ones, marked."""
    obj = extract_json_object(text) or {}
    raw: list[Any] = obj["sources"] if isinstance(obj.get("sources"), list) else []
    memory: list[Any] = obj["from_memory"] if isinstance(obj.get("from_memory"), list) else []
    raw = [*raw[:MAX_PROPOSALS], *({**m, "_memory": True} for m in memory[:MAX_FROM_MEMORY]
                                   if isinstance(m, dict))]
    allowed_presets = {**SCOUT_PRESETS, **({k: catalog.PRESETS[k] for k in X_SCOUT_PRESETS}
                                           if x else {})}
    out, seen, wildcards = [], set(), 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        preset = str(entry.get("preset") or "").strip()
        fields: dict[str, Any] = {}
        if preset:
            if preset not in allowed_presets or not isinstance(entry.get("fields") or {}, dict):
                continue
            allowed = {f.key for f in allowed_presets[preset].fields}
            required = {f.key for f in allowed_presets[preset].fields
                        if not f.label.endswith("(optional)")}
            fields = {str(k): " ".join(str(v).split())[:300]
                      for k, v in (entry.get("fields") or {}).items()
                      if k in allowed and isinstance(v, str | int | float) and str(v).strip()}
            if not required <= set(fields):
                continue
            kind, value = PRESET, " ".join([preset, *(fields[k] for k in sorted(fields))])
        else:
            kind = str(entry.get("kind") or "").strip().lower()
            value = str(entry.get("value") or "").strip()
            if kind not in PROPOSAL_KINDS or not value:
                continue
        if (kind, value.lower()) in seen:
            continue
        role = str(entry.get("role") or "core").strip().lower()
        role = role if role in ROLES else "core"
        if role == "wildcard":
            # Extra wildcards are dropped rather than relabelled as core: the model
            # said they are unrelated to the topic, so core handling would be wrong.
            if wildcards >= MAX_WILDCARDS:
                continue
            wildcards += 1
        seen.add((kind, value.lower()))
        replaces = str(entry.get("replaces") or "").strip()[:100] or None
        named: list[Any] = entry["from"] if isinstance(entry.get("from"), list) else []
        cites = tuple(dict.fromkeys(" ".join(str(c).strip("[] ").lower().split())
                                    for c in named if isinstance(c, str) and c.strip()))[:10]
        out.append(Proposal(kind, value, str(entry.get("why") or "").strip()[:300], role,
                            preset or None, fields, replaces, cites,
                            bool(entry.get("_memory"))))
    return out


def reddit_sources(store: Store, topic_id: int) -> list[str]:
    """Labels of the Reddit sources watched for a topic: the ones to replace."""
    linked = {r["source_id"] for r in store.query(
        "SELECT source_id FROM topic_links WHERE topic_id = ?", (topic_id,))}
    return [s.label for s in library.list_sources(store, "approved")
            if s.kind == "reddit" and s.id in linked]


def propose(llm: LLMClient, topic: library.Topic,
            replace: list[str] | None = None,
            x: XScouting | None = None,
            results: websearch.Results | None = None,
            weeks: int = 12) -> tuple[list[Proposal], int]:
    """``results``: the live search block the proposals come from (``ground``); None or
    not live: the prompt says there is no live search."""
    results = results or websearch.Results(topic.name, (), None, iso(utcnow()),
                                           note=websearch.NO_SEARCH)
    prompt = prompts.load("scout")
    completion = llm.complete(
        tier="reason",
        purpose="scout",
        prompt_version=prompt.version,
        messages=[
            {"role": "user", "content": prompt.render_keeping(
                "results", name=topic.name, description=topic.description,
                presets=presets_text(x), replacements=_replacements_text(replace or []),
                results=grounding_text(results, weeks), today=results.searched_at[:10])}
        ],
        # The tier-2 model reasons before it answers: at 2000 every scout call
        # was cut off with no content; one complete reply used 3,263 tokens.
        max_tokens=llm.max_tokens("scout"),
        temperature=0.4,
    )
    return parse_proposals(completion.text, x=x is not None), completion.call_id


def search_summary(results: websearch.Results) -> dict[str, Any]:
    """The run's live search as the page and the CLI show it: the chip's words."""
    return {"live": results.live, "backends": list(results.labels or results.backends),
            "searched_at": results.searched_at, "results": len(results.hits),
            "note": results.note}


def grounding(proposal: Proposal, results: websearch.Results) -> tuple[str, list[dict[str, Any]]]:
    """How a proposal is grounded: ``results`` with the hits it cites, ``cites nothing``
    when it names no result the block has, ``memory`` when it came from memory."""
    if not results.live or proposal.from_memory:
        return "memory", []
    found = [(label, websearch.hit_for(results, label)) for label in proposal.cites]
    hits = [{"label": label, "url": h.url, "title": h.title[:200], "date": h.date}
            for label, h in found if h is not None]
    return ("results" if hits else "cites nothing"), hits


def _watch_by_search(store: Store, proposal: Proposal, cited: list[dict[str, Any]],
                     record: dict[str, Any],
                     topic: library.Topic, call_id: int, now: datetime | None,
                     searcher: Any) -> int | None:
    """A ``websearch`` source for a site the results show without a feed: proposed (or the
    existing one), linked to the topic, with what each run costs; None when live search is off
    for sources or the site has no address."""
    from .sources.websearch_source import host_of
    site = host_of(str(proposal.fields.get("site") or proposal.fields.get("url")
                       or proposal.value))
    if searcher is None or not site or searcher.cfg.caller("sources") == "off":
        return None
    params = {"site": site}
    existing = store.query_one("SELECT id FROM sources WHERE kind = ? AND params = ?",
                               ("websearch", sources.canonical_params("websearch", params)))
    if existing:
        source_id = int(existing["id"])
    else:
        from . import pricing
        backend = searcher.web
        free = backend == "exa" and getattr(searcher.backends.get("exa"), "free_mode", False)
        run = 0.0 if free else pricing.search_cost(websearch.SPEND_PROVIDER.get(backend or "",
                                                                                 ""))
        source_id = library.add_source(
            store, "websearch", params, label=f"Live search: {site}", origin="scout",
            status="proposed", origin_call_id=call_id, now=now,
            validation=stored_sources.Validation.from_dict({
                **record, "status": "unverified", "preset": "web.search",
                "fields": {"site": site},
                "error": "no feed found: watched through live search instead",
                "cost_usd": {"check": 0.0, "run": round(run, 4)}}))
    library.link_topic_source(store, topic.id, source_id)
    return source_id


def _refuse_excluded(kind: str, params: dict[str, Any]) -> None:
    """Refuse Reddit and Lobsters even when proposed as a plain feed URL or a homepage
    (owner decisions of 6 Oct 2026: Reddit's feeds stop on 13 Nov 2026; Lobsters
    signals ``ai-input=no``)."""
    if kind == "reddit":
        raise ValueError("the scout does not propose Reddit: its feeds stop on 13 Nov 2026")
    host = (urlparse(str(params.get("url") or "")).hostname or "").lower()
    for domain, name in EXCLUDED_HOSTS.items():
        if host == domain or host.endswith("." + domain):
            raise ValueError(f"the scout does not propose {name}")


ARXIV_QUIET = ("arXiv publishes no listing on weekends and holidays; checked again on the "
               "next run")
# Hosts that serve many unrelated feeds: there a feed URL's path names the channel,
# repository or listing, and the root's feed would be a different source.
PLATFORM_HOSTS = frozenset({
    "arxiv.org", "bsky.app", "github.com", "medium.com", "news.ycombinator.com", "reddit.com",
    "substack.com", "youtube.com", "stackexchange.com", "stackoverflow.com", "x.com",
    "twitter.com",
})


def is_arxiv_listing(kind: str, params: dict[str, Any] | None) -> bool:
    """An arXiv category listing feed, which is empty on days without announcements."""
    host = (urlparse(str((params or {}).get("url") or "")).hostname or "").lower()
    return kind == "rss" and (host == "arxiv.org" or host.endswith(".arxiv.org"))


def site_root(feed_url: str) -> str | None:
    """The homepage to look a feed up from when a proposed feed URL fails, or None when
    the host is a platform whose root belongs to no one publication."""
    parsed = urlparse(feed_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    if parsed.scheme not in ("http", "https") or not host \
            or any(host == p or host.endswith("." + p) for p in PLATFORM_HOSTS):
        return None
    root = f"{parsed.scheme}://{parsed.netloc}/"
    return None if root == feed_url else root


def _site_feed(kind: str, params: dict[str, Any] | None, discovered_from: str | None,
               http: sources.HTTP) -> Proposal | None:
    """#78: a proposed feed URL is often the right publication with the wrong path. When
    it fails for good on a publication's own host, the site's feed is looked up from its
    homepage and validated in its place (``validate`` records the failed URL as
    ``discovered_from``). None when that finds nothing, or the URL was already found by
    discovery."""
    if kind != "rss" or discovered_from is not None:
        return None
    root = site_root(str((params or {}).get("url") or ""))
    if root is None:
        return None
    try:
        found = discover_feed(http, root)
    except sources.SourceError:
        return None
    if found == (params or {}).get("url"):
        return None
    return Proposal(PRESET, f"web.feed {found}", "", preset="web.feed", fields={"url": found})


def _found_instead(found: Proposal, failed: dict[str, Any], http: sources.HTTP,
                   embedder: Embedder, topic: library.Topic | None, now: datetime | None
                   ) -> tuple[Validation, str, str, dict[str, Any] | None] | None:
    validation, label, kind, params = validate(found, http, embedder, topic, now=now)
    if validation.status != "valid":
        return None
    return replace(validation, discovered_from=failed.get("url")), label, kind, params


def validate(
    proposal: Proposal,
    http: sources.HTTP,
    embedder: Embedder,
    topic: library.Topic | None,
    *,
    now: datetime | None = None,
    x: XScouting | None = None,
) -> tuple[Validation, str, str, dict[str, Any] | None]:
    """Fetch a proposed source and measure it. Returns (validation, label, kind, params).
    With ``topic`` None the similarity is not measured (``median_similarity`` None).

    A preset proposal is built through the catalog. For a ``site`` proposal the
    kind and params are those of the ``rss`` source found for it, and
    ``discovered_from`` records the homepage.
    """
    discovered_from, label = None, None
    kind, value = proposal.kind, proposal.value
    if x is not None and proposal.preset in X_SCOUT_PRESETS:
        return _validate_x(proposal, x, embedder, topic, now=now)
    if kind == PRESET:
        try:
            resolved = catalog.resolve(proposal.preset or "", proposal.fields, http)
        except (ValueError, TypeError) as exc:
            return Validation("invalid", error=str(exc)), proposal.value, kind, None
        except sources.SourceError as exc:
            status = "unverified" if exc.transient else "invalid"
            return Validation(status, error=str(exc)), proposal.value, kind, None
        kind, params, label = resolved.kind, resolved.params, resolved.label
        if proposal.preset == "web.site":
            discovered_from = proposal.fields.get("site")
    elif kind == SITE:
        try:
            value = discover_feed(http, proposal.value)
        except sources.SourceError as exc:
            status = "unverified" if exc.transient else "invalid"
            return Validation(status, error=str(exc)), proposal.value, "rss", None
        kind, discovered_from = "rss", proposal.value
    try:
        if label is None:
            params = sources.params_from_value(kind, value)
        _refuse_excluded(kind, params)
        adapter = sources.build(kind, params, http)
    except (ValueError, TypeError, sources.SourceError) as exc:
        return Validation("invalid", error=str(exc)), proposal.value, kind, None
    try:
        items = adapter.fetch()
    except sources.SourceError as exc:
        status = "unverified" if exc.transient else "invalid"
        found = None if exc.transient else _site_feed(kind, params, discovered_from, http)
        instead = found and _found_instead(found, params, http, embedder, topic, now)
        if instead:
            return instead
        return (Validation(status, error=str(exc), discovered_from=discovered_from),
                label or adapter.label, kind, params)
    # A feed's own title, read by the fetch, names a source added the older way.
    label = label or adapter.label
    if not items:
        if is_arxiv_listing(kind, params):
            return (Validation("unverified", error=ARXIV_QUIET), label, kind, params)
        found = _site_feed(kind, params, discovered_from, http)
        instead = found and _found_instead(found, params, http, embedder, topic, now)
        if instead:
            return instead
        return (Validation("invalid", error="feed has no items", discovered_from=discovered_from),
                label, kind, params)

    return (_measure(items, embedder, topic, now or utcnow(), discovered_from), label, kind,
            params)


def _measure(items: list[sources.Item], embedder: Embedder, topic: library.Topic | None,
             now: datetime, discovered_from: str | None = None) -> Validation:
    """A fetched source's numbers. Without a topic (a pasted list with none chosen) the
    similarity is not measured: every item is judged."""
    dated = [it.published_at for it in items if it.published_at]
    recent = sum(1 for d in dated if d >= now - timedelta(days=RECENT_DAYS))
    similarity = None
    if topic is not None:
        sims = embedder.embed_documents([it.text_for_prefilter() for it in
                                         items[:SIMILARITY_SAMPLE]]) @ topic.embedding
        similarity = round(float(statistics.median(sims.tolist())), 4)
    return Validation("valid", items=len(items), recent=recent,
                      latest=iso(max(dated)) if dated else None,
                      median_similarity=similarity, discovered_from=discovered_from)


def _validate_x(proposal: Proposal, x: XScouting, embedder: Embedder,
                topic: library.Topic | None,
                *, now: datetime | None = None
                ) -> tuple[Validation, str, str, dict[str, Any] | None]:
    """An X proposal: resolved and checked with the account, one fetch of 10 posts (about
    $0.05 at X's list price, counted in api_spend)."""
    try:
        resolved = catalog.resolve(proposal.preset or "", proposal.fields, x.http)
        adapter = sources.build(resolved.kind, resolved.params, x.http,
                                connections=x.connections)
        items = cast("XSource", adapter).fetch_after(None, X_CHECK_POSTS)
    except (ValueError, TypeError) as exc:
        return Validation("invalid", error=str(exc)), proposal.value, "x", None
    except sources.SourceError as exc:
        status = "unverified" if exc.transient else "invalid"
        return Validation(status, error=str(exc)), proposal.value, "x", None
    if not items:
        return (Validation("invalid", error="no posts"), resolved.label, resolved.kind,
                resolved.params)
    return (_measure(items, embedder, topic, now or utcnow()), resolved.label, resolved.kind,
            resolved.params)


def _preset_record(proposal: Proposal, params: dict[str, Any] | None = None) -> dict[str, Any]:
    """The preset and fields a proposal is reviewed with (the Review page prefills them).
    A feed URL that failed and was replaced by the site's own feed is reviewed as
    the feed found."""
    if proposal.kind == PRESET:
        record: dict[str, Any] = {"preset": proposal.preset, "fields": dict(proposal.fields)}
    else:
        found = catalog.preset_for_proposal(proposal.kind, proposal.value)
        record = {"preset": found[0], "fields": found[1]} if found else {}
    url = (params or {}).get("url")
    if record.get("preset") == "web.feed" and url and record["fields"].get("url") != url:
        record["fields"] = {"url": url}
    return record


def scout_topic(
    store: Store,
    llm: LLMClient,
    embedder: Embedder,
    http: sources.HTTP,
    topic: library.Topic,
    *,
    auto_approve_min_similarity: float | None = None,
    now: datetime | None = None,
    connections: Any = None,
    xcfg: Any = None,
    searcher: websearch.Searcher | None = None,
) -> list[ScoutResult]:
    """Propose, validate and record sources for a topic.

    ``searcher``: live search to ground the proposals in (``websearch.for_runtime(rt,
    "scout")``); None: proposals from memory, said so on every record.

    With ``auto_approve_min_similarity`` set, valid core proposals whose median
    item similarity reaches it are approved straight away; wildcards and
    everything else wait for a person. Wildcards are not linked to the topic.

    With ``connections`` and ``xcfg`` (``config.XConfig``), and X connected and under its
    cap, the scout may also propose X searches, accounts and the person's own lists; at most
    ``x.scout_max_proposals`` of them are checked (one fetch of 10 posts each), the rest are
    recorded as not fetched, and none is approved without a person.
    """
    from .retention import set_source_retention
    from .sources.x import run_cost

    x = x_scouting(store, connections, xcfg, http)
    found = ground(searcher, topic)
    summary = search_summary(found)
    weeks = cast(Any, searcher.cfg).recent_weeks if searcher is not None else 12
    proposals, call_id = propose(llm, topic, reddit_sources(store, topic.id), x, found, weeks)
    results = []
    checked_x = 0
    for proposal in proposals:
        is_x = proposal.preset in X_SCOUT_PRESETS
        if is_x and (x is None or checked_x >= x.max_proposals):
            v = Validation("invalid", error="not fetched: X proposal cap")
            results.append(ScoutResult(None, proposal.value, proposal, v, "invalid", summary))
            continue
        checked_x += int(is_x)
        validation, label, kind, params = validate(proposal, http, embedder, topic, now=now,
                                                   x=x)
        how, cited = grounding(proposal, found)
        record = {**asdict(validation), "why": proposal.why, "topic_id": topic.id,
                  "role": proposal.role, **_preset_record(proposal, params),
                  "grounding": how, "cites": cited, "search": summary}
        if is_x and params is not None:
            # what checking it read, and what each run of it will (X's list price)
            record["cost_usd"] = {"check": round(X_CHECK_POSTS * 0.005, 4),
                                  "run": round(run_cost(params, xcfg), 4)}
        if proposal.replaces:
            record["replaces"] = proposal.replaces
        if params is None:
            if how == "results" and (validation.error or "").startswith("no feed found"):
                # a real site the results show, with no feed Kranto can read: proposed as a
                # source watched through live search, never approved here
                watched = _watch_by_search(store, proposal, cited, record, topic, call_id, now,
                                           searcher)
                validation = replace(validation, status="unverified", error=(
                    f"{validation.error}; found by live search ({cited[0]['label']}): proposed "
                    "to watch through live search instead"))
                results.append(ScoutResult(watched, label, proposal, validation, NO_FEED,
                                           summary))
                continue
            results.append(ScoutResult(None, label, proposal, validation, "invalid", summary))
            continue
        status = {"valid": "proposed", "unverified": "proposed", "invalid": "invalid"}[
            validation.status
        ]
        if (
            status == "proposed"
            and not is_x                           # paid per read: a person approves it
            and proposal.role == "core"
            and auto_approve_min_similarity is not None
            and validation.median_similarity is not None
            and validation.median_similarity >= auto_approve_min_similarity
        ):
            status = "approved"
        existing = store.query_one(
            "SELECT id FROM sources WHERE kind = ? AND params = ?",
            (kind, sources.canonical_params(kind, params)),
        )
        if existing:
            source_id = int(existing["id"])
            current = store.current_status("source", source_id)
            if status == "approved" and current != "approved":
                store.set_status("source", source_id, "approved", "scout auto-approve", now=now)
            status = store.current_status("source", source_id) or status
        else:
            source_id = library.add_source(
                store, kind, params, label=label, origin="scout", status=status,
                origin_call_id=call_id, validation=stored_sources.Validation.from_dict(record),
                now=now,
            )
            days = catalog.PRESETS[record["preset"]].retention_days \
                if record.get("preset") in catalog.PRESETS else None
            if days is not None:
                set_source_retention(store, source_id, days, "newsletter: kept 30 days")
        if status != "invalid" and proposal.role == "core":
            library.link_topic_source(store, topic.id, source_id)
        results.append(ScoutResult(source_id, label, proposal, validation, status, summary))
    return results
