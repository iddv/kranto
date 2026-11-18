from __future__ import annotations

import json
import os
import shutil
import socket
import sys
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

# The page's tests are their own suite (tests/page/pytest.ini, its own conftest): `pytest tests`
# runs the server's, `pytest tests/page` the page's.
collect_ignore = ["page"]

# Hypothesis's per-example deadline (200 ms) is a timing assertion: on a loaded machine or two
# workers it fails a test that is right. No test here is about speed; each that needs a limit
# says so itself.
from hypothesis import settings as _hypothesis  # noqa: E402

_hypothesis.register_profile("kranto", deadline=None)
_hypothesis.load_profile("kranto")

# -- Isolation, before any Kranto import ------------------------------------------------------
# No test may open the developer's kranto home, loop home, token store, gh login or a model:
# HOME is a temp dir for the session (each xdist worker has its own), the network is loopback
# only, and `claude` and `gh` on PATH are stand-ins that fail loudly.
_REAL_HOME = Path.home()
os.environ.setdefault("UV_CACHE_DIR", str(_REAL_HOME / ".cache" / "uv"))
os.environ.setdefault("KRANTO_VENV_ROOT", str(_REAL_HOME / ".cache" / "kranto" / "venvs"))
# a variable under its name from before the rename (which importing kranto adopted) never
# reaches a test
from kranto import legacy as _legacy  # noqa: E402

_legacy.forget_env()
TEST_HOME = Path(tempfile.mkdtemp(prefix="kranto-home-")).resolve()
os.environ["HOME"] = str(TEST_HOME)
os.environ["KRANTO_LOOP_HOME"] = str(TEST_HOME / "kranto-loop")
os.environ["GH_CONFIG_DIR"] = str(TEST_HOME / ".config" / "gh")
for _k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "KRANTO_HOME", "KRANTO_UNIT",
           "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "ANTHROPIC_API_KEY",
           "CLAUDE_CODE_OAUTH_TOKEN", "OPENROUTER_API_KEY", "KRANTO_GITHUB_DIR",
           "KRANTO_GITHUB_CLIENT_ID", "KRANTO_GITHUB_API", "KRANTO_GITHUB_WEB", "EXA_API_KEY"):
    os.environ.pop(_k, None)
SHIMS = Path(__file__).resolve().parent / "_shims"
os.environ["PATH"] = f"{SHIMS}{os.pathsep}{os.environ.get('PATH', '')}"

_LOOPBACK = {"localhost", "", "0.0.0.0", "::", "::1", "testserver"}


