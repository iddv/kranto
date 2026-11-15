"""The sandbox probes are bounded (P3-4; review C-5): a hung probe means
"unavailable", not a hung session."""
import subprocess

from kranto.page.box import isolation


def test_a_hung_or_missing_probe_is_unavailable(monkeypatch):
    def hang(cmd, **kw):
        assert kw.get("timeout") == 30
        raise subprocess.TimeoutExpired(cmd, 30)
    monkeypatch.setattr(isolation.subprocess, "run", hang)
    assert isolation._probe(["bwrap"]) is False
    monkeypatch.setattr(isolation.subprocess, "run",
                        lambda cmd, **kw: (_ for _ in ()).throw(OSError("gone")))
    assert isolation._probe(["unshare"]) is False
