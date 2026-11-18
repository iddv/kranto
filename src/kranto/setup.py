"""First-run setup: the model key, the two logins builds need, and
the few config values onboarding writes.

The key is kept like a connection's token: never in the YAML, the library, a log line or
a page. It is written to ``<workspace>/.env`` (mode 0600, the file ``config.load`` already
reads) under the variable ``llm.api_key_env`` names, and set in this process's
environment so the running server uses it at once. Responses say only whether a key is
set and whether the endpoint accepted it; error text is scrubbed of the key before it is
stored or returned.

The key is tested with one request that runs no completion: OpenRouter's ``GET /key``
(which needs a valid key), else the endpoint's ``GET /models`` with the key. The two
logins are ``claude auth status`` and ``gh auth status``; their output is read for a yes
or no and an account name, never shown whole (``gh`` prints a masked token).

The YAML is edited as text, one key in one top-level section at a time, so its comments
survive; the result is parsed and checked before it replaces the file.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from .store import Store, iso, utcnow
from .stored.settings import KeyTest as StoredKeyTest
from .stored.settings import get_blob, set_blob

DONE = "setup.done"
KEY_TEST = "setup.key_test"
BUILD_MODE = "setup.build_mode"
CONCURRENCY = "setup.concurrency"
BUILD_MODES = ("auto", "manual")
MAX_KEY_CHARS = 512
KEY_TEST_SECONDS = 15.0
log = logging.getLogger(__name__)

LOGIN_SECONDS = 15.0
LOGIN_CACHE_SECONDS = 30.0
# What a person runs when a login is missing (shown in a code block on the page).
LOGIN_COMMANDS = {"claude": "claude auth login", "gh": "gh auth login"}
_KEY_CHARS = re.compile(r"[\x21-\x7e]+")      # printable ASCII, no spaces: one .env line
# What Kranto costs, as Welcome's Ready step and `kranto setup`'s ready say it (
# measured on live: judge and screen, News and cards for one topic of about ten sources)
COST = "About $5 to $8 a month for one topic with ten sources, on your own model key."
# Claude Code's own installer (no Node needed: Kranto never asks for Node)
CONSOLE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"


# What it costs on a Claude Code login (fix 9: Ready said "on your own model
# key" to a subscriber): the plan's usage, never a bill; the first read's calls as the walk counted
COST_PLAN = ("Your Claude plan's usage, no bill. The first read is about 200 short model calls, "
             "shared with your own Claude Code.")


def cost_words(monthly_cap: float | None, provider: str | None = None) -> str:
    """The cost line with what is capped: "No cap is set; set one in Spend." or the cap. On the
    Claude Code login (``provider`` ``claude_code``): the plan's usage, no dollars."""
    if provider == "claude_code":
        return COST_PLAN
    if monthly_cap is None:
        return f"{COST} No cap is set; set one in Spend."
    return f"{COST} Watching stops for the month at your cap of ${monthly_cap:.2f} (Spend)."


class SetupError(ValueError):
    """A request onboarding cannot carry out; the message is safe to show."""


# -- the key ------------------------------------------------------------------------------

def check_key_shape(key: str) -> str:
    """The key as it will be stored, or SetupError. One line of printable ASCII, so it
    cannot add a second variable to ``.env``."""
    key = (key or "").strip()
    if not key:
        raise SetupError("paste the key")
    if len(key) > MAX_KEY_CHARS or not _KEY_CHARS.fullmatch(key):
        raise SetupError("that does not look like an API key: one line, no spaces")
    return key


def check_base_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise SetupError("the endpoint must be an http(s) URL, such as "
                         "https://openrouter.ai/api/v1")
    return url


def scrub_key(text: str, key: str) -> str:
    return text.replace(key, "[redacted]") if key and len(key) >= 4 else text


@dataclass(frozen=True)
class KeyTest:
    ok: bool
    detail: str


