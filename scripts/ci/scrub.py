#!/usr/bin/env python3
"""Check that the repository holds nothing that should not be public.

Usage:
    python3 scripts/ci/scrub.py                   # tracked files and workflows
    python3 scripts/ci/scrub.py --commits A..B    # commit metadata and messages
    python3 scripts/ci/scrub.py --title T --body B

PR_TITLE and PR_BODY in the environment are checked like --title and --body.

Prints "scrub: clean" and exits 0, or prints one line per finding
("kind path:line: excerpt", with the match replaced by ***) and exits 1.
Exits 2 if git fails. Standard library only.
"""

from __future__ import annotations

import argparse
import bisect
import os
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

# Every pattern below is assembled from pieces so this file does not match
# its own checks.
OLD = "bea" + "rs"
LOGIN = "id" + "dv"
REPO = LOGIN + "/kranto"
NOREPLY_DOMAIN = "users.noreply.github.com"
MAX_BYTES = 1_000_000

# Paths where a kind of finding is expected, with the reason for each.
# Nothing is skipped by file name unless it is listed here.
ALLOW: dict[str, dict[str, str]] = {
    "old-name": {
        "src/kranto/legacy.py": "maps the old name to the new one for upgrades",
        "src/kranto/page/ui/web/src/lib/legacy.ts": "same mapping for the web UI",
        "src/bears_cub/**": "the SDK package keeps its name",
        "sdk/**": "the SDK keeps its name",
        "**/migrations/**": "migrations keep the names they shipped with",
        "src/kranto/prompts/**": "prompts keep their exact bytes until reworded",
        "prompts.lock.json": "hashes of the prompts, kept with them",
        "docs/design/TENETS.md": "read by the prompts, kept byte for byte",
        "tests/fixtures/evals/**": "recorded with the prompts' exact bytes, kept with them",
        "tests/fixtures/post_evals/owner_read_2.json": "three outside writers' drafts kept "
        "verbatim, as a reader judged them (they use the verb \"bears on\")",
        "tests/test_public_tree.py": "tests for this scanner",
        "scripts/ci/scrub.py": "this scanner",
        "uv.lock": "lock file written by the package manager",
        "**/package-lock.json": "lock file written by the package manager",
        "**/cub.yaml": "the cub manifest's host-range key keeps its name (cub.yaml schema 1)",
        "tests/fixtures/cub_manifests/**": "cub manifests, with that same key",
    },
    "bear-art": {},
    "owner-login": {},
    "email": {},
    "home-path": {},
    "host": {
        "tests/test_no_internal_refs.py": "a test's own list of words a stranger must not meet",
        "tests/page/test_no_internal_refs.py": "the same, for the page's help and strings",
    },
    "private-repo": {
        "src/kranto/legacy.py": "an old install's default loop folder, still read where it is",
    },
    "plan-ref": {},
    "owner-site": {},
    "foreign-account": {
        "tests/test_public_tree.py": "tests for this scanner",
    },
    "attribution": {
        "scripts/ci/no_attribution.py": "the check's own patterns",
        "scripts/release/notes.py": "release notes drop these lines: the patterns that find them",
        "tests/test_no_attribution.py": "tests of that check",
        "tests/test_release_scripts.py": "tests that release notes drop them",
    },
    "big-file": {},
    "nul-byte": {},
    "workflow": {},
}


@dataclass(frozen=True)
class Finding:
    kind: str
    path: str
    line: int
    excerpt: str  # the matched text is replaced by ***


# ---------------------------------------------------------------- allow-list

def _glob_to_re(pattern: str) -> re.Pattern[str]:
    """Translate a path glob ("*", "?", "**") to a regex for whole paths."""
    out: list[str] = []
    i = 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


_ALLOW_RE = {
    kind: [_glob_to_re(glob) for glob in globs] for kind, globs in ALLOW.items()
}


def allowed(kind: str, path: str) -> bool:
    return any(rx.match(path) for rx in _ALLOW_RE.get(kind, ()))


# ---------------------------------------------------------------- text rules

# keep(match, text, in_commit) returns True when the match should be reported.
Keep = Callable[["re.Match[str]", str, bool], bool]


@dataclass(frozen=True)
class Rule:
    kind: str
    regex: re.Pattern[str]
    keep: Keep | None = None


_IDENT = re.compile(r"[A-Za-z0-9_]")
# The SDK keeps its name, and stored names keep theirs (a column of the cubs table)
_SDK_TOKENS = (OLD + "-cub-sdk", OLD + "_cub", OLD + "_range")


