"""News's articles: one brief item a day per topic earns a deep dive.

``pick`` is code (no model): an item that rests on an observation, scored by its signal, the
lines it cites and whether it continues a story of the week's briefs. ``research`` gathers the
material, every line labelled and dated: the item's observations in full, the pages behind them
(``ctx.fetch``: only the URLs those observations name), the library's earlier lines on the
story, the previous briefs' items, two live searches. ``write`` makes one reason-tier call with
``prompts/news_article.md`` and runs ``check_article`` before anything is stored: a paragraph,
figure, date, entity or relation the material does not carry is dropped and counted. The
picture is always one the page draws from the article's own data (``diagram``); a source's own
lead image is kept as an address with its site, shown linked and credited when
``news.lead_image`` is on, never copied into anything Kranto publishes.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime, timedelta

from kranto.core.text import (
    NO_SEARCH,
    combine,
    domain,
    fenced,
    iso,
    outlet,
    parse_time,
    scrub,
)

from . import brief as briefs
from . import check as checks
from .stored import (
    ArticleBody,
    ArticleChecks,
    ArticleMaterial,
    ArticleSources,
    BriefItems,
    PageImage,
)

KINDS = ("paper", "release", "funding", "incident", "trend", "other")
SECTIONS = (("what", "What happened"), ("why", "Why it matters here"),
            ("before", "What came before"), ("who", "Who is involved"),
            ("next", "What to watch next"))
ENTITY_KINDS = ("company", "lab", "product", "model", "project", "benchmark", "paper", "other")
SOURCES = ("pages", "search", "library", "briefs")
# depth: pages read at most, characters of each, search results per query
DEPTH = {"light": (0, 0, 0), "standard": (4, 6000, 8), "deep": (6, 12000, 12)}
DEPTH_CHOICES = tuple(DEPTH)
EARLIER_MAX = 12
EARLIER_DAYS = 60
BRIEF_DAYS = 14
THREAD_DAYS = 7
PAGE_REUSE_DAYS = 7
MIN_PAGE_CHARS = 200
MIN_WORDS = 120
MAX_ATTEMPTS_A_DAY = 2
CAP_SHARE = 0.8              # articles pause at 80% of News a month: the briefs keep the rest
WORDS_A_MINUTE = 200
# pages that answer without their text (a script draws them): the observation's own text is the
# page for these
UNREADABLE = ("x.com", "twitter.com", "mobile.twitter.com", "bsky.app", "threads.net",
              "instagram.com", "facebook.com", "linkedin.com")
_STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "and", "or", "with", "its", "is", "at",
         "by", "as", "from", "new", "says", "after", "into", "over", "than", "that", "this",
         "tested", "finds", "study", "paper", "report", "post", "models", "model"}
_NOUN_STOP = {"The", "A", "An", "Paper", "Study", "Report", "Post", "New", "This", "How", "Why",
              "What", "When", "LLM", "LLMs", "AI"}
_CITE = re.compile(r"^\s*\[?\s*([a-z]{2,6})\s+([A-Za-z0-9._-]{1,60})\s*\]?\s*$")
_URL = re.compile(r"https?://[^\s)\]>\"']+|\bwww\.[^\s)\]>\"']+")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
# a citation label written into the prose ("… the present. [obs 10570] [page 1]"): the cites
# field carries them, the page numbers them; the reader never sees Kranto's labels
_LABEL = re.compile(r"\s*\[\s*(?:obs|page|brief|exa|hn|web|tav|brave)\s+[^\[\]]{1,80}\]",
                    re.I)


_BRAND = re.compile(r"(?:^|[/_.-])(?:logo|logos|favicon|icon|icons|apple-touch|brand|"
                    r"default|placeholder|site-image|og-default)(?:[/_.-]|$)", re.I)


def brand_image(url) -> bool:
    """Whether a page's sharing image is the site's own logo, icon or default card (arXiv's
    `arxiv-logo-fb.png`), which shows the outlet, not the story: not shown as its picture."""
    from urllib.parse import urlsplit
    try:
        path = urlsplit(str(url or "")).path
    except ValueError:
        return True
    return bool(_BRAND.search(path))


def unlabelled(text) -> str:
    """``text`` without the citation labels a model wrote into it, its spacing tidied."""
    out = _LABEL.sub("", str(text or ""))
    return re.sub(r"\s+([.,;:])", r"\1", " ".join(out.split()))
_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_LOCKS: dict[tuple[int, int], threading.Lock] = {}
_GUARD = threading.Lock()


def lock_for(brief_id: int, n: int) -> threading.Lock:
    with _GUARD:
        return _LOCKS.setdefault((int(brief_id), int(n)), threading.Lock())


def running(brief_id: int, n: int) -> bool:
    return lock_for(brief_id, n).locked()


def minutes(words: int | None) -> int:
    return max(1, round((words or 0) / WORDS_A_MINUTE))


# -- which items earn an article -----------------------------------------------------------


def _at(ctx, b: dict) -> datetime:
    """When a brief was written (now, for a row whose time cannot be read)."""
    return parse_time(b["created_at"]) or ctx.now()


def nouns(text: str) -> set[str]:
    return {w for w in re.findall(r"[A-Z][A-Za-z0-9.+-]{2,}", text or "") if w not in _NOUN_STOP}


def scores(ctx, b: dict) -> list[dict]:
    """Every item of brief ``b`` (a ``news_briefs`` row) with its score and whether it may
    earn an article, highest first (ties: the earlier item)."""
    items = BriefItems.load(b["items"]).items
    since = iso(_at(ctx, b) - timedelta(days=THREAD_DAYS))
    earlier = ctx.db.query("SELECT items FROM news_briefs WHERE topic_id = ? AND id < ? AND "
                           "status = 'ok' AND created_at >= ?", (b["topic_id"], b["id"], since))
    seen_nouns: set[str] = set()
    seen_obs: set[int] = set()
    for r in earlier:
        for it in BriefItems.load(r["items"]).items:
            seen_nouns |= nouns(it.get("headline", ""))
            seen_obs |= set(it.get("observation_ids") or [])
    out = []
    for n, it in enumerate(items):
        obs = set(it.get("observation_ids") or [])
        thread = bool(nouns(it.get("headline", "")) & seen_nouns or obs & seen_obs)
        score = float(it.get("signal") or 0.0) + 0.05 * max(0, len(it.get("cites") or []) - 1) \
            + (0.10 if thread else 0.0)
        out.append({"n": n, "headline": it.get("headline", ""), "score": round(score, 4),
                    "eligible": bool(obs), "thread": thread})
    return sorted(out, key=lambda s: (-s["score"], s["n"]))


def pick(ctx, b: dict) -> list[int]:
    """The items of brief ``b`` that earn an article: eligible, at least ``news.article_min``,
    the top ``news.articles_per_day``."""
    s = ctx.settings
    want = int(s["news.articles_per_day"])
    floor = float(s["news.article_min"])
    return [x["n"] for x in scores(ctx, b) if x["eligible"] and x["score"] >= floor][:want]


# -- the material --------------------------------------------------------------------------


class Material:
    """The labelled lines a reply may cite (``lines``: label -> {kind, id, date, title, url,
    source, text, …}), the prompt's six blocks, and what was read (``log``)."""

    def __init__(self) -> None:
        self.lines: dict[str, dict] = {}
        self.blocks: dict[str, str] = {}
        self.log: dict = {"pages": [], "search": None, "earlier": 0, "briefs": 0}
        self.images: list[dict] = []

    def add(self, label: str, **line) -> None:
        self.lines[label] = line

    def count(self, kind: str) -> int:
        return sum(1 for v in self.lines.values() if v["kind"] == kind)

    def empty(self) -> bool:
        return not self.lines


