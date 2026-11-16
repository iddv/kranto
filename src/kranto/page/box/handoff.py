"""How every ``claude`` Kranto starts gets its Claude login (TS.REVIEW R1, for builds, fixes,
repairs, chat, the no-tools prompts and Open in Claude Code alike): through a pipe, never in an
environment or on a command line.

The token Kranto was started with (``CLAUDE_CODE_OAUTH_TOKEN`` from ``claude setup-token``, or
``ANTHROPIC_API_KEY``) is written into a pipe whose read end the process inherits;
``CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR`` or ``CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR`` names it
(both read by the CLI since at least 2.1.300; measured with a fake API: the bearer header, or
``x-api-key``, carries the token). claude reads the pipe once at start, so a tool command that
looks at ``env``, ``/proc/*/environ`` or the descriptor later finds nothing. Every other variable
that could carry a login (``LOGIN_VARS``) is dropped from the process's environment, and the
shell prefix (``box/kranto-shell``) drops them again for each tool command.

``ANTHROPIC_AUTH_TOKEN`` (a gateway's bearer) is not handed over: no launch passes it any more.

Without a token in Kranto's environment nothing is piped; claude then logs in from the
credentials file in its config dir (``profile.clean_config`` copies the owner's), which a build's
shell can read: ``kranto doctor``'s ``claude token`` line says so.

Whose token it is (``credential``, TK, from #213): a ``CLAUDE_CODE_OAUTH_TOKEN`` is the owner's
Claude login; an ``ANTHROPIC_API_KEY`` the process was started with (the unit's ``Environment=``
or ``EnvironmentFile=``, or the shell that ran Kranto) is a key the owner gave Kranto; one that only
Kranto's ``.env`` gave it (the server's ``config.load`` adds those lines with ``setdefault``, after the
start, so they are not in ``/proc/self/environ``) is the watcher's key, saved by Settings ›
Watching. Open in Claude Code does not log in with the watcher's key unless the owner chose it
(``term.allow_api_key``).

One policy for every launch (BL, the owner's decision of 2026-10-18: "Builds should use Claude
Code and the subscription"): ``choose`` picks the token each ``claude`` gets, and ``source`` (so
``piped``, which every launch goes through) hands over only that one:

1. the Claude login token Kranto keeps itself (``claude_login``: ``kranto setup building``,
   Settings › Building › Builds run on);
2. a token the process was started with (the unit's ``CLAUDE_CODE_OAUTH_TOKEN``, or an
   ``ANTHROPIC_API_KEY`` the unit gives it: deliberate, so it keeps working);
3. the watcher's API key (``.env``) only with ``build.allow_api_key`` (default false).

Without any of them nothing is piped and claude logs in from Claude Code's own sign-in (also
the person's plan). The names Kranto's ``.env`` added are kept in
``$KRANTO_DOTENV_VARS`` (the server's ``load_dotenv``, else ``mark_dotenv``), so a process Kranto
starts (a build, a fix) still tells the watcher's key from one the unit gave."""
from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path

TOKEN_ENV = {"CLAUDE_CODE_OAUTH_TOKEN": "CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR",
             "ANTHROPIC_API_KEY": "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR"}
TOKEN_FD_ENV = tuple(TOKEN_ENV.values())
# Keys of the watcher's own providers that no process Kranto starts has a use for: the xAI key
# (the server's X search, 5.1) and the live search backends' (4.4: searches go
# through Kranto's own API and its kranto_search tool, so a key never leaves Kranto's process) are
# dropped with the logins.
WATCHER_KEYS = ("XAI_API_KEY", "EXA_API_KEY", "BRAVE_API_KEY", "TAVILY_API_KEY")
LOGIN_VARS = (*TOKEN_ENV, *TOKEN_FD_ENV, "ANTHROPIC_AUTH_TOKEN",
              "CLAUDE_CODE_GATEWAY_TOKEN_FILE_DESCRIPTOR",
              "CLAUDE_CODE_WEBSOCKET_AUTH_FILE_DESCRIPTOR", *WATCHER_KEYS)


