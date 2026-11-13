"""`brb --help` says what brb is and every command says what it does; `brb --version` answers."""
import argparse

import pytest

from kranto.page import __version__
from kranto.page.cli import main

from .test_no_internal_refs import brb_parser


def test_every_command_has_a_line_and_brb_says_what_it_is(monkeypatch):
    p = brb_parser(monkeypatch)
    assert p.description and "kranto" in p.description.lower()
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    helped = {c.dest for c in sub._choices_actions if c.help}
    assert sorted(set(sub.choices) - helped) == []


def test_version(capsys):
    with pytest.raises(SystemExit) as e:
        main(["--version"])
    assert e.value.code == 0 and capsys.readouterr().out.strip() == f"brb {__version__} (the page)"