def _sources_on(ctx) -> set[str]:
    return set(ctx.settings["news.sources"] or ()) & set(SOURCES)


def _obs_text(o: dict) -> str:
    return f"{o['title']} {o['summary']} {o.get('why') or ''}"


def _obs_line(o: dict) -> str:
    return (f"[obs {o['id']}] {o['date'] or 'undated'} | {o['title']} | {o['source']} | "
            f"{o['url'] or ''}\n{o['summary']}")


def evidence(ctx, item: dict, m: Material) -> list[dict]:
    """Block 1: the item's own observations in full (the library's record of each)."""
    rows = []
    for oid in item.get("observation_ids") or []:
        try:
            rows.append(ctx.read("objects.get", kind="observation", id=int(oid))["object"])
        except Exception as exc:  # noqa: BLE001 - a purged observation is left out, and counted
            m.log.setdefault("missing", []).append({"id": oid, "why": str(exc)[:80]})
    rows.sort(key=lambda o: (o["date"] or "", o["id"]))
    lines = []
    for o in rows:
        m.add(f"obs {o['id']}", kind="obs", id=o["id"], date=o["date"] or None,
              title=o["title"], url=o["url"], source=o["source"], text=_obs_text(o))
        lines.append(_obs_line(o) + (f"\nWhy kept: {o['why']}" if o.get("why") else ""))
    m.blocks["evidence"] = "\n".join(lines) or "(none)"
    return rows


def _readable(url: str | None) -> str | None:
    """Why a URL's page is not read, or None when it may be."""
    if not url:
        return "no address"
    host = (domain(url) or "").lower()
    if any(host == h or host.endswith("." + h) for h in UNREADABLE):
        return "a page a script draws: the observation's own text stands for it"
    return None