DOTENV_ENV = "KRANTO_DOTENV_VARS"     # the names Kranto's .env added (names only, comma-separated)


def _env_token(environ=None) -> tuple[str, str] | None:
    environ = os.environ if environ is None else environ
    for k in TOKEN_ENV:
        v = (environ.get(k) or "").strip()
        if v:
            return k, v
    return None


def _stored(environ=None) -> str | None:
    """The Claude login token Kranto keeps (``claude_login``), or None."""
    from .. import claude_login
    try:
        return claude_login.Store(env=os.environ if environ is None else environ).token()
    except OSError:
        return None


def found(environ=None) -> tuple[str, str] | None:
    """``(variable, value)`` of a Claude token Kranto has, whoever's it is: the one it keeps,
    else one in its environment. No policy: what a launch gets is ``source``."""
    kept = _stored(environ)
    if kept:
        return "CLAUDE_CODE_OAUTH_TOKEN", kept
    return _env_token(environ)


def source(environ=None) -> tuple[str, str] | None:
    """``(variable, value)`` of the Claude token a launch gets (``choose``), or None."""
    cred = choose(environ)[0]
    return (cred.var, cred.value) if cred is not None else None


def started_names() -> frozenset[str] | None:
    """The variable names this process was started with (``/proc/self/environ``), without any
    value; None where ``/proc`` cannot say."""
    try:
        raw = Path("/proc/self/environ").read_bytes()
    except OSError:
        return None
    return frozenset(e.partition(b"=")[0].decode(errors="replace") for e in raw.split(b"\0") if e)


@dataclass(frozen=True)
class Credential:
    """The Claude token ``source`` found, and whose it is (never printed: ``value`` is kept out
    of the repr)."""
    var: str
    value: str = field(repr=False)
    watchers: bool = False                       # an API key only Kranto's .env gave the process
    stored: bool = False                         # the login token Kranto keeps (claude_login)

    @property
    def kind(self) -> str:
        return "login" if self.var == "CLAUDE_CODE_OAUTH_TOKEN" else "api_key"

    @property
    def words(self) -> str:
        """The doctor's and the page's name for it."""
        if self.kind == "login":
            return "Claude login token"
        return "Claude API key (the watcher's)" if self.watchers else "Claude API key"

    @property
    def on(self) -> str:
        """What builds run on, for Settings › Building and the status lines."""
        if self.kind == "login":
            return "your Claude plan (login token)"
        return ("your Claude API key (opted in)" if self.watchers
                else "your Claude API key (the unit's)")


def credential(environ=None, started=None) -> Credential | None:
    """``source``'s token as a ``Credential``. ``started``: the names the process was started
    with (default: ``started_names()`` for Kranto's own environment, every name of an ``environ``
    passed in); an API key not among them came from Kranto's ``.env``, the watcher's. Where
    ``/proc`` cannot say, an API key counts as the watcher's (Open asks before using it). So
    does one ``$KRANTO_DOTENV_VARS`` names: a process Kranto starts inherits the key, and the
    name with it. The token in Kranto's environment only: ``choose`` adds the one Kranto keeps."""
    env = os.environ if environ is None else environ
    tok = _env_token(env)
    if tok is None:
        return None
    if started is None:
        started = started_names() if environ is None or environ is os.environ else set(environ)
    dotenv = {n.strip() for n in (env.get(DOTENV_ENV) or "").split(",") if n.strip()}
    watchers = tok[0] != "CLAUDE_CODE_OAUTH_TOKEN" and (
        started is None or tok[0] not in started or tok[0] in dotenv)
    return Credential(tok[0], tok[1], watchers)


def mark_dotenv(environ=None, started=None) -> None:
    """Name in ``$KRANTO_DOTENV_VARS`` the token variables this process has but was not started
    with (Kranto's ``.env``'s), so a process it starts inherits the knowledge. The server's
    ``load_dotenv`` does it as it loads them; this covers an older one. Names only."""
    env = os.environ if environ is None else environ
    started = started_names() if started is None else started
    if started is None:
        return
    have = {n for n in (env.get(DOTENV_ENV) or "").split(",") if n}
    add = {k for k in TOKEN_ENV if env.get(k) and k not in started} - have
    if add:
        env[DOTENV_ENV] = ",".join(sorted(have | add))


