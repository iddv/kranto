"""The repository must be safe to publish.

The first test scans the real tree. The rest feed the scanner tiny fixture
trees, each with one known leak, to show that every check fires and that the
allowed forms stay quiet. Leaks are assembled from pieces at run time so this
file does not trip the scanner itself.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_scrub():
    path = ROOT / "scripts" / "ci" / "scrub.py"
    spec = importlib.util.spec_from_file_location("kranto_ci_scrub", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


scrub = _load_scrub()

OLD = "bea" + "rs"
LOGIN = "id" + "dv"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
SHA = "0123456789abcdef" * 2 + "01234567"
NOREPLY = "users.noreply.github.com"


def _git_files(root: Path) -> list[str] | None:
    if shutil.which("git") is None:
        return None
    top = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
        capture_output=True,
        text=True,
    )
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != root:
        return None
    out = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    )
    return [p for p in out.stdout.decode("utf-8", errors="replace").split("\0") if p]


def _format(findings) -> str:
    return "\n".join(f"{f.kind} {f.path}:{f.line}: {f.excerpt}" for f in findings)


def test_the_tree_is_clean():
    files = _git_files(ROOT)
    if files is None:
        pytest.skip("not a git checkout")
    findings = scrub.scan_tree(ROOT, files) + scrub.scan_workflows(ROOT)
    if findings:
        print(_format(findings))
    assert not findings, "public tree check failed:\n" + _format(findings)


# ---------------------------------------------------------------- fixtures

def _workflow(body: str) -> dict[str, str]:
    return {".github/workflows/ci.yml": "name: ci\n" + body}


# (kind, files) where files holds exactly one leak of that kind.
LEAKS = [
    ("old-name", {"README.md": f"Run {OLD}afk to start.\n"}),
    ("old-name", {"src/kranto/config.py": f"{OLD.upper()}_HOME = 1\n"}),
    ("old-name", {"docs/a.md": f"The afk{OLD} tool.\n"}),
    ("bear-art", {"assets/" + "be" + "ar" + "-logo.png": PNG}),
    ("bear-art", {"README.md": "Hello " + chr(0x1F43B) + "\n"}),
    ("bear-art", {"docs/a.md": "Our " + "mas" + "cot says hi.\n"}),
    ("owner-login", {"README.md": f"Ask @{LOGIN} for access.\n"}),
    ("owner-login", {"docs/a.md": "1234+" + LOGIN + "@" + NOREPLY + "\n"}),
    ("email", {"README.md": "Write to dev" + "@" + "acme-corp.io today.\n"}),
    ("home-path", {"run.sh": "cd /" + "home" + "/builder/src\n"}),
    ("host", {"docs/a.md": "Deploy to the " + "home" + "lab box.\n"}),
    ("host", {"docs/a.md": "ssh box." + "tail1234" + ".ts" + ".net\n"}),
    ("private-repo", {"docs/a.md": "See " + OLD + "-evals for details.\n"}),
    ("private-repo", {"docs/a.md": "See " + "brb" + "-loop for details.\n"}),
    ("plan-ref", {"docs/a.md": "See ACME" + "-PL" + "AN.md first.\n"}),
    ("plan-ref", {"docs/a.md": "As in " + "\u00a7" + "4 above.\n"}),
    ("plan-ref", {"docs/a.md": "From R" + "CA 20" + "24-01-02.\n"}),
    ("plan-ref", {"docs/a.md": "UI" + " fi" + "x 3b landed.\n"}),
    ("owner-site", {"src/kranto/connections/x.py": "placeholder = '" + "ueyw" + "95bi'\n"}),
    ("attribution", {"docs/a.md": "Co-" + "Authored-By: a bot\n"}),
    ("attribution", {"docs/a.md": "Gener" + "ated with a tool.\n"}),
    ("big-file", {"data/blob.bin": b"\x00" * 1_000_001}),
    ("workflow", _workflow("jobs:\n  a:\n    runs-on: [self" + "-hosted]\n")),
    ("workflow", _workflow("on: pull_request" + "_target\n")),
    ("workflow", _workflow("on:\n  workflow" + "_run:\n")),
    ("workflow", _workflow("env:\n  T: ${{ " + "secrets." + "NPM_TOKEN }}\n")),
    ("workflow", _workflow("jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")),
]

# (kind, files) where every file is an allowed form and nothing is reported.
ALLOWED = [
    ("old-name", {
        "src/kranto/legacy.py": f"OLD_NAME = '{OLD}'\n",
        "src/kranto/page/ui/web/src/lib/legacy.ts": f"export const OLD = '{OLD}';\n",
        "src/bears_cub/client.py": f"# {OLD} client\n",
        "db/migrations/0001.sql": f"-- {OLD}\n",
        "docs/sdk.md": "pip install bears-cub-sdk\nimport bears_cub\n",
    }),
    ("bear-art", {"assets/kranto-logo.png": PNG, "docs/a.md": "The cub module.\n"}),
    ("owner-login", {"README.md": "https://github.com/iddv/kranto\n"}),
    ("email", {
        "docs/a.md": "someone@example.com, ci@users.noreply.github.com, a@b.test, x@y.invalid\n",
    }),
    ("home-path", {"run.sh": "/home/user /home/runner/work /home/you /home/someone\n"}),
    ("host", {"docs/a.md": "Use localhost or example.net.\n"}),
    ("private-repo", {"docs/a.md": "See kranto-notes.\n"}),
    ("plan-ref", {"docs/a.md": "See docs/design/TENETS.md and the release plan.\n"}),
    ("attribution", {"docs/a.md": "Written by hand. Generated files live in build/.\n"}),
    ("big-file", {"data/blob.bin": b"\x00" * 1000}),
    ("workflow", _workflow(
        "on: pull_request\n"
        "jobs:\n  a:\n    runs-on: ubuntu-latest\n    steps:\n"
        f"      - uses: actions/checkout@{SHA}\n"
        "      - uses: ./.github/actions/setup\n"
        "        with:\n          token: ${{ secrets.GITHUB_TOKEN }}\n"
    )),
]


def _build(root: Path, files: dict) -> list[str]:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return sorted(files)


def _scan(root: Path, files: list[str]):
    return scrub.scan_tree(root, files) + scrub.scan_workflows(root)


def _ids(cases):
    seen: dict[str, int] = {}
    out = []
    for kind, _ in cases:
        seen[kind] = seen.get(kind, 0) + 1
        out.append(f"{kind}-{seen[kind]}")
    return out


@pytest.mark.parametrize("kind,files", LEAKS, ids=_ids(LEAKS))
def test_leak_is_reported(tmp_path, kind, files):
    findings = _scan(tmp_path, _build(tmp_path, files))
    assert any(f.kind == kind for f in findings), _format(findings)


@pytest.mark.parametrize("kind,files", ALLOWED, ids=_ids(ALLOWED))
def test_allowed_form_is_quiet(tmp_path, kind, files):
    findings = _scan(tmp_path, _build(tmp_path, files))
    assert not findings, _format(findings)


def test_every_kind_has_a_leak_case():
    assert set(scrub.ALLOW) == {kind for kind, _ in LEAKS}


def test_private_repo_also_counts_as_old_name(tmp_path):
    files = _build(tmp_path, {"docs/a.md": "See " + OLD + "-notes.\n"})
    kinds = {f.kind for f in _scan(tmp_path, files)}
    assert {"private-repo", "old-name"} <= kinds


def test_excerpt_hides_the_match(tmp_path):
    address = "dev" + "@" + "acme-corp.io"
    files = _build(tmp_path, {"README.md": f"line one\nmail {address} now\n"})
    findings = [f for f in _scan(tmp_path, files) if f.kind == "email"]
    assert len(findings) == 1
    assert findings[0].line == 2
    assert address not in findings[0].excerpt
    assert findings[0].excerpt == "mail *** now"


def test_path_is_checked(tmp_path):
    files = _build(tmp_path, {f"src/{OLD}afk/__init__.py": ""})
    assert any(f.kind == "old-name" and f.line == 0 for f in _scan(tmp_path, files))


# ---------------------------------------------------------------- commits

def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_GLOBAL"] = os.devnull
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    return env


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, env=_git_env()
    )


def _commit(repo: Path, name: str, message: str) -> None:
    (repo / name).write_text(name + "\n", encoding="utf-8")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", message)


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commits(tmp_path):
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.name", "dev")
    _git(tmp_path, "config", "commit.gpgsign", "false")

    _git(tmp_path, "config", "user.email", "dev" + "@" + "acme-corp.io")
    _commit(tmp_path, "a.txt", "first change")
    findings = scrub.scan_commits("HEAD", repo=tmp_path)
    assert any(f.kind == "commit" for f in findings), _format(findings)

    _git(tmp_path, "config", "user.email", "1+dev@" + NOREPLY)
    _commit(tmp_path, "b.txt", "second change")
    assert scrub.scan_commits("HEAD~1..HEAD", repo=tmp_path) == []

    _commit(tmp_path, "c.txt", "third change\n\n" + "Co-" + "Authored-By: a bot\n")
    findings = scrub.scan_commits("HEAD~1..HEAD", repo=tmp_path)
    assert [f.kind for f in findings] == ["commit"], _format(findings)
    assert "[attribution]" in findings[0].excerpt


def test_pr_text():
    assert scrub.scan_message("Fix the start-up race", "pr-title") == []
    findings = scrub.scan_message("Port from " + "brb" + "-work", "pr-body")
    assert findings and all(f.kind == "commit" for f in findings)


# ---------------------------------------------------------------- CLI

@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_cli(tmp_path):
    script = ROOT / "scripts" / "ci" / "scrub.py"
    env = _git_env()
    env.pop("PR_TITLE", None)
    env.pop("PR_BODY", None)
    _git(tmp_path, "init", "-q")
    _build(tmp_path, {"README.md": "Kranto\n"})
    _git(tmp_path, "add", "-A")

    run = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, env=env
    )
    assert run.returncode == 0, run.stdout + run.stderr
    assert run.stdout.strip() == "scrub: clean"

    _build(tmp_path, {"docs/a.md": "cd /" + "home" + "/builder\n"})
    _git(tmp_path, "add", "-A")
    run = subprocess.run(
        [sys.executable, str(script)], cwd=tmp_path, capture_output=True, text=True, env=env
    )
    assert run.returncode == 1
    assert run.stdout.strip() == "home-path docs/a.md:1: cd ***"
