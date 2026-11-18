"""Every command line Kranto prints, in its docs and in its own messages, runs on an installed
Kranto: each is parsed by the real parsers (``kranto``, and behind ``kranto watch`` the watcher's,
behind ``kranto cub`` the features', behind ``kranto telemetry`` the usage reports'), so a
renamed or removed command fails here instead of in a stranger's terminal.

An installed Kranto has the ``kranto`` command and no Python of its own on PATH, so no doc or
message prints ``python -m kranto …``; ``python -m kranto`` (and ``python -m kranto.cli``) still run
the watcher for whoever works from a checkout.
"""

from __future__ import annotations

import argparse
import ast
import functools
import re
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from kranto import cli as watcher_cli
from kranto import launcher
from kranto.core.cubs import cli as cubs_cli
from kranto.telemetry import cli as telemetry_cli

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "kranto"

# Markdown a person reads. Not: the design papers and the changelog (history, kept as written).
SKIP_DOCS = ("docs/design/", "CHANGELOG.md", "src/kranto/prompts/", "tests/")
# Developer tools run from a checkout, not commands of an installed Kranto.
DEV_MODULES = ("kranto.features.post.evals", "kranto.page.proc", "kranto.page.mcp.server",
               "kranto.page.cli")
# Files whose printed commands another pull request in flight rewrites; each leaves this set
# when that change is on main.
PENDING = {"src/kranto/web/app.py"}
# kranto subcommands whose words after them another program parses as it likes
FREE_TAIL = {"term", "trace", "eval", "settings"}
STOP = {"|", "||", "&&", ";", "#", ">", ">>", "2>", "2>&1", "&", "<", "\\"}


def _git_files(pattern: str) -> list[str]:
    out = subprocess.run(["git", "ls-files", pattern], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return [f for f in out.splitlines() if f]


def _docs() -> list[str]:
    return [f for f in _git_files("*.md") if not f.startswith(SKIP_DOCS) and f not in PENDING]


@functools.cache
def _kranto_parser() -> argparse.ArgumentParser:
    return launcher.build_parser(developer=True)


@functools.cache
def _cub_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="kranto")
    cubs_cli.add_parser(p.add_subparsers(dest="cmd", required=True))
    return p._subparsers._group_actions[0].choices["cub"]  # type: ignore[union-attr]


def _subparsers(p: argparse.ArgumentParser) -> dict[str, argparse.ArgumentParser]:
    for a in p._actions:
        if isinstance(a, argparse._SubParsersAction):
            return dict(a.choices)
    return {}


def _options(p: argparse.ArgumentParser) -> dict[str, argparse.Action]:
    return dict(p._option_string_actions)


@functools.cache
def _behind(name: str) -> argparse.ArgumentParser | None:
    """The parser that reads the words after ``kranto NAME`` when ours takes them whole."""
    if name == "watch":
        return watcher_cli.build_parser()
    if name == "cub":
        return _cub_parser()
    if name == "telemetry":
        return telemetry_cli.parser()
    return None


def check(line: str) -> str | None:
    """None when ``line`` (``kranto …``) parses; else what is wrong with it."""
    try:
        words = shlex.split(line.replace("[", " ").replace("]", " "), posix=True)
    except ValueError:
        words = line.replace("[", " ").replace("]", " ").split()
    cut = next((i for i, w in enumerate(words) if w in STOP or w.startswith("#")), len(words))
    words = words[:cut]
    if not words or words[0] != "kranto":
        return f"not a kranto command: {line!r}"
    if len(words) > 1 and (not re.fullmatch(r"-?-?[a-z][\w-]*", words[1]) or "@" in line):
        return None  # 'kranto 0.7.0' (a version), 'kranto release <…@…>' (a name): not a command
    parser = _kranto_parser()
    path = ["kranto"]
    i, positionals = 1, False
    while i < len(words):
        w = words[i]
        if w in ("…", "...") or w.startswith(("<", "$", "{", "\"$", "'$")):
            i += 1
            positionals = True
            continue
        if w.startswith("-") and len(w) > 1:
            name = w.split("=", 1)[0]
            opts = _options(parser)
            if name not in opts:
                return f"{' '.join(path)}: no option {name} in {line!r}"
            act = opts[name]
            i += 1 if ("=" in w or act.nargs == 0) else 2
            continue
        subs = _subparsers(parser)
        if subs and not positionals:
            if w not in subs:
                return f"{' '.join(path)}: no command {w!r} in {line!r}"
            path.append(w)
            if len(path) == 2 and w in FREE_TAIL:
                return None
            behind = _behind(w) if len(path) == 2 else None
            parser = behind if behind is not None else subs[w]
            i += 1
            continue
        positionals = True
        i += 1
    return None


# -- what the docs print ------------------------------------------------------------------------

FENCE = re.compile(r"^\s*(```|~~~)")
SPAN = re.compile(r"``?([^`]+?)``?")
CMD = re.compile(r"^(?:\$\s+)?(kranto(?:\s.*)?)$")
PYM = re.compile(r"python3?\s+-m\s+(kranto[\w.]*)")


def _a_label(text: str) -> bool:
    """``kranto setup: …``, ``kranto home: …``: a message's prefix or a line of output."""
    words = text.split()
    return any(w.endswith(":") for w in words[1:3])


