"""Versioned prompt files, and the owner's additions and overrides to them.

A prompt's version is derived from a hash of its text, so every recorded LLM
call and every observation names the exact prompt that produced it, and a
prompt edit cannot silently share a version with its predecessor.

The owner can see and steer these prompts from Kranto UI (Settings › Prompts, through
``web/prompts_api.py``):

- ``REGISTRY`` lists them, each with what it does, its placeholders and ``editable``:
  ``full`` (additions and a full override) or ``additions-only``. ``verify`` (the citation
  check) is additions-only: the rule is to fix the writer, never the checker, so its rules
  can only be added to, under a heading that says they can't be relaxed.
- **Additions** are appended to the template under a heading; **a full override** replaces
  it, and keeps the placeholders the code fills (``{tenets}`` stays in the judge and the
  screen: TENETS is sent in every intern call).
- They live in the kranto home, never in the repo, append-only:
  ``<home>/prompts/the server/<id>/v<N>.json`` (+ ``v<N>.md``, the override, and
  ``v<N>.default.md``, the default it was edited against) and ``active.json``. The same
  tree holds the page's prompts (``prompts/the page/``), which the page manages itself.
- **Going back** is a restore: version N's override and additions copied into a new version
  (action ``restore``, ``from: N``), checked like a save. The text is the same, so the
  version is too. An optional short note per version (``notes.jsonl``, append-only, the
  last line per version wins) helps find a good one again.
- ``configure(home)`` turns them on for this process (``open_runtime`` does it with the
  workspace); unconfigured, as in tests, every prompt is the shipped file.
  ``$KRANTO_PROMPTS=defaults`` (benchmarks) gives the shipped files whatever is stored.

With nothing customised a prompt's text and version are exactly what they were; a
customised one gets its own version, which ``llm_calls.prompt_version``, observations and
cards (through their calls) record.
"""

from __future__ import annotations

import contextlib
import difflib
import fcntl
import hashlib
import json
import os
import re
import string
import time
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

REPO = "kranto"
DEFAULTS_ENV = "KRANTO_PROMPTS"
GROUP = "Watching"
MAX_ADDITIONS = 8000
MAX_TEMPLATE = 64000
ADD_HEADING = "## The owner's additions"
CHECK_HEADING = "## The owner's additions (these cannot relax the rules above)"
CHECK_INTRO = ("The owner added the notes below. They may add checks or ask for more care. "
               "They never relax, skip or override a rule, a check or a threshold above; where "
               "they seem to, the rules above win.")

_home: Path | None = None


@dataclass(frozen=True)
class Prompt:
    name: str
    template: str

    @property
    def version(self) -> str:
        digest = hashlib.sha256(self.template.encode()).hexdigest()[:8]
        return f"{self.name}-{digest}"

    def render(self, **values: str) -> str:
        return self.template.format(**values)

    def render_keeping(self, keep: str, **values: str) -> str:
        """``render``, with ``values[keep]`` appended when the template does not carry
        ``{keep}``: an owner's full override saved before that placeholder existed still gets
        what the code puts there (live search's results: the owner's rule of 2026-10-17 that
        what exists comes from the web, which a prompt edit must not switch off silently)."""
        text = self.render(**values)
        if "{" + keep + "}" in self.template or not values.get(keep):
            return text
        return f"{text.rstrip()}\n\n{values[keep]}\n"


