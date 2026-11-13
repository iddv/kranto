"""``learn``: what the person changed before sending, as proposals.

``learn(draft, sent)`` diffs the two texts word by word and returns proposals; it changes
nothing. :func:`observe` adds a diff to a tally and stores the proposals it makes, and
:func:`answer` applies one proposal on a yes (through the verb ``prose.learn``, under the
ladder). Nothing reaches the profile without that yes.

- **never:** a word or short phrase the person cut. A floor word, or a phrase on the checker's
  lists, is proposed at once ("Kranto noticed you cut 'game-changer'. Never use it?"); any
  other word once they have cut it twice.
- **keep:** text the person added (or left in) that the checker flags: they wrote it on
  purpose, so the checker should leave it alone.
- **voice:** a phrase of two to six words the person added twice, offered as a line for the
  voice card ("You often write: 'for what it's worth'").

Stored data: the ``settings`` row ``prose.learned`` (:class:`Learned`): the tally,
the open proposals and the answers. Written by :func:`observe` and :func:`answer`; read by
them and ``GET /api/prose`` (the open proposals). A missing or malformed row reads as empty.
"""

from __future__ import annotations

import difflib
import hashlib
import re
from dataclasses import dataclass, field, replace
from typing import Any

from ..stored.base import Iso, Stored
from .checker import _STOP, _WORD, check
from .profile import Profile, default

TALLY_MAX = 400
OPEN_MAX = 30


@dataclass(frozen=True)
class Learned(Stored):
    SETTING = "prose.learned"
    cut: dict[str, Any] = field(default_factory=dict)      # word or phrase -> times cut
    added: dict[str, Any] = field(default_factory=dict)    # phrase -> times added
    proposals: list[Any] = field(default_factory=list)     # the open ones
    answered: dict[str, Any] = field(default_factory=dict)  # proposal id -> yes / no
    updated_at: Iso | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _tokens(text: str) -> list[str]:
    return re.findall(r"[A-Za-z][A-Za-z'’-]*|\S", text or "")


def _pid(kind: str, entry: str) -> str:
    return hashlib.sha256(f"{kind}:{entry.lower()}".encode()).hexdigest()[:10]


def _proposal(kind: str, entry: str, words: str) -> dict:
    return {"id": _pid(kind, entry), "kind": kind, "entry": entry, "words": words}


def diff(draft: str, sent: str) -> tuple[list[str], list[str]]:
    """The runs of words cut from the draft, and the runs added in what was sent."""
    a, b = _tokens(draft), _tokens(sent)
    cut, added = [], []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op in ("delete", "replace"):
            run = " ".join(t for t in a[i1:i2] if _WORD.fullmatch(t))
            if run:
                cut.append(run)
        if op in ("insert", "replace"):
            run = " ".join(t for t in b[j1:j2] if _WORD.fullmatch(t))
            if run:
                added.append(run)
    return cut, added


def _flagged_words(text: str, profile: Profile) -> list[tuple[str, str]]:
    """(the flagged text, its rule) for the word and phrase rules."""
    return [(f["text"], f["rule"]) for f in check(text, None, profile, strictness="strict")
            ["flags"] if f["group"] == "words"]