def doc_commands(text: str) -> list[tuple[int, str]]:
    """``(line number, command)`` for each ``kranto …`` in a fenced block or a code span."""
    found: list[tuple[int, str]] = []
    fenced = False
    for n, raw in enumerate(text.splitlines(), 1):
        if FENCE.match(raw):
            fenced = not fenced
            continue
        if fenced:  # a shell line, not a program's output that mentions kranto
            pieces = [raw.strip()] if CMD.match(raw.strip()) else []
        else:
            pieces = [m.group(1).strip() for m in SPAN.finditer(raw)]
        for piece in pieces:
            for part in re.split(r"\s*(?:&&|;|\|\|)\s*", piece):
                m = CMD.match(part.strip())
                if m and not _a_label(m.group(1)):
                    found.append((n, m.group(1)))
    return found


def _doc_lines() -> list[tuple[str, int, str]]:
    out = []
    for rel in _docs():
        text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
        out += [(rel, n, cmd) for n, cmd in doc_commands(text)]
    return out


def test_the_docs_print_many_commands():
    assert len(_doc_lines()) > 100


@pytest.mark.parametrize("rel", _docs())
def test_every_command_a_doc_prints_runs(rel):
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    bad = [f"{rel}:{n}: {why}" for n, cmd in doc_commands(text) if (why := check(cmd))]
    assert not bad, "\n".join(bad)


@pytest.mark.parametrize("rel", _docs())
def test_no_doc_prints_python_m_kranto(rel):
    text = (ROOT / rel).read_text(encoding="utf-8", errors="replace")
    bad = [f"{rel}:{n}: {m.group(0)}" for n, line in enumerate(text.splitlines(), 1)
           for m in PYM.finditer(line) if not m.group(1).startswith(DEV_MODULES)]
    assert not bad, "an installed Kranto has no such Python; print kranto watch …\n" + \
        "\n".join(bad)


# -- what Kranto's own messages print ------------------------------------------------------------

LIT_QUOTED = re.compile(r"(?:'|``?)(kranto [^'`\n]+?)(?:'|``?)")


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                ids.add(id(body[0].value))
    return ids


def _literals(path: Path) -> list[tuple[int, str]]:
    """Each string a module could print: its literals and f-strings' fixed parts, docstrings
    left out (they are read in the code, not printed)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_ids(tree)
    docs |= {id(v) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr)
             for v in node.values}  # an f-string's parts: read whole, below
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in node.values)
            out.append((node.lineno, text))
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docs):
            out.append((node.lineno, node.value))
    return out


def _sources() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "node_modules" not in p.parts
                  and str(p.relative_to(ROOT)) not in PENDING)


def literal_commands(text: str) -> list[str]:
    """``kranto …`` written as a command in a string: quoted ('kranto x', `kranto x`) or the
    whole string."""
    found = [m.group(1) for m in LIT_QUOTED.finditer(text)]
    if text.startswith("kranto ") and "\n" not in text and not found:
        found.append(text)
    return [f.replace("{}", "<x>") for f in found if not _a_label(f)]


def test_messages_print_no_python_m_kranto():
    bad = []
    for path in _sources():
        for n, text in _literals(path):
            for m in PYM.finditer(text):
                if not m.group(1).startswith(DEV_MODULES):
                    bad.append(f"{path.relative_to(ROOT)}:{n}: {m.group(0)}")
    assert not bad, "print kranto watch … instead:\n" + "\n".join(bad)


def test_every_command_a_message_prints_runs():
    bad = []
    for path in _sources():
        for n, text in _literals(path):
            for cmd in literal_commands(text):
                why = check(cmd)
                if why:
                    bad.append(f"{path.relative_to(ROOT)}:{n}: {why}")
    assert not bad, "\n".join(bad)


# -- the door itself -----------------------------------------------------------------------------

def test_watch_hands_this_home_to_the_watcher(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(watcher_cli, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    launcher.main(["--home", str(tmp_path), "watch", "topics", "list"],
                  launcher.Host(home=tmp_path))
    assert seen["argv"] == ["-w", str(tmp_path), "topics", "list"]


def test_watch_keeps_a_workspace_it_is_given(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(watcher_cli, "main", lambda argv: seen.setdefault("argv", argv) and 0)
    launcher.main(["watch", "-w", "/elsewhere", "status"], launcher.Host(home=tmp_path))
    assert seen["argv"] == ["-w", "/elsewhere", "status"]


def test_watch_help_is_the_watchers(capsys, tmp_path):
    with pytest.raises(SystemExit) as e:
        launcher.main(["watch", "--help"], launcher.Host(home=tmp_path))
    assert e.value.code == 0
    out = capsys.readouterr().out
    assert out.startswith("usage: kranto watch") and "topics" in out and "websearch" in out


def test_kranto_help_lists_watch(capsys, tmp_path):
    with pytest.raises(SystemExit):
        launcher.main(["--help"], launcher.Host(home=tmp_path))
    assert re.search(r"^\s+watch\s", capsys.readouterr().out, re.M)


@pytest.mark.parametrize("module", ["kranto", "kranto.cli"])
def test_python_m_still_runs_the_watcher(module):
    r = subprocess.run([sys.executable, "-m", module, "--help"], capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and "topics" in r.stdout


@pytest.mark.parametrize("line,ok", [
    ("kranto watch topics list", True),
    ("kranto watch sources approve <id>", True),
    ("kranto watch provider use claude_code --accept-terms", True),
    ("kranto cub add FOLDER --ref v1", True),
    ("kranto up --port 8790", True),
    ("kranto restart", False),
    ("kranto provider openai --key-stdin", False),
    ("kranto topics list", False),
    ("kranto watch topics nope", False),
    ("kranto up --nope", False),
])
def test_the_checker_itself(line, ok):
    assert (check(line) is None) is ok
