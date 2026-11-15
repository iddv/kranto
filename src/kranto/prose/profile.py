"""The prose profile: one per Kranto, a variant per site inside it.

Where it is stored, and who reads it:

- **the ``settings`` row ``prose.profile``** (:class:`ProfileRow`): the switches, the checker's
  strictness and the rules turned off, the guides per site, disclosure per site, whether Kranto
  asks "What do you think?", the writer's own model per writer (``writers``: P-11, apart from
  the watcher's models), and the record of the one-time tone migration. Written only by
  :func:`save_row` (``POST /api/prose/voice``, the verb ``prose.voice``, ``prose.learn``'s yes,
  and the migration). Readers: :func:`load` (every compose, check and revise: the writers
  through the cub host, ``/api/prose/*``, the eval).
- **files under ``<home>/prose/``**, which the person or their Claude Code may edit by hand:
  ``voice.md`` (the voice card), ``never.txt``, ``keep.txt``, ``always.txt`` (one entry a line;
  ``#`` starts a comment; ``/…/`` is a regular expression), ``samples/<id>.md`` (one sample a
  file, an optional first line ``site: <site>``), ``guides/<name>.md`` (the person's own guides;
  ``guides/sites/<site>.md`` replaces Kranto's template of that site) and ``vectors.json`` (the
  samples' embeddings, a cache keyed by the text's hash, rebuilt when missing). Readers:
  :func:`load` and :func:`samples`; nothing else in Kranto opens them.

Every reader takes a missing file, an empty file, a value stored as null or of another type, and
a key it does not know, as the default (the RCA rule of 23 October): the row goes through
``Stored.load``, which coerces each field and notes a bad one, and each file is read as text.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from ..stored.base import Iso, Stored

GUIDES = Path(__file__).parent / "guides"
SWITCHES: dict[str, tuple[str, ...]] = {
    "length": ("short", "medium", "long"),
    "register": ("casual", "neutral", "formal"),
    "opinions": ("mine", "suggest"),
    "emoji": ("never", "sparingly"),
    "hashtags": ("never", "site"),
    "links": ("post", "reply"),
}
SWITCH_DEFAULTS = {"length": "medium", "register": "neutral", "opinions": "mine",
                   "emoji": "never", "hashtags": "site", "links": "post", "grade": 8}
SWITCH_WORDS = {
    "length": "how long: short, medium or long",
    "register": "how formal: casual, neutral or formal",
    "opinions": "opinions: only mine, or suggest one marked for me to accept",
    "emoji": "emoji: never, or sparingly",
    "hashtags": "hashtags: never, or as the site's template says",
    "links": "links: in the post, or in the first reply where the site prefers it",
    "grade": "reading level: a school grade, 8 by default",
}
STRICTNESS = ("off", "light", "strict")
SITES = ("blog", "newsletter", "mastodon", "bluesky", "linkedin", "threads", "x", "substack")
# what each of Kranto's writers writes, as a site (the toot cub posts to Mastodon)
WRITER_SITE = {"blog": "blog", "newsletter": "newsletter", "toot": "mastodon",
               # Kranto's own short-post writer (kranto.social): every site's variant; no model
               # is chosen for it by default (P-11 is the owner's)
               "social": "short"}
# the old tone keys, migrated once into the voice card's first line
TONE_KEYS = (("blog", "tone", "On the blog"), ("toot", "tone", "On Mastodon"),
             ("newsletter", "intro", "In the newsletter"))
VOICE_MAX = 2000           # about 250 words, with room for the person's own edits
SAMPLE_MAX = 6000
SAMPLES_MAX = 40
LIST_MAX = 200
DISCLOSURE_LINE = "Drafted with Kranto from my notes; edited and sent by me."
# a site's limits when the caller passes none (SOCIAL's registry passes its own)
SITE_LIMITS: dict[str, dict[str, Any]] = {
    "blog": {"max_words": 1200, "hashtags": 0},
    "newsletter": {"max_words": 120, "hashtags": 0},
    "mastodon": {"max_chars": 500, "unit": "characters", "links": 1, "hashtags": 3},
    "bluesky": {"max_chars": 300, "unit": "graphemes", "links": 1, "hashtags": 2},
    "linkedin": {"max_chars": 3000, "unit": "characters", "links": 1, "hashtags": 3},
    "threads": {"max_chars": 500, "unit": "characters", "links": 1, "hashtags": 1},
    "x": {"max_chars": 280, "unit": "characters, a link counts 23", "links": 1, "hashtags": 1},
    "substack": {"max_words": 2500, "hashtags": 0},
}


@dataclass(frozen=True)
class ProfileRow(Stored):
    """The ``settings`` row ``prose.profile``: everything of the profile that is not a file."""

    SETTING = "prose.profile"
    switches: dict[str, Any] = field(default_factory=dict)
    strictness: str = "light"
    rules_off: list[str] = field(default_factory=list)
    guides: dict[str, Any] = field(default_factory=dict)      # site -> [guide names]
    disclosure: dict[str, Any] = field(default_factory=dict)  # site -> line ("" or absent: off)
    take: bool = True
    # writer (blog, toot, newsletter) -> {provider, model}: the model that writes its posts
    #; absent: the reason tier's, as before. Readers: ``load`` (the cub
    # host's model call for that writer, Write a post's angles, ``GET /api/prose``)
    writers: dict[str, Any] = field(default_factory=dict)
    migrated: dict[str, Any] = field(default_factory=dict)    # key -> the value moved
    migrated_at: Iso | None = None
    updated_at: Iso | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Sample:
    id: str
    text: str
    site: str | None = None


@dataclass(frozen=True)
class Profile:
    """What compose, check and revise read: the row and the files, as one value."""

    voice: str = ""
    never: tuple[str, ...] = ()
    keep: tuple[str, ...] = ()
    always: tuple[str, ...] = ()
    switches: dict[str, Any] = field(default_factory=lambda: dict(SWITCH_DEFAULTS))
    strictness: str = "light"
    rules_off: tuple[str, ...] = ()
    guides: dict[str, tuple[str, ...]] = field(default_factory=dict)
    disclosure: dict[str, str] = field(default_factory=dict)
    take: bool = True
    writers: dict[str, dict[str, str]] = field(default_factory=dict)
    samples: tuple[Sample, ...] = ()
    own_guides: dict[str, str] = field(default_factory=dict)   # name -> text
    home: Path | None = None

    def guides_for(self, site: str | None) -> tuple[str, ...]:
        """The guides a site's writer follows: the floor always, then the chosen ones (by
        default plain words and the site's template)."""
        chosen = self.guides.get(site or "") if site else None
        if chosen is None:
            chosen = ("plain", f"sites/{site}") if site else ("plain",)
        return ("floor", *[g for g in chosen if g != "floor"])

    def writer_model(self, writer: str | None) -> dict[str, str] | None:
        """The model that writes ``writer``'s posts, ``{provider, model}``, or None: the
        reason tier's model (P-11: no default is chosen until the owner's read)."""
        return self.writers.get(writer or "")

    def rhythm(self) -> dict[str, float] | None:
        """The samples' sentence length (mean, spread) and dash rate per 100 words."""
        if not self.samples:
            return None
        from .checker import dash_spans, sentence_lengths
        lengths: list[int] = []
        dashes = words = 0
        for s in self.samples:
            lengths += sentence_lengths(s.text)
            dashes += len(dash_spans(s.text))
            words += len(s.text.split())
        if not lengths:
            return None
        mean = sum(lengths) / len(lengths)
        sd = math.sqrt(sum((x - mean) ** 2 for x in lengths) / len(lengths))
        return {"mean": round(mean, 1), "sd": round(sd, 1),
                "dashes_per_100": round(100 * dashes / max(words, 1), 2)}