def pages(ctx, rows: list[dict], m: Material, today: str) -> None:
    """Block 2: the pages behind the item's observations, through ``ctx.fetch`` (the URLs the
    observations name, nothing else); a page read in the last 7 days is reused."""
    n_max, chars, _ = DEPTH[ctx.settings["news.depth"]]
    if "pages" not in _sources_on(ctx) or n_max == 0:
        m.blocks["pages"] = "(none: the pages behind the item are not read at this depth)"
        return
    lines: list[str] = []
    seen: set[str] = set()
    for o in rows:
        url = o.get("url")
        if not url or url in seen or len(lines) >= n_max:
            continue
        seen.add(url)
        why = _readable(url)
        if why:
            m.log["pages"].append({"url": url, "obs": o["id"], "skipped": why})
            continue
        since = iso(ctx.now() - timedelta(days=PAGE_REUSE_DAYS))
        kept = ctx.db.query_one("SELECT text, fetched_at, chars, image FROM news_article_pages "
                                "WHERE url = ? AND fetched_at >= ? ORDER BY id DESC LIMIT 1",
                                (url, since))
        if kept is not None and kept["chars"] >= MIN_PAGE_CHARS:
            text, fetched, reused = kept["text"][:chars], kept["fetched_at"], True
            image = _image(kept["image"])
        else:
            got = ctx.fetch(url, max_chars=chars)
            if got.get("error"):
                m.log["pages"].append({"url": url, "obs": o["id"], "error": got["error"]})
                continue
            text, fetched, image, reused = got["text"], got["fetched_at"], got.get("image"), False
            if len(text) < MIN_PAGE_CHARS:
                m.log["pages"].append({"url": url, "obs": o["id"], "chars": len(text),
                                       "error": "too little readable text"})
                continue
        label = f"page {len(lines) + 1}"
        m.add(label, kind="page", id=None, date=today, title=o["title"], url=url,
              source="the page behind it", text=text, obs=o["id"], fetched_at=fetched,
              reused=reused, image=image)
        if image and not brand_image(image.get("url")):
            m.images.append({**image, "page": url, "obs": o["id"]})
        lines.append(f"[{label}] fetched {fetched[:10]} | {url} | behind obs {o['id']}\n{text}")
        m.log["pages"].append({"url": url, "obs": o["id"], "label": label, "chars": len(text),
                               "reused": reused})
    m.blocks["pages"] = "\n".join(lines) or "(none: no page behind the item could be read)"


def _image(raw) -> dict | None:
    """A stored page's lead image (``{url, site, alt}``, JSON) or None; one that does not read
    as that shape is no image."""
    got = PageImage.parse(raw if isinstance(raw, (str, bytes, dict)) else None)
    if got is None or not (got.url or "").startswith("https://"):
        return None
    return {"url": got.url, "site": got.site or "", "alt": got.alt or ""}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}", text or "")
            if w.lower() not in _STOP]


def earlier(ctx, topic: dict, item: dict, exclude: set[int], m: Material) -> None:
    """Block 3: the library's earlier lines on the story: the semantic index on the headline
    when this context has it, and the topic's last 60 days by the headline's words, ranked by
    the words they share and then signal."""
    if "library" not in _sources_on(ctx):
        m.blocks["earlier"] = "(none: the library's earlier lines are not read)"
        return
    words = {w.lower() for w in _words(item.get("headline", ""))}
    found: dict[int, dict] = {}
    if ctx.index is not None and ctx.embedder is not None:
        try:
            for o in ctx.read("library.search", q=item["headline"], topic_id=topic["id"],
                              limit=EARLIER_MAX)["observations"]:
                found[o["id"]] = o
        except Exception as exc:  # noqa: BLE001 - the word match stands alone
            ctx.log.info("news: library.search for an article failed: %s", exc)
    since = iso(ctx.now() - timedelta(days=EARLIER_DAYS))
    for o in ctx.read("library.observations", topic_id=topic["id"], since=since, limit=100,
                      sort="signal")["observations"]:
        found.setdefault(o["id"], o)

    def shared(o: dict) -> int:
        text = f"{o['title']} {o['summary']}".lower()
        return sum(1 for w in words if w in text)

    rows = [o for o in found.values() if o["id"] not in exclude and "unreadable" not in o
            and shared(o) > 0]
    rows.sort(key=lambda o: (-shared(o), -float(o.get("signal") or 0)))
    rows = sorted(rows[:EARLIER_MAX], key=lambda o: (o["date"] or "", o["id"]))
    for o in rows:
        m.add(f"obs {o['id']}", kind="obs", id=o["id"], date=o["date"] or None,
              title=o["title"], url=o["url"], source=o["source"], text=_obs_text(o),
              earlier=True)
    m.log["earlier"] = len(rows)
    m.blocks["earlier"] = "\n".join(_obs_line(o) for o in rows) or "(none)"


def previous_briefs(ctx, b: dict, m: Material) -> None:
    """Block 4: the previous briefs' items on this topic, the last 14 days."""
    if "briefs" not in _sources_on(ctx):
        m.blocks["briefs"] = "(none: the previous briefs are not read)"
        return
    since = iso(_at(ctx, b) - timedelta(days=BRIEF_DAYS))
    lines = []
    for r in ctx.db.query("SELECT id, created_at, items FROM news_briefs WHERE topic_id = ? AND "
                          "id < ? AND status = 'ok' AND created_at >= ? ORDER BY id",
                          (b["topic_id"], b["id"], since)):
        for n, it in enumerate(BriefItems.load(r["items"]).items):
            label = f"brief {r['id']}.{n}"
            obs = it.get("observation_ids") or []
            m.add(label, kind="brief", id=r["id"], n=n, date=r["created_at"][:10],
                  title=it.get("headline", ""), url=None, source="the brief",
                  text=f"{it.get('headline', '')} {it.get('body', '')} {it.get('why', '')}",
                  observation_ids=obs)
            lines.append(f"[{label}] {r['created_at'][:10]} | {it.get('headline', '')} | "
                         f"obs {', '.join(str(i) for i in obs) or 'search only'}\n"
                         f"{it.get('body', '')}")
    m.log["briefs"] = len(lines)
    m.blocks["briefs"] = "\n".join(lines) or "(none)"


