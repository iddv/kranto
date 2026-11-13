import json
import os
import shutil
import socket
import sys
import tempfile
from pathlib import Path

import pytest

# -- Isolation, before any the page import ----------------------------------------------------
# No test may open the developer's live loop home (~/kranto-loop), kranto home, token store, gh login
# or a model: HOME is a temp dir for the whole session (each xdist worker has its own), the
# uv cache stays on the real one (it only holds wheels), the network is loopback only,
# and `claude` and `gh` on PATH are stand-ins that fail loudly.
_REAL_HOME = Path.home()
os.environ.setdefault("UV_CACHE_DIR", str(_REAL_HOME / ".cache" / "uv"))
TEST_HOME = Path(tempfile.mkdtemp(prefix="kranto-home-")).resolve()
os.environ["HOME"] = str(TEST_HOME)
os.environ["KRANTO_LOOP_HOME"] = str(TEST_HOME / "kranto-loop")
for _k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "KRANTO_HOME", "KRANTO_UNIT",
           "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "KRANTO_DOTENV_VARS",
           "KRANTO_CLAUDE_DIR"):
    os.environ.pop(_k, None)
# a variable under its name from before the rename never reaches a test
from kranto import legacy as _legacy  # noqa: E402

_legacy.forget_env()
SHIMS = Path(__file__).resolve().parent / "_shims"
os.environ["PATH"] = f"{SHIMS}{os.pathsep}{os.environ.get('PATH', '')}"

_LOOPBACK = {"localhost", "", "0.0.0.0", "::", "::1"}


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
                           "(tests/page/conftest.py)")


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
                              "(tests/page/conftest.py)")
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo

ROOT = Path(__file__).resolve().parents[2]
# The token store (OI) is never the developer's ~/.config/kranto: one per test session.
os.environ["KRANTO_TOKENS_DIR"] = tempfile.mkdtemp(prefix="kranto-tokens-")
# Without bubblewrap (CI's runner has none) the suite's own fixtures still run, as before;
# tests of the refusal unset it.
os.environ.setdefault("KRANTO_ALLOW_UNSANDBOXED", "1")
# No test acts on GitHub as the developer: a real `gh` reached by mistake (an app whose loop
# home has no loop.yaml uses the default gh) finds no login and no token, and fails.
os.environ["GH_CONFIG_DIR"] = tempfile.mkdtemp(prefix="kranto-gh-")
for _k in ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN"):
    os.environ.pop(_k, None)


@pytest.fixture(autouse=True)
def _own_claude_store(tmp_path_factory, monkeypatch):
    """Each test has its own store for the Claude login token Kranto keeps (BL): none unless a
    test keeps one; the names a test's .env added are that test's."""
    monkeypatch.setenv("KRANTO_CLAUDE_DIR", str(tmp_path_factory.mktemp("claude")))
    monkeypatch.delenv("KRANTO_DOTENV_VARS", raising=False)


@pytest.fixture(scope="session")
def _standin_build(tmp_path_factory):
    """A build with an empty module: what the page links when no real build is there."""
    from kranto.page.ui.routes import static
    d = tmp_path_factory.mktemp("app")
    (d / ".vite").mkdir()
    (d / "app-standin.js").write_text("export {};\n")
    (d / ".vite" / "manifest.json").write_text(json.dumps({static.ENTRY: {
        "file": "app-standin.js", "isEntry": True, "src": static.ENTRY}}))
    return d


@pytest.fixture(autouse=True)
def _a_built_page(_standin_build, monkeypatch):
    """The page is the built UI, and without a build "/" answers one line saying how to
    get one. The fast and slow lanes build nothing, so where there is no real build the tests
    see a stand-in (a manifest and an empty module) and "/" is the page a build serves. A real
    build (CI's browser job) is used as it is; a test of the notice points APP_DIR elsewhere."""
    from kranto.page.ui.routes import static
    if not (static.APP_DIR / ".vite" / "manifest.json").is_file():
        monkeypatch.setattr(static, "APP_DIR", _standin_build)


# -- The lanes --------------------------------------------------------------------------------
# CI runs `-m "not slow"` and `-m slow` as two jobs side by side. Slow: every test that took 5 s
# or more in tests/page/.test_durations (regenerate it with `pytest tests/page --store-durations
# --durations-path tests/page/.test_durations -n 8`, pytest-split's
# file).
SLOW_S = 5.0
DURATIONS = Path(__file__).resolve().parent / ".test_durations"


def pytest_collection_modifyitems(config, items):
    try:
        took = json.loads(DURATIONS.read_text())
    except (OSError, ValueError):
        took = {}
    for item in items:
        if took.get(item.nodeid, 0) >= SLOW_S:
            item.add_marker(pytest.mark.slow)


# a missing import CI's jobs may skip, and why (every other one fails there)
IMPORT_SKIP_OK = {
    "kranto": "the other half of Kranto, a separate repository not installed in the page's CI: "
                "tests/page/test_paths.py's cross-repo checks run "
                "where both are installed",
}


def import_skip(longrepr) -> str | None:
    """A skip's reason when it is ``pytest.importorskip``'s "could not import …" of a module
    CI must have (not one of ``IMPORT_SKIP_OK``), else None."""
    reason = str(longrepr[2] if isinstance(longrepr, tuple) and len(longrepr) == 3 else longrepr)
    if "could not import" not in reason:
        return None
    module = reason.split("could not import '", 1)[-1].split("'", 1)[0].split(".", 1)[0]
    return None if module in IMPORT_SKIP_OK else reason


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """With ``KRANTO_NO_IMPORT_SKIPS=1`` (CI's fast and slow jobs), a test skipped because an
    import failed fails instead: tests/page/test_mcp_server.py skipped "could not import 'mcp'" on
    every CI run for days and nobody saw it."""
    outcome = yield
    rep = outcome.get_result()
    if rep.skipped and os.environ.get("KRANTO_NO_IMPORT_SKIPS") == "1":
        why = import_skip(rep.longrepr)
        if why:
            rep.outcome = "failed"
            rep.longrepr = f"skipped because an import failed, which CI does not allow: {why}"


def pytest_sessionfinish(session, exitstatus):
    """The session's HOME was the temp dir throughout: nothing reached the developer's."""
    if Path.home().resolve() != TEST_HOME:
        print(f"\nERROR: a test left HOME at {Path.home()} (expected {TEST_HOME}); tests "
              "change HOME only through monkeypatch", file=sys.stderr)
        session.exitstatus = 1
        return
    shutil.rmtree(TEST_HOME, ignore_errors=True)