def default() -> Profile:
    """The profile of someone who skipped "How you write": the floor plus plain words."""
    return Profile()


# -- the home's files ---------------------------------------------------------------------------


def home_of(cfg) -> Path:
    return Path(cfg.root) / "prose"


def _read(path: Path, limit: int) -> str:
    try:
        return path.read_text(encoding="utf-8")[:limit]
    except (OSError, UnicodeDecodeError):
        return ""


def _lines(path: Path) -> tuple[str, ...]:
    out = []
    for line in _read(path, 100_000).splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line[:200])
    return tuple(dict.fromkeys(out))[:LIST_MAX]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def samples(home: Path) -> tuple[Sample, ...]:
    out = []
    folder = home / "samples"
    if not folder.is_dir():
        return ()
    for p in sorted(folder.glob("*.md"))[:SAMPLES_MAX]:
        text = _read(p, SAMPLE_MAX).strip()
        site = None
        m = re.match(r"site:\s*([a-z]+)\s*\n", text)
        if m:
            site, text = m.group(1), text[m.end():].strip()
        if text:
            out.append(Sample(p.stem, text, site))
    return tuple(out)


def own_guides(home: Path) -> dict[str, str]:
    folder = home / "guides"
    if not folder.is_dir():
        return {}
    out = {}
    for p in sorted(folder.rglob("*.md"))[:50]:
        name = p.relative_to(folder).with_suffix("").as_posix()
        if re.fullmatch(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)?", name):
            out[name] = _read(p, 20_000)
    return out


