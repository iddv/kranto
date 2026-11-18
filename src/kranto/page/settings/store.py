"""The page's settings file, ``loop.yaml``, and the folder it lives in.

The folder: ``$KRANTO_LOOP_HOME``, else this user's Kranto install's (``kranto_loop_home``),
else ``~/kranto-loop``. ``loop.yaml`` holds any subset of ``DEFAULTS``; a missing key takes its
default. The folder also keeps the console's and Open in Claude Code's sessions (``term/``) and
kept research runs; ``paths.LoopLayout`` names them.

Before 0.7 this file also held the build loop's settings (builds, pitches, publishing,
maintenance, projects). Those features left Kranto; an old file that still has them is read
as before and the keys are ignored without a warning (``schema.RETIRED``).
"""
from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from kranto import legacy

from .. import paths
from ..upstream import REPOS as UPSTREAM

HOME_ENV = paths.LOOP_HOME_ENV
# The server's URL, when something starts the page apart from the server: wins over
# ``kranto.url`` in loop.yaml.
KRANTO_URL_ENV = "KRANTO_SERVER_URL"

DEFAULTS: dict = {
    # The server's API, for the page's own reads when it runs apart from the server (the
    # console's and the assistant's tools); the server that mounts the page passes its own.
    "kranto": {"enabled": True, "url": None},
    # The page's writes need a token (the page's cookie, or a token's Bearer); false is the
    # old way, for a page on its own in a test.
    "api": {"require_token": True},
    # The Claude Code binary the console and Open in Claude Code run (``kranto setup --claude
    # PATH``, or found off PATH by the wizard); null: claude on PATH. allow_api_key: without a
    # Claude login token, Open in Claude Code may log in with the watcher's Claude API key
    # (Kranto's .env) and bill it (``box/handoff.py``). The section keeps its old name, so an
    # existing file keeps working.
    "build": {"claude_command": None, "allow_api_key": False},
    # Feedback: the repository its issues go to, as the person who sends it (their own gh,
    # or GitHub's new-issue page); a fork or a move sets its own here.
    "feedback": {"repo": UPSTREAM["watcher"]},
    # Open in Claude Code: the real Claude Code in the page, one session per subject under
    # <home>/term/. enabled null (automatic): offered where bubblewrap can make its sandbox
    # and Kranto has a Claude token (kranto doctor says both); true: offered, also without
    # bubblewrap (with a warning that the sandbox is absent); false: not offered.
    # max_sessions live at once (a further Open says which to end); idle_min: a session
    # nobody watches and that prints nothing for this long is ended (Open again resumes the
    # conversation). model null: the CLI's default. net_hosts: what the session may reach
    # without asking; any other host is refused until you allow it in the page, for that
    # session only. quiet_hosts: Claude Code's own background traffic (its updater, changelog
    # and telemetry), refused without asking (net.jsonl says "quiet"); a host also in
    # net_hosts is allowed. daily_usd null: no cap. allow_api_key: a session may log in with
    # the watcher's Claude API key (ANTHROPIC_API_KEY from Kranto's .env) when there is no
    # Claude login token; false: Open says what it would bill and offers Use the API key (a
    # key in the unit's own environment is used either way). On an API key, a sources session
    # runs on the watcher's reason model unless model is set.
    "term": {"enabled": None, "allow_api_key": False, "max_sessions": 3, "idle_min": 60,
             "model": None,
             "net_hosts": ["api.anthropic.com"],
             "quiet_hosts": ["downloads.claude.ai", "raw.githubusercontent.com",
                             "datadoghq.com", "statsig.anthropic.com"],
             "daily_usd": None},
    # The console (Settings › Assistant): its keys and their defaults are ``term.console``'s
    # (``console.DEFAULTS``, read by ``console.settings``); empty here, so each has one
    # default.
    "ask": {},
    # Traces: a payload is shown page_kb at a time, and one span's payload is read whole up
    # to payload_max_mb (beyond it: open the file at its line). export: where ``kranto trace
    # export --otlp`` sends a trace when no URL is given (empty: nowhere) and whether it sends
    # the redacted content too.
    "trace": {"page_kb": 64, "payload_max_mb": 2,
              "export": {"otlp_url": None, "content": False}},
}


def kranto_loop_home() -> Path | None:
    """The loop home of this user's kranto install, if there is one: the kranto home
    (``$KRANTO_HOME``, else the one ``kranto up`` or ``kranto adopt`` recorded in
    ``~/.config/kranto/home``, or ``home.<unit>`` for another ``$KRANTO_UNIT``), then its
    config's ``brb.loop_home`` (the old key, still read), else its ``loop/`` folder. So the page
    on a Kranto install uses that install's folder, never a second, empty ``~/kranto-loop``."""
    found = os.environ.get(paths.KRANTO_HOME_ENV) or paths.read_pointer(Path.home())
    if not found:
        return None
    kranto = Path(found).expanduser()
    f = paths.Layout(kranto).config          # kranto.yaml, else an adopted home's kranto.yaml
    if f.is_file():
        try:
            brb = (yaml.safe_load(f.read_text()) or {}).get("brb") or {}
        except (OSError, yaml.YAMLError, AttributeError):
            brb = {}
        if isinstance(brb, dict) and brb.get("loop_home"):
            at = Path(str(brb["loop_home"])).expanduser()
            return at if at.is_absolute() else kranto / at
    default = paths.Layout(kranto).loop
    return default if default.is_dir() else None


def home(path: str | Path | None = None) -> Path:
    p = Path(path or os.environ.get(HOME_ENV) or kranto_loop_home()
             or paths.DEFAULT_LOOP_HOME).expanduser()
    return p.resolve()


_said: set = set()


def _say_once(f: Path, text: str) -> None:
    """Log a loop.yaml's problems once per version of the file (it is read on every request)."""
    try:
        key = (str(f), f.stat().st_mtime_ns, text)
    except OSError:
        key = (str(f), None, text)
    if key not in _said:
        _said.add(key)
        import logging
        logging.getLogger("kranto.page.settings").warning("%s", text)


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


_parsed: dict = {}          # loop.yaml by path: (its text, the settings with defaults, problems)


def _settings(f: Path) -> tuple[dict, list]:
    """``f`` parsed and checked once per text: the pages build a Config many times a request,
    and parsing the YAML was most of ``/api/kranto``; reading the file is cheap. The
    caller gets its own copy."""
    from .schema import check
    text = f.read_text() if f.exists() else None
    hit = _parsed.get(str(f))
    if hit is None or hit[0] != text:
        user = (yaml.safe_load(text) or {}) if text is not None else {}
        user = legacy.loop_settings(user)      # an old install's section name
        hit = (text, _merge(DEFAULTS, user), check(user))   # unknown keys, wrong values
        _parsed[str(f)] = hit
    return copy.deepcopy(hit[1]), list(hit[2])


class Config:
    """``cfg["term"]["idle_min"]``, plus the folder (``home``) and its ``layout``."""

    def __init__(self, root: str | Path | None = None, overrides: dict | None = None):
        self.home = home(root)
        self.layout = paths.LoopLayout(self.home)
        f = self.layout.settings
        data, self.problems = _settings(f)
        self.data = _merge(data, overrides or {}) if overrides else data
        from .schema import describe
        if self.problems:
            _say_once(f, describe(self.problems))
        if os.environ.get(KRANTO_URL_ENV):
            self.data["kranto"]["url"] = os.environ[KRANTO_URL_ENV]

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)
