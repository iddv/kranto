""" B (Codex 10, Gemini 6): ``kranto --help`` read "Watch topics, build what converges. One app:
the watcher, the build loop and the UI." and listed the build tools, plugins, MCP servers, repo
maintenance, the corpus, traces and evals to a stranger whose Kranto has builds off. Help now opens
with the one line from the strategy; the factory's commands left with it, traces and evals
are not listed, kranto cub only for a developer (cubs.developer), and help says nothing of what
left (acceptance.py's WORDS, as the page's word test)."""

from __future__ import annotations

import argparse
import importlib.util
import re
from pathlib import Path

from kranto import launcher, legacy

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "preview" / "acceptance.py"


def _words() -> re.Pattern:
    import sys
    spec = importlib.util.spec_from_file_location("preview_acceptance_words", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = m
    spec.loader.exec_module(m)
    return m.WORDS


def _commands(p: argparse.ArgumentParser) -> set[str]:
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    return {a.dest for a in sub._choices_actions}


def test_help_opens_with_the_strategys_line():
    assert launcher.build_parser().description == launcher.PITCH
    assert launcher.PITCH.startswith("Kranto reads the sources you pick")


FACTORY = {"tools", "cap", "plugin", "mcp-server", "maintain", "github", "corpus", "research"}


def test_help_lists_no_factory_command_and_no_word_of_what_left():
    p = launcher.build_parser()
    listed = _commands(p)
    assert not listed & (launcher.HIDDEN_COMMANDS | launcher.DEVELOPER_COMMANDS | FACTORY), listed
    assert {"up", "status", "doctor", "open", "mcp", "update"} <= listed
    words = _words()
    lines = [re.sub(r"^\s{4}\S+", "", ln) for ln in p.format_help().splitlines()]
    hits = [ln.strip() for ln in lines if words.search(ln) or "converge" in ln or " afk " in ln]
    assert not hits, hits
    # the hidden commands still run (they say what they need); the factory's are gone
    assert p.parse_args(["trace", "list"]).command == "trace"
    assert p.parse_args(["cub", "list"]).command == "cub"
    sub = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))
    assert not FACTORY & set(sub.choices)


def test_a_developer_sees_kranto_cub_in_help():
    assert "cub" in _commands(launcher.build_parser(developer=True))
    assert not launcher.HIDDEN_COMMANDS & _commands(launcher.build_parser(developer=True))


# the earlier product's words in a command's help: its builds, its loop, its names, the page's
# projects ("pause … (the page's Pause pauses building too)", "sources: what the kranto watch")
RETIRED = re.compile(r"\b(?:build(?:s|ing)?|" + "|".join(legacy.COMMANDS) + r"s?)\b|\bloop\b"
                     r"|\bprojects\b|\bthe kranto watch", re.I)
# a developer's commands (cub: Made by Kranto builds one), the evals (an eval set is built) and
# adopt (which reads an older install's loop home) say their own words
OWN_WORDS = ("cub", "eval", "adopt")


def test_no_command_help_describes_what_left():
    from kranto import cli

    from .test_no_internal_refs import help_texts
    texts = [*help_texts(cli.build_parser(), "python -m kranto"),
             *help_texts(launcher.build_parser(developer=True), "kranto")]
    assert len(texts) > 50
    def command(where: str) -> str:
        parts = where.split()
        at = 3 if where.startswith("python -m kranto") else 1
        return parts[at] if len(parts) > at else ""

    said = [(w, t) for w, t in texts if command(w) not in OWN_WORDS]
    # a key or a file by its own name (build.claude_command, loop.yaml) is no description
    hits = [(w, t[:120]) for w, t in said if RETIRED.search(re.sub(r"[\w-]+\.[\w.]+", "", t))]
    assert hits == [], hits
    by = dict(said)
    assert "the page's Pause is the same switch" in by["python -m kranto pause"]
    assert by["python -m kranto sources"].startswith("the sources Kranto reads")


def test_help_reads_the_homes_config_only_for_help():
    assert launcher._help_developer(["status"], None) is False        # a command parses everything
    assert launcher._help_developer(["cub", "--help"], None) is False  # a command's own help