def search(ctx, topic: dict, item: dict, m: Material) -> None:
    """Block 5: the topic's name with the headline's proper nouns on the web (4 weeks), and
    the nouns alone on the discussion backend; the day's cache makes a retry free."""
    n = DEPTH[ctx.settings["news.depth"]][2]
    if ctx.search is None or "search" not in _sources_on(ctx) or n == 0:
        m.blocks["search"] = f"Live search results: none. {NO_SEARCH}"
        m.log["search"] = {"live": False, "note": "not searched"}
        return
    found = [w for w in nouns(item.get("headline", "")) if w.lower() not in
             {x.lower() for x in re.findall(r"[A-Za-z]+", topic["name"])}][:4]
    results = None
    try:
        results = ctx.search.search(f"{topic['name']} {' '.join(found)}".strip(), kind="web",
                                    recency="4w", n=n)
        if found and "discussion" in ctx.search.kinds:
            results = combine(results, ctx.search.search(" ".join(found[:2]), kind="discussion",
                                                         recency="4w", n=n))
    except Exception as exc:  # noqa: BLE001 - an article without search says so
        ctx.log.warning("news: the article's search failed: %s", exc)
    if results is None:
        m.blocks["search"] = f"Live search results: none. {NO_SEARCH}"
        m.log["search"] = {"live": False, "note": "the search failed"}
        return
    for label, h in results.numbered():
        m.add(label, kind="web", id=None, date=h.date, title=fenced(h.title), url=h.url,
              source=outlet(h.url, results.labels[0] if results.labels else h.backend),
              text=fenced(f"{h.title} {h.snippet}"))
    m.blocks["search"] = results.block()
    m.log["search"] = {"live": results.live, "labels": list(results.labels),
                       "searched_at": results.searched_at, "query": results.query[:300],
                       "hits": len(results.hits), "note": results.note}


def research(ctx, topic: dict, b: dict, n: int) -> tuple[Material, dict]:
    """Everything the article may rest on, labelled; and the item."""
    item = BriefItems.load(b["items"]).items[n]
    m = Material()
    today = briefs.local(ctx.now()).date().isoformat()
    ctx.progress("Reading the item's observations")
    rows = evidence(ctx, item, m)
    pages(ctx, rows, m, today)
    ctx.progress("Reading what came before")
    earlier(ctx, topic, item, {o["id"] for o in rows}, m)
    previous_briefs(ctx, b, m)
    search(ctx, topic, item, m)
    return m, item


# -- the checks ----------------------------------------------------------------------------


class Checks:
    def __init__(self) -> None:
        self.bad_citations = 0
        self.dropped_paragraphs = 0
        self.dropped_numbers = 0
        self.dropped_timeline = 0
        self.dropped_entities = 0
        self.dropped_relations = 0
        self.series_dropped = 0
        self.names_replaced = 0
        self.urls_removed = 0
        self.labels_removed = 0

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def _cites(raw, lines: dict, rep: Checks) -> list[str]:
    out: list[str] = []
    for c in raw if isinstance(raw, list) else []:
        mt = _CITE.match(str(c))
        label = f"{mt.group(1).lower()} {mt.group(2)}" if mt else None
        if label is not None and label in lines:
            if label not in out:
                out.append(label)
        else:
            rep.bad_citations += 1
    return out


def _cited_text(cites: list[str], lines: dict) -> str:
    return " ".join(f"{lines[c].get('title') or ''} {lines[c]['text']}" for c in cites)


def _clean(text, cited: str, rep: Checks) -> str:
    """Strangers' text as the article may show it: one line, scrubbed, a person the cited
    lines do not name in a role, no URL and no address, no citation label in the prose."""
    raw = " ".join(str(text or "").split())
    labels = len(_LABEL.findall(raw))
    if labels:
        rep.labels_removed += labels
        raw = unlabelled(raw)
    text = scrub(raw)
    names = checks.Report()
    text = checks._names(text, cited, names)
    rep.names_replaced += names.names_replaced
    found = _URL.findall(text) + _EMAIL.findall(text)
    if found:
        rep.urls_removed += len(found)
        text = _EMAIL.sub("", _URL.sub("", text))
    return " ".join(text.split())