def shipped_guides() -> dict[str, str]:
    return {p.relative_to(GUIDES).with_suffix("").as_posix(): p.read_text(encoding="utf-8")
            for p in sorted(GUIDES.rglob("*.md"))}


def guide_text(profile: Profile, name: str) -> str:
    """A guide by name: the person's own file wins over Kranto's of the same name."""
    if name in profile.own_guides:
        return profile.own_guides[name]
    p = GUIDES / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.is_file() else ""


# -- the row ------------------------------------------------------------------------------------


def _clean_switches(raw) -> dict[str, Any]:
    out = dict(SWITCH_DEFAULTS)
    for k, v in (raw.items() if isinstance(raw, dict) else ()):
        grade = k == "grade" and isinstance(v, int) and not isinstance(v, bool) and 3 <= v <= 16
        if (k in SWITCHES and v in SWITCHES[k]) or grade:
            out[k] = v
    return out


def load_row(store) -> ProfileRow:
    from ..stored.settings import get_blob
    return get_blob(store, ProfileRow.SETTING, ProfileRow) or ProfileRow()


def save_row(store, row: ProfileRow) -> None:
    from ..store import iso, utcnow
    from ..stored.settings import set_blob
    set_blob(store, ProfileRow.SETTING, replace(row, updated_at=iso(utcnow())))


def clean_writers(raw) -> dict[str, dict[str, str]]:
    """The ``writers`` field as stored: each known writer's ``{provider, model}`` when both are
    text and the provider is one Kranto has; anything else (null, a list, an unknown writer or
    provider, an empty model) reads as unset."""
    from ..config import PROVIDERS
    out: dict[str, dict[str, str]] = {}
    for w, v in (raw.items() if isinstance(raw, dict) else ()):
        if w not in WRITER_SITE or not isinstance(v, dict):
            continue
        prov, model = v.get("provider"), v.get("model")
        if prov in PROVIDERS and isinstance(model, str) and model.strip():
            out[w] = {"provider": prov, "model": model.strip()[:120]}
    return out


def load(cfg, store) -> Profile:
    """The profile as in force now (the tone keys migrated first, once)."""
    migrate_tone(cfg, store)
    row = load_row(store)
    home = home_of(cfg)
    guides = {s: tuple(str(g) for g in v if isinstance(g, str))
              for s, v in (row.guides or {}).items() if isinstance(v, list)}
    disclosure = {s: str(v)[:200] for s, v in (row.disclosure or {}).items()
                  if isinstance(v, str) and v.strip()}
    return Profile(
        voice=_read(home / "voice.md", VOICE_MAX).strip(),
        never=_lines(home / "never.txt"), keep=_lines(home / "keep.txt"),
        always=_lines(home / "always.txt"), switches=_clean_switches(row.switches),
        strictness=row.strictness if row.strictness in STRICTNESS else "light",
        rules_off=tuple(str(r) for r in row.rules_off or () if isinstance(r, str)),
        guides=guides, disclosure=disclosure, take=row.take is not False,
        writers=clean_writers(row.writers), samples=samples(home),
        own_guides=own_guides(home), home=home)


