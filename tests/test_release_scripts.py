"""The release scripts (scripts/release): the version rules, the notes and their attribution
guard, and the manifest. No network: git runs on local repositories in tmp_path."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import tomllib
from datetime import UTC, datetime
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts" / "release"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"release_{name}", SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


decide = _load("decide")
notes = _load("notes")
publish = _load("publish")


# -- decide --------------------------------------------------------------------------------


def test_parse_reads_stable_nightly_and_the_retired_rc_tags():
    assert decide.parse("v0.2.0") == (0, 2, 0, None, None)
    assert decide.parse("v0.7.0-dev12") == (0, 7, 0, "dev", 12)
    assert decide.parse("v1.10.3-rc2") == (1, 10, 3, "rc", 2)
    for bad in ("0.2.0", "v0.2", "v0.2.0rc1", "v0.7.0.dev12"):
        assert decide.parse(bad) is None


def test_nightly_builds_toward_the_next_stable_minor_counted_never_dated():
    assert decide.next_nightly([]) == ("0.7.0.dev1", "v0.7.0-dev1", None)   # the floor
    tags = ["v0.5.27", "v0.5.28", "v0.5.27-rc1"]
    assert decide.next_nightly(tags) == ("0.6.0.dev1", "v0.6.0-dev1", "v0.5.28")
    tags += ["v0.6.0-dev1", "v0.6.0-dev2"]
    assert decide.next_nightly(tags) == ("0.6.0.dev3", "v0.6.0-dev3", "v0.6.0-dev2")
    # after the promotion of 0.6.0, nightly moves on to 0.7.0
    assert decide.next_nightly([*tags, "v0.6.0"]) == ("0.7.0.dev1", "v0.7.0-dev1", "v0.6.0")


def test_a_promotion_is_the_nightly_builds_minor_from_its_own_tag():
    tags = ["v0.5.28", "v0.6.0-dev1", "v0.6.0-dev2"]
    assert decide.promotion(tags, "v0.6.0-dev2") == ("0.6.0", "v0.6.0", "v0.5.28",
                                                     "release/0.6")
    with pytest.raises(decide.DecideError, match="already exists"):
        decide.promotion([*tags, "v0.6.0"], "v0.6.0-dev2")
    with pytest.raises(decide.DecideError, match="vX.Y.0-devN"):
        decide.promotion(tags, "v0.5.27-rc1")


def test_a_stable_fix_is_the_next_patch_on_its_line():
    tags = ["v0.6.0", "v0.6.1", "v0.7.0-dev3", "v0.5.28"]
    assert decide.next_fix(tags) == ("0.6.2", "v0.6.2", "v0.6.1", "release/0.6")
    with pytest.raises(decide.DecideError, match="no stable release yet"):
        decide.next_fix(["v0.1.0-dev1"])


@pytest.mark.parametrize("pyproject", ["pyproject.toml"])
def test_a_checkout_past_a_nightly_tag_counts_from_the_last_release(tmp_path, pyproject):
    """setuptools-scm refuses to count past vX.Y.0-devN ("choosing custom numbers for the .devX
    distance is not supported"): after v0.6.0-dev1, no clone with the tags could uv sync. The
    version's git describe skips the nightly tags."""
    import shlex
    import tomllib

    raw = tomllib.loads((SCRIPTS.parents[1] / pyproject).read_text())["tool"]["hatch"][
        "version"]["raw-options"]
    describe = shlex.split(raw["scm"]["git"]["describe_command"])

    def git(*a):
        return subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=t",
                               "-c", "user.email=t@example.invalid", *a],
                              capture_output=True, text=True, check=True).stdout.strip()

    git("init", "-q")
    for tag in ("v0.5.29", "v0.6.0-dev1", None):
        git("commit", "-q", "--allow-empty", "-m", tag or "after")
        if tag:
            git("tag", tag)
    assert subprocess.run(describe, cwd=tmp_path, capture_output=True, text=True,
                          check=True).stdout.startswith("v0.5.29-2-g")