def _old_name_keep(m: re.Match[str], text: str, in_commit: bool) -> bool:
    # The SDK keeps its name: the exact tokens above are not reported.
    s = m.start()
    if s and _IDENT.match(text[s - 1]):
        return True
    for token in _SDK_TOKENS:
        if text.startswith(token, s):
            e = s + len(token)
            if e >= len(text) or not _IDENT.match(text[e]):
                return False
    return True


_REPO_RE = re.compile(re.escape(REPO) + r"(?![A-Za-z0-9_-])", re.I)
_NOREPLY_LOGIN_RE = re.compile(
    r"\d+\+" + LOGIN + "@" + re.escape(NOREPLY_DOMAIN), re.I
)


def _login_keep(m: re.Match[str], text: str, in_commit: bool) -> bool:
    s = m.start()
    if _REPO_RE.match(text, s):
        return False
    if in_commit and s > 1 and text[s - 1] == "+":
        k = s - 1
        while k > 0 and text[k - 1].isdigit():
            k -= 1
        if k < s - 1 and _NOREPLY_LOGIN_RE.match(text, k):
            return False
    if in_commit:
        # a sign-off whose address is the GitHub no-reply one: the account's own name for it
        line = text[text.rfind("\n", 0, s) + 1:text.find("\n", s) if "\n" in text[s:] else None]
        if line.startswith("Signed-off-by: ") and \
                line.rstrip().endswith("@" + NOREPLY_DOMAIN + ">"):
            return False
    return True


_OK_EMAIL_DOMAINS = ("example.com", "example.org", "example.net")
_OK_EMAIL_EXACT = (NOREPLY_DOMAIN, "localhost")
_OK_EMAIL_SUFFIXES = (".invalid", ".test", ".example")


def _email_keep(m: re.Match[str], text: str, in_commit: bool) -> bool:
    domain = m.group(1).lower()
    if domain in _OK_EMAIL_EXACT or domain.endswith(_OK_EMAIL_SUFFIXES):
        return False
    return not any(domain == ok or domain.endswith("." + ok) for ok in _OK_EMAIL_DOMAINS)


_OK_HOMES = {"user", "you", "someone", "runner"}


def _home_keep(m: re.Match[str], text: str, in_commit: bool) -> bool:
    return m.group(1).rstrip(".") not in _OK_HOMES


_PRIVATE_REPOS = [
    OLD + "-notes",
    OLD + "-evals",
    OLD + "-site",
    "brb" + "-fleet2",  # before the shorter name so the whole token matches
    "brb" + "-fleet",
    "brb" + "-work",
    "brb" + "-loop",
]

_PLAN_PATTERNS = [
    r"\b[A-Z][A-Z0-9]+-(?:DES" + r"IGN|PL" + r"AN|STRAT" + r"EGY)(?:\.md)?",
    r"\bR" + r"CA 20\d\d-\d\d-\d\d",
    "§" + r" ?\d",
    r"\b[A-Z]{2,}[0-9]*" + " fi" + r"x \d+[a-z]?\b",
]

# the owner's own site's identifiers, which once stood in the tree as an example (a Sanity
# project id): refused anywhere, built from pieces so this file does not hold them whole
_OWNER_SITE = ["ueyw" + "95bi"]

# a GitHub account that is not the project's, and the collection of features it was said to
# hold (it never existed): code, docs and tests once sent people there; refused anywhere
_FOREIGN = [r"\bocto" + r"-owner\b", "bear" + "cub"]

_ATTRIBUTION = ["Co-" + "Authored-By:", "Gener" + "ated with", "noreply" + "@" + "anthropic"]
_ATTRIBUTION_RX = r"\b(?:" + "|".join(re.escape(a) for a in _ATTRIBUTION) + ")"