def schema(name: str) -> dict | None:
    """The JSON schema of a stage's reply (``<name>.schema.json`` beside its prompt: screen,
    judge, name), or None for a stage without one. A provider sends it only where structured
    outputs are turned on for the call (``llm.anthropic.structured``,
    ``llm.claude_code.structured``); the reply is read the same way either way. Shipped with
    Kranto, not edited in Settings › Prompts: it is the shape the code reads, not wording."""
    try:
        text = resources.files(__package__).joinpath(f"{name}.schema.json").read_text(
            encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    return json.loads(text)


class PromptError(ValueError):
    """A request the store refuses, with a message for the owner."""

    def __init__(self, msg: str, code: int = 400) -> None:
        super().__init__(msg)
        self.code = code


@dataclass(frozen=True)
class Entry:
    id: str
    title: str
    step: str
    purpose: str
    where: str
    placeholders: dict  # name -> (description, required in a full override)
    editable: str = "full"
    subject: str = "none"  # what a preview runs against: observation | idea | topic | none

    @property
    def file(self) -> str:
        return f"src/kranto/prompts/{self.id}.md"

    @property
    def checker(self) -> bool:
        return self.editable == "additions-only"


_TENETS = ("TENETS.md, re-read on every call (kept in every override)", True)
REGISTRY: tuple[Entry, ...] = (
    Entry("screen", "Screen", "screen",
          "A cheap first look at each new item: is it worth the judge's time?",
          "every item that passes the prefilter", {"tenets": _TENETS}, subject="observation"),
    Entry("screen_batch", "Screen, short posts together", "screen",
          "The same first look for short posts (X, Bluesky, Mastodon), many to one call.",
          "short posts that pass the prefilter, many to a call (20 unless you set fewer)",
          {"tenets": _TENETS}, subject="observation"),
    Entry("judge", "Judge", "judge",
          "Reads an item and writes the observation: what it says, why it matters and its "
          "signal scores. Novelty here is the model's own knowledge, by the owner's grading; "
          "live search is applied where novelty is claimed: the idea card's prior art and the "
          "weekly editor.", "every item the screen passes", {"tenets": _TENETS},
          subject="observation"),
    Entry("card", "Idea card", "ideas",
          "Writes an idea card from a cluster of observations, citing them.",
          "the daily ideas job",
          {"observations": ("the observations, numbered, one per line", True),
           "why_selected": ("why this group of observations was chosen", False),
           "today": ("today's date", False),
           "prior_art": ("live search results for what the observations are about, dated and "
                         "numbered, with the rules for citing them (or that no search ran)",
                         False)}, subject="idea"),
    Entry("verify", "Citation check", "ideas",
          "Checks that each claim on a card is supported by the observation it cites.",
          "after each card is written",
          {"pairs": ("each claim with the observation it cites", True)},
          editable="additions-only", subject="idea"),
    Entry("scout", "Source scout", "topics",
          "Proposes sources to watch for a topic.", "when a topic is added or scouted",
          {"name": ("the topic's name", True),
           "description": ("the topic's description", False),
           "presets": ("the source presets it may propose", False),
           "replacements": ("sources being replaced, if any", False),
           "results": ("the live search results it proposes from, dated and numbered, or the "
                       "sentence that there is no live search", False),
           "today": ("today's date", False)}, subject="topic"),
    Entry("resolve", "Resolve a pasted list", "topics",
          "Turns a pasted list of sources into catalog presets, without adding any of its own.",
          "Settings › Add source › Describe what to add, and python -m kranto sources describe",
          {"presets": ("the catalog: the presets a line may become, which accounts are "
                       "connected, and what is not offered", False),
           "max_proposals": ("how many proposals at most", False),
           "text": ("the pasted text", True),
           "results": ("on a second look at lines that failed: one live search per line, "
                       "dated; empty on the first pass", False)}),
    Entry("explain", "Explain", "explain",
          "Says what a neighbourhood of observations has in common.", "on request",
          {"observations": ("the observations, numbered", True)}, subject="observation"),
    Entry("name", "Cluster name", "map",
          "Names a cluster on the map.", "the daily snapshot",
          {"observations": ("a sample of the cluster's observations", True),
           "keywords": ("the cluster's keywords", False)}),
    Entry("xai_search", "X search through Grok", "watch",
          "Asks Grok to search X for a topic and list the posts it read, in its own words "
          "(the xAI path, off until an xAI key is set).",
          "each X-through-Grok source, once a day",
          {"query": ("the source's search", True), "since": ("the first day searched", False),
           "max_posts": ("how many posts at most", False)}),
    Entry("rollup", "Rollup", "retention",
          "Summarises observations past their retention age before they are removed.",
          "compaction",
          {"observations": ("the observations' summaries", True),
           "period": ("the period they cover", False), "size": ("how many", False),
           "sources": ("their sources", False), "keywords": ("their keywords", False)}),
)


def _feature_entries() -> tuple[Entry, ...]:
    """Each feature's prompts (its manifest's ``prompts``), editable like the core's. Their
    files ship in this package beside the core's, so one lock file covers both."""
    from ..features import FEATURES
    return tuple(Entry(p.id, p.title, f.id, p.purpose, p.where, dict(p.placeholders),
                       p.editable) for f in FEATURES for p in f.prompts)


REGISTRY = REGISTRY + _feature_entries()
BY_ID = {e.id: e for e in REGISTRY}


def entry(pid: str) -> Entry:
    try:
        return BY_ID[pid]
    except KeyError:
        raise PromptError(f"no prompt {pid!r} in the server's registry", 404) from None


# -- where the owner's versions live ------------------------------------------------------------


def configure(home: Path | None) -> None:
    """Use the store under ``home`` (a workspace / kranto home); None turns it off."""
    global _home
    _home = Path(home) if home is not None else None


def defaults_only() -> bool:
    return os.environ.get(DEFAULTS_ENV, "").strip().lower() in ("defaults", "default", "off")


def store() -> Store | None:
    return Store(_home / "prompts") if _home is not None else None


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _create(path: Path, text: str) -> None:
    """A new file, never an existing one (versions are append-only)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


MAX_NOTE = 80


def clean_note(note) -> str:
    """A version's note: one line, at most ``MAX_NOTE`` characters (empty: none)."""
    if note is None:
        return ""
    if not isinstance(note, str):
        raise PromptError("note must be a string (empty: none)")
    note = " ".join(note.split())
    if len(note) > MAX_NOTE:
        raise PromptError(f"a note is at most {MAX_NOTE} characters")
    return note


def _version_n(n) -> int:
    try:
        n = int(n) if not isinstance(n, bool) else 0
    except (TypeError, ValueError):
        n = 0
    if n < 1:
        raise PromptError("version must be a version number (1 or more)")
    return n


class Store:
    """Append-only versions under ``root`` (``<home>/prompts``); only ``active.json``, the
    pointer, is ever replaced."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def dir(self, *parts: str) -> Path:
        return self.root.joinpath(*parts)

    def versions(self, *parts: str) -> list[dict]:
        d = self.dir(*parts)
        out = []
        for p in d.glob("v*.json") if d.is_dir() else []:
            if re.fullmatch(r"v\d+\.json", p.name):
                with contextlib.suppress(OSError, ValueError):
                    out.append(json.loads(p.read_text()))
        return sorted(out, key=lambda v: v["n"])

    def active(self, *parts: str) -> dict | None:
        d = self.dir(*parts)
        try:
            n = int(json.loads((d / "active.json").read_text())["version"])
            meta = json.loads((d / f"v{n}.json").read_text())
        except (OSError, ValueError, KeyError, TypeError):
            return None
        meta["template"] = (d / f"v{n}.md").read_text() if meta.get("has_template") else None
        base = d / f"v{n}.default.md"
        meta["base"] = base.read_text() if base.exists() else None
        return meta

    def version(self, parts: tuple, n: int) -> dict:
        """Version ``n`` as ``active()`` gives it (its ``template`` and ``base``), or a 404."""
        d = self.dir(*parts)
        try:
            meta = json.loads((d / f"v{int(n)}.json").read_text())
        except (OSError, ValueError, TypeError):
            raise PromptError(f"no version {n}", 404) from None
        meta["template"] = (d / f"v{meta['n']}.md").read_text() if meta.get("has_template") \
            else None
        base = d / f"v{meta['n']}.default.md"
        meta["base"] = base.read_text() if base.exists() else None
        return meta

    def notes(self, *parts: str) -> dict[int, str]:
        """``{n: note}``: the owner's short note per version. ``notes.jsonl`` is append-only
        too: the last line for a version wins (an empty note clears it)."""
        out: dict[int, str] = {}
        try:
            lines = (self.dir(*parts) / "notes.jsonl").read_text().splitlines()
        except OSError:
            return out
        for line in lines:
            with contextlib.suppress(ValueError, KeyError, TypeError):
                rec = json.loads(line)
                out[int(rec["n"])] = str(rec.get("note") or "")
        return {n: t for n, t in out.items() if t}

    def set_note(self, parts: tuple, n: int, note: str) -> None:
        d = self.dir(*parts)
        if not (d / f"v{int(n)}.json").exists():
            raise PromptError(f"no version {n}", 404)
        with open(d / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            with open(d / "notes.jsonl", "a") as f:
                f.write(json.dumps({"n": int(n), "note": note, "at": _now()}) + "\n")

    def append(self, parts: tuple, *, action: str, template: str | None, additions: str,
               default: str | None = None, extra: dict | None = None,
               note: str = "") -> dict:
        d = self.dir(*parts)
        d.mkdir(parents=True, exist_ok=True)
        with open(d / ".lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            n = max((v["n"] for v in self.versions(*parts)), default=0) + 1
            meta = {"n": n, "at": _now(),
                    "action": action, "has_template": template is not None,
                    "additions": additions or "",
                    "default_hash": sha(default) if default is not None else None,
                    **(extra or {})}
            if template is not None:
                _create(d / f"v{n}.md", template)
                if default is not None:
                    _create(d / f"v{n}.default.md", default)
            _create(d / f"v{n}.json", json.dumps(meta, indent=1) + "\n")
            if note:
                with open(d / "notes.jsonl", "a") as f:
                    f.write(json.dumps({"n": n, "note": note, "at": meta["at"]}) + "\n")
            tmp = d / f".active.{os.getpid()}.tmp"
            tmp.write_text(json.dumps({"version": n, "at": meta["at"]}) + "\n")
            os.replace(tmp, d / "active.json")
        return meta


# -- the text a call gets -------------------------------------------------------------------------


def default_text(name: str) -> str:
    return resources.files(__package__).joinpath(f"{name}.md").read_text(encoding="utf-8")


def additions_block(e: Entry, text: str) -> str:
    text = text.strip().replace("{", "{{").replace("}", "}}")
    if not text:
        return ""
    if e.checker:
        return f"{CHECK_HEADING}\n\n{CHECK_INTRO}\n\n{text}"
    return f"{ADD_HEADING}\n\n{text}"


def compose(e: Entry, template: str, additions: str) -> str:
    block = additions_block(e, additions)
    return template if not block else template.rstrip("\n") + "\n\n" + block + "\n"


def _active(name: str, st: Store | None) -> dict | None:
    if st is None or name not in BY_ID:
        return None
    try:
        return st.active(REPO, name)
    except OSError:
        return None


def load(name: str, *, defaults: bool | None = None) -> Prompt:
    """The prompt a call gets: the shipped file, with the owner's override and additions
    when a store is configured (``configure``) and ``defaults`` is not asked for (the
    ``$KRANTO_PROMPTS`` flag by default)."""
    text = default_text(name)
    only = defaults_only() if defaults is None else defaults
    a = None if only else _active(name, store())
    if a:
        e = BY_ID[name]
        tpl = a.get("template") if a.get("template") is not None and not e.checker else None
        text = compose(e, tpl if tpl is not None else text, a.get("additions") or "")
    return Prompt(name, text)


def tenets() -> str:
    """Read TENETS fresh on every call: Kranto re-read them every iteration."""
    return resources.files(__package__).joinpath("TENETS.md").read_text(encoding="utf-8")


# -- the API's views and writes -------------------------------------------------------------------


def fields(template: str) -> set[str]:
    try:
        return {f.split(".")[0].split("[")[0] for _, f, _, _ in string.Formatter().parse(template)
                if f}
    except ValueError:
        return set()


def check_template(e: Entry, template: str) -> list[str]:
    """Why a full override can't be saved (empty: it can)."""
    if e.checker:
        return [f"{e.title} is a checker: its rules can't be replaced, only added to "
                "(additions-only)"]
    if not template.strip():
        return ["the template is empty"]
    if len(template) > MAX_TEMPLATE:
        return [f"the template is over {MAX_TEMPLATE} characters"]
    try:
        list(string.Formatter().parse(template))
    except ValueError as exc:
        return [f"the template's braces don't parse ({exc}); write a literal brace as {{{{ "
                "or }}"]
    have = fields(template)
    probs = [f"the template must keep {{{k}}} ({d})" for k, (d, req) in e.placeholders.items()
             if req and k not in have]
    unknown = sorted(have - set(e.placeholders))
    if unknown:
        probs.append("the template names placeholders the code doesn't fill: "
                     + ", ".join(f"{{{k}}}" for k in unknown)
                     + "; write a literal brace as {{ or }}")
    return probs


def _default_changed(name: str, a: dict | None) -> bool:
    return bool(a and a.get("has_template") and a.get("default_hash")
                and a["default_hash"] != sha(default_text(name)))


def summary(e: Entry, st: Store) -> dict:
    a = st.active(REPO, e.id)
    adds = bool(a and (a.get("additions") or "").strip())
    return {"repo": REPO, "id": e.id, "title": e.title, "group": GROUP, "step": e.step,
            "file": e.file, "purpose": e.purpose, "where": e.where, "editable": e.editable,
            "house_rules": False, "subject": e.subject,
            "customised": bool(a and (a.get("has_template") or adds)),
            "override": bool(a and a.get("has_template")), "additions": adds,
            "version": load(e.id).version, "n": int((a or {}).get("n") or 0),
            "default_changed": _default_changed(e.id, a)}


def registry(st: Store) -> list[dict]:
    return [summary(e, st) for e in REGISTRY]


def _diff(a: str, b: str, an: str, bn: str) -> str:
    return "".join(difflib.unified_diff(a.splitlines(keepends=True),
                                        b.splitlines(keepends=True), an, bn))


def detail(pid: str, st: Store) -> dict:
    e = entry(pid)
    a = st.active(REPO, e.id)
    dflt = default_text(e.id)
    yours = a.get("template") if a else None
    out = {**summary(e, st), "syntax": "format",
           "placeholders": [{"name": k, "token": f"{{{k}}}", "description": d, "required": r}
                            for k, (d, r) in e.placeholders.items()],
           "notes": [], "slots": [], "sections": [],
           "default": dflt, "default_hash": sha(dflt), "template": yours,
           "additions_text": (a or {}).get("additions") or "", "active": load(e.id).template,
           "defaults_only": defaults_only(),
           "versions": _version_rows(e, st, a, dflt), "max_note": MAX_NOTE,
           "headings": {"house_rules": None,
                        "additions": CHECK_HEADING if e.checker else ADD_HEADING}}
    if e.checker:
        out["checker_note"] = "additions only: this step's rules can't be relaxed"
    if out["default_changed"]:
        out["three_way"] = {"old_default": a.get("base"), "new_default": dflt, "yours": yours,
                            "diff_default": _diff(a.get("base") or "", dflt, "old default",
                                                  "new default")}
        out["notice"] = "the default changed since you edited this"
    if yours is not None:
        out["diff"] = _diff(dflt, yours, "default", "yours")
    return out


# -- versions: see one, restore one, note one ----------------------------------------------------


def _composed(e: Entry, v: dict, dflt: str) -> str:
    """The text version ``v`` gives a call now (today's default), so its version is the one
    provenance records; a restore of it has the same version."""
    tpl = v.get("template") if v.get("has_template") and not e.checker else None
    return compose(e, tpl if tpl is not None else dflt, v.get("additions") or "")


def _same_as(first: dict, h: str, n: int) -> int | None:
    m = first.get(h)
    return m if m is not None and m < n else None


def _version_rows(e: Entry, st: Store, a: dict | None, dflt: str) -> list[dict]:
    notes = st.notes(REPO, e.id)
    rows, first = [], {}
    for v in st.versions(REPO, e.id):
        if v.get("has_template"):
            p = st.dir(REPO, e.id) / f"v{v['n']}.md"
            v["template"] = p.read_text() if p.exists() else None
        h = Prompt(e.id, _composed(e, v, dflt)).version
        rows.append({k: v.get(k) for k in ("n", "at", "action", "has_template",
                                           "default_hash", "from")}
                    | {"additions_chars": len(v.get("additions") or ""),
                       "active": bool(a and v["n"] == a["n"]), "note": notes.get(v["n"], ""),
                       "hash": h, "same_as": _same_as(first, h, v["n"])})
        first.setdefault(h, v["n"])
    return rows


def _restore_problems(e: Entry, v: dict) -> list[str]:
    """Why version ``v`` can't be restored now (empty: it can): the same checks as a save."""
    if v.get("template") is None:
        return []
    if e.checker:
        return [f"{e.title} is a checker: additions only, so v{v['n']}'s full template can't "
                "be restored"]
    return check_template(e, v["template"])


def version_view(pid: str, n, st: Store) -> dict:
    """Version ``n``: its template (None: the default), its additions, the text it gives a
    call and a unified diff of that against the version in use."""
    e = entry(pid)
    v = st.version((REPO, e.id), _version_n(n))
    a = st.active(REPO, e.id)
    mine = Prompt(e.id, _composed(e, v, default_text(e.id)))
    cur = load(e.id)
    probs = _restore_problems(e, v)
    an = int((a or {}).get("n") or 0)
    return {"repo": REPO, "id": e.id, "n": v["n"], "at": v.get("at"),
            "action": v.get("action"), "from": v.get("from"),
            "note": st.notes(REPO, e.id).get(v["n"], ""),
            "template": v.get("template"),
            "template_kind": "override" if v.get("template") is not None else "default",
            "additions": v.get("additions") or "", "text": mine.template,
            "hash": mine.version, "active": an == v["n"], "active_n": an,
            "active_hash": cur.version, "same_as_active": mine.version == cur.version,
            "diff": _diff(cur.template, mine.template, f"in use (v{an})", f"v{v['n']}"),
            "restorable": not probs,
            "why_not": ("can't restore: " + "; ".join(probs)) if probs else None}


def restore(pid: str, body: dict | None, st: Store) -> dict:
    """``{"version": N}``: version N's template and additions as a new version N+1 (action
    ``restore``, ``from: N``), checked like a save. Nothing moves back, nothing is deleted."""
    e = entry(pid)
    n = _version_n((body or {}).get("version"))
    note = clean_note((body or {}).get("note"))
    v = st.version((REPO, e.id), n)
    probs = _restore_problems(e, v)
    if probs:
        raise PromptError(f"not restored: v{n} can't be used now: " + "; ".join(probs))
    tpl = v.get("template")
    if tpl is not None and tpl == default_text(e.id):
        tpl = None
    st.append((REPO, e.id), action="restore", template=tpl, additions=v.get("additions") or "",
              default=(v.get("base") or default_text(e.id)) if tpl is not None else None,
              extra={"from": n}, note=note)
    return detail(pid, st)


def set_note(pid: str, n, body: dict | None, st: Store) -> dict:
    """``{"note": str}`` (at most 80 characters; empty clears it) on version ``n``."""
    e = entry(pid)
    st.set_note((REPO, e.id), _version_n(n), clean_note((body or {}).get("note")))
    return detail(pid, st)


def save(pid: str, body: dict, st: Store) -> dict:
    """``{"additions": str}`` and/or ``{"template": str | None}`` as a new version, with an
    optional ``note``."""
    e = entry(pid)
    if not isinstance(body, dict) or not ({"additions", "template"} & set(body)):
        raise PromptError("send additions, template, or both")
    note = clean_note(body.get("note"))
    a = st.active(REPO, e.id) or {}
    adds, tpl, base = a.get("additions") or "", a.get("template"), a.get("base")
    if "additions" in body:
        if not isinstance(body["additions"], str):
            raise PromptError("additions must be a string (empty: none)")
        if len(body["additions"]) > MAX_ADDITIONS:
            raise PromptError(f"additions are at most {MAX_ADDITIONS} characters")
        adds = body["additions"].strip()
    if "template" in body:
        t = body["template"]
        if t is not None and not isinstance(t, str):
            raise PromptError("template must be a string, or null to drop the override")
        if e.checker and t is not None:
            raise PromptError(f"{e.title} is a checker: additions only, its rules can't be "
                              "replaced")
        if t is not None:
            probs = check_template(e, t)
            if probs:
                raise PromptError("not saved: " + "; ".join(probs))
            if t == default_text(e.id):
                t = None
        if t != tpl:
            base = default_text(e.id) if t is not None else None
        tpl = t
    action = "template" if "template" in body else "additions"
    if tpl is None and not adds:
        action = "reset"
    st.append((REPO, e.id), action=action, template=tpl, additions=adds,
              default=(base or default_text(e.id)) if tpl is not None else None, note=note)
    return detail(pid, st)


def reset(pid: str, body: dict | None, st: Store) -> dict:
    """Back to the default as a new version (``what``: all, template or additions)."""
    e = entry(pid)
    what = (body or {}).get("what") or "all"
    if what not in ("all", "template", "additions"):
        raise PromptError("what must be all, template or additions")
    a = st.active(REPO, e.id) or {}
    tpl = None if what in ("all", "template") else a.get("template")
    adds = "" if what in ("all", "additions") else (a.get("additions") or "")
    st.append((REPO, e.id), action="reset", template=tpl, additions=adds,
              default=(a.get("base") or default_text(e.id)) if tpl is not None else None)
    return detail(pid, st)


class _Missing(dict):
    def __missing__(self, k):
        return f"[{k}]"


def fill(e: Entry, template: str, values: dict) -> str:
    """The template filled as the code fills it; a value the subject can't give shows as
    ``[name: description]``."""
    vals = {k: f"[{k}: {d}]" for k, (d, _) in e.placeholders.items()}
    vals.update({k: v for k, v in values.items() if v is not None})
    return template.format_map(_Missing(vals))