def test_the_rc_flag_is_retired_with_the_reason(tmp_path):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    with pytest.raises(decide.DecideError, match="retired"):
        decide.decide(afk, brb, prerelease="rc1")


def _repo(path: Path) -> Path:
    path.mkdir()
    for cmd in (["init", "-q", "-b", "main"], ["config", "user.name", "t"],
                ["config", "user.email", "t@example.invalid"],
                ["commit", "-q", "--allow-empty", "-m", "first"]):
        subprocess.run(["git", "-C", str(path), *cmd], check=True)
    return path


def _git(path: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(path), *args], check=True, capture_output=True)


def test_the_dead_release_workflow_is_gone():
    # it never ran green (three runs, 2026-10-10 to 10-12) and waited on a credential; the one
    # way to cut is cut_local.sh (finding 6)
    root = SCRIPTS.parent.parent
    assert not (root / ".github" / "workflows" / "release.yml").exists()
    for f in (*SCRIPTS.iterdir(), root / "packages" / "kranto" / "README.md"):
        text = f.read_text() if f.is_file() else ""
        assert "release.yml" not in text and "KRANTO_DEPLOY_KEY" not in text, f
        assert "GITHUB_OUTPUT" not in text and "--scheduled" not in text, f


def test_a_cut_releases_and_records_commits(tmp_path):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    out = decide.decide(afk, brb)
    assert out["release"] and out["version"] == "0.7.0.dev1" and out["prerelease"]
    assert out["line"] == "nightly" and not out["held"]
    assert len(out["commits"]["kranto"]) == 40


def test_a_page_with_a_web_ui_needs_node_to_cut(tmp_path):
    """the page's web UI is built at release: without Node 22.12 nothing is cut;
    a the page without one never asks."""
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    assert decide.decide(afk, brb, node=lambda: None)["release"]
    web = brb / "src" / "kranto" / "page" / "ui" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text("{}")
    for old in (None, (20, 19), (22, 11)):
        with pytest.raises(decide.DecideError, match="Node 22.12 or newer"):
            decide.decide(afk, brb, node=lambda v=old: v)
    for ok in ((22, 12), (24, 21)):
        assert decide.decide(afk, brb, node=lambda v=ok: v)["release"]


def test_the_release_build_builds_the_web_ui_and_the_smoke_loads_it():
    build = (SCRIPTS / "build.sh").read_text()
    assert build.index('python3 "$SRC/scripts/dev/build_ui.py"') < build.index(
        'uv build --wheel --out-dir "$DIST" "$SRC"')
    smoke = (SCRIPTS / "smoke.sh").read_text()
    assert "/app/app-" in smoke and 'curl -sf -o /dev/null "http://127.0.0.1:$PORT/brb/$asset"' \
        in smoke


def test_users_never_need_node():
    """The setup guide installs Kranto without Node or npm: the wheel carries the built UI."""
    guide = (Path(__file__).resolve().parent.parent / "docs" / "setup.md").read_text().lower()
    assert "npm" not in guide and "node.js" not in guide and "nodejs" not in guide


