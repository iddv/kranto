"""The question (opt-in, asked once, Enter sends nothing):
`kranto setup` asks it once and Enter leaves Kranto counting on this machine only; `--yes` asks
nothing and answers nothing; `--telemetry` and the answers file answer it; a re-run never
undoes a later choice; Today's reminder comes once after seven unanswered days; the notice names
the controller, has no placeholder left, and is on the field page."""

from __future__ import annotations

import builtins
import json
import sys
from datetime import UTC, datetime, timedelta

import pytest
import yaml

from kranto import launcher, telemetry, wizard
from kranto.telemetry import docs, local

from .test_kranto import make_host, user_home  # noqa: F401


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    for k in (local.DNT, local.ENV_MODE, local.ENV_ENDPOINT):
        monkeypatch.delenv(k, raising=False)


def setup(host, *argv, capsys):
    code = launcher.main(["setup", *argv], host)
    return code, capsys.readouterr()


def mode_in(home):
    return (yaml.safe_load((home / "kranto.yaml").read_text()).get("telemetry") or {})


def test_yes_answers_nothing_and_sends_nothing(user_home, capsys):  # noqa: F811
    code, out = setup(make_host(user_home), "--yes", "--no-start", "--json", capsys=capsys)
    home = user_home / ".kranto"
    assert code == 0
    assert mode_in(home).get("answered_at") is None
    eff = telemetry.effective(home)
    assert (eff.mode, eff.answered) == ("local", False)
    assert "not answered, so nothing is sent" in out.err
    assert "telemetry" not in json.loads(out.out)["answers"]


def test_the_flag_and_the_answers_file_answer_it(user_home, capsys, tmp_path):  # noqa: F811
    host = make_host(user_home)
    code, out = setup(host, "--yes", "--no-start", "--telemetry", "off", capsys=capsys)
    home = user_home / ".kranto"
    assert code == 0 and mode_in(home)["mode"] == "off" and mode_in(home)["answered_at"]
    answers = tmp_path / "a.yaml"
    answers.write_text("telemetry: basic\nstart: false\n")
    code, out = setup(host, "--answers", str(answers), capsys=capsys)
    assert code == 0 and mode_in(home)["mode"] == "basic"


def test_a_rerun_never_undoes_a_later_choice(user_home, capsys):  # noqa: F811
    host = make_host(user_home)
    setup(host, "--yes", "--no-start", "--telemetry", "basic", capsys=capsys)
    home = user_home / ".kranto"
    telemetry.set_mode(home, "off")                         # Settings › Privacy, later
    code, out = setup(host, "--yes", "--no-start", capsys=capsys)
    assert code == 0 and mode_in(home)["mode"] == "off"
    assert "usage reports off" in out.out


