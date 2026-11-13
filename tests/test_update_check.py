"""The update check (kranto.update): release selection, the ETag, offline, redaction,
staging and a tampered set. gh and GitHub's API are fakes; nothing reaches the network."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import subprocess
from pathlib import Path

import pytest

from kranto import config as config_mod
from kranto.update import apply, check, sources
from kranto.update.backup import backup, lower_counts, prune, table_counts

INSTALLED = {"version": "0.1.0", "versions": {"kranto": "0.1.0",
                                              "kranto.page": "0.1.0"},
             "channel": "main", "env": "/x",
             "spec": {"kind": "git", "commits": {"kranto": "a" * 40, "kranto.page": "b" * 40},
                      "extras": "connections,notify"}}


def rel(tag, prerelease=False, draft=False, body="- One\n- Two\n"):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": body,
            "published_at": "2026-10-11T05:20:00Z",
            "html_url": f"https://github.com/iddv/kranto/releases/tag/{tag}",
            "assets": [{"name": "SHA256SUMS"}]}


RELEASES = [rel("v0.3.0-dev2", prerelease=True), rel("v0.3.0-dev1", prerelease=True),
            rel("v0.2.1-rc1", prerelease=True), rel("v0.2.0"), rel("v0.1.9"),
            rel("v0.3.0", draft=True), rel("nightly")]


def write_set(dest: Path, version: str, tamper: str | None = None) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    sums, wheels = [], []
    for n in apply.NAMES:
        w = dest / f"{n}-{version}-py3-none-any.whl"
        w.write_bytes(f"{n} {version}".encode())
        digest = hashlib.sha256(w.read_bytes()).hexdigest()
        sums.append(f"{digest}  {w.name}")
        wheels.append({"name": w.name, "sha256": digest, "size": w.stat().st_size})
    if tamper:
        (dest / f"{tamper}-{version}-py3-none-any.whl").write_bytes(b"not what was signed")
    (dest / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    (dest / "manifest.json").write_text(json.dumps(
        {"version": version, "pins": {"kranto": version, "kranto.page": version},
         "wheels": wheels}))


class FakeGh:
    """``gh api .../releases`` and ``gh release download``; records every call."""

    def __init__(self, releases=None, fail=None, tamper=None):
        self.releases = RELEASES if releases is None else releases
        self.fail = fail
        self.tamper = tamper
        self.calls = []

    def __call__(self, cmd, env=None, timeout=None):
        self.calls.append((cmd, env))
        if self.fail:
            return subprocess.CompletedProcess(cmd, 1, "", self.fail)
        if cmd[1] == "api":
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.releases), "")
        if cmd[1:3] == ["release", "download"]:
            dest = Path(cmd[cmd.index("-D") + 1])
            write_set(dest, apply.tag_version(cmd[3]), self.tamper)
            return subprocess.CompletedProcess(cmd, 0, "", "")
        raise AssertionError(cmd)


def gh_source(fake, **kw):
    return sources.GitHubReleases("iddv/kranto", run=fake, which=lambda n: "/usr/bin/gh",
                                  **kw)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(check, "installed_here", lambda env=None: INSTALLED)
    h = tmp_path / "home"
    (h / "data").mkdir(parents=True)
    return h


def ucfg(**kw):
    return config_mod.UpdateConfig(**kw)


# -- choosing the release ------------------------------------------------------------------


def test_stable_is_the_newest_published_non_prerelease():
    assert sources.pick(RELEASES, "stable")["tag_name"] == "v0.2.0"


def test_nightly_is_the_newest_nightly_build_and_rc_is_read_as_nightly():
    assert sources.pick(RELEASES, "nightly")["tag_name"] == "v0.3.0-dev2"
    assert sources.pick(RELEASES, "rc")["tag_name"] == "v0.3.0-dev2"


def test_each_line_is_offered_only_its_own_builds():
    """a stable install never sees a nightly; a nightly install never a
    stable fix, a held stable candidate or an old rc; a withdrawn nightly never counts."""
    rels = [rel("v0.6.3"), rel("v0.6.2"), rel("v0.7.0", prerelease=True),   # held candidate
            rel("v0.7.0-dev14", prerelease=True, body="**Do not install:** rc_check failed"),
            rel("v0.7.0-dev13", prerelease=True), rel("v0.5.27-rc1", prerelease=True)]
    assert sources.pick(rels, "stable")["tag_name"] == "v0.6.3"
    assert sources.pick(rels, "nightly")["tag_name"] == "v0.7.0-dev13"
    assert sources.pick([rel("v0.6.2"), rel("v0.5.27-rc1", prerelease=True)], "nightly") is None


def test_versions_order_dev_rc_final():
    order = ["0.0.0+unknown", "0.1.0", "0.2.0.dev3+g1234567", "0.2.0rc1", "0.2.0rc2",
             "0.2.0", "0.2.1.dev1", "0.10.0"]
    assert sorted(order, key=apply.vkey) == order
    assert apply.vkey("v0.2.0-rc1") == apply.vkey("0.2.0rc1")
    assert apply.vkey("garbage") < apply.vkey("0.0.1")


def test_the_two_lines_sort_as_rel_design_says():
    order = ["0.6.2", "0.6.3", "0.7.0.dev12", "v0.7.0-dev13", "0.7.0", "0.7.1", "0.8.0.dev1"]
    assert sorted(order, key=apply.vkey) == order
    assert apply.vkey("v0.7.0-dev12") == apply.vkey("0.7.0.dev12") == (0, 7, 0, 0, 0, 12)
    assert apply.tag_version("v0.7.0-dev12") == "0.7.0.dev12"
    assert apply.tag_version("v0.5.27-rc1") == "0.5.27rc1"
    assert [apply.line_of(v) for v in ("0.7.0.dev12", "0.5.27rc1", "0.6.2", None)] == \
        ["nightly", "nightly", "stable", "stable"]


def test_a_stable_install_finds_the_last_stable_past_a_page_of_nightlies():
    """Nightlies come several a day: when the list holds no stable, the check asks GitHub's
    latest release."""
    nightlies = [rel(f"v0.7.0-dev{n}", prerelease=True) for n in range(1, 101)]

    def run(cmd, env=None, timeout=None):
        if cmd[2].endswith("/releases/latest"):
            return subprocess.CompletedProcess(cmd, 0, json.dumps(rel("v0.6.2")), "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps(nightlies), "")

    got, _ = gh_source(run).latest("stable")
    assert got.tag == "v0.6.2"
    assert gh_source(run).latest("nightly")[0].tag == "v0.7.0-dev100"


# -- the check -----------------------------------------------------------------------------


def test_check_records_the_release_and_stages_a_verified_set(home):
    fake = FakeGh()
    cache = check.run_check(home, ucfg(), source=gh_source(fake))
    assert cache["ok"] and cache["latest"]["version"] == "0.2.0"
    assert cache["latest"]["notes"] == ["- One", "- Two"]
    assert check.available(cache) == "0.2.0"
    staged = Path(cache["staged"]["dir"])
    assert staged == home / "update" / "releases" / "v0.2.0" and staged.is_dir()
    assert set(apply.verify_set(staged, "0.2.0")) == set(apply.NAMES)
    assert json.loads(apply.cache_path(home).read_text())["staged"]["version"] == "0.2.0"
    assert "0.2.0 available since 2026-10-11, staged" in check.status_line(home)
    # a second check does not download again
    fake.calls.clear()
    check.run_check(home, ucfg(), source=gh_source(fake))
    assert [c[0][1] for c in fake.calls] == ["api"]


def test_nightly_channel_offers_the_newest_nightly(home):
    cache = check.run_check(home, ucfg(channel="nightly"), source=gh_source(FakeGh()))
    assert check.available(cache) == "0.3.0.dev2"
    assert cache["staged"]["tag"] == "v0.3.0-dev2"


def test_nothing_newer_is_up_to_date(home, monkeypatch):
    monkeypatch.setattr(check, "installed_here",
                        lambda env=None: {**INSTALLED, "version": "0.2.0", "channel": "stable",
                                          "spec": {"kind": "wheels", "dir": "/w"}})
    cache = check.run_check(home, ucfg(), source=gh_source(FakeGh()))
    assert check.available(cache) is None and not cache.get("staged")
    assert "up to date, checked" in check.status_line(home)


def test_a_git_install_is_offered_the_release_of_its_own_version(home, monkeypatch):
    # a git install at the tagged commit reports the tag's version: moving to the release's
    # wheels is still an update (main -> stable); a wheel install at that version is current
    git = {**INSTALLED, "version": "0.2.0"}
    monkeypatch.setattr(check, "installed_here", lambda env=None: git)
    cache = check.run_check(home, ucfg(), source=gh_source(FakeGh()))
    assert check.available(cache) == "0.2.0" and cache["staged"]["version"] == "0.2.0"
    assert "0.2.0 available as a release (this install is from git)" in check.status_line(home)
    wheels = {**git, "channel": "stable", "spec": {"kind": "wheels", "dir": "/w"}}
    assert check.available(cache, wheels) is None
    older = {**git, "version": "0.2.1.dev3+g1234567"}
    assert check.available(cache, older) is None


def test_download_off_records_without_staging(home):
    cache = check.run_check(home, ucfg(download=False), source=gh_source(FakeGh()))
    assert check.available(cache) == "0.2.0" and not cache.get("staged")
    assert not (home / "update" / "releases").exists()


def test_a_tampered_set_is_deleted_and_reported(home):
    cache = check.run_check(home, ucfg(), source=gh_source(FakeGh(tamper="kranto.page")))
    assert cache["staged"] is None
    assert "kranto.page-0.2.0-py3-none-any.whl" in cache["stage_error"]
    assert not (home / "update" / "releases" / "v0.2.0").exists()
    assert not list((home / "update" / "releases").glob("*.partial"))
    assert "not staged" in check.status_line(home)


def test_offline_is_recorded_and_skipped(home):
    store_rows = []

    class Store:
        def insert(self, table, row):
            store_rows.append((table, row))

    fake = FakeGh(fail="error connecting to api.github.com")
    cache = check.run_check(home, ucfg(), source=gh_source(fake))
    assert cache["ok"] is False and "error connecting" in cache["error"]
    assert "check failed" in check.status_line(home)
    # the job records a skipped run (retried hourly by the scheduler)
    import kranto.update.check as c
    orig = c.make_source
    c.make_source = lambda cfg, **kw: gh_source(fake)
    try:
        c.make_job(home, Store(), 24).run()
    finally:
        c.make_source = orig
    table, row = store_rows[0]
    assert table == "runs" and row["kind"] == "update" and row["status"] == "skipped"


def test_a_token_never_reaches_the_cache_or_the_log(home, monkeypatch, caplog, tmp_path):
    token = "ghp_" + secrets.token_hex(16)
    monkeypatch.setenv("GH_TOKEN", token)
    fake = FakeGh(fail=f"HTTP 401: Bad credentials (Authorization: token {token})")
    with caplog.at_level(logging.DEBUG):
        cache = check.run_check(home, ucfg(), source=gh_source(fake))
    text = apply.cache_path(home).read_text()
    assert token not in text and token not in json.dumps(cache) and token not in caplog.text
    assert "[redacted]" in cache["error"]
    assert token not in apply.redact(f"x {token} y")
    assert "github_pat_" + "[redacted]" in apply.redact("github_pat_" + secrets.token_hex(12))


def test_token_env_file_goes_to_gh_only_and_must_be_private(home, tmp_path, monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    f = tmp_path / "gh.env"
    value = secrets.token_hex(12)
    f.write_text(f"GH_TOKEN={value}\n")
    f.chmod(0o644)
    fake = FakeGh()
    cache = check.run_check(home, ucfg(), source=gh_source(fake, token_env_file=str(f)))
    assert cache["ok"] is False and "chmod 600" in cache["error"]
    f.chmod(0o600)
    check.run_check(home, ucfg(), source=gh_source(fake, token_env_file=str(f)))
    env = fake.calls[-1][1]
    assert env["GH_TOKEN"] == value
    import os
    assert os.environ.get("GH_TOKEN") is None


def test_public_repo_uses_the_etag(home):
    seen = []

    def http_get(url, headers, timeout=20):
        seen.append(dict(headers))
        if headers.get("If-None-Match") == '"abc"':
            return 304, {}, b""
        return 200, {"etag": '"abc"'}, json.dumps(RELEASES).encode()

    src = sources.GitHubReleases("iddv/kranto", http_get=http_get, which=lambda n: None)
    first = check.run_check(home, ucfg(download=False), source=src)
    assert first["etag"] == '"abc"' and first["latest"]["version"] == "0.2.0"
    second = check.run_check(home, ucfg(download=False), source=src)
    assert seen[1]["If-None-Match"] == '"abc"'
    assert second["ok"] and second["latest"]["version"] == "0.2.0"


def test_gh_without_a_login_falls_back_to_anonymous_https(home, tmp_path):
    """A stranger with gh installed but never logged in: the public repo's releases are read
    and downloaded over anonymous HTTPS, not refused as "gh is not logged in"."""
    fake = FakeGh(fail="To get started with GitHub CLI, please run:  gh auth login")
    urls = []

    def http_get(url, headers, timeout=20):
        urls.append(url)
        return 200, {"etag": '"e"'}, json.dumps(RELEASES).encode()

    src = gh_source(fake, http_get=http_get)
    cache = check.run_check(home, ucfg(download=False), source=src)
    assert cache["ok"] and cache["latest"]["version"] == "0.2.0"
    assert len(fake.calls) == 1 and urls == [
        "https://api.github.com/repos/iddv/kranto/releases?per_page=100"]
    assert not src.use_gh          # the download goes the same anonymous way


class FakeGitHub:
    """GitHub's REST API for one repo, over the ``http_get`` seam: private (404 without the
    right token, as GitHub answers) or public; assets on the API's asset address only."""

    def __init__(self, token=None, private=True):
        self.token = token
        self.private = private
        self.calls = []
        self.files = {}

    def __call__(self, url, headers, timeout=20):
        self.calls.append((url, dict(headers)))
        auth = headers.get("Authorization")
        if self.private and auth != f"Bearer {self.token}":
            return 404, {}, b'{"message": "Not Found"}'
        base = "https://api.github.com/repos/iddv/kranto"
        if url == f"{base}/releases?per_page=100":
            return 200, {"etag": '"e"'}, json.dumps(self.releases()).encode()
        if url.startswith(f"{base}/releases/assets/"):
            assert headers["Accept"] == "application/octet-stream"
            return 200, {}, self.files[url.rsplit("/", 1)[1]]
        return 404, {}, b""

    def releases(self):
        if not self.files:
            tmp = Path(__import__("tempfile").mkdtemp())
            write_set(tmp, "0.2.0")
            self.files = {p.name: p.read_bytes() for p in tmp.iterdir()}
        base = "https://api.github.com/repos/iddv/kranto"
        assets = [{"name": n, "url": f"{base}/releases/assets/{n}",
                   "browser_download_url": f"https://github.com/iddv/kranto/releases/"
                                           f"download/v0.2.0/{n}"} for n in self.files]
        return [{**rel("v0.2.0"), "assets": assets}]


def _token_file(tmp_path, value):
    f = tmp_path / "user.env"
    f.write_text(f"GH_TOKEN={value}\n")
    f.chmod(0o600)
    return str(f)


def test_no_gh_with_a_token_reads_and_downloads_a_private_repo(home, tmp_path):
    """The friend's install stuck on 0.5.5: no gh, Kranto connected to GitHub, a private repo.
    The token from the connection's file goes with every HTTPS request and the assets come
    from the API's asset address, never browser_download_url (which a private repo refuses)."""
    value = secrets.token_hex(12)
    gh = FakeGitHub(token=value)
    src = sources.GitHubReleases("iddv/kranto", http_get=gh, which=lambda n: None,
                                 token_env_file=_token_file(tmp_path, value))
    cache = check.run_check(home, ucfg(), source=src)
    assert cache["ok"] and cache["latest"]["version"] == "0.2.0"
    assert cache["staged"]["version"] == "0.2.0"
    assert all(h["Authorization"] == f"Bearer {value}" for _, h in gh.calls)
    assert not any("browser_download" in u or u.startswith("https://github.com/")
                   for u, _ in gh.calls)
    assert value not in apply.cache_path(home).read_text()


def test_no_gh_and_no_token_reads_a_public_repo_anonymously(home):
    gh = FakeGitHub(private=False)
    src = sources.GitHubReleases("iddv/kranto", http_get=gh, which=lambda n: None)
    cache = check.run_check(home, ucfg(), source=src)
    assert cache["ok"] and cache["staged"]["version"] == "0.2.0"
    assert not any("Authorization" in h for _, h in gh.calls)


def test_no_gh_and_no_token_on_a_private_repo_says_it_needs_a_login(home):
    src = sources.GitHubReleases("iddv/kranto", http_get=FakeGitHub(token="x"),
                                 which=lambda n: None)
    cache = check.run_check(home, ucfg(), source=src)
    assert not cache["ok"]
    assert "GitHub answered 404" in cache["error"]
    assert "a private repo needs a GitHub login" in cache["error"]


def test_gh_logged_out_falls_back_to_https_with_the_token(home, tmp_path):
    value = secrets.token_hex(12)
    fake = FakeGh(fail="To get started with GitHub CLI, please run:  gh auth login")
    gh = FakeGitHub(token=value)
    src = gh_source(fake, http_get=gh, token_env_file=_token_file(tmp_path, value))
    # gh would get GH_TOKEN from the file; this gh still says it is not logged in
    cache = check.run_check(home, ucfg(), source=src)
    assert cache["ok"] and cache["staged"]["version"] == "0.2.0"
    assert len(fake.calls) == 1 and not src.use_gh
    assert all(h.get("Authorization") == f"Bearer {value}" for _, h in gh.calls)


def test_a_check_failing_for_more_than_two_days_is_said_on_the_pill(home, monkeypatch):
    from datetime import UTC, datetime, timedelta

    src = sources.GitHubReleases("iddv/kranto", http_get=FakeGitHub(token="x"),
                                 which=lambda n: None)
    monkeypatch.setattr(check, "can_apply", lambda: False)
    first = check.run_check(home, ucfg(), source=src)
    since = first["failing_since"]
    assert check.summary(home)["check_failing"] is None          # one failed check: silent
    later = check.run_check(home, ucfg(), source=src)
    assert later["failing_since"] == since                       # the first failure counts
    three_days = datetime.now(UTC) + timedelta(days=3)
    said = check.failing(later, three_days)
    assert said and "GitHub answered 404" in said
    old = (datetime.now(UTC) - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    apply.write_json(apply.cache_path(home), {**later, "failing_since": old})
    assert "a private repo needs a GitHub login" in check.summary(home)["check_failing"]
    ok = check.run_check(home, ucfg(download=False),
                         source=sources.GitHubReleases("iddv/kranto",
                                                       http_get=FakeGitHub(private=False),
                                                       which=lambda n: None))
    assert ok["ok"] and "failing_since" not in ok
    assert check.summary(home)["check_failing"] is None


def test_gh_failing_for_another_reason_still_says_why(home):
    fake = FakeGh(fail="HTTP 502: Bad Gateway (https://api.github.com/repos/x)")
    src = gh_source(fake, http_get=lambda *a, **k: pytest.fail("no fallback"))
    cache = check.run_check(home, ucfg(download=False), source=src)
    assert not cache["ok"] and "502" in cache["error"]


def test_main_channel_compares_commits(home):
    def run(cmd, env=None, timeout=None):
        sha = {"repos/iddv/kranto/commits/main": "a" * 40}[cmd[2]]
        return subprocess.CompletedProcess(cmd, 0, sha + "\n", "")

    cache = check.run_check(home, ucfg(channel="main"), source=sources.GitMain(run=run))
    assert check.available(cache) == "main@aaaaaaa/aaaaaaa"
    assert not cache.get("staged")


def test_settings_follow_the_file(home):
    (home / "kranto.yaml").write_text("update:\n  channel: nightly\n  auto: off\n")
    s = check.settings(home)
    assert s.channel == "nightly" and s.auto == "off"
    (home / "kranto.yaml").write_text("update:\n  channel: rc\n")    # retired: read as nightly
    assert check.settings(home).channel == "nightly"
    (home / "kranto.yaml").write_text("update:\n  channel: beta\n")
    assert check.settings(home).channel == "stable"   # a typo never breaks the check


def test_the_retired_rc_channel_is_read_as_nightly_and_said_once(caplog):
    config_mod._SAID.clear()
    with caplog.at_level(logging.WARNING):
        assert config_mod.parse_update({"channel": "rc"}).channel == "nightly"
        assert config_mod.parse_update({"channel": "rc"}).channel == "nightly"
    assert sum("read as nightly" in r.message for r in caplog.records) == 1


def test_a_nightly_install_that_chose_stable_says_it_moves_at_the_next_promotion(home,
                                                                                monkeypatch):
    nightly = {**INSTALLED, "version": "0.7.0.dev14", "channel": "nightly",
               "spec": {"kind": "wheels", "dir": "/w"}}
    monkeypatch.setattr(check, "installed_here", lambda env=None: nightly)
    rels = [rel("v0.6.2"), rel("v0.7.0-dev14", prerelease=True)]
    check.run_check(home, ucfg(), source=gh_source(FakeGh(releases=rels)))
    (home / "kranto.yaml").write_text("update:\n  channel: stable\n")
    line = check.status_line(home)
    assert line.startswith("0.7.0.dev14 (nightly, moving to stable at the next promotion) · "
                           "up to date")                  # 0.6.2 is older: never a downgrade
    (home / "kranto.yaml").write_text("update:\n  channel: nightly\n")
    assert check.status_line(home).startswith("0.7.0.dev14 (nightly) · up to date")


def test_update_config_is_validated():
    assert config_mod.parse_update({"auto": False}).auto == "off"
    for bad in ({"channel": "beta"}, {"auto": "always"}, {"quiet_window": "3-6"},
                {"keep_backups": 0}, {"repo": "nope"}, {"surprise": 1}):
        with pytest.raises(config_mod.ConfigError):
            config_mod.parse_update(bad)
    assert config_mod.quiet_window("23:00-02:00") == (1380, 120)


# -- the installed environment ---------------------------------------------------------------


def _dist(sp: Path, name: str, version: str, url: dict | None):
    d = sp / f"{name}-{version}.dist-info"
    d.mkdir(parents=True)
    (d / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n")
    if url:
        (d / "direct_url.json").write_text(json.dumps(url))


def test_installed_from_git_and_from_wheels(tmp_path):
    git = tmp_path / "git" / "lib" / "python3.12" / "site-packages"
    for n, sha in (("kranto", "1" * 40), ("kranto.page", "2" * 40)):
        _dist(git, n, "0.1.0", {"url": "https://github.com/octo-owner/x",
                                "vcs_info": {"vcs": "git", "commit_id": sha}})
    got = apply.installed(tmp_path / "git")
    assert got["channel"] == "main" and got["version"] == "0.1.0"
    assert got["spec"] == {"kind": "git", "commits": {"kranto": "1" * 40,
                                                      "kranto.page": "2" * 40},
                           "extras": "connections,notify"}
    whl = tmp_path / "whl" / "lib" / "python3.12" / "site-packages"
    for n in apply.NAMES:
        _dist(whl, n, "0.2.0rc1",
              {"url": f"file:///h/update/releases/v0.2.0-rc1/{n}-0.2.0rc1-py3-none-any.whl",
               "archive_info": {}})
    got = apply.installed(tmp_path / "whl")
    assert got["channel"] == "nightly"                   # an old rc was a build from main too
    assert got["spec"] == {"kind": "wheels", "dir": "/h/update/releases/v0.2.0-rc1",
                           "version": "0.2.0rc1"}
    dev = tmp_path / "dev" / "lib" / "python3.12" / "site-packages"
    for n in apply.NAMES:
        _dist(dev, n, "0.7.0.dev12",
              {"url": f"file:///h/update/releases/v0.7.0-dev12/{n}-0.7.0.dev12-py3-none-any.whl",
               "archive_info": {}})
    got = apply.installed(tmp_path / "dev")
    assert got["channel"] == "nightly" and got["version"] == "0.7.0.dev12"


# -- kranto backup ------------------------------------------------------------------------------


def test_backup_copies_the_databases_and_files_but_no_secret(tmp_path):
    import sqlite3

    user = tmp_path / "user"
    home = tmp_path / "home"
    loop = tmp_path / "loop"
    for d in (home / "data" / "secrets", loop, user / ".config" / "systemd" / "user" /
              "kranto.service.d"):
        d.mkdir(parents=True)
    text = config_mod.DEFAULT_CONFIG_YAML + f"\nbrb:\n  enabled: true\n  loop_home: {loop}\n"
    (home / "kranto.yaml").write_text(text)
    (home / ".env").write_text("A_KEY=" + secrets.token_hex(8) + "\n")
    (home / "data" / "secrets" / "k").write_text(secrets.token_hex(8))
    for db in (home / "data" / "kranto.db", loop / "loop.db"):
        c = sqlite3.connect(db)
        c.execute("CREATE TABLE t (x)")
        c.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(3)])
        c.commit()
        c.close()
    (loop / "loop.yaml").write_text("concurrency: 1\n")
    unit_dir = user / ".config" / "systemd" / "user"
    (unit_dir / "kranto.service").write_text("[Service]\n")
    (unit_dir / "kranto.service.d" / "20-token.conf").write_text(
        "[Service]\nEnvironmentFile=-%h/.config/kranto/claude.env\n")
    # the operator's capabilities are kept; the owner's targets (large programs) are not
    (home / "capabilities" / "mine" / ".claude-plugin").mkdir(parents=True)
    (home / "capabilities" / "mine" / "capability.yaml").write_text("schema: 1\n")
    (home / "targets" / "i-1").mkdir(parents=True)
    (home / "targets" / "i-1" / "app.bin").write_bytes(b"x" * 10)
    # the adopted repos' profiles (the page MX) are kept; their onboarding logs are not
    (loop / "maintain" / "repos" / "o--tool" / "onboard").mkdir(parents=True)
    (loop / "maintain" / "repos" / "o--tool.yaml").write_text("schema: 1\nrepo: o/tool\n")
    (loop / "maintain" / "repos" / "o--tool" / "onboard" / "x.log").write_text("x")
    # the owner's own data: prompt versions, the corpus, plugins, MCP servers, chat threads
    for d, f in (("prompts", "charter/v2.md"), ("corpus", "e1/entry.json"),
                 ("plugins", "fd/plugin.json"), ("mcp-servers", "time/manifest.json")):
        (home / d / f).parent.mkdir(parents=True)
        (home / d / f).write_text("x")
    (loop / "chat").mkdir()
    (loop / "chat" / "t1.jsonl").write_text("{}\n")
    out = backup(tmp_path / "b", home, user_home=user, versions={"kranto": "0.1.0"})
    for f in ("prompts/charter/v2.md", "corpus/e1/entry.json", "plugins/fd/plugin.json",
              "mcp-servers/time/manifest.json", "loop-chat/t1.jsonl"):
        assert (tmp_path / "b" / f).is_file(), f
    assert (tmp_path / "b" / "maintain-repos" / "o--tool.yaml").is_file()
    assert not (tmp_path / "b" / "maintain-repos" / "o--tool" / "onboard").exists()
    assert (tmp_path / "b" / "capabilities" / "mine" / "capability.yaml").is_file()
    assert not (tmp_path / "b" / "targets").exists()
    dest = tmp_path / "b"
    assert out["databases"]["kranto.db"]["integrity"] == "ok"
    assert out["databases"]["loop.db"]["integrity"] == "ok"
    names = {p.name for p in dest.rglob("*")}
    assert {"kranto.db", "loop.db", "kranto.yaml", "loop.yaml", "kranto.service",
            "20-token.conf", "counts-before.json", "versions.json"} <= names
    assert ".env" not in names and "secrets" not in names and "k" not in names
    assert json.loads((dest / "counts-before.json").read_text())["afk"]["t"] == 3
    assert (dest.stat().st_mode & 0o777) == 0o700
    assert table_counts(dest / "loop.db") == {"t": 3}
    assert lower_counts({"afk": {"t": 3}}, {"afk": {"t": 2}}) == ["afk.t 3 -> 2"]


def test_prune_keeps_the_newest(tmp_path):
    for ts in ("20261001T000000Z", "20261002T000000Z", "20261003T000000Z", "20261004T000000Z"):
        (tmp_path / f"update-{ts}").mkdir()
    assert prune(tmp_path, "update-", 3) == ["update-20261001T000000Z"]
    assert len(list(tmp_path.iterdir())) == 3