def test_decide_prints_its_json(tmp_path, capsys):
    afk, brb = _repo(tmp_path / "afk"), _repo(tmp_path / "brb")
    assert decide.main(["--afk", str(afk), "--brb", str(brb)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tag"] == "v0.7.0-dev1" and out["version"] == "0.7.0.dev1" and out["prerelease"]


# -- notes and the attribution guard --------------------------------------------------------

AFK_PRS = [{"number": 121, "title": "Releases:  versions from tags",
            "mergedAt": "2026-10-10T20:00:00Z"},
           {"number": 120, "title": "Prompt versions you can roll back to",
            "mergedAt": "2026-10-10T08:00:00Z"}]
BRB_PRS = [{"number": 77, "title": "Claude Code harness: the fake harness for tests",
            "mergedAt": "2026-10-10T09:00:00Z"}]


def test_a_milestones_intro_opens_the_notes_before_the_changes():
    text = notes.render("0.4.0", "v0.4.0", "iddv/kranto", "iddv/kranto", AFK_PRS, BRB_PRS,
                        "2026-10-10T00:00:00Z", intro="## What 0.4.0 is\n\nOne install.\n")
    assert text.index("## What 0.4.0 is") < text.index("## Changes") < text.index("## Merged")
    assert "\nOne install.\n" in text
    assert "## Changes" not in _render()                   # no intro: as before


def _render(afk=AFK_PRS, brb=BRB_PRS):
    return notes.render("0.2.0", "v0.2.0", "iddv/kranto", "iddv/kranto", afk, brb,
                        "2026-10-03T00:00:00Z")


def test_notes_list_the_merges_then_pins_install_and_verify():
    text = _render()
    assert text.index("## Merged") < text.index("## Pins") \
        < text.index("## Install") < text.index("## Verify")
    # oldest merge first, whitespace in a title collapsed
    assert text.index("(#120)") < text.index("(#121)")
    assert "- Releases: versions from tags" in text
    assert "One wheel, `kranto 0.2.0`" in text
    assert '"kranto[connections,notify,mcp] @ ./kranto-0.2.0-py3-none-any.whl"' in text
    assert "sha256sum -c SHA256SUMS" in text


def test_the_pins_tell_a_cub_author_the_sdk_and_its_tag():
    text = notes.render("0.2.0", "v0.2.0", "iddv/kranto", "iddv/kranto", AFK_PRS, BRB_PRS,
                        "2026-10-03T00:00:00Z", sdk="1.2.0")
    pins = text.split("## Pins", 1)[1].split("## Install", 1)[0]
    assert "`bears-cub-sdk 1.2.0`" in pins
    assert "git+https://github.com/iddv/kranto.git@v0.2.0#subdirectory=sdk" in pins
    assert "bears-cub-sdk" not in _render()                 # no version known: no line
    assert notes.sdk_version() == tomllib.loads(
        (Path(__file__).resolve().parents[1] / "sdk" / "pyproject.toml").read_text()
    )["project"]["version"]


def test_a_repo_with_no_changes_says_so():
    assert "## Merged\n\n- No changes." in _render(afk=[], brb=[])


def test_a_title_that_names_the_harness_is_not_attribution():
    text = _render()
    assert "Claude Code harness: the fake harness for tests" in text
    assert notes.attribution_hits(text) == []
    assert notes.attribution_hits("Use Claude for the pitch; Claude Code builds it") == []


# The attribution forms are assembled here, so this file carries none of them literally.
TOOL = "Claude" + " Code"
NOREPLY = "noreply" + "@" + "anthropic.com"


@pytest.mark.parametrize("line", [
    "Co-Authored" + "-By: Someone <x@example.invalid>",
    "  co-authored" + "-by: lower case",
    "Claude" + "-Session: https://example.invalid/s/1",
    "Generated with " + TOOL,
    f"Generated with [{TOOL}](https://example.invalid)",
    "Contact " + NOREPLY,
])
def test_attribution_lines_are_caught(line):
    assert notes.attribution_hits(f"- a title\n{line}\n") == [line.strip()]


def test_a_stable_cut_from_an_rc_lists_only_what_it_holds(monkeypatch):
    # 0.3.72's rc was cut at 19:48; #226 merged at 21:10 rides the next release
    prs = [{"number": 224, "title": "a", "mergedAt": "2026-10-16T19:30:00Z"},
           {"number": 225, "title": "b", "mergedAt": "2026-10-16T19:40:12Z"},
           {"number": 226, "title": "c", "mergedAt": "2026-10-16T21:10:00Z"}]
    monkeypatch.setattr(notes, "gh_json", lambda *a: prs)
    assert [p["number"] for p in notes.merged_since("o/r", "x")] == [224, 225, 226]
    got = notes.merged_since("o/r", "x", "2026-10-16T21:40:12+02:00")   # the commit's own time
    assert [p["number"] for p in got] == [224, 225]


def test_notes_main_refuses_attribution(tmp_path, monkeypatch, capsys):
    bad = [{"number": 9, "title": "Fix", "mergedAt": "2026-10-10T00:00:00Z"}]
    monkeypatch.setattr(notes, "merged_since",
                        lambda repo, since, until=None, base="main", label="":
                        bad if repo else [])
    out = tmp_path / "notes.md"
    assert notes.main(["--tag", "v0.2.0", "--version", "0.2.0", "--since", "2026-10-01",
                       "--out", str(out)]) == 0
    assert out.exists()
    bad[0]["title"] = f"Fix ({NOREPLY})"
    out.unlink()
    assert notes.main(["--tag", "v0.2.0", "--version", "0.2.0", "--since", "2026-10-01",
                       "--out", str(out)]) == 1
    assert not out.exists()
    assert "attribution" in capsys.readouterr().err


# -- the manifest ------------------------------------------------------------------------


def _dist(tmp_path: Path, version: str = "0.2.0", names=("kranto", "kranto.page")):
    dist = tmp_path / "dist"
    dist.mkdir()
    lines = []
    for n in names:
        w = dist / f"{n}-{version}-py3-none-any.whl"
        w.write_bytes(f"wheel {n} {version}".encode())
        lines.append(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
    (dist / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return dist


def test_manifest_shape(tmp_path):
    dist = _dist(tmp_path)
    m = publish.manifest(dist, "0.2.0", "v0.2.0", "iddv/kranto",
                         {"kranto": "a" * 40, "kranto.page": "b" * 40},
                         now=datetime(2026, 10, 11, 5, 17, tzinfo=UTC))
    assert set(m) == {"version", "tag", "published_at", "python", "pins", "commits", "wheels",
                      "notes_url", "verify"}
    assert m["pins"] == {"kranto": "0.2.0", "kranto.page": "0.2.0"}
    assert [w["name"] for w in m["wheels"]] == [f"{n}-0.2.0-py3-none-any.whl"
                                               for n in ("kranto", "kranto.page")]
    assert all(len(w["sha256"]) == 64 and w["size"] > 0 for w in m["wheels"])
    assert m["published_at"] == "2026-10-11T05:17:00Z" and m["verify"] == "sha256"
    assert m["notes_url"].endswith("/releases/tag/v0.2.0")


def test_manifest_refuses_a_wrong_set(tmp_path):
    dist = _dist(tmp_path, names=("kranto",))
    with pytest.raises(publish.PublishError, match="exactly"):
        publish.check_set(dist, "0.2.0")


def test_manifest_refuses_a_tampered_wheel(tmp_path):
    dist = _dist(tmp_path)
    (dist / "kranto.page-0.2.0-py3-none-any.whl").write_bytes(b"something else")
    with pytest.raises(publish.PublishError, match="does not match"):
        publish.check_set(dist, "0.2.0")


def test_manifest_refuses_mixed_versions(tmp_path):
    dist = _dist(tmp_path)
    (dist / "kranto-0.2.0-py3-none-any.whl").rename(dist / "kranto-0.1.9-py3-none-any.whl")
    with pytest.raises(publish.PublishError, match="not version"):
        publish.check_set(dist, "0.2.0")


def test_rc_check_takes_any_release_tag_and_a_scratch_place(tmp_path):
    # the check of a published build (a nightly, a held stable, an old rc); its real run is
    # seven steps on a scratch unit: install the previous release, update, roll back, update
    # again, every page, the odd installs
    script = SCRIPTS / "rc_check.sh"
    assert script.stat().st_mode & 0o100
    env = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    r = subprocess.run(["bash", str(script), "v0.3"], capture_output=True, text=True, env=env)
    assert r.returncode == 2 and "not a release tag" in r.stderr
    for tag in ("v0.3.72-rc1", "v0.7.0-dev12", "v0.7.0"):
        r = subprocess.run(["bash", str(script), tag], capture_output=True, text=True, env=env)
        assert r.returncode != 0 and "E2E_DIR" in r.stderr, tag
    text = script.read_text()
    assert 'KRANTO_UNIT="kranto-rc-$PORT.service"' in text           # never the live unit
    assert "teardown" in text and "killed" in text