def test_interactive_enter_sends_nothing_and_a_number_answers(user_home, capsys,  # noqa: F811
                                                              monkeypatch):
    host = make_host(user_home)
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    asked = []
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt: "")   # no model key typed
    code, out = setup(host, "--no-start", capsys=capsys)
    home = user_home / ".kranto"
    assert code == 0
    q = [p for p in asked if "Send usage reports?" in p]
    assert len(q) == 1 and q[0].endswith("[]: ")                  # nothing chosen for you
    assert "Never your topics, cards, posts, prompts" in out.out
    # a fresh home says nothing about builds or repositories
    assert "how long builds" not in out.out and "repo names" not in out.out
    assert telemetry.effective(home).answered is False
    replies = iter(["2"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(replies) if
                        "Send usage reports?" in prompt else "")
    code, out = setup(host, "usage", capsys=capsys)
    assert code == 0 and mode_in(home)["mode"] == "detailed"
    monkeypatch.setattr(builtins, "input", lambda prompt: asked.append(prompt) or "")
    n = len(asked)
    setup(host, "usage", capsys=capsys)
    assert not any("Send usage reports?" in p for p in asked[n:])    # asked once


def test_a_mistyped_answer_is_asked_again_and_setup_goes_on(user_home, capsys,  # noqa: F811
                                                            monkeypatch):
    """A stranger typed "y" (or a port) at the question: setup asked again and went on, where it
    used to stop with words that were not the 1/2/3 it offered."""
    host = make_host(user_home)
    host.stdin_tty = True
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    replies = iter(["y", "10211", "Basic"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(replies) if
                        "Send usage reports?" in prompt else "")
    monkeypatch.setattr(wizard.getpass, "getpass", lambda prompt: "")
    code, out = setup(host, "--no-start", capsys=capsys)
    home = user_home / ".kranto"
    assert code == 0
    assert "'y' is not one of them: type 1, 2 or 3" in out.out
    assert mode_in(home)["mode"] == "basic"
    assert "Sources › Topics" in out.out                      # the sections after it still ran
    replies2 = iter(["x", "x", "x"])
    monkeypatch.setattr(builtins, "input", lambda prompt: next(replies2) if
                        "Send usage reports?" in prompt else "")
    telemetry.set_mode(home, "local")
    cfg = yaml.safe_load((home / "kranto.yaml").read_text())
    cfg["telemetry"].pop("answered_at", None)
    (home / "kranto.yaml").write_text(yaml.safe_dump(cfg))
    code, out = setup(host, "usage", capsys=capsys)
    assert code == 0 and "not answered, so nothing is sent" in out.err + out.out


def test_the_question_names_the_real_command():
    assert "(kranto telemetry show)" in telemetry.SUMMARY
    assert "Kranto telemetry" not in telemetry.SUMMARY


def test_do_not_track_is_kept_and_said(user_home, capsys, monkeypatch):  # noqa: F811
    monkeypatch.setenv("DO_NOT_TRACK", "1")
    code, out = setup(make_host(user_home), "--yes", "--no-start", capsys=capsys)
    assert code == 0 and "usage reports off: set by DO_NOT_TRACK" in out.out


def test_the_reminder_comes_once_after_seven_days(tmp_path):
    from kranto import config as config_mod
    home = tmp_path / "h"
    config_mod.init_workspace(home)
    assert telemetry.remind(home) is False                   # the first look starts the week
    st = local.read_state(home)
    st["first_seen"] = (datetime.now(UTC) - timedelta(days=8)).strftime("%Y-%m-%d")
    local.write_state(home, st)
    assert telemetry.remind(home) is True
    telemetry.dismiss(home)
    assert telemetry.remind(home) is False
    st["reminder_dismissed"] = None
    local.write_state(home, st)
    telemetry.set_mode(home, "basic")
    assert telemetry.remind(home) is False                   # answered: never


def test_the_notice_names_the_controller_and_the_page_has_the_notice():
    n = docs.notice()
    assert "The controller is The Kranto authors" in n
    assert "https://github.com/iddv/kranto" in n and "no personal data" in n
    assert local.DEFAULT_ENDPOINT in n and local.DEFAULT_ENDPOINT in docs.page()
    assert "eu-west-1" in n and "Art. 6(1)(a)" in n and "90 days" in n
    assert n.strip() in docs.page()


def test_no_placeholder_is_left_anywhere():
    """The owner's two placeholders, and any ``{{...}}`` in the notice and the page, are gone
    from everything a person can read (built at run time, so this file is not a match)."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    names = ["{{" + "CONTROLLER_NAME" + "}}", "{{" + "CONTACT" + "}}"]
    files = [p for d in ("src", "docs", "packages") for p in (root / d).rglob("*")
             if p.is_file() and p.suffix in (".py", ".md", ".txt", ".json", ".yaml")]
    files.append(root / "README.md")
    for p in files:
        text = p.read_text(errors="replace")
        for name in names:
            assert name not in text, p
    for text in (docs.notice(), docs.page()):
        assert not re.search(r"\{\{[^}]*\}\}", text)
    assert "no endpoint" not in docs.page() and "no address" not in docs.page()