def try_key(base_url: str, key: str, *, transport: httpx.BaseTransport | None = None
             ) -> KeyTest:
    """One request with the key and no completion: does the endpoint accept it?"""
    host = (urlparse(base_url).hostname or "").lower()
    openrouter = host == "openrouter.ai" or host.endswith(".openrouter.ai")
    url = f"{base_url}/key" if openrouter else f"{base_url}/models"
    try:
        with httpx.Client(timeout=KEY_TEST_SECONDS, transport=transport) as client:
            r = client.get(url, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as exc:
        return KeyTest(False, scrub_key(f"could not reach {host}: {type(exc).__name__}", key))
    if r.status_code in (401, 403):
        return KeyTest(False, f"{host} refused the key (HTTP {r.status_code})")
    if r.status_code != 200:
        return KeyTest(False, f"{host} answered HTTP {r.status_code}")
    if openrouter:
        return KeyTest(True, "OpenRouter accepted the key")
    return KeyTest(True, f"{host} accepted the key")


def write_env_key(root: Path, name: str, key: str) -> Path:
    """Set ``name=key`` in ``<root>/.env``, keeping its other lines, as a 0600 file that is
    replaced in one step (never left half-written or readable by others)."""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        raise SetupError("llm.api_key_env is not a variable name")
    path = root / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    kept = [ln for ln in lines
            if ln.strip().removeprefix("export ").partition("=")[0].strip() != name]
    kept.append(f"{name}={key}")
    tmp = path.with_name(f".env.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("\n".join(kept) + "\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
    return path


def record_key_test(store: Store, result: KeyTest, base_url: str) -> dict[str, Any]:
    test = StoredKeyTest(ok=result.ok, detail=result.detail, base_url=base_url,
                         at=iso(utcnow()))
    set_blob(store, KEY_TEST, test)
    return test.to_dict(nulls=True)


def last_key_test(store: Store) -> dict[str, Any] | None:
    got = get_blob(store, KEY_TEST, StoredKeyTest)
    return got.to_dict(nulls=True) if got is not None else None


# -- the two logins builds need -------------------------------------------------------------

def _run(cmd: list[str]) -> tuple[int, str]:
    exe = shutil.which(cmd[0])
    if exe is None:
        return 127, ""
    try:
        p = subprocess.run([exe, *cmd[1:]], capture_output=True, text=True,
                           timeout=LOGIN_SECONDS, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return 124, ""
    return p.returncode, (p.stdout or "") + (p.stderr or "")


RUN: Callable[[list[str]], tuple[int, str]] = _run


def _claude(rc: int, out: str) -> dict[str, Any]:
    # installed: Welcome's Ready tells "not installed" from "not signed in"
    if rc == 127:
        return {"ok": False, "installed": False,
                "detail": "Claude Code is not installed (no claude on PATH)"}
    try:
        info = json.loads(out[out.index("{"):]) if "{" in out else {}
    except ValueError:
        info = {}
    if rc == 0 and info.get("loggedIn"):
        how = str(info.get("authMethod") or "").strip()
        return {"ok": True, "installed": True, "detail": "signed in" + (f" ({how})" if re.fullmatch(
            r"[\w.-]{1,40}", how) else "")}
    return {"ok": False, "installed": True, "detail": "not signed in"}


def connection() -> dict[str, Any] | None:
    """Kranto's own GitHub connection: gone with builds (CUT; it published repositories). gh's
    own login is what "File a Kranto issue" uses. Always None; kept for ``kranto.py``'s doctor
    until its own cut."""
    return None


def _gh(rc: int, out: str) -> dict[str, Any]:
    if rc == 127:
        return {"ok": False, "detail": "the GitHub CLI is not installed (no gh on PATH)"}
    m = re.search(r"Logged in to (\S+) account ([A-Za-z0-9-]{1,39})", out)
    if rc == 0 and m:
        return {"ok": True, "detail": f"signed in to {m.group(1)} as {m.group(2)}"}
    return {"ok": False, "detail": "not signed in" if rc != 124 else "gh did not answer"}


_logins: tuple[float, dict[str, Any], Callable[..., Any]] | None = None
_logins_lock = threading.Lock()
_busy: set[str] = set()
_busy_lock = threading.Lock()


def again(name: str, fn: Callable[[], object]) -> None:
    """Run ``fn`` once on a background thread, unless one for ``name`` is still running (SL:
    a page gets the last answer of a slow local check at once; this asks it again)."""
    with _busy_lock:
        if name in _busy:
            return
        _busy.add(name)

    def go() -> None:
        try:
            fn()
        except Exception:  # noqa: BLE001 - the next ask tries again
            log.debug("refreshing %s failed", name, exc_info=True)
        finally:
            with _busy_lock:
                _busy.discard(name)
    threading.Thread(target=go, daemon=True, name=f"kranto-{name}").start()


def _ask_logins() -> dict[str, Any]:
    global _logins
    run = RUN
    out = {"claude": _claude(*run(["claude", "auth", "status"])),
           "gh": _gh(*run(["gh", "auth", "status"]))}
    for name, row in out.items():
        row["command"] = LOGIN_COMMANDS[name]
    _logins = (time.monotonic(), out, run)
    return out


def warm() -> None:
    """Ask the slow local checks once in the background (``kranto serve`` at start), so the
    first page that shows them does not wait: the two logins and Claude Code's version."""
    from . import providers
    again("logins", _ask_logins)
    again("claude-code", providers.claude_code_kept)


def logins(*, fresh: bool = False) -> dict[str, Any]:
    """``{"claude": {ok, detail, command}, "gh": {...}}``. The last answer comes back at once
    and one older than ``LOGIN_CACHE_SECONDS`` is asked again in the background (the page
    polls, and ``claude auth status`` takes about half a second); the first ask, or with
    ``fresh`` (Check again), waits for it."""
    hit = _logins
    if not fresh and hit and hit[2] is RUN:
        if time.monotonic() - hit[0] >= LOGIN_CACHE_SECONDS:
            again("logins", _ask_logins)
        return hit[1]
    with _logins_lock:
        return _ask_logins()


# -- the YAML, edited as text --------------------------------------------------------------

def _scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return repr(value)
    if isinstance(value, list | dict):
        return json.dumps(value)        # a flow sequence or mapping: JSON is YAML
    return json.dumps(str(value))       # a double-quoted YAML scalar


def set_yaml_value(text: str, section: str, key: str, value: Any) -> str:
    """``text`` with ``section.key`` set to ``value``: the key's line replaced, or added at
    the end of the section, or the section added at the end. Comments and every other
    line stay as they were."""
    if not (re.fullmatch(r"[a-z_]+", section) and re.fullmatch(r"[a-z0-9_]+", key)):
        raise SetupError("not a config key")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    head = re.compile(rf"^{section}:\s*(\{{\s*\}})?\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if head.match(ln.rstrip("\n"))), None)
    entry = f"  {key}: {_scalar(value)}\n"
    if start is None:
        return "".join(lines) + ("\n" if lines else "") + f"{section}:\n" + entry
    lines[start] = f"{section}:\n"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    mine = re.compile(rf"^  {key}:(\s|$)")
    for i in range(start + 1, end):
        if mine.match(lines[i]):
            # the old value's own lines go with it: a block list or mapping written by hand or by
            # a YAML dumper ("  widgets:" then "  - id: greeting" / "    size: L")
            last_own = i
            for j in range(i + 1, end):
                if lines[j].startswith(("   ", "  - ", "  -\n", "\t")):
                    last_own = j
                elif lines[j].strip():
                    break
            lines[i:last_own + 1] = [entry]
            return "".join(lines)
    last = start
    for i in range(start + 1, end):
        if lines[i].startswith(("  ", "\t")) and lines[i].strip() and \
                not lines[i].lstrip().startswith("#"):
            last = i
    lines.insert(last + 1, entry)
    return "".join(lines)


def set_yaml_nested(text: str, section: str, sub: str, key: str, value: Any) -> str:
    """``text`` with ``section.sub.key`` set (a mapping inside a top-level section, such as
    ``llm.models.judge``): the key's value replaced with its line's comment kept, or the key
    added to ``sub``, or ``sub`` added to the section. A flow-style ``sub: {}`` becomes a
    block. Every other line stays as it was."""
    if not all(re.fullmatch(r"[a-z0-9_]+", k) for k in (section, sub, key)):
        raise SetupError("not a config key")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    head = re.compile(rf"^{section}:\s*(#.*)?$")
    start = next((i for i, ln in enumerate(lines) if head.match(ln.rstrip("\n"))), None)
    if start is None:
        return "".join(lines) + ("\n" if lines else "") + \
            f"{section}:\n  {sub}:\n    {key}: {_scalar(value)}\n"
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].strip() and not lines[i].startswith((" ", "\t", "#"))), len(lines))
    sub_re = re.compile(rf"^  {sub}:\s*(\{{\s*\}})?\s*(#.*)?$")
    at = next((i for i in range(start + 1, end) if sub_re.match(lines[i].rstrip("\n"))), None)
    entry = f"    {key}: {_scalar(value)}\n"
    if at is None:
        last = start
        for i in range(start + 1, end):
            if lines[i].strip() and not lines[i].lstrip().startswith("#"):
                last = i
        lines[last + 1:last + 1] = [f"  {sub}:\n", entry]
        return "".join(lines)
    m = sub_re.match(lines[at].rstrip("\n"))
    assert m is not None                      # ``at`` is the line the pattern found
    if m.group(1):          # sub: {} -> a block
        lines[at] = f"  {sub}:" + (f"  {m.group(2)}" if m.group(2) else "") + "\n"
    sub_end = next((i for i in range(at + 1, end) if lines[i].strip()
                    and not lines[i].lstrip().startswith("#")
                    and len(lines[i]) - len(lines[i].lstrip(" ")) <= 2), end)
    mine = re.compile(rf"^    {key}:[ \t]*(?:[^#\n]*?)([ \t]+#.*)?$")
    for i in range(at + 1, sub_end):
        hit = mine.match(lines[i].rstrip("\n"))
        if hit:
            lines[i] = entry.rstrip("\n") + (hit.group(1) or "") + "\n"
            return "".join(lines)
    last = at
    for i in range(at + 1, sub_end):
        if lines[i].startswith("    ") and lines[i].strip() and \
                not lines[i].lstrip().startswith("#"):
            last = i
    lines.insert(last + 1, entry)
    return "".join(lines)


def write_config_values(path: Path, values: dict[tuple[str, ...], object]) -> None:
    """Set each ``(section, key)`` or ``(section, sub, key)`` in the YAML at ``path``,
    check the result parses to the values asked for, then replace the file in one step."""
    text = path.read_text(encoding="utf-8")
    for keys, value in values.items():
        if len(keys) == 2:
            text = set_yaml_value(text, keys[0], keys[1], value)
        else:
            text = set_yaml_nested(text, keys[0], keys[1], keys[2], value)
    parsed = yaml.safe_load(text) or {}
    for keys, value in values.items():
        node = parsed
        for k in keys[:-1]:
            node = (node or {}).get(k) if isinstance(node, dict) else None
        if not isinstance(node, dict) or keys[-1] not in node or node[keys[-1]] != value:
            raise SetupError(f"could not set {'.'.join(keys)} in {path.name}")
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        os.chmod(tmp, path.stat().st_mode & 0o777)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


# -- the state the page reads -----------------------------------------------------------

def is_done(store: Store) -> bool:
    return bool(store.get_setting(DONE))


def build_choice(store: Store) -> dict[str, Any]:
    """The onboarding answer kept from before builds left Kranto (``setup.build_mode``,
    ``setup.concurrency``): read for a page that still shows it, never written to the loop."""
    mode = store.get_setting(BUILD_MODE)
    try:
        concurrency = int(store.get_setting(CONCURRENCY) or 1)
    except ValueError:
        concurrency = 1
    return {"mode": mode if mode in BUILD_MODES else None, "concurrency": concurrency}


def mark_done(store: Store, mode: str, concurrency: int) -> str:
    if mode not in BUILD_MODES:
        raise SetupError("building must be auto or manual")
    if isinstance(concurrency, bool) or not isinstance(concurrency, int) or \
            not 1 <= concurrency <= 8:
        raise SetupError("builds at once must be a whole number from 1 to 8")
    store.set_setting(BUILD_MODE, mode)
    store.set_setting(CONCURRENCY, str(concurrency))
    at = iso(utcnow())
    store.set_setting(DONE, at)
    return at