# -- the tone migration ("today's *.tone becomes its first line") -------------


def _written_tone(cfg) -> dict[str, str]:
    """The tone keys as the person wrote them in ``kranto.yaml`` (a default is not theirs)."""
    from ..core.settings import _raw_section
    out = {}
    for cub, key, _ in TONE_KEYS:
        raw = _raw_section(cfg, cub)
        v = raw.get(key) if isinstance(raw, dict) else None
        if isinstance(v, str) and v.strip():
            out[f"{cub}.{key}"] = " ".join(v.split())[:120]
    return out


def tone_line(tones: dict[str, str]) -> str:
    """One line for the voice card: "Tone: plain." or, when the writers differed, each."""
    if not tones:
        return ""
    values = list(dict.fromkeys(tones.values()))
    if len(values) == 1:
        return f"Tone: {values[0]}."
    words = {f"{c}.{k}": w for c, k, w in TONE_KEYS}
    return "Tone: " + "; ".join(f"{words[k].lower()}, {v}" for k, v in tones.items()) + "."


def migrate_tone(cfg, store) -> bool:
    """Once: the tone keys written in ``kranto.yaml`` become the voice card's first line. The keys
    stay declared (an old file still loads) and are read by nothing else. True when it ran."""
    row = load_row(store)
    if row.migrated_at:
        return False
    from ..store import iso, utcnow
    tones = _written_tone(cfg)
    line = tone_line(tones)
    if line:
        path = home_of(cfg) / "voice.md"
        card = _read(path, VOICE_MAX).strip()
        if line not in card:
            _write(path, (line + "\n" + card).strip() + "\n")
    save_row(store, replace(row, migrated=tones, migrated_at=iso(utcnow())))
    return True


# -- changes (the verb prose.voice and prose.learn's yes) ---------------------------------------


class ProfileError(ValueError):
    pass


def _writers_changed(stored, wm) -> dict[str, dict[str, str]]:
    """``writer_model``'s change: writer -> ``{provider, model}``, or null for the tier's."""
    from ..config import PROVIDERS
    if not isinstance(wm, dict):
        raise ProfileError("writer_model is an object: writer -> {provider, model} or null")
    writers = clean_writers(stored)
    for w, v in wm.items():
        if w not in WRITER_SITE:
            raise ProfileError(f"no writer {w}: {', '.join(WRITER_SITE)}")
        if v is None:
            writers.pop(w, None)
            continue
        if (not isinstance(v, dict) or set(v) - {"provider", "model"}
                or v.get("provider") not in PROVIDERS
                or not isinstance(v.get("model"), str) or not v["model"].strip()
                or len(v["model"]) > 120):
            raise ProfileError(f"writer_model for {w}: a provider ({', '.join(PROVIDERS)}) "
                               "and a model in that provider's names")
        writers[w] = {"provider": v["provider"], "model": v["model"].strip()}
    return writers