def _digits_in(value, text: str) -> bool:
    nums = re.findall(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    plain = text.replace(",", "")
    return bool(nums) and all(re.search(rf"(?<![\d.]){re.escape(x)}(?![\d])", plain)
                              for x in nums)


def _date_ok(d: str, cites: list[str], lines: dict) -> bool:
    if not _DAY.match(d):
        return False
    text = _cited_text(cites, lines)
    return any(lines[c].get("date") == d for c in cites) or d in text or d[:7] in text


def _headline(text: str) -> str:
    text = " ".join(str(text or "").split())
    if len(text) >= checks.HEADLINE_MAX:
        text = text[:checks.HEADLINE_MAX - 4].rsplit(" ", 1)[0] + "..."
    return text


def check_article(reply: dict, lines: dict, *, today: date) -> tuple[dict, Checks]:
    """The checked article and what the checks did. Every list keeps only what cites a label
    of the material; a figure's digits must be in a cited line, a date a cited line's own or
    written in it, an entity's name in its cited lines, a relation between kept entities, a
    series' points in the cited line's own numbers."""
    rep = Checks()
    if not isinstance(reply, dict):
        reply = {}
    sf = reply.get("standfirst")
    sf_text, sf_raw = (sf.get("text"), sf.get("cites")) if isinstance(sf, dict) else \
        (sf, reply.get("standfirst_cites") or reply.get("cites"))
    sf_cites = _cites(sf_raw, lines, rep)
    kind = reply.get("kind") if reply.get("kind") in KINDS else "other"
    art: dict = {"kind": kind, "standfirst_cites": sf_cites,
                 "standfirst": _clean(sf_text, _cited_text(sf_cites, lines), rep)
                 if sf_cites else ""}
    art["headline"] = _headline(_clean(reply.get("headline"), _cited_text(sf_cites, lines),
                                       rep))
    by_id = {}
    for s in reply.get("sections") or []:
        if not isinstance(s, dict) or s.get("id") not in dict(SECTIONS) or s["id"] in by_id:
            continue
        paras = []
        for p in s.get("paragraphs") or []:
            if not isinstance(p, dict):
                continue
            cites = _cites(p.get("cites"), lines, rep)
            text = _clean(p.get("text"), _cited_text(cites, lines), rep) if cites else ""
            if not cites or not text:
                rep.dropped_paragraphs += 1
                continue
            paras.append({"text": text, "cites": cites})
        if paras:
            by_id[s["id"]] = {"id": s["id"], "title": dict(SECTIONS)[s["id"]],
                              "paragraphs": paras}
    art["sections"] = [by_id[k] for k, _ in SECTIONS if k in by_id]
    nums: list[dict] = []
    for x in reply.get("numbers") or []:
        if not isinstance(x, dict):
            continue
        cites = _cites(x.get("cites"), lines, rep)
        value = " ".join(str(x.get("value") if x.get("value") is not None else "").split())
        if not cites or not _digits_in(value, _cited_text(cites, lines)) or len(nums) >= 8:
            rep.dropped_numbers += 1
            continue
        nums.append({"label": _clean(x.get("label"), "", rep)[:60], "value": value[:24],
                     "unit": " ".join(str(x.get("unit") or "").split())[:12], "cites": cites})
    art["numbers"] = nums
    tl: list[dict] = []
    for t in reply.get("timeline") or []:
        if not isinstance(t, dict):
            continue
        cites = _cites(t.get("cites"), lines, rep)
        d = str(t.get("date") or "")[:10]
        event = _clean(t.get("event"), _cited_text(cites, lines), rep)[:100]
        if not cites or not event or not _date_ok(d, cites, lines):
            rep.dropped_timeline += 1
            continue
        tl.append({"date": d, "event": event, "cites": cites})
    art["timeline"] = sorted(tl, key=lambda x: str(x["date"]))[:10]
    art["series"] = _series(reply.get("series"), lines, rep)
    ents: list[dict] = []
    for e in reply.get("entities") or []:
        if not isinstance(e, dict):
            continue
        cites = _cites(e.get("cites"), lines, rep)
        name = " ".join(str(e.get("name") or "").split())[:60]
        if not cites or not name or name.lower() not in _cited_text(cites, lines).lower() \
                or any(x["name"] == name for x in ents) or len(ents) >= 10:
            rep.dropped_entities += 1
            continue
        ents.append({"name": name, "kind": e.get("kind") if e.get("kind") in ENTITY_KINDS
                     else "other", "cites": cites})
    names = {x["name"] for x in ents}
    rels: list[dict] = []
    for r in reply.get("relations") or []:
        if not isinstance(r, dict):
            continue
        cites = _cites(r.get("cites"), lines, rep)
        if not cites or r.get("from") not in names or r.get("to") not in names or \
                r.get("from") == r.get("to") or len(rels) >= 12:
            rep.dropped_relations += 1
            continue
        rels.append({"from": r["from"], "to": r["to"],
                     "kind": _clean(r.get("kind"), "", rep)[:30], "cites": cites})
    art["entities"], art["relations"] = ents, rels
    art["themes"] = [t for t in (_clean(x, "", rep)[:40] for x in reply.get("themes") or []
                                 if isinstance(x, str)) if t][:5]
    seed = reply.get("idea_seed")
    seed = _clean(seed, "", rep) if isinstance(seed, str) else ""
    art["idea_seed"] = " ".join(seed.split()[:30]) or None
    art["quiet"] = _clean(reply.get("quiet"), "", rep)[:300] if reply.get("quiet") else None
    art["words"] = sum(len(p["text"].split()) for s in art["sections"]
                       for p in s["paragraphs"])
    art["sources"] = sources_of(art, lines)
    art["diagram"] = diagram(art)
    art["evidence_timeline"] = evidence_timeline(art, lines, today)
    return art, rep


def _series(raw, lines: dict, rep: Checks) -> dict | None:
    if not isinstance(raw, dict) or not raw.get("points"):
        return None
    cites = _cites(raw.get("cites"), lines, rep)
    known: set[tuple[str, float]] = set()
    for c in cites:
        for pts in (lines[c].get("series") or {}).values():
            known |= {(str(x), float(y)) for x, y in pts}
    pts = []
    for p in raw["points"] if isinstance(raw["points"], list) else []:
        try:
            pt = (str(p["x"]), float(p["y"]))
        except (KeyError, TypeError, ValueError):
            continue
        if pt in known:
            pts.append({"x": pt[0], "y": pt[1]})
    if len(pts) < 3:
        rep.series_dropped += 1
        return None
    return {"name": _clean(raw.get("name"), "", rep)[:60],
            "unit": " ".join(str(raw.get("unit") or "").split())[:12], "cites": cites,
            "points": sorted(pts, key=lambda p: p["x"])}


def sources_of(art: dict, lines: dict) -> list[dict]:
    """The cited lines in reading order (the standfirst first), each once: what Sources
    lists, title, outlet, date, link."""
    order: list[str] = list(art.get("standfirst_cites") or [])
    for s in art["sections"]:
        for p in s["paragraphs"]:
            order += p["cites"]
    for key in ("numbers", "timeline", "entities", "relations"):
        for x in art.get(key) or []:
            order += x["cites"]
    if art.get("series"):
        order += art["series"]["cites"]
    seen: list[str] = []
    for c in order:
        if c not in seen:
            seen.append(c)
    keep = ("kind", "id", "n", "date", "title", "url", "source", "obs", "fetched_at")
    return [{"label": c, **{k: lines[c].get(k) for k in keep if lines[c].get(k) is not None}}
            for c in seen]


def diagram(art: dict) -> str:
    """The lead figure: the series when one survived, else the timeline with 3 points,
    the numbers with 3, the relationship map with 3 relations, else the evidence timeline (the
    cited lines' own dates), which never fails."""
    if art.get("series"):
        return "series"
    if len(art.get("timeline") or []) >= 3:
        return "timeline"
    if len(art.get("numbers") or []) >= 3:
        return "numbers"
    if len(art.get("relations") or []) >= 3 and len(art.get("entities") or []) >= 3:
        return "relations"
    return "evidence"


def evidence_timeline(art: dict, lines: dict, today: date) -> list[dict]:
    """The fallback figure: each dated cited line once by day (the earliest label of a day),
    and today, so it always has two points."""
    days: dict[str, dict] = {}
    for s in art.get("sources") or []:
        d = (lines.get(s["label"]) or {}).get("date")
        if d and _DAY.match(str(d)) and d not in days and s.get("kind") != "page":
            days[d] = {"date": d, "event": str(s.get("title") or "")[:100],
                       "cites": [s["label"]]}
    out = sorted(days.values(), key=lambda x: x["date"])[-9:]
    if not out or out[-1]["date"] != today.isoformat():
        out.append({"date": today.isoformat(), "event": "this article", "cites": []})
    if len(out) < 2:
        out.insert(0, {"date": today.isoformat(), "event": "the brief", "cites": []})
    return out


def _json(text: str):
    """The model's JSON, from a reply that may wrap it in a fence or prose."""
    text = (text or "").strip()
    try:
        return json.loads(text)
    except ValueError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("the reply has no JSON object") from None
        return json.loads(text[start:end + 1])


# -- writing one -------------------------------------------------------------------


def prompt_text(ctx, topic: dict, b: dict, item: dict, m: Material) -> tuple[str, str]:
    prompt = ctx.prompt("news_article")
    today = briefs.local(ctx.now()).date().isoformat()
    text = prompt.render_keeping(
        "search_block", topic_name=fenced(topic["name"]),
        topic_description=fenced(topic.get("description") or ""),
        item_headline=fenced(item.get("headline", "")), item_body=fenced(item.get("body", "")),
        item_why=fenced(item.get("why", "")), today=today,
        period_start=(b["period_start"] or "")[:10], evidence=fenced(m.blocks["evidence"]),
        pages=fenced(m.blocks["pages"]), earlier=fenced(m.blocks["earlier"]),
        briefs=fenced(m.blocks["briefs"]), search_block=m.blocks["search"])
    return text, prompt.version


def _material_meta(m: Material) -> dict:
    keep = ("kind", "id", "n", "date", "title", "url", "source", "obs", "fetched_at", "reused")
    return {"lines": {k: {kk: v.get(kk) for kk in keep if v.get(kk) is not None}
                      for k, v in m.lines.items()},
            "log": m.log, "counts": {k: m.count(k) for k in ("obs", "page", "brief", "web")},
            "earlier": sum(1 for v in m.lines.values() if v.get("earlier"))}


def capped(ctx) -> str | None:
    """Why no article is written now for the cap's sake (an article is the luxury: articles
    pause at 80% of News a month, so the briefs keep the rest), or None."""
    cap = ctx.settings["news.monthly_usd"]
    if cap is None:
        return None
    spent = float(ctx.read("spend.mine")["month_usd"])
    if spent >= CAP_SHARE * float(cap):
        return (f"News has spent ${spent:.2f} of its ${float(cap):.2f} this month; articles "
                "pause at 80% so the briefs keep the rest")
    return None


def write(ctx, topic: dict, b: dict, n: int, *, trigger: str, dry_run: bool = False) -> dict | None:
    """Write the article for item ``n`` of brief ``b``. None when one is being written for it
    already. ``dry_run``: the material and the prompt, no call, no row."""
    lock = lock_for(b["id"], n)
    if not lock.acquire(blocking=False):
        return None
    try:
        return _write(ctx, topic, b, n, trigger, dry_run)
    finally:
        lock.release()


def _write(ctx, topic: dict, b: dict, n: int, trigger: str, dry_run: bool) -> dict:
    items = BriefItems.load(b["items"]).items
    if not 0 <= n < len(items):
        raise ValueError(f"brief {b['id']} has no item {n}")
    now = ctx.now()
    base = {"topic_id": topic["id"], "brief_id": b["id"], "item_n": n,
            "run_uuid": ctx.run_uuid, "trigger": trigger, "created_at": iso(now)}
    ctx.progress(f"Writing the article: {items[n].get('headline', '')[:60]}")
    m, item = research(ctx, topic, b, n)
    if m.count("obs") == 0 or not any(v["kind"] == "obs" and not v.get("earlier")
                                      for v in m.lines.values()):
        out = {**base, "status": "quiet", "quiet": "nothing behind the item can be read now "
               "(its observations are gone)", "material": ArticleMaterial.write(_material_meta(m)),
               "checks": ArticleChecks.write({"no_material": True})}
        return out if dry_run else _store(ctx, out, m)
    text, version = prompt_text(ctx, topic, b, item, m)
    if dry_run:
        return {**base, "status": "dry_run", "prompt": text, "prompt_version": version,
                "material": _material_meta(m)}
    why = capped(ctx)
    if why:
        return _store(ctx, {**base, "status": "failed", "error": why,
                            "prompt_version": version,
                            "material": ArticleMaterial.write(_material_meta(m))}, m)
    try:
        reply = ctx.llm.complete(purpose="news_article", tier=ctx.settings["news.model"],
                                 messages=[{"role": "user", "content": text}],
                                 prompt_version=version, run_uuid=ctx.run_uuid,
                                 max_tokens=6000, temperature=0.2,
                                 schema=ctx.prompt_schema("news_article"), retry_truncated=True)
        parsed = _json(reply.text)
        if not isinstance(parsed, dict):
            raise ValueError("the reply is not a JSON object")
    except Exception as exc:  # noqa: BLE001 - a failed article is a row with its reason
        return _store(ctx, {**base, "status": "failed",
                            "error": f"{type(exc).__name__}: {exc}"[:500],
                            "prompt_version": version,
                            "material": ArticleMaterial.write(_material_meta(m))}, m)
    today = briefs.local(now).date()
    art, rep = check_article(parsed, m.lines, today=today)
    quiet = art["quiet"]
    if not quiet and (art["words"] < MIN_WORDS or not any(s["id"] == "what"
                                                          for s in art["sections"])):
        quiet = (f"the material carried {art['words']} checked words"
                 + ("" if any(s["id"] == "what" for s in art["sections"])
                    else " and no account of what happened"))
    image = m.images[0] if m.images else None
    body = {k: art[k] for k in ("sections", "numbers", "timeline", "series", "entities",
                                "relations", "themes", "idea_seed", "standfirst_cites",
                                "evidence_timeline")}
    body["image"] = image
    body["item"] = {"headline": item.get("headline"), "body": item.get("body"),
                    "why": item.get("why")}
    report = {**rep.as_dict(), "words": art["words"],
              "material": {k: m.count(k) for k in ("obs", "page", "brief", "web")},
              "earlier": m.log["earlier"],
              "pages_read": sum(1 for p in m.log["pages"] if p.get("label")),
              "search_live": bool((m.log.get("search") or {}).get("live"))}
    return _store(ctx, {**base, "status": "quiet" if quiet else "ok", "kind": art["kind"],
                        "headline": art["headline"] or item.get("headline"),
                        "standfirst": art["standfirst"],
                        "body": ArticleBody.write(body),
                        "sources": ArticleSources.write(art["sources"]),
                        "material": ArticleMaterial.write(_material_meta(m)),
                        "words": art["words"], "diagram": art["diagram"],
                        "quiet": quiet and str(quiet)[:300], "llm_call_id": reply.call_id,
                        "model": reply.model, "prompt_version": version,
                        "cost_usd": round(float(reply.cost_usd or 0), 6),
                        "equiv_usd": round(float(reply.equiv_usd or 0), 6)
                        if reply.equiv_usd else None,
                        "checks": ArticleChecks.write(report)}, m)


def _store(ctx, row: dict, m: Material) -> dict:
    with ctx.db.tx():
        aid = ctx.db.insert("news_articles", row)
        for label, line in m.lines.items():
            if line["kind"] != "page" or line.get("reused"):
                continue
            ctx.db.insert("news_article_pages", {
                "article_id": aid, "label": label, "url": line["url"],
                "observation_id": line.get("obs"), "fetched_at": line["fetched_at"],
                "chars": len(line["text"]), "text": line["text"],
                "image": PageImage.write(line["image"]) if line.get("image") else None,
                "created_at": row["created_at"]})
    return {**row, "id": aid}


# -- the job's second half -----------------------------------------------------------------------


def attempts_today(ctx, brief_id: int, n: int, day: date) -> list:
    rows = ctx.db.query("SELECT id, status, created_at FROM news_articles WHERE brief_id = ? AND "
                        "item_n = ? ORDER BY id", (int(brief_id), int(n)))
    return [r for r in rows if (t := parse_time(r["created_at"])) is not None
            and briefs.local(t).date() == day]


def due_items(ctx, b: dict, day: date) -> list[int]:
    """The picks of brief ``b`` still without an article: none ok or quiet yet, and fewer
    than two failed tries today."""
    out = []
    for n in pick(ctx, b):
        rows = ctx.db.query("SELECT status FROM news_articles WHERE brief_id = ? AND "
                            "item_n = ?", (b["id"], n))
        if any(r["status"] in ("ok", "quiet") for r in rows):
            continue
        if len(attempts_today(ctx, b["id"], n, day)) >= MAX_ATTEMPTS_A_DAY:
            continue
        out.append(n)
    return out


def run_due(ctx, topics: list[dict] | None = None) -> dict:
    """After the briefs: the article for each of today's briefs still missing its picks."""
    if int(ctx.settings["news.articles_per_day"]) == 0:
        return {"articles": 0, "failed": 0}
    now = ctx.now()
    day = briefs.local(now).date()
    made, failed = 0, 0
    for t in topics if topics is not None else ctx.read("topics.list")["topics"]:
        if t.get("status") not in (None, "active") or \
                not briefs.topic_setting(ctx, t["id"])["enabled"]:
            continue
        for b in reversed(briefs.briefs_on_local_day(ctx, t["id"], day)):
            if b["status"] != "ok":
                continue
            row = ctx.db.query_one("SELECT * FROM news_briefs WHERE id = ?", (b["id"],))
            for n in due_items(ctx, dict(row), day):
                if ctx.stop_requested():
                    return {"articles": made, "failed": failed, "stopped_by": "owner"}
                out = write(ctx, t, dict(row), n, trigger="schedule")
                if out is None:
                    continue
                made += out["status"] != "failed"
                failed += out["status"] == "failed"
            break                       # the day's newest ok brief is the one that counts
    return {"articles": made, "failed": failed}


# -- reading them ---------------------------------------------------------------------------------


def _shown(body: dict) -> dict:
    """The body as the page shows it: a citation label a model wrote into a paragraph (stored
    before the checks removed them) is taken out on the way to the reader; the row stays as it
    was written."""
    secs = body.get("sections")
    if not isinstance(secs, list):
        return body
    out = []
    for s in secs:
        if not isinstance(s, dict) or not isinstance(s.get("paragraphs"), list):
            out.append(s)
            continue
        out.append({**s, "paragraphs": [{**p, "text": unlabelled(p.get("text"))}
                                        if isinstance(p, dict) else p
                                        for p in s["paragraphs"]]})
    return {**body, "sections": out}


def row_view(r, *, full: bool, lead_image: bool = True) -> dict:
    body = _shown(ArticleBody.load(r["body"]).extra)
    out = {"id": r["id"], "topic_id": r["topic_id"], "brief_id": r["brief_id"],
           "item_n": r["item_n"], "status": r["status"], "kind": r["kind"],
           "headline": unlabelled(r["headline"]) if r["headline"] is not None else None,
           "standfirst": unlabelled(r["standfirst"]) if r["standfirst"] is not None else None,
           "words": r["words"],
           "minutes": minutes(r["words"]), "diagram": r["diagram"], "quiet": r["quiet"],
           "error": r["error"], "trigger": r["trigger"], "created_at": r["created_at"],
           "timeline": [{"date": x["date"]} for x in
                        (body.get("timeline") if r["diagram"] == "timeline"
                         else body.get("evidence_timeline")) or []],
           "image": None}
    img = body.get("image")
    if lead_image and isinstance(img, dict) and not brand_image(img.get("url")):
        out["image"] = img
    if full:
        material = ArticleMaterial.load(r["material"]).extra
        out.update({"body": body, "sources": ArticleSources.load(r["sources"]).items,
                    "checks": ArticleChecks.load(r["checks"]).extra,
                    "material": {"counts": material.get("counts") or {},
                                 "earlier": material.get("earlier") or 0,
                                 "pages": (material.get("log") or {}).get("pages") or [],
                                 "search": (material.get("log") or {}).get("search")},
                    "model": r["model"], "prompt_version": r["prompt_version"],
                    "cost_usd": r["cost_usd"], "equiv_usd": r["equiv_usd"]})
        if out["image"] is None:
            out["body"] = {**body, "image": None}
    return out


def for_items(ctx, brief_id: int) -> dict[int, dict]:
    """``{item_n: the newest article's row (ok first, else the newest try)}`` for a brief."""
    rows = ctx.db.query("SELECT * FROM news_articles WHERE brief_id = ? ORDER BY id",
                        (int(brief_id),))
    out: dict[int, dict] = {}
    for r in rows:
        cur = out.get(r["item_n"])
        if cur is None or r["status"] == "ok" or cur["status"] != "ok":
            out[r["item_n"]] = r
    return out
