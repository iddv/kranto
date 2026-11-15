"""No silent unsandboxed runs: without bubblewrap, a command the box would run is refused unless
the owner sets KRANTO_ALLOW_UNSANDBOXED=1; with it, the command is the sandbox's. (The build
loop's solvers, check commands, exam and MCP servers left with it, CUT.)"""
import sys

import pytest

from kranto.page.box import isolation as iso


@pytest.fixture
def no_bwrap(monkeypatch):
    monkeypatch.setattr(iso, "isolation", lambda: "none")
    monkeypatch.delenv(iso.ALLOW_UNSANDBOXED, raising=False)


def test_without_bubblewrap_nothing_runs_unless_allowed(no_bwrap, tmp_path, monkeypatch):
    with pytest.raises(iso.SandboxRequired, match="KRANTO_ALLOW_UNSANDBOXED=1"):
        iso.sandbox_cmd(tmp_path)
    monkeypatch.setenv(iso.ALLOW_UNSANDBOXED, "1")          # the owner's choice
    assert iso.sandbox_cmd(tmp_path, interp="/bin/sh") == ["/bin/sh"]


def test_with_bubblewrap_it_is_the_sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(iso, "isolation", lambda: "bwrap")
    monkeypatch.delenv(iso.ALLOW_UNSANDBOXED, raising=False)
    cmd = iso.sandbox_cmd(tmp_path, interp=sys.executable)
    assert "--unshare-all" in cmd and cmd[-1] == sys.executable