RULES: list[Rule] = [
    Rule("old-name", re.compile(OLD, re.I), _old_name_keep),
    Rule("bear-art", re.compile(chr(0x1F43B) + r"|\b" + "mas" + "cot", re.I)),
    Rule("owner-login", re.compile(r"\b" + LOGIN + r"\b", re.I), _login_keep),
    Rule(
        "email",
        re.compile(
            # a fediverse handle (@name@instance) is not an address
            r"(?<![A-Za-z0-9._%+@-])[A-Za-z0-9._%+-]+"
            + "@"
            + r"((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})\b"
        ),
        _email_keep,
    ),
    # a home folder: not a folder named home inside another path (/api/home/x, $ROOT/home/x)
    Rule("home-path", re.compile(r"(?<![\w.$}/-])/" + "home" + r"/([A-Za-z0-9._-]+)"),
         _home_keep),
    Rule(
        "host",
        re.compile(
            "home" + "lab" + r"|\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.ts" + r"\.net\b", re.I
        ),
    ),
    Rule(
        "private-repo",
        re.compile("|".join(re.escape(n) for n in _PRIVATE_REPOS), re.I),
    ),
    Rule("plan-ref", re.compile("|".join(_PLAN_PATTERNS))),
    Rule("owner-site", re.compile("|".join(re.escape(n) for n in _OWNER_SITE), re.I)),
    Rule("foreign-account", re.compile("|".join(_FOREIGN), re.I)),
    Rule(
        "attribution",
        re.compile(_ATTRIBUTION_RX, re.I),
    ),
]

# Commit messages and PR text get every text rule except the art check.
COMMIT_RULES = [r for r in RULES if r.kind != "bear-art"]

_ART_PATH_RE = re.compile(
    r"(?:.*" + "be" + "ar" + r".*\.(?:png|svg|webp|ico|jpe?g)|" + "mas" + "cot" + r".*)\Z",
    re.I,
)

_EXCERPT_MAX = 160


def _excerpt(line_text: str, spans: list[tuple[int, int]]) -> str:
    parts: list[str] = []
    pos = 0
    for start, end in sorted(spans):
        if start < pos:
            start = pos
        if end <= start:
            continue
        parts.append(line_text[pos:start])
        parts.append("***")
        pos = end
    parts.append(line_text[pos:])
    text = "".join(parts).strip()
    if len(text) > _EXCERPT_MAX:
        text = text[: _EXCERPT_MAX - 3] + "..."
    return text


def scan_text(
    text: str, rules: list[Rule], in_commit: bool = False
) -> list[tuple[str, int, str]]:
    """Return (kind, line, excerpt) for each line where a rule matches."""
    out: list[tuple[str, int, str]] = []
    newlines: list[int] | None = None
    for rule in rules:
        by_line: dict[int, list[tuple[int, int]]] = {}
        for m in rule.regex.finditer(text):
            if rule.keep is not None and not rule.keep(m, text, in_commit):
                continue
            if newlines is None:
                newlines = [nl.start() for nl in re.finditer("\n", text)]
            line = bisect.bisect_left(newlines, m.start()) + 1
            by_line.setdefault(line, []).append((m.start(), m.end()))
        for line, spans in by_line.items():
            assert newlines is not None
            begin = newlines[line - 2] + 1 if line > 1 else 0
            finish = newlines[line - 1] if line - 1 < len(newlines) else len(text)
            local = [
                (max(s, begin) - begin, min(e, finish) - begin) for s, e in spans
            ]
            out.append((rule.kind, line, _excerpt(text[begin:finish], local)))
    return out


# ---------------------------------------------------------------- tree scan

# files that are text by their name: a NUL byte in one is a finding, never a reason to skip it
TEXT_SUFFIXES = (".md", ".txt", ".py", ".sh", ".toml", ".yaml", ".yml", ".json", ".ts", ".js",
                 ".svelte", ".css", ".html", ".svg", ".cfg", ".ini")


def scan_tree(root: Path, files: list[str]) -> list[Finding]:
    """Check the given paths (relative to root) for content that must not ship."""
    root = Path(root)
    findings: list[Finding] = []
    for rel in files:
        rel = rel.replace(os.sep, "/")
        path = root / rel
        rules = [r for r in RULES if not allowed(r.kind, rel)]

        # The path itself is text too; findings on it use line 0.
        for kind, _line, excerpt in scan_text(rel, rules):
            findings.append(Finding(kind, rel, 0, excerpt))
        if not allowed("bear-art", rel) and _ART_PATH_RE.match(rel.rsplit("/", 1)[-1]):
            findings.append(Finding("bear-art", rel, 0, "image file name"))

        try:
            st = path.lstat()
        except OSError:
            continue  # listed but missing from the working tree
        if path.is_symlink():
            text: str | None = os.readlink(path)
            size = 0
        elif path.is_file():
            size = st.st_size
            try:
                data = path.read_bytes()
            except OSError:
                continue
            text = None
            if b"\x00" not in data:
                try:
                    text = data.decode("utf-8")
                except UnicodeDecodeError:
                    text = None  # binary: only path and size checks apply
            elif rel.lower().endswith(TEXT_SUFFIXES) and not allowed("nul-byte", rel):
                # a text file with a NUL byte reads as binary to git, so a diff, a review and
                # the checks above would all skip it: the byte itself is the finding, and the
                # rest is checked with it taken out
                nul = data.count(b"\x00")
                findings.append(Finding("nul-byte", rel, 0, f"{nul} NUL bytes in a text file"))
                try:
                    text = data.replace(b"\x00", b"").decode("utf-8")
                except UnicodeDecodeError:
                    text = None
        else:
            continue  # directories, submodules

        if size > MAX_BYTES and not allowed("big-file", rel):
            findings.append(Finding("big-file", rel, 0, f"{size} bytes"))
        if text:
            for kind, line, excerpt in scan_text(text, rules):
                findings.append(Finding(kind, rel, line, excerpt))
    findings.sort(key=lambda f: (f.path, f.line, f.kind))
    return findings