def _loop_settings() -> dict:
    """Kranto's own ``loop.yaml``, found as ``settings.store.home`` finds the loop home
    (``$KRANTO_LOOP_HOME``, else the kranto install's ``brb.loop_home`` or its ``loop/``, else
    ``~/kranto-loop``): copied here, as box/ reads no settings module. Only the owner's values,
    no defaults (``build.allow_api_key``'s default is false)."""
    import yaml

    from .. import paths

    def load(f: Path) -> dict:
        data = yaml.safe_load(f.read_text()) if f.is_file() else None
        return data if isinstance(data, dict) else {}

    root = os.environ.get(paths.LOOP_HOME_ENV)
    if not root:
        found = os.environ.get(paths.KRANTO_HOME_ENV) or paths.read_pointer(Path.home())
        if found:
            kranto = Path(found).expanduser()
            brb = load(paths.Layout(kranto).config).get("brb") or {}
            if isinstance(brb, dict) and brb.get("loop_home"):
                at = Path(str(brb["loop_home"])).expanduser()
                root = at if at.is_absolute() else kranto / at
            elif paths.Layout(kranto).loop.is_dir():
                root = paths.Layout(kranto).loop
    root = Path(root or paths.DEFAULT_LOOP_HOME).expanduser().resolve()
    return load(paths.LoopLayout(root).settings)


def api_key_allowed(cfg=None) -> bool:
    """``build.allow_api_key``: the owner chose to let Claude Code bill the watcher's API key
    when there is no Claude login token. ``cfg``: the loop's settings (default: Kranto's own
    ``loop.yaml``, ``_loop_settings``); settings that cannot be read: no."""
    try:
        if cfg is None:
            cfg = _loop_settings()
        return bool((cfg.get("build") or {}).get("allow_api_key"))
    except Exception:                                # noqa: BLE001 - no choice read: no key
        return False


def choose(environ=None, started=None, allow: bool | None = None
           ) -> tuple[Credential | None, Credential | None]:
    """``(usable, held)``: the credential a launch gets, and the one it may not use without the
    owner's choice (the watcher's API key while ``build.allow_api_key`` is off; ``allow``
    overrides the setting). The login token Kranto keeps comes first, then Kranto's environment
    (``credential``). Both None: no Claude token at all."""
    kept = _stored(environ)
    if kept:
        return Credential("CLAUDE_CODE_OAUTH_TOKEN", kept, stored=True), None
    cred = credential(environ, started)
    if cred is not None and cred.watchers and not (api_key_allowed() if allow is None
                                                   else allow):
        return None, cred
    return cred, None


def scrub(env: dict) -> dict:
    """``env`` without any login variable (changed in place, and returned)."""
    for k in LOGIN_VARS:
        env.pop(k, None)
    return env


def pipe(value: str) -> int:
    """The read end of a pipe that holds ``value`` and is closed for writing."""
    r, w = os.pipe()
    try:
        os.write(w, value.encode())
    finally:
        os.close(w)
    return r


@contextlib.contextmanager
def piped(env: dict, environ=None):
    """For one process: ``env`` (its environment, changed in place) loses every login variable
    and, when ``environ`` (default: Kranto's own) holds a token, names the pipe that carries it.
    Yields the descriptors to pass (``pass_fds``; empty without a token), closed afterwards.
    A pipe is read once: every start (a retry too) needs its own ``piped``."""
    scrub(env)
    tok = source(environ)
    if tok is None:
        yield ()
        return
    r = pipe(tok[1])
    env[TOKEN_ENV[tok[0]]] = str(r)
    try:
        yield (r,)
    finally:
        os.close(r)


def process_env(extra: dict | None = None, environ=None) -> dict:
    """Kranto's environment for an unsandboxed ``claude`` (the no-tools prompts), with ``extra`` on top and no login variable; ``piped`` adds the pipe."""
    env = dict(os.environ if environ is None else environ)
    env.update(extra or {})
    return scrub(env)