def _sample_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def change(cfg, store, body: dict) -> dict:
    """Apply one change to the profile; what changed, in words. Each key is optional:

    ``voice`` (text), ``switches`` (object), ``strictness``, ``rules_off`` (list), ``guides``
    (site -> list of names, or null for the default), ``disclosure`` (site -> line, "" off),
    ``take`` (bool), ``writer_model`` (writer -> ``{provider, model}``, or null for the reason
    tier's model), ``never_add``/``never_remove``, ``keep_add``/``keep_remove``,
    ``always_add``/``always_remove`` (lists), ``samples_add`` ([{text, site}]),
    ``samples_remove`` (ids)."""
    from .checker import RULES
    known = {"voice", "switches", "strictness", "rules_off", "guides", "disclosure", "take",
             "writer_model",
             "never_add", "never_remove", "keep_add", "keep_remove", "always_add",
             "always_remove", "samples_add", "samples_remove"}
    extra = sorted(set(body) - known)
    if extra:
        raise ProfileError(f"no {', '.join(extra)} in a voice change")
    if not set(body) & known:
        raise ProfileError("say what to change")
    migrate_tone(cfg, store)
    row = load_row(store)
    home = home_of(cfg)
    said: list[str] = []
    if "voice" in body:
        v = body["voice"]
        if not isinstance(v, str) or len(v) > VOICE_MAX:
            raise ProfileError(f"voice is text of at most {VOICE_MAX} characters")
        _write(home / "voice.md", v.strip() + "\n")
        said.append("the voice card")
    if "switches" in body:
        sw = body["switches"]
        if not isinstance(sw, dict):
            raise ProfileError("switches is an object")
        for k, v in sw.items():
            if k == "grade":
                if not isinstance(v, int) or isinstance(v, bool) or not 3 <= v <= 16:
                    raise ProfileError("grade is a whole number from 3 to 16")
            elif k not in SWITCHES or v not in SWITCHES[k]:
                raise ProfileError(f"{k} is one of {', '.join(SWITCHES.get(k, ()))}"
                                   if k in SWITCHES else f"no switch {k}")
        row = replace(row, switches={**_clean_switches(row.switches), **sw})
        said.append("switches")
    if "strictness" in body:
        if body["strictness"] not in STRICTNESS:
            raise ProfileError("strictness is off, light or strict")
        row = replace(row, strictness=body["strictness"])
        said.append("strictness")
    if "rules_off" in body:
        r = body["rules_off"]
        if not isinstance(r, list) or any(x not in RULES for x in r):
            raise ProfileError("rules_off lists rule ids (GET /api/prose/rules)")
        row = replace(row, rules_off=sorted(set(r)))
        said.append("rules")
    if "guides" in body:
        g = body["guides"]
        if not isinstance(g, dict):
            raise ProfileError("guides is an object: site -> list of guide names")
        names = set(shipped_guides()) | set(own_guides(home))
        guides = dict(row.guides or {})
        for site, v in g.items():
            if v is None:
                guides.pop(site, None)
                continue
            if not isinstance(v, list) or any(n not in names for n in v):
                raise ProfileError(f"guides for {site}: names of guides (GET /api/prose)")
            guides[site] = list(v)
        row = replace(row, guides=guides)
        said.append("guides")
    if "disclosure" in body:
        d = body["disclosure"]
        if not isinstance(d, dict) or not all(isinstance(v, str) and len(v) <= 200
                                              for v in d.values()):
            raise ProfileError("disclosure is an object: site -> a line (\"\": off)")
        row = replace(row, disclosure={**(row.disclosure or {}), **d})
        said.append("disclosure")
    if "take" in body:
        if not isinstance(body["take"], bool):
            raise ProfileError("take is true or false")
        row = replace(row, take=body["take"])
        said.append("“What do you think?”")
    if "writer_model" in body:
        row = replace(row, writers=_writers_changed(row.writers, body["writer_model"]))
        said.append("the writer's model")
    for name in ("never", "keep", "always"):
        add, drop = body.get(f"{name}_add") or [], body.get(f"{name}_remove") or []
        if not add and not drop:
            continue
        if not all(isinstance(x, str) and 0 < len(x.strip()) <= 200 for x in [*add, *drop]):
            raise ProfileError(f"{name}_add and {name}_remove list text of 1 to 200 characters")
        for x in add:
            if x.startswith("/") and x.endswith("/") and len(x) > 2:
                try:
                    re.compile(x[1:-1])
                except re.error:
                    raise ProfileError(f"{x} is not a regular expression") from None
        now = list(_lines(home / f"{name}.txt"))
        now = [x for x in now if x not in {d.strip() for d in drop}]
        now += [x.strip() for x in add if x.strip() not in now]
        if len(now) > LIST_MAX:
            raise ProfileError(f"a list holds at most {LIST_MAX} entries")
        _write(home / f"{name}.txt", "\n".join(now) + ("\n" if now else ""))
        said.append(f"the {name} list")
    added = body.get("samples_add") or []
    if added:
        if not isinstance(added, list) or not all(
                isinstance(s, dict) and isinstance(s.get("text"), str)
                and 20 <= len(s["text"].strip()) <= SAMPLE_MAX
                and s.get("site") in (None, *SITES) for s in added):
            raise ProfileError(f"samples_add lists {{text, site}}: text of 20 to {SAMPLE_MAX} "
                               "characters, site one of Kranto's sites or none")
        if len(samples(home)) + len(added) > SAMPLES_MAX:
            raise ProfileError(f"at most {SAMPLES_MAX} samples")
        for s in added:
            text = s["text"].strip()
            head = f"site: {s['site']}\n\n" if s.get("site") else ""
            _write(home / "samples" / f"{_sample_id(text)}.md", head + text + "\n")
        said.append(f"{len(added)} sample{'s' if len(added) != 1 else ''}")
    for sid in body.get("samples_remove") or []:
        if not isinstance(sid, str) or not re.fullmatch(r"[a-z0-9_-]{1,40}", sid):
            raise ProfileError("samples_remove lists sample ids")
        p = home / "samples" / f"{sid}.md"
        if p.is_file():
            p.unlink()
            said.append("a sample removed")
    save_row(store, row)
    return {"ok": True, "changed": said,
            "say": "Saved: " + ", ".join(dict.fromkeys(said)) + "." if said else "No change."}