# ---------------------------------------------------------------- workflows

_LITERALS = ("self-hosted", "pull_request_target", "workflow_run")
_SECRET_RE = re.compile(r"\$\{\{\s*secrets\.([A-Za-z0-9_]+)")
_USES_RE = re.compile(r"^\s*(?:-\s*)?uses:\s*[\"']?([^\"'\s#]+)")
_SHA_RE = re.compile(r"[0-9a-f]{40}\Z")


def scan_workflows(root: Path) -> list[Finding]:
    """Check GitHub Actions workflows for risky triggers, runners and refs."""
    root = Path(root)
    wf_dir = root / ".github" / "workflows"
    if not wf_dir.is_dir():
        return []
    files = sorted(set(wf_dir.glob("*.yml")) | set(wf_dir.glob("*.yaml")))
    findings: list[Finding] = []
    for wf in files:
        rel = wf.relative_to(root).as_posix()
        if allowed("workflow", rel) or not wf.is_file():
            continue
        text = wf.read_text("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            spans: list[tuple[int, int]] = []
            for lit in _LITERALS:
                for m in re.finditer(re.escape(lit), line):
                    spans.append(m.span())
            for m in _SECRET_RE.finditer(line):
                if m.group(1) != "GITHUB_TOKEN":
                    spans.append(m.span())
            m = _USES_RE.match(line)
            if m:
                target = m.group(1)
                if not target.startswith("./"):
                    ref = target.rsplit("@", 1)[1] if "@" in target else ""
                    if not _SHA_RE.match(ref):
                        spans.append(m.span(1))
            if spans:
                findings.append(Finding("workflow", rel, n, _excerpt(line, spans)))
    return findings


# ---------------------------------------------------------------- commits

def scan_message(text: str, label: str) -> list[Finding]:
    """Check free text such as a commit message or a PR title or body."""
    return [
        Finding("commit", label, line, f"[{kind}] {excerpt}")
        for kind, line, excerpt in scan_text(text, COMMIT_RULES, in_commit=True)
    ]


# Dependabot's own identity, and the sign-off it writes on its own commits. The bot's sign-off
# counts only on a commit the bot both wrote and committed; anyone else's commit (a person who
# rebased or edited a Dependabot branch included) needs that person's own sign-off.
BOT_NAME = "dependabot[bot]"
BOT_EMAIL = "49699333+dependabot[bot]@" + NOREPLY_DOMAIN
BOT_SIGNOFF = "Signed-off-by: dependabot[bot] <support@" + "github.com>"
_SIGNOFF_RE = re.compile(r"^Signed-off-by: (.+?) <([^<>]+)>\s*$", re.M)


def is_bot(name: str, email: str) -> bool:
    return name == BOT_NAME and email.lower() == BOT_EMAIL.lower()


# GitHub's own identity as the committer of a commit it writes for a person: a pull request
# squash-merged or merged on the site or through its API (the push run on main checks it).
# Only as the committer: the author is still the person, with their own no-reply address and
# sign-off.
GITHUB_COMMITTER = ("GitHub", "noreply@" + "github.com")


def is_github_committer(name: str, email: str) -> bool:
    return name == GITHUB_COMMITTER[0] and email.lower() == GITHUB_COMMITTER[1]


def is_bots_own(author: tuple[str, str], committer: tuple[str, str]) -> bool:
    """A commit Dependabot wrote, committed by the bot itself or by GitHub for it (Dependabot's
    commits are made through GitHub, which commits them as ``GITHUB_COMMITTER``; so are its
    pull requests squash-merged on main). A person committing a bot commit is not this."""
    return is_bot(*author) and (is_bot(*committer) or is_github_committer(*committer))


def dco_problem(author: tuple[str, str], committer: tuple[str, str], body: str) -> str | None:
    """Why a commit's sign-off does not hold, or None. ``author`` and ``committer``: (name,
    email).

    - A commit Dependabot wrote and committed (itself, or GitHub for it: ``is_bots_own``) may
      carry the bot's own sign-off (``BOT_SIGNOFF``).
    - Any other commit needs a sign-off with its author's address; one the bot wrote but a
      person committed (a rebase or an edit of its branch) may instead carry the committer's,
      who then certifies it. The bot's sign-off counts on no commit but the bot's own."""
    offs = [(m[1].strip(), m[2].strip().lower()) for m in _SIGNOFF_RE.finditer(body)]
    bot_commit = is_bots_own(author, committer)
    if bot_commit and BOT_SIGNOFF in body.splitlines():
        return None
    human = [o for o in offs if o != (BOT_NAME, "support@" + "github.com")]
    emails = {e for _, e in human}
    if author[1].lower() in emails:
        return None
    if is_bot(*author) and committer[1].lower() in emails:
        return None
    if not offs:
        return "no Signed-off-by line (git commit -s)"
    if len(human) < len(offs):
        return "the Dependabot sign-off counts only on a commit Dependabot wrote and committed"
    return "no Signed-off-by line with the author's address (git commit -s)"


def scan_commits(range_spec: str, repo: str | Path = ".", dco: bool = False) -> list[Finding]:
    """Check author and committer emails and messages for a range of commits; with ``dco``,
    each message also carries a sign-off (``Signed-off-by:``, the Developer Certificate of
    Origin) matching its author (``dco_problem``)."""
    proc = subprocess.run(
        [
            "git", "-C", str(repo), "log",
            "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x1e", range_spec, "--",
        ],
        capture_output=True,
        check=True,
    )
    findings: list[Finding] = []
    for record in proc.stdout.decode("utf-8", errors="replace").split("\x1e"):
        record = record.lstrip("\n")
        if not record.strip():
            continue
        parts = record.split("\x00", 5)
        if len(parts) < 6:
            continue
        sha, a_name, author, c_name, committer, body = parts
        label = sha[:12]
        for role, name, email in (("author", a_name, author), ("committer", c_name, committer)):
            if role == "committer" and is_github_committer(name, email):
                continue
            if not email.lower().endswith("@" + NOREPLY_DOMAIN):
                findings.append(
                    Finding(
                        "commit", label, 0, f"{role} email *** is not a GitHub no-reply address"
                    )
                )
        scanned = body
        if is_bots_own((a_name, author), (c_name, committer)):
            # the bot's own sign-off names GitHub's support address: not a person's
            scanned = "\n".join(ln for ln in body.splitlines() if ln != BOT_SIGNOFF)
        findings.extend(scan_message(scanned, label))
        if dco:
            why = dco_problem((a_name, author), (c_name, committer), body)
            if why:
                findings.append(Finding("commit", label, 0, why))
    return findings


# ---------------------------------------------------------------- CLI


def _tracked_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"], capture_output=True, check=True
    )
    return [p for p in proc.stdout.decode("utf-8", errors="replace").split("\0") if p]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check the tree or commits before publishing.")
    parser.add_argument(
        "--commits", metavar="RANGE", help="check commits in RANGE instead of the tree"
    )
    parser.add_argument("--title", help="PR title to check (default: $PR_TITLE)")
    parser.add_argument("--body", help="PR body to check (default: $PR_BODY)")
    parser.add_argument(
        "--dco",
        action="store_true",
        help="with --commits: every commit is signed off (git commit -s)",
    )
    args = parser.parse_args(argv)

    title = args.title if args.title is not None else os.environ.get("PR_TITLE")
    body = args.body if args.body is not None else os.environ.get("PR_BODY")

    findings: list[Finding] = []
    try:
        if args.commits:
            findings += scan_commits(args.commits, dco=args.dco)
        else:
            root = Path.cwd()
            findings += scan_tree(root, _tracked_files(root))
            findings += scan_workflows(root)
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        detail = getattr(exc, "stderr", b"") or b""
        if isinstance(detail, bytes):
            detail = detail.decode("utf-8", errors="replace")
        print(f"scrub: git failed: {detail.strip() or exc}", file=sys.stderr)
        return 2
    if title:
        findings += scan_message(title, "pr-title")
    if body:
        findings += scan_message(body, "pr-body")

    if not findings:
        print("scrub: clean")
        return 0
    for f in findings:
        print(f"{f.kind} {f.path}:{f.line}: {f.excerpt}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
