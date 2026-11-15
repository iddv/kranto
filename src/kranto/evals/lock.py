"""``prompts.lock.json``: every prompt the server ships, the version it is
at, and the scorecard that evaluated that version. ``tests/test_prompt_lock.py`` fails a
change to a shipped prompt (or to TENETS, which every intern call carries) that does not
update the lock, so a prompt never changes without naming the evidence for it.

An entry::

    "screen": {"version": "screen-f0e11eac", "evaluated": "2026-10-17",
               "scorecard": "scorecards/2026-10-17-watching-v1-claude-haiku-5-5.md"}

``evaluated`` may instead say ``"skipped: <reason>"`` (visible in review). The owner's own
prompts (Settings › Prompts) are not in the lock: they are the owner's, versioned by the
store; the lock covers what ships."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path

from .. import prompts

LOCK = "prompts.lock.json"
TENETS = "TENETS"
# The stage whose eval a prompt's change makes due (kranto eval <stage>)
STAGE = {"screen": "watching", "screen_batch": "watching", "judge": "watching",
         TENETS: "watching and ideas", "card": "ideas", "verify": "ideas", "name": "ideas",
         "explain": "ideas", "rollup": "ideas", "scout": "discovery", "resolve": "discovery",
         "xai_search": "discovery"}


def shipped() -> dict[str, str]:
    """``{name: version}`` for every prompt file the server ships, TENETS included."""
    out = {}
    for f in resources.files(prompts.__package__).iterdir():
        if f.name.endswith(".md"):
            name = f.name.removesuffix(".md")
            out[name] = prompts.Prompt(name, f.read_text(encoding="utf-8")).version
    return dict(sorted(out.items()))


def read(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text())
    except OSError:
        return {}


def problems(lock: dict, now: dict[str, str] | None = None) -> list[str]:
    """Why the lock does not match what ships (empty: it does)."""
    now = now if now is not None else shipped()
    out = []
    for name, version in now.items():
        e = lock.get(name)
        if not isinstance(e, dict):
            out.append(f"`{name}` is not in {LOCK}: add it with the scorecard that evaluated "
                       f"{version} (kranto eval lock set {name} --scorecard FILE), or "
                       f"--skipped REASON")
            continue
        if e.get("version") != version:
            out.append(f"`{name}` changed ({e.get('version')} -> {version}): run kranto eval "
                       f"{STAGE.get(name, 'watching').split(' and ')[0]} and name its scorecard "
                       f"in {LOCK} (kranto eval lock set {name} --scorecard FILE), or say "
                       "--skipped REASON")
        ev = str(e.get("evaluated") or "")
        if not ev:
            out.append(f"`{name}`: say when it was evaluated, or \"skipped: <reason>\"")
        elif not ev.startswith("skipped: ") and not e.get("scorecard"):
            out.append(f"`{name}`: evaluated {ev} but names no scorecard")
    for name in sorted(set(lock) - set(now)):
        out.append(f"`{name}` is in {LOCK} but the server ships no such prompt: remove it")
    return out


def set_entry(path: Path, name: str, *, scorecard: str | None = None,
              skipped: str | None = None) -> dict:
    """``kranto eval lock set``: the entry for ``name`` at its shipped version."""
    now = shipped()
    if name not in now:
        raise ValueError(f"the server ships no prompt {name!r} (prompts: {', '.join(now)})")
    if bool(scorecard) == bool(skipped):
        raise ValueError("give --scorecard FILE or --skipped REASON")
    lock = read(path)
    lock[name] = {"version": now[name],
                  "evaluated": datetime.now(UTC).strftime("%Y-%m-%d") if scorecard
                  else f"skipped: {skipped}",
                  **({"scorecard": scorecard} if scorecard else {})}
    Path(path).write_text(json.dumps(dict(sorted(lock.items())), indent=1) + "\n")
    return lock[name]