def learn(draft: str, sent: str, profile: Profile | None = None,
          tally: Learned | None = None) -> list[dict]:
    """Proposals from one draft and what was sent (nothing is stored or changed)."""
    p = profile or default()
    t = tally or Learned()
    cut, added = diff(draft, sent)
    out: dict[str, dict] = {}
    never = {x.lower() for x in p.never}
    keep = {x.lower() for x in p.keep}
    flagged_cut = {w.lower(): w for run in cut for w, _ in _flagged_words(run, p)}
    for low, w in flagged_cut.items():
        if low not in never:
            pr = _proposal("never", w, f"Kranto noticed you cut “{w}”. Never use it?")
            out[pr["id"]] = pr
    for run in cut:
        for w in run.split():
            low = w.lower().strip("'’")
            if len(low) < 4 or low in _STOP or low in never or low in flagged_cut:
                continue
            if int(t.cut.get(low) or 0) + 1 >= 2:
                pr = _proposal("never", low, f"You have cut “{low}” more than once. Never "
                                             "use it?")
                out[pr["id"]] = pr
    for w, _rule in _flagged_words(sent, p):
        if w.lower() not in keep and w.lower() not in flagged_cut and (
                w.lower() in " ".join(added).lower() or w.lower() in draft.lower()):
            pr = _proposal("keep", w, f"You kept “{w}”. Stop flagging it?")
            out[pr["id"]] = pr
    for run in added:
        n = len(run.split())
        if 2 <= n <= 6 and int(t.added.get(run.lower()) or 0) + 1 >= 2:
            pr = _proposal("voice", run, f"You often write “{run}”. Add it to your voice "
                                         "card?")
            out[pr["id"]] = pr
    return [pr for pr in out.values() if pr["id"] not in (t.answered or {})]


def load(store) -> Learned:
    from ..stored.settings import get_blob
    return get_blob(store, Learned.SETTING, Learned) or Learned()


def _save(store, row: Learned) -> None:
    from ..store import iso, utcnow
    from ..stored.settings import set_blob
    set_blob(store, Learned.SETTING, replace(row, updated_at=iso(utcnow())))


def observe(store, profile: Profile, draft: str, sent: str) -> list[dict]:
    """Count one diff and keep its proposals open for a yes or a no; the new ones."""
    row = load(store)
    props = learn(draft, sent, profile, row)
    cut, added = diff(draft, sent)
    tally_cut = dict(row.cut or {})
    for run in cut:
        for w in run.split():
            low = w.lower().strip("'’")
            if len(low) >= 4 and low not in _STOP:
                tally_cut[low] = int(tally_cut.get(low) or 0) + 1
    tally_added = dict(row.added or {})
    for run in added:
        if 2 <= len(run.split()) <= 6:
            tally_added[run.lower()] = int(tally_added.get(run.lower()) or 0) + 1
    keep_top = lambda d: dict(sorted(d.items(), key=lambda kv: -int(kv[1] or 0))[:TALLY_MAX])  # noqa: E731
    have = {pr.get("id") for pr in row.proposals if isinstance(pr, dict)}
    new = [pr for pr in props if pr["id"] not in have]
    open_ = ([pr for pr in row.proposals if isinstance(pr, dict)] + new)[-OPEN_MAX:]
    _save(store, replace(row, cut=keep_top(tally_cut), added=keep_top(tally_added),
                         proposals=open_))
    return new


class LearnError(ValueError):
    pass


def answer(cfg, store, pid: str, yes: bool) -> dict:
    """A yes applies the proposal to the profile; a no remembers it so it is not asked again."""
    from . import profile as profile_mod
    row = load(store)
    pr = next((x for x in row.proposals if isinstance(x, dict) and x.get("id") == pid), None)
    if pr is None:
        raise LearnError(f"no open proposal {pid}")
    said = "No change."
    if yes:
        if pr["kind"] == "never":
            said = profile_mod.change(cfg, store, {"never_add": [pr["entry"]]})["say"]
        elif pr["kind"] == "keep":
            said = profile_mod.change(cfg, store, {"keep_add": [pr["entry"]]})["say"]
        else:
            card = profile_mod.load(cfg, store).voice
            line = f"Phrases I use: “{pr['entry']}”."
            said = profile_mod.change(cfg, store, {
                "voice": (card + "\n" + line).strip()[:profile_mod.VOICE_MAX]})["say"]
    _save(store, replace(row, proposals=[x for x in row.proposals
                                         if not (isinstance(x, dict) and x.get("id") == pid)],
                         answered={**(row.answered or {}), pid: "yes" if yes else "no"}))
    return {"ok": True, "say": said, "proposal": pr, "answer": "yes" if yes else "no"}
