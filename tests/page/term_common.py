"""Helpers for Open in Claude Code's tests: a Term on a scratch loop home with the fake claude
(``fake_claude_term.py``) first on PATH, a subject whose files are a small git repo, and a
screen that collects a session's terminal output. No model, no network."""
from __future__ import annotations

import os
import secrets
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml

from kranto.page import gitcmd
from kranto.page.settings.store import Config
from kranto.page.term import service
from kranto.page.term.subject import Subject

FAKE = Path(__file__).with_name("fake_claude_term.py")


def canary(tag: str = "tok") -> str:
    """A token-shaped value made at run time (never a literal: GitGuardian)."""
    return tag + "-" + "x" + secrets.token_hex(16)


def make_home(tmp: Path, **settings) -> Config:
    """A loop home with only a loop.yaml of the given settings."""
    home = tmp / "loop"
    home.mkdir(parents=True, exist_ok=True)
    (home / "loop.yaml").write_text(yaml.safe_dump(settings or {}))
    return Config(home)


class StubApp:
    """What ``Term`` reads of the page's ``App``: the loop home's settings (``loop_cfg``, read
    from loop.yaml each time, with a test's ``over`` on top: ``app.over["term"]["x"] = …``)."""

    def __init__(self, cfg: Config):
        self.loop_home = cfg.home
        self.over: dict = {"term": {}, "ask": {}}

    def loop_cfg(self) -> Config:
        return Config(self.loop_home, overrides=self.over)


def install_fake_claude(tmp: Path, monkeypatch) -> Path:
    """``claude`` on PATH is the fake, in a folder of its own (bound read-only into the
    sandbox as the claude install)."""
    d = tmp / "claude-install"
    d.mkdir(exist_ok=True)
    exe = d / "claude"
    shutil.copyfile(FAKE, exe)
    exe.chmod(0o755)
    monkeypatch.setenv("PATH", f"{d}{os.pathsep}{os.environ.get('PATH', '')}")
    return exe


def make_repo(d: Path, files: dict[str, str] | None = None) -> Path:
    """A git repo with one commit, standing in for the clone Kranto keeps of a project."""
    d.mkdir(parents=True, exist_ok=True)
    for name, text in (files or {"README.md": "# a project\n"}).items():
        p = d / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    for args in (("init", "-q", "-b", "main"), ("add", "-A"),
                 ("-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-q", "-m",
                  "first")):
        gitcmd.git(*args, cwd=d)
    return d


def make_term(tmp: Path, monkeypatch, *, token: str | None = None, source: Path | None = None,
              kind: str = "sources", sandboxed: bool | None = None, **term_cfg):
    """A Term on a scratch loop (``term.enabled``), with the fake claude, the token in Kranto's
    own environment, and every subject resolving to ``source`` (None: a scratch idea)."""
    install_fake_claude(tmp, monkeypatch)
    if token is not None:
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", token)
    cfg = make_home(tmp, term={"enabled": True, **term_cfg})
    t = service.Term(StubApp(cfg))

    def resolve(app, s):
        return Subject(s["kind"], s["id"], f"the {s['kind']} {s['id']}", source,
                       {"README.md": f"# about {s['id']}\n"})
    monkeypatch.setattr(service, "resolve", resolve)
    if sandboxed is not None:
        monkeypatch.setattr(t, "sandboxed", lambda: sandboxed)
    return t


class Screen:
    """A viewer that keeps everything a session printed."""

    def __init__(self):
        self.buf = bytearray()
        self.ended = False
        self.cv = threading.Condition()

    def __call__(self, data):
        with self.cv:
            if data is None:
                self.ended = True
            else:
                self.buf += data
            self.cv.notify_all()
        return True

    @property
    def text(self) -> str:
        return self.buf.decode(errors="replace")

    def wait(self, needle: str | tuple[str, ...], timeout: float = 20.0, start: int = 0) -> str:
        """Wait until ``needle`` (or any of several) is on the screen after ``start``."""
        needles = (needle,) if isinstance(needle, str) else needle
        end = time.time() + timeout
        with self.cv:
            while not any(n in self.buf[start:].decode(errors="replace") for n in needles):
                left = end - time.time()
                if left <= 0 or self.ended:
                    raise AssertionError(f"{needle!r} not seen; screen:\n{self.text[-3000:]}")
                self.cv.wait(min(left, 0.2))
        return self.text

    def said(self, text: str, timeout: float = 20.0) -> str:
        """Wait until the program printed ``text`` as a line of its own. The terminal echoes
        what is typed (``> say hi\\r\\n``), so ``wait("hi\\r\\n")`` was met by the echo alone,
        before the program had read the line or written its transcript (the program's own line
        comes through as ``hi\\r\\r\\n``): main went red on that. Its line starts a line, or
        follows its prompt directly when the line was typed before the terminal's echo was on
        (``> hi\\r``, seen on a loaded runner); the echo is never either (it has ``say``)."""
        return self.wait((f"\n{text}\r", f"> {text}\r"), timeout)


def run(term, tid: str, screen: Screen, cmd: str, timeout: float = 60.0) -> str:
    """Type ``run <cmd>`` into the session; the output up to its ``[exit N]`` line."""
    lv = term.live[tid]
    start = len(screen.buf)
    lv.pty.write(f"run {cmd}\n".encode())
    screen.wait("[exit ", timeout, start)
    out = screen.buf[start:].decode(errors="replace")
    return out


def needs_bwrap():
    """Skip without bubblewrap, except where it is required (CI's sandbox job)."""
    from kranto.page.box.isolation import isolation
    if isolation() == "bwrap":
        return
    if os.environ.get("KRANTO_BWRAP_REQUIRED") == "1":
        import tempfile

        from kranto.page.box.isolation import bwrap_cmd
        why = "no bwrap on PATH"
        if shutil.which("bwrap"):
            with tempfile.TemporaryDirectory() as tmp:
                cmd = bwrap_cmd(shutil.which("bwrap"), Path(tmp)) + ["-I", "-c", "pass"]
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                why = f"exit {p.returncode}: {p.stderr.strip()[:500]}; command: {cmd}"
        pytest.fail("bubblewrap is required here (KRANTO_BWRAP_REQUIRED=1) and its probe "
                    f"fails: {why}")
    pytest.skip("needs bubblewrap")


def git_out(*args, cwd) -> str:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout
