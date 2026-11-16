"""The release scripts (scripts/release): the version rules, the notes and their attribution
guard, and the manifest. No network: git runs on local repositories in tmp_path."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import re
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
guards = _load("guards")
compat = _load("compat_wheels")
names = _load("names")
LEGACY, PRODUCT = names.legacy(), names.product()


# -- decide --------------------------------------------------------------------------------


def test_parse_reads_stable_nightly_and_the_retired_rc_tags():
    assert decide.parse("v0.2.0") == (0, 2, 0, None, None)
    assert decide.parse("v0.7.0-dev12") == (0, 7, 0, "dev", 12)
    assert decide.parse("v1.10.3-rc2") == (1, 10, 3, "rc", 2)
    for bad in ("0.2.0", "v0.2", "v0.2.0rc1", "v0.7.0.dev12"):
        assert decide.parse(bad) is None


def test_nightly_builds_toward_the_next_stable_minor_counted_never_dated():
    assert decide.next_nightly([]) == ("0.7.0.dev1", "v0.7.0-dev1", None)   # the floor
    tags = ["v0.7.27", "v0.7.28", "v0.7.27-rc1"]
    assert decide.next_nightly(tags) == ("0.8.0.dev1", "v0.8.0-dev1", "v0.7.28")
    tags += ["v0.8.0-dev1", "v0.8.0-dev2"]
    assert decide.next_nightly(tags) == ("0.8.0.dev3", "v0.8.0-dev3", "v0.8.0-dev2")
    # after the promotion of 0.8.0, nightly moves on to 0.9.0
    assert decide.next_nightly([*tags, "v0.8.0"]) == ("0.9.0.dev1", "v0.9.0-dev1", "v0.8.0")


def test_no_nightly_is_numbered_below_the_first_tag_of_this_repository():
    """An install made before the rename runs 0.6.0.devN: whatever older tags a clone holds, the
    next nightly is v0.7.0-dev1 or newer, never v0.6.0-devN+1."""
    assert decide.FLOOR == (0, 7, 0)
    old = ["v0.5.27", "v0.5.28", "v0.6.0-dev17", "v0.6.0-dev18"]
    assert decide.next_nightly(old) == ("0.7.0.dev1", "v0.7.0-dev1", "v0.5.28")
    assert decide.next_nightly([*old, "v0.7.0-dev1"]) == ("0.7.0.dev2", "v0.7.0-dev2",
                                                         "v0.7.0-dev1")


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
    src = _repo(tmp_path / "src")
    with pytest.raises(decide.DecideError, match="retired"):
        decide.decide(src, prerelease="rc1")


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


def test_a_cut_releases_and_records_its_commit(tmp_path):
    src = _repo(tmp_path / "src")
    out = decide.decide(src)
    assert out["release"] and out["version"] == "0.7.0.dev1" and out["prerelease"]
    assert out["line"] == "nightly" and not out["held"]
    assert len(out["commit"]) == 40 and out["since"] is None


def test_a_page_with_a_web_ui_needs_node_to_cut(tmp_path):
    """The page's web UI is built at release: without Node 22.12 nothing is cut;
    a version of the page without one never asks."""
    src = _repo(tmp_path / "src")
    assert decide.decide(src, node=lambda: None)["release"]
    web = src / "src" / "kranto" / "page" / "ui" / "web"
    web.mkdir(parents=True)
    (web / "package.json").write_text("{}")
    for old in (None, (20, 19), (22, 11)):
        with pytest.raises(decide.DecideError, match="Node 22.12 or newer"):
            decide.decide(src, node=lambda v=old: v)
    for ok in ((22, 12), (24, 21)):
        assert decide.decide(src, node=lambda v=ok: v)["release"]


def test_the_release_build_builds_the_web_ui_and_the_smoke_loads_it():
    build = (SCRIPTS / "build.sh").read_text()
    assert build.index('python3 "$SRC/scripts/dev/build_ui.py"') < build.index(
        'uv build --wheel --out-dir "$DIST" "$SRC"')
    smoke = (SCRIPTS / "smoke.sh").read_text()
    assert "/app/app-" in smoke and 'curl -sf -o /dev/null "http://127.0.0.1:$PORT/brb/$asset"' \
        in smoke
    # Kranto is served at / (/brb/ only redirects there; curl without -L reads an empty body)
    assert 'page="$(curl -sfL "http://127.0.0.1:$PORT/")"' in smoke


def test_every_kranto_import_in_the_release_scripts_exists():
    """A release script's inline Python imports only what the wheel has (the smoke once asked
    for the retired build policy, ``kranto.page.resources``, and stopped every cut)."""
    for script in sorted(SCRIPTS.glob("*.sh")):
        for mod, names_ in re.findall(r"^\s*from (kranto[\w.]*) import ([\w, ]+)$",
                                      script.read_text(), re.M):
            assert importlib.util.find_spec(mod), (script.name, mod)
            m = importlib.import_module(mod)
            for n in (x.strip() for x in names_.split(",")):
                assert hasattr(m, n) or importlib.util.find_spec(f"{mod}.{n}"), \
                    (script.name, f"{mod}.{n}")


def test_users_never_need_node():
    """The setup guide installs Kranto without Node or npm: the wheel carries the built UI."""
    guide = (Path(__file__).resolve().parent.parent / "docs" / "setup.md").read_text().lower()
    assert "npm" not in guide and "node.js" not in guide and "nodejs" not in guide


def test_decide_prints_its_json(tmp_path, capsys):
    src = _repo(tmp_path / "src")
    assert decide.main(["--src", str(src)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["tag"] == "v0.7.0-dev1" and out["version"] == "0.7.0.dev1" and out["prerelease"]


# -- notes and the attribution guard --------------------------------------------------------

AFK_PRS = [{"number": 121, "title": "Releases:  versions from tags",
            "mergedAt": "2026-10-10T20:00:00Z"},
           {"number": 120, "title": "Prompt versions you can roll back to",
            "mergedAt": "2026-10-10T08:00:00Z"}]
BRB_PRS = [{"number": 77, "title": "Claude Code harness: the fake harness for tests",
            "mergedAt": "2026-10-10T09:00:00Z"}]
PRS = AFK_PRS + BRB_PRS


def test_a_milestones_intro_opens_the_notes_before_the_changes():
    text = notes.render("0.4.0", "v0.4.0", "iddv/kranto", PRS,
                        "2026-10-10T00:00:00Z", intro="## What 0.4.0 is\n\nOne install.\n")
    assert text.index("## What 0.4.0 is") < text.index("## Changes") < text.index("## Merged")
    assert "\nOne install.\n" in text
    assert "## Changes" not in _render()                   # no intro: as before


def _render(prs=None, shape="final"):
    return notes.render("0.2.0", "v0.2.0", "iddv/kranto", PRS if prs is None else prs,
                        "2026-10-03T00:00:00Z", shape=shape)


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
    text = notes.render("0.2.0", "v0.2.0", "iddv/kranto", PRS,
                        "2026-10-03T00:00:00Z", sdk="1.2.0")
    pins = text.split("## Pins", 1)[1].split("## Install", 1)[0]
    assert "`bears-cub-sdk 1.2.0`" in pins
    assert "git+https://github.com/iddv/kranto.git@v0.2.0#subdirectory=sdk" in pins
    assert "bears-cub-sdk" not in _render()                 # no version known: no line
    assert notes.sdk_version() == tomllib.loads(
        (Path(__file__).resolve().parents[1] / "sdk" / "pyproject.toml").read_text()
    )["project"]["version"]


def test_a_repo_with_no_changes_says_so():
    assert "## Merged\n\n- No changes." in _render(prs=[])


def test_the_crossings_notes_name_its_three_wheels_and_no_install_line():
    text = _render(shape="compat")
    pins = text.split("## Pins", 1)[1].split("## Install", 1)[0]
    assert sum(f"`{d} 0.2.0`" in pins for d in LEGACY.COMPAT_DISTS) == 3
    install = text.split("## Install", 1)[1].split("## Verify", 1)[0]
    assert "uv tool install" not in install and "install.sh" in install


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


# -- the manifest and the two shapes -------------------------------------------------------

FINAL = (PRODUCT.DIST,)
COMPAT = tuple(LEGACY.COMPAT_DISTS)


def _dist(tmp_path: Path, version: str = "0.2.0", names=FINAL):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    lines = []
    for n in names:
        w = dist / f"{n}-{version}-py3-none-any.whl"
        w.write_bytes(f"wheel {n} {version}".encode())
        lines.append(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
    (dist / "SHA256SUMS").write_text("\n".join(lines) + "\n")
    return dist


def test_the_final_manifest_pins_its_one_wheel(tmp_path):
    dist = _dist(tmp_path)
    m = publish.manifest(dist, "0.2.0", "v0.2.0", "iddv/kranto", "a" * 40,
                         now=datetime(2026, 10, 11, 5, 17, tzinfo=UTC))
    assert set(m) == {"version", "shape", "tag", "published_at", "python", "pins", "commits",
                      "wheels", "notes_url", "verify"}
    assert m["shape"] == 2 and m["pins"] == {PRODUCT.DIST: "0.2.0"}
    assert [w["name"] for w in m["wheels"]] == [f"{PRODUCT.DIST}-0.2.0-py3-none-any.whl"]
    assert all(len(w["sha256"]) == 64 and w["size"] > 0 for w in m["wheels"])
    assert m["published_at"] == "2026-10-11T05:17:00Z" and m["verify"] == "sha256"
    assert m["notes_url"].endswith("/releases/tag/v0.2.0")
    assert m["commits"] == {PRODUCT.DIST: "a" * 40}


def test_the_compat_manifest_is_what_the_old_helper_compares(tmp_path):
    """The old helper compares pins to exactly {server: V, page: V} and each listed wheel's
    hash to SHA256SUMS; any other wheel in the set is refused."""
    dist = _dist(tmp_path, names=COMPAT)
    m = publish.manifest(dist, "0.2.0", "v0.2.0-dev1", "iddv/kranto", "a" * 40)
    assert m["shape"] == 1 and m["version"] == "0.2.0"
    assert m["pins"] == {LEGACY.COMPAT_SERVER: "0.2.0", LEGACY.COMPAT_PAGE: "0.2.0"}
    sums = publish.read_sums(dist / "SHA256SUMS")
    assert [w["name"] for w in m["wheels"]] == [f"{d}-0.2.0-py3-none-any.whl" for d in COMPAT]
    assert all(sums[w["name"]] == w["sha256"] for w in m["wheels"])
    with pytest.raises(publish.PublishError, match="final shape, not compat"):
        publish.check_set(_dist(tmp_path / "f", names=FINAL), "0.2.0", "compat")


def test_a_set_must_be_exactly_one_shape(tmp_path):
    for i, bad in enumerate([(), COMPAT[:2], (*FINAL, *COMPAT), (*FINAL, COMPAT[1])]):
        with pytest.raises(publish.PublishError, match="exactly one of the two shapes"):
            publish.check_set(_dist(tmp_path / str(i), names=bad), "0.2.0")
    d = _dist(tmp_path / "x")
    (d / "other-0.2.0-py3-none-any.whl").write_bytes(b"x")
    with pytest.raises(publish.PublishError, match="unexpected file"):
        publish.check_set(d, "0.2.0")


def test_manifest_refuses_a_tampered_wheel(tmp_path):
    dist = _dist(tmp_path, names=COMPAT)
    (dist / f"{COMPAT[2]}-0.2.0-py3-none-any.whl").write_bytes(b"something else")
    with pytest.raises(publish.PublishError, match="does not match"):
        publish.check_set(dist, "0.2.0")


def test_manifest_refuses_mixed_versions(tmp_path):
    dist = _dist(tmp_path)
    w = dist / f"{PRODUCT.DIST}-0.2.0-py3-none-any.whl"
    w.rename(dist / f"{PRODUCT.DIST}-0.1.9-py3-none-any.whl")
    with pytest.raises(publish.PublishError, match="not version"):
        publish.check_set(dist, "0.2.0")


def _rel(tag, *wheels, draft=False):
    return {"tag_name": tag, "draft": draft,
            "assets": [{"name": f"{w}-{tag.lstrip('v').replace('-dev', '.dev')}-py3-none-any.whl"}
                       for w in wheels] + [{"name": "SHA256SUMS"}]}


def test_a_final_release_needs_a_previous_one_with_the_two_shape_helper():
    assert guards.TWO_SHAPE_MIN == "0.7.0.dev1"
    k0 = _rel("v0.7.0-dev1", *COMPAT)
    refuse = guards.shape_refusal
    assert refuse("final", "v0.7.0-dev2", [k0]) is None                   # K1, after K0
    assert "no release before" in refuse("final", "v0.7.0-dev1", [])
    assert "no release before" in refuse("final", "v0.7.0-dev2", [_rel("v0.7.0-dev1", *COMPAT,
                                                                        draft=True)])
    old = _rel("v0.6.0-dev18", *COMPAT)
    assert "older than v0.7.0-dev1" in refuse("final", "v0.6.0-dev19", [old])
    # a promotion: no stable before it here, so the nightly before it is what installs run
    assert refuse("final", "v0.7.0", [k0, _rel("v0.7.0-dev2", *FINAL)]) is None
    assert refuse("final", "v0.7.1", [_rel("v0.7.0", *FINAL)]) is None
    assert "not a release tag" in refuse("final", "main", [k0])


def test_compat_is_one_nightly_and_never_after_a_final_release():
    refuse = guards.shape_refusal
    assert refuse("compat", "v0.7.0-dev1", []) is None
    assert refuse("compat", "v0.7.0-dev1", [_rel("v0.7.0-dev1", *FINAL)]) is None   # a re-run
    assert "one nightly crossing" in refuse("compat", "v0.7.0", [])
    why = refuse("compat", "v0.7.0-dev3", [_rel("v0.7.0-dev1", *COMPAT),
                                           _rel("v0.7.0-dev2", *FINAL)])
    assert "a final release exists (v0.7.0-dev2)" in why
    assert refuse("compat", "v0.7.0-dev3", [_rel("v0.7.0-dev2", *FINAL, draft=True)]) is None


def test_guards_shape_reads_a_release_list_file(tmp_path, capsys):
    f = tmp_path / "releases.json"
    f.write_text(json.dumps([_rel("v0.7.0-dev1", *COMPAT), _rel("v0.7.0-dev2", *FINAL)]))
    assert guards.main(["shape", "final", "v0.7.0-dev3", "--releases", str(f)]) == 0
    assert guards.main(["shape", "compat", "v0.7.0-dev3", "--releases", str(f)]) == 1
    assert "a final release exists" in capsys.readouterr().err


def test_publish_runs_the_shape_guard_before_anything_is_pushed(tmp_path, monkeypatch):
    dist = _dist(tmp_path)
    (dist / "manifest.json").write_text("{}")
    pushed = []
    monkeypatch.setattr(publish, "push_tag", lambda *a: pushed.append(a) or "pushed")
    with pytest.raises(publish.PublishError, match="no release before"):
        publish.publish(dist, "0.2.0", "v0.7.0-dev1", "o/r", tmp_path, tmp_path / "n", True,
                        known=[])
    with pytest.raises(publish.PublishError, match="a final release exists"):
        publish.publish(_dist(tmp_path / "c", names=COMPAT), "0.2.0", "v0.7.0-dev3", "o/r",
                        tmp_path, tmp_path / "n", True, known=[_rel("v0.7.0-dev2", *FINAL)])
    assert pushed == []


# -- the compat wheels' trees -----------------------------------------------------------------


def test_the_servers_tree_is_the_real_pyproject_renamed_without_commands():
    real = (SCRIPTS.parents[1] / "pyproject.toml").read_text()
    text = compat.server_pyproject(real, LEGACY.COMPAT_SERVER, "0.7.0.dev1")
    data, want = tomllib.loads(text), tomllib.loads(real)
    assert data["project"]["name"] == LEGACY.COMPAT_SERVER
    assert data["project"]["version"] == "0.7.0.dev1" and "dynamic" not in data["project"]
    assert "scripts" not in data["project"]
    assert data["project"]["dependencies"] == want["project"]["dependencies"]
    extras = data["project"]["optional-dependencies"]
    assert {"connections", "notify", "mcp"} <= set(extras)
    assert extras == want["project"]["optional-dependencies"]
    assert "version" not in data["tool"]["hatch"]                      # no version from git
    assert data["tool"]["hatch"]["build"] == want["tool"]["hatch"]["build"]   # the same files


def test_the_meta_package_carries_both_commands_and_pins_the_other_two():
    entry = compat.entry_of(SCRIPTS.parents[1], PRODUCT)
    meta, server, page = COMPAT
    data = tomllib.loads(compat.meta_pyproject(meta, server, page, "0.7.0.dev1",
                                               [PRODUCT.COMMAND, LEGACY.COMMAND], entry, "N"))
    p = data["project"]
    assert p["name"] == meta and p["version"] == "0.7.0.dev1"
    assert p["dependencies"] == [f"{server}[connections,notify]==0.7.0.dev1",
                                 f"{page}==0.7.0.dev1"]
    assert p["optional-dependencies"] == {"mcp": [f"{server}[mcp]==0.7.0.dev1"]}
    assert p["scripts"] == {PRODUCT.COMMAND: entry, LEGACY.COMMAND: entry}
    assert data["tool"]["hatch"]["build"]["targets"]["wheel"] == {"bypass-selection": True}
    empty = tomllib.loads(compat.page_pyproject(page, "0.7.0.dev1", "N"))
    assert empty["project"]["name"] == page and "dependencies" not in empty["project"]
    assert "scripts" not in empty["project"]
    assert empty["tool"]["hatch"]["build"]["targets"]["wheel"] == {"bypass-selection": True}


def test_build_sh_takes_a_shape_and_writes_the_manifest():
    build = (SCRIPTS / "build.sh").read_text()
    assert "--shape" in build and "compat_wheels.py" in build
    assert 'guards.py" shape compat' in build                 # compat refused after a final
    assert 'publish.py" manifest' in build and "--shape \"$SHAPE\"" in build
    r = subprocess.run(["bash", str(SCRIPTS / "build.sh"), "--shape", "other"],
                       capture_output=True, text=True)
    assert r.returncode == 2 and "final or compat" in r.stderr


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
    assert 'KRANTO_UNIT="${KRANTO_UNIT:-kranto-rc-$PORT.service}"' in text
    assert "teardown" in text and "killed" in text


def _rc(tmp_path, *args, **env):
    base = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path / "home"), "PORT": "8971",
            "E2E_DIR": str(tmp_path / "e2e")}
    return subprocess.run(["bash", str(SCRIPTS / "rc_check.sh"), *args], capture_output=True,
                          text=True, env={**base, **env}, timeout=60)


def test_rc_check_dry_run_names_its_scratch_place_and_runs_nothing(tmp_path):
    copy = tmp_path / "a-home"
    copy.mkdir()
    r = _rc(tmp_path, "v0.7.0-dev2", "v0.6.0-dev18", "--home-copy", str(copy), "--dry-run",
            PREV_REPO="o/before", KRANTO_UNIT="scratch-rc.service",
            UV_TOOL_DIR=str(tmp_path / "t"), UV_TOOL_BIN_DIR=str(tmp_path / "b"))
    assert r.returncode == 0, r.stderr
    out = r.stdout
    assert f"v0.6.0-dev18 (o/before) -> v0.7.0-dev2 ({names.repo()})" in out
    assert "127.0.0.1:8971 (scratch-rc.service)" in out and f"a copy of {copy}" in out
    assert f"tools {tmp_path / 't'}" in out
    assert "FROM_TAG=v0.6.0-dev18 e2e_update.sh install        (expects 0.6.0.dev18)" in out
    assert not (tmp_path / "e2e").exists()                    # nothing ran, nothing written
    r = _rc(tmp_path, "v0.7.0-dev2", "v0.7.0-dev1", "--dry-run")
    assert r.returncode == 0 and "(kranto-rc-8971.service)" in r.stdout and "empty" in r.stdout


def test_rc_check_refuses_a_real_installs_unit_and_a_missing_copy(tmp_path):
    for unit in (PRODUCT.UNIT, LEGACY.UNIT):
        r = _rc(tmp_path, "v0.7.0-dev2", "v0.7.0-dev1", "--dry-run", KRANTO_UNIT=unit)
        assert r.returncode == 2 and "a real install's unit" in r.stderr, unit
    r = _rc(tmp_path, "v0.7.0-dev2", "v0.7.0-dev1", "--home-copy", str(tmp_path / "none"))
    assert r.returncode == 2 and "is not a folder" in r.stderr


def test_the_scratch_install_copies_a_home_by_the_previews_rules():
    e2e = (SCRIPTS / "e2e_update.sh").read_text()
    assert "preview/copy_live.py" in e2e and "--src-home \"$HOME_COPY\"" in e2e
    assert "rsync" not in e2e                      # one copier: copy_live.py's excludes
    assert 'names.py" old-env' in e2e              # an old release reads the old variables


def test_every_release_script_parses():
    for sh in sorted(SCRIPTS.glob("*.sh")):
        r = subprocess.run(["bash", "-n", str(sh)], capture_output=True, text=True)
        assert r.returncode == 0, (sh.name, r.stderr)


def test_the_old_names_of_a_variable_come_from_legacy():
    old = names.old_env("KRANTO_UNIT")
    assert old and all(LEGACY.new_env_name(n) == "KRANTO_UNIT" for n in old)
    assert names.old_env("KRANTO_HOME") and names.old_env("NOT_OURS") == []
