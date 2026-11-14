"""The sign-off check (``scripts/ci/scrub.py --commits RANGE --dco``, ci.yml's gitleaks job):
every commit carries a ``Signed-off-by`` with its author's address. Dependabot's own sign-off
(``dependabot[bot] <support@...>``) counts on a commit Dependabot both wrote and committed, and
on no other: a person's commit carrying it still needs the person's own, and a Dependabot commit
a person committed (a rebase or an edit of its branch) needs the committer's sign-off, who then
certifies it. Real git commits in tmp_path; no network."""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ci_scrub_dco", ROOT / "scripts" / "ci" /
                                              "scrub.py")
scrub = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = scrub              # its dataclasses look their module up
spec.loader.exec_module(scrub)

PERSON = ("dev one", "7+devone@" + scrub.NOREPLY_DOMAIN)
OTHER = ("dev two", "8+devtwo@" + scrub.NOREPLY_DOMAIN)
BOT = (scrub.BOT_NAME, scrub.BOT_EMAIL)


def signoff(who: tuple[str, str]) -> str:
    return f"Signed-off-by: {who[0]} <{who[1]}>"


def repo(tmp: Path) -> Path:
    env = _env()
    subprocess.run(["git", "init", "-q", "-b", "main", str(tmp)], check=True, env=env)
    return tmp


def _env(**more: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1", **more)
    return env


def commit(r: Path, author, committer, message: str) -> None:
    env = _env(GIT_AUTHOR_NAME=author[0], GIT_AUTHOR_EMAIL=author[1],
               GIT_COMMITTER_NAME=committer[0], GIT_COMMITTER_EMAIL=committer[1])
    subprocess.run(["git", "-C", str(r), "-c", "commit.gpgsign=false", "commit", "-q",
                    "--allow-empty", "-m", message], check=True, env=env)


def found(r: Path) -> list[str]:
    return [f.excerpt for f in scrub.scan_commits("HEAD~1..HEAD" if _n(r) > 1 else "HEAD",
                                                  repo=r, dco=True)]


def sign_offs(r: Path) -> list[str]:
    """The sign-off findings only (an address in a message is the words' check)."""
    return [f for f in found(r) if not f.startswith("[")]


def _n(r: Path) -> int:
    return int(subprocess.run(["git", "-C", str(r), "rev-list", "--count", "HEAD"],
                              capture_output=True, text=True, check=True).stdout)


def test_a_person_signs_off_their_own_commit(tmp_path):
    r = repo(tmp_path)
    commit(r, PERSON, PERSON, f"Fix the start\n\n{signoff(PERSON)}")
    assert found(r) == []
    commit(r, PERSON, PERSON, "Fix the start again")
    assert found(r) == ["no Signed-off-by line (git commit -s)"]
    commit(r, PERSON, PERSON, f"Fix it for someone\n\n{signoff(OTHER)}")
    assert found(r) == ["no Signed-off-by line with the author's address (git commit -s)"]


def test_dependabots_own_commit_may_carry_its_own_sign_off(tmp_path):
    r = repo(tmp_path)
    commit(r, BOT, BOT, f"Bump a dependency from 1 to 2\n\n{scrub.BOT_SIGNOFF}")
    assert found(r) == []                 # its support address is not reported as an email


def test_a_persons_commit_with_the_bots_sign_off_is_refused(tmp_path):
    r = repo(tmp_path)
    commit(r, PERSON, PERSON, f"Bump by hand\n\n{scrub.BOT_SIGNOFF}")
    got = found(r)
    assert "the Dependabot sign-off counts only on a commit Dependabot wrote and committed" in got
    assert any("[email]" in g for g in got)           # and its address is still an email here
    commit(r, PERSON, PERSON, f"Bump by hand\n\n{scrub.BOT_SIGNOFF}\n{signoff(PERSON)}")
    assert sign_offs(r) == []


def test_a_bot_commit_a_person_committed_needs_the_committers_sign_off(tmp_path):
    """A person who rebased or edited Dependabot's branch committed it: the bot's sign-off no
    longer counts; the committer's does (they certify what they committed)."""
    r = repo(tmp_path)
    commit(r, BOT, PERSON, f"Bump a dependency from 1 to 2\n\n{scrub.BOT_SIGNOFF}")
    assert "the Dependabot sign-off counts only on a commit Dependabot wrote and committed" \
        in found(r)
    commit(r, BOT, PERSON, f"Bump a dependency from 1 to 2\n\n{scrub.BOT_SIGNOFF}\n"
                           f"{signoff(PERSON)}")
    assert sign_offs(r) == []
    commit(r, BOT, PERSON, f"Bump a dependency from 1 to 2\n\n{signoff(OTHER)}")
    assert found(r) == ["no Signed-off-by line with the author's address (git commit -s)"]


def test_a_look_alike_bot_identity_is_not_the_bot(tmp_path):
    r = repo(tmp_path)
    fake = (scrub.BOT_NAME, "9+someone@" + scrub.NOREPLY_DOMAIN)
    commit(r, fake, fake, f"Bump\n\n{scrub.BOT_SIGNOFF}")
    assert "the Dependabot sign-off counts only on a commit Dependabot wrote and committed" \
        in found(r)
