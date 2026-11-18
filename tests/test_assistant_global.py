"""Add Kranto to your own Claude Code or Codex from Settings › Assistant (as the owner decided on
2026-10-25: "nothing outside Kranto's folder unless asked; a Settings › Assistant action and a
console request both work, the change shown first";). Before, only the command line
did it. ``GET /api/assistant/global`` shows the exact change; ``POST`` makes it, on the owner's
press only: an assistant asked for it prepares the press. The harness's commands are faked:
nothing runs a real client, nothing touches the network, the home is the test's."""

import subprocess

from .conftest import web_client
from .test_verbs import BASE, app, bare, bearer, rt  # noqa: F401 - fixtures


def fake_tools(monkeypatch, tmp_path, installed=("claude", "codex", "kranto"), rc=0):
    ran: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda c: f"/usr/bin/{c}" if c in installed else None)

    def run(cmd, **kw):
        ran.append(list(cmd))
        return subprocess.CompletedProcess(cmd, rc, "", "" if rc == 0 else "no network")
    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setenv("HOME", str(tmp_path / "me"))
    return ran


def test_the_change_is_shown_before_anything_is_written(app, monkeypatch, tmp_path):  # noqa: F811
    ran = fake_tools(monkeypatch, tmp_path)
    with web_client(app, BASE) as page:
        r = page.get("/api/assistant/global", params={"harness": "claude"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["steps"] == ["claude plugin marketplace add " + out["steps"][0].split()[-1],
                                "claude plugin install kranto@kranto"]
        assert out["files"] == [] and out["missing"] == []
        assert "Nothing is changed until you click Add" in out["says"]
        codex = page.get("/api/assistant/global", params={"harness": "codex"}).json()
        assert codex["steps"][0].startswith("codex mcp add kranto -- ")
        assert codex["files"] and all(f["state"] == "new" for f in codex["files"])
        assert page.get("/api/assistant/global", params={"harness": "x"}).status_code == 400
    assert ran == []                                          # a look runs nothing
    assert not (tmp_path / "me" / ".agents").exists()          # and writes nothing


def test_the_owners_press_makes_it(app, monkeypatch, tmp_path):  # noqa: F811
    ran = fake_tools(monkeypatch, tmp_path)
    with web_client(app, BASE) as page:
        r = page.post("/api/assistant/global", json={"harness": "codex"})
    assert r.status_code == 200, r.text
    assert r.json()["done"] and "Restart your own client" in r.json()["says"]
    assert ran and ran[0][:4] == ["codex", "mcp", "add", "kranto"]
    assert (tmp_path / "me" / ".agents" / "skills" / "kranto" / "SKILL.md").is_file()


def test_a_missing_client_or_a_failed_command_changes_nothing_more(app, monkeypatch, tmp_path):  # noqa: F811
    fake_tools(monkeypatch, tmp_path, installed=("kranto",))
    with web_client(app, BASE) as page:
        r = page.post("/api/assistant/global", json={"harness": "claude"})
        assert r.status_code == 409 and "claude is not installed" in r.json()["error"]
    ran = fake_tools(monkeypatch, tmp_path, rc=1)
    with web_client(app, BASE) as page:
        r = page.post("/api/assistant/global", json={"harness": "codex"})
    assert r.status_code == 502 and "nothing more was changed" in r.json()["error"]
    assert len(ran) == 1 and not (tmp_path / "me" / ".agents").exists()


def test_an_assistant_asked_for_it_only_prepares_the_press(app, monkeypatch, tmp_path):  # noqa: F811
    ran = fake_tools(monkeypatch, tmp_path)
    with bare(app) as web:
        r = web.post("/api/verbs/assistant.global", headers=bearer("console"),
                     json={"fields": {"harness": "claude"}, "client": "claude"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["prepared"] and not out["ok"] and out["page"] == "#/settings/assistant?sel=eoutside"
    assert ran == []                                          # nothing ran for the assistant