def _loopback(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode(errors="replace")
    h = str(host).strip("[]").lower()
    return h in _LOOPBACK or h.startswith("127.") or h.endswith(".localhost")


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _guard(sock, address):
    if sock.family == getattr(socket, "AF_UNIX", None):
        return
    host = address[0] if isinstance(address, tuple) else address
    if not _loopback(host):
        raise OSError(101, f"tests never touch the network: connect to {host!r} refused "
                           "(tests/conftest.py)")


def _connect(self, address):
    _guard(self, address)
    return _real_connect(self, address)


def _connect_ex(self, address):
    _guard(self, address)
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if host is not None and not _loopback(host):
        raise socket.gaierror(socket.EAI_NONAME,
                              f"tests never touch the network: lookup of {host!r} refused "
                              "(tests/conftest.py)")
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo

import httpx  # noqa: E402
import pytest  # noqa: E402
import time_machine  # noqa: E402

from kranto.config import BudgetConfig, LLMConfig, ModelPrice  # noqa: E402
from kranto.embed import StubEmbedder  # noqa: E402
from kranto.llm import LLMClient  # noqa: E402
from kranto.store import Store  # noqa: E402


def pytest_sessionfinish(session, exitstatus):
    """The session's HOME was the temp dir throughout: nothing reached the developer's."""
    if Path.home().resolve() != TEST_HOME:
        print(f"\nERROR: a test left HOME at {Path.home()} (expected {TEST_HOME}); tests "
              "change HOME only through monkeypatch", file=sys.stderr)
        session.exitstatus = 1
        return
    shutil.rmtree(TEST_HOME, ignore_errors=True)

FIXED_NOW = datetime(2026, 9, 24, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _environment_restored():
    """A test, or the code it runs (``kranto serve`` sets ``KRANTO_HOME``), never leaves the
    process environment changed for the next test."""
    saved = dict(os.environ)
    yield
    if os.environ != saved:
        os.environ.clear()
        os.environ.update(saved)


def reports_threads_left(before: set, wait_s: float = 1.0) -> list:
    """The error reports' flusher threads started since ``before`` that are still running after
    ``wait_s`` (a stopped one ends at once)."""
    import threading

    left = [t for t in threading.enumerate()
            if t.name == "kranto-error-reports" and t not in before]
    for t in left:
        t.join(timeout=wait_s)
    return [t for t in left if t.is_alive()]


@pytest.fixture(autouse=True)
def _no_reports_thread_left():
    """A test that starts the error reports' flusher (``server_jobs``, ``errors.start``) stops it:
    one left running flushes another test's home every tick (the telemetry tests'
    flake). Fails the test that left it, after stopping it."""
    import threading

    from kranto.telemetry import assistant, errors

    before = {t for t in threading.enumerate() if t.name == "kranto-error-reports"}
    yield
    fl = errors._flusher
    left = reports_threads_left(before)
    if isinstance(fl, errors.Flusher) and fl._thread in left:
        fl.stop()
        errors._flusher = None
        assistant._server_home = None
    assert not left, "a test left the error reports' flusher running: stop it (fl.stop())"


@pytest.fixture(autouse=True)
def _loaded_cubs_restored():
    """The cubs a test's runtime loaded (``cubs.registry.set_loaded``) are the registry's for
    every later test in the same process otherwise: the next ``registry.check()`` then validates
    a cub that test made. Each test starts and ends with the list it found."""
    from kranto.core.cubs import registry as cubs_registry

    saved = cubs_registry.loaded()
    yield
    cubs_registry.set_loaded(saved)


@pytest.fixture(autouse=True)
def _fixed_clock():
    """Fixtures carry dates near FIXED_NOW; code under test reads the real clock.
    Time still ticks, so durations measured inside a test advance."""
    with time_machine.travel(FIXED_NOW, tick=True):
        yield


@pytest.fixture(autouse=True)
def _shipped_prompts(monkeypatch):
    """The owner's prompt store (``prompts.configure``, set by ``open_runtime``) never
    carries from one test to the next, and the developer's flags never reach a test."""
    from kranto import prompts

    monkeypatch.delenv("KRANTO_PROMPTS", raising=False)
    prompts.configure(None)
    yield
    prompts.configure(None)


@pytest.fixture(autouse=True)
def _builds_switch_restored():
    """``builds.enabled``'s process-wide effects (``open_runtime``: the held topic kinds and
    whether the loop's actions are verbs) never carry from one test to the next. Between
    tests: nothing held, and builds as the default, off."""
    from kranto import assistant, library
    from kranto.core import verbs

    library.configure(held_kinds=())
    verbs.configure(builds=False, rt=None)
    assistant.configure(off_features=())
    yield
    library.configure(held_kinds=())
    verbs.configure(builds=False, rt=None)
    assistant.configure(off_features=())


@pytest.fixture(autouse=True)
def _token_dir(monkeypatch, tmp_path_factory):
    """Each test has its own token store (OI): never the developer's ~/.config/kranto."""
    monkeypatch.setenv("KRANTO_TOKENS_DIR", str(tmp_path_factory.mktemp("tokens")))
    monkeypatch.delenv("KRANTO_UNIT", raising=False)
    # a broker's sign-in (core.brokers.mcp): its own ~/.config/kranto per test, and never a
    # broker's real server
    monkeypatch.setenv("KRANTO_BROKER_HOME", str(tmp_path_factory.mktemp("kranto-config")))
    monkeypatch.delenv("KRANTO_BROKER_MCP_URL", raising=False)


@pytest.fixture(autouse=True)
def _not_inside_an_assistant(monkeypatch):
    """A developer running the tests from inside Claude Code or Kranto's console is not an
    assistant's session for the code under test (``kranto telemetry basic`` refuses there)."""
    for k in ("CLAUDECODE", "KRANTO_MCP_CONSOLE"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _no_notify_targets(monkeypatch):
    """Delivery targets from the developer's environment must never reach a test."""
    monkeypatch.delenv("KRANTO_NOTIFY_URLS", raising=False)


@pytest.fixture(autouse=True)
def _no_memory_scope(monkeypatch):
    """A command under test never runs itself again inside a systemd scope (memory.py)."""
    monkeypatch.setenv("KRANTO_NO_SCOPE", "1")


@pytest.fixture
def store() -> Store:
    s = Store.memory()
    yield s
    s.close()


@pytest.fixture
def embedder() -> StubEmbedder:
    return StubEmbedder()


def old_grade(store: Store, target: str, target_id, value: str, *, at: datetime | None = None,
              reasons: list[str] | None = None, origin: str = "ui",
              context: dict | None = None) -> int:
    """A grade row as an older Kranto wrote it (a build's, a source's, a theme's, a message's, or
    a ``wrong``/``missed``): ``feedback`` keeps such rows as history and its readers still read
    them, but the writer refuses new ones. Encoded as ``feedback.validate``
    encodes a row."""
    from kranto.store import iso, utcnow
    from kranto.stored.misc import FeedbackReasons

    return store.insert("feedback", {
        "target": target, "target_id": str(target_id), "kind": "grade", "value": value,
        "reasons": FeedbackReasons.write(reasons or []), "pair": None, "note": None,
        "origin": origin, "context": json.dumps(context or {}, sort_keys=True),
        "created_at": iso(at or utcnow())})


def llm_config(**overrides) -> LLMConfig:
    base = dict(
        base_url="https://llm.test/v1",
        api_key_env="TEST_KEY",
        cost_source="provider",
        models={"judge": "judge-model", "reason": "reason-model"},
        pricing={},
        timeout_seconds=5,
        max_retries=3,
    )
    base.update(overrides)
    return LLMConfig(**base)


def chat_response(text: str | None, *, cost: float | None = 0.001, prompt=100, completion=20,
                  finish_reason: str | None = None):
    usage = {"prompt_tokens": prompt, "completion_tokens": completion}
    if cost is not None:
        usage["cost"] = cost
    choice = {"message": {"content": text}}
    if finish_reason is not None:
        choice["finish_reason"] = finish_reason
    return httpx.Response(
        200, json={"model": "judge-model", "choices": [choice], "usage": usage},
    )


class FakeLLM:
    """An httpx transport that answers chat completions from a handler.

    The handler receives the parsed request body and returns an httpx.Response.
    Every request is kept in ``requests`` for assertions.
    """

    def __init__(self, handler: Callable[[dict], httpx.Response]):
        self.handler = handler
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        return self.handler(body)


@pytest.fixture
def make_client(store):
    clients = []

    def _make(handler, *, budget=10.0, api_key="k", sleeps=None, **config_overrides):
        fake = FakeLLM(handler)
        client = LLMClient(
            store,
            llm_config(**config_overrides),
            BudgetConfig(monthly_usd=budget),
            api_key=api_key,
            transport=httpx.MockTransport(fake),
            sleep=(sleeps.append if sleeps is not None else lambda s: None),
            clock=lambda: FIXED_NOW,
        )
        client.fake = fake
        clients.append(client)
        return client

    yield _make
    for c in clients:
        c.close()


__all__ = ["FIXED_NOW", "ModelPrice", "chat_response", "llm_config"]


def web_client(app, base_url: str = "http://127.0.0.1", signed_in: bool = True):
    """A test client that behaves like a browser on the UI's own pages: POSTs
    carry an Origin header, which the server requires, and the browser is
    signed in (OI): it has the session cookie, read from the test's token store."""
    from starlette.testclient import TestClient

    client = TestClient(app, base_url=base_url, headers={"origin": base_url})
    return sign_in(client, app) if signed_in else client


def sign_in(client, app):
    """Give a test client the browser's session cookie (as /auth/open does)."""
    auth = app.state.app.auth
    client.cookies.set(auth.cookie, auth.store.value("ui"))
    return client


# -- look before judging ---------------------------------------------------------

SCREEN_PASS = json.dumps({"pass": True, "reason": "potentially on topic"})
SCREEN_DROP = json.dumps({"pass": False, "reason": "spam: an advert"})


def is_screen(body: dict) -> bool:
    """Whether a recorded chat request is the screen's rather than the judge's."""
    return "This is a first, quick look at ONE item" in body["messages"][0]["content"]


def judge_requests(client) -> list[dict]:
    """The judge's requests among everything a FakeLLM-backed client sent."""
    return [r for r in client.fake.requests if not is_screen(r)]


def screen_requests(client) -> list[dict]:
    return [r for r in client.fake.requests if is_screen(r)]


@pytest.fixture(autouse=True)
def no_reddit_pacing(monkeypatch):
    """Reddit requests are paced a minute apart in production; tests do not wait."""
    from kranto.sources import reddit

    monkeypatch.setattr(reddit, "PACER", reddit._Pacer(0.0))


@pytest.fixture(autouse=True)
def no_host_pacing(monkeypatch):
    """Per-host gaps and backoff (sources.pacing) never sleep in tests: a fresh state per
    test, with no gap and a sleep that records instead of waiting (``HOSTS.slept``)."""
    from kranto.sources import pacing

    hosts = pacing.Hosts(default_gap=0.0, gaps={"export.arxiv.org": 0.0})
    hosts.slept = []
    hosts.sleep = hosts.slept.append
    hosts.configure = lambda cfg: None   # a config's gaps would only make tests record sleeps
    monkeypatch.setattr(pacing, "HOSTS", hosts)
    yield hosts