# -- the samples closest to a piece (by embedding, LaMP) ----------------------


def closest(profile: Profile, query: str, site: str | None, embedder, n: int = 3
            ) -> list[Sample]:
    """The ``n`` samples nearest the piece: cosine similarity of the embeddings, plus 0.1 for a
    sample written for the same site. With no embedder, the site's samples first, then the
    rest, in file order. The vectors are cached in ``vectors.json`` by the text's hash."""
    pool = list(profile.samples)
    if len(pool) <= n or embedder is None:
        return sorted(pool, key=lambda s: s.site != site)[:n]
    cache_path = (profile.home / "vectors.json") if profile.home else None
    cache: dict[str, list[float]] = {}
    if cache_path is not None:
        try:
            got = json.loads(cache_path.read_text(encoding="utf-8"))
            cache = got if isinstance(got, dict) else {}
        except (OSError, ValueError):
            cache = {}
    key = getattr(embedder, "model_name", type(embedder).__name__)
    keys = [f"{key}:{_sample_id(s.text)}" for s in pool]
    missing = [i for i, k in enumerate(keys) if not isinstance(cache.get(k), list)]
    if missing:
        vecs = embedder.embed_documents([pool[i].text for i in missing])
        for i, v in zip(missing, vecs, strict=True):
            cache[keys[i]] = [float(x) for x in v]
        if cache_path is not None:
            with contextlib.suppress(OSError):        # a cache: a read-only home is fine
                _write(cache_path, json.dumps({k: cache[k] for k in keys}))
    q = [float(x) for x in embedder.embed_query(query)]

    def cos(a: list[float], b: list[float]) -> float:
        na = math.sqrt(sum(x * x for x in a)) or 1.0
        nb = math.sqrt(sum(x * x for x in b)) or 1.0
        return sum(x * y for x, y in zip(a, b, strict=False)) / (na * nb)

    scored = [(cos(q, cache[k]) + (0.1 if s.site == site else 0.0), i)
              for i, (s, k) in enumerate(zip(pool, keys, strict=True))]
    return [pool[i] for _, i in sorted(scored, key=lambda t: (-t[0], t[1]))[:n]]
