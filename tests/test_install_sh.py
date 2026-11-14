"""``install.sh`` (the owner's D1 of 2026-10-17), run for real in a scratch HOME
with fake ``uv``, ``gh`` and ``kranto`` and a fake GitHub on loopback: no network, no model,
nothing of this machine's HOME touched."""

from __future__ import annotations

import hashlib
import http.server
import json
import os
import secrets
import shutil
import stat
import subprocess
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"
REAL_PY = sys.executable

FAKE_UV = f"""#!/bin/sh
echo "uv $*" >> "$LOG"
case "$1" in
  --version) echo "uv 0.0.0-test" ;;
  run) shift; while [ "$1" != "-I" ]; do shift; done; exec {REAL_PY} "$@" ;;
  tool)
    mkdir -p "$HOME/.local/bin"
    cp "$FAKE_KRANTO" "$HOME/.local/bin/kranto"
    chmod +x "$HOME/.local/bin/kranto" ;;
esac
"""

FAKE_KRANTO = """#!/bin/sh
echo "kranto $*" >> "$LOG"
env | sort > "$LOG.kranto-env"
case "$1" in
  --version) echo "kranto 0.0.0 (test)" ;;
  setup) [ "$2" = --help ] && [ -n "$NO_SETUP" ] && exit 2; exit 0 ;;
esac
"""

FAKE_GH = """#!/bin/sh
echo "gh $*" >> "$LOG"
case "$1 $2" in
  "auth status") [ -n "$GH_LOGGED_IN" ] || { echo "not logged in" >&2; exit 1; } ;;
  "release view") echo v9.9.9 ;;
  "release download")
    while [ $# -gt 0 ]; do [ "$1" = -D ] && dest="$2"; shift; done
    cp "$RELEASE"/* "$dest"/ ;;
esac
"""


def release_dir(tmp: Path, *, corrupt: bool = False) -> Path:
    d = tmp / "release"
    d.mkdir()
    sums = []
    for name in ("kranto",):
        w = d / f"{name}-9.9.9-py3-none-any.whl"
        w.write_bytes(f"wheel {name}".encode())
        sums.append(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    if corrupt:
        (d / "kranto-9.9.9-py3-none-any.whl").write_bytes(b"tampered")
    return d


@pytest.fixture
def box(tmp_path):
    home = tmp_path / "home"
    (home / ".local" / "bin").mkdir(parents=True)
    fake = tmp_path / "bin"
    fake.mkdir()
    for name, text in (("uv", FAKE_UV), ("gh", FAKE_GH), ("apt-get", "#!/bin/sh\nexit 1\n")):
        (fake / name).write_text(text)
        (fake / name).chmod(0o755)
    tools = tmp_path / "tools"        # only what the script needs: no real gh, uv or curl
    tools.mkdir()
    for name in ("sh", "cp", "mkdir", "chmod", "mv", "rm", "mktemp", "uname", "env", "sort",
                 "cat", "sed", "ls", "printf"):
        found = shutil.which(name)
        if found:
            (tools / name).symlink_to(found)
    (tmp_path / "kranto").write_text(FAKE_KRANTO)
    log = tmp_path / "log"
    env = {"HOME": str(home), "PATH": f"{fake}:{tools}", "LOG": str(log),
           "FAKE_KRANTO": str(tmp_path / "kranto"), "TMPDIR": str(tmp_path),
           "KRANTO_GITHUB_API": "http://127.0.0.1:9", "KRANTO_GITHUB_WEB": "http://127.0.0.1:9"}
    return {"tmp": tmp_path, "home": home, "fake": fake, "log": log, "env": env}


def run(box, *args, extra=None, stdin=subprocess.DEVNULL):
    env = dict(box["env"], **(extra or {}))
    r = subprocess.run(["sh", str(SCRIPT), *args], env=env, capture_output=True, text=True,
                       timeout=120, stdin=stdin)
    log = box["log"].read_text() if box["log"].exists() else ""
    return r, log


def test_it_parses_as_posix_sh():
    assert subprocess.run(["sh", "-n", str(SCRIPT)]).returncode == 0
    if shutil.which("shellcheck"):
        assert subprocess.run(["shellcheck", "-s", "sh", str(SCRIPT)]).returncode == 0


def test_from_a_folder_it_verifies_installs_and_runs_setup(box):
    rel = release_dir(box["tmp"])
    r, log = run(box, "--from", str(rel), "--", "--yes", "--port", "9021")
    assert r.returncode == 0, r.stderr
    assert "kranto-9.9.9-py3-none-any.whl: OK" in r.stdout
    tool = next(line for line in log.splitlines() if line.startswith("uv tool install"))
    assert "kranto[connections,notify,mcp] @ file://" in tool and "--python 3.12" in tool
    assert log.splitlines()[-1] == "kranto setup --yes --port 9021"


def test_a_release_without_a_kranto_wheel_is_refused_in_one_line(box):
    """The crossing's release carries only the old names' wheels: install.sh installs the final
    shape only, and says so in one line."""
    d = box["tmp"] / "crossing"
    d.mkdir()
    sums = []
    for name in ("meta", "server", "page"):
        w = d / f"old{name}-9.9.9-py3-none-any.whl"
        w.write_bytes(name.encode())
        sums.append(f"{hashlib.sha256(w.read_bytes()).hexdigest()}  {w.name}")
    (d / "SHA256SUMS").write_text("\n".join(sums) + "\n")
    r, log = run(box, "--from", str(d))
    assert r.returncode != 0 and "uv tool install" not in log
    said = [ln for ln in r.stderr.splitlines() if ln.strip()]
    assert len(said) == 1 and "has no kranto wheel" in said[0], r.stderr


def test_a_hash_that_does_not_match_installs_nothing(box):
    rel = release_dir(box["tmp"], corrupt=True)
    r, log = run(box, "--from", str(rel))
    assert r.returncode != 0
    assert "does not match SHA256SUMS" in r.stderr
    assert "uv tool install" not in log and "kranto" not in log.replace("kranto-install", "")


def test_private_with_a_gh_login_downloads_with_gh_and_setup_reuses_it(box):
    rel = release_dir(box["tmp"])
    r, log = run(box, extra={"GH_LOGGED_IN": "1", "RELEASE": str(rel)})
    assert r.returncode == 0, r.stderr
    assert "gh release download v9.9.9 -R iddv/kranto" in log
    assert log.splitlines()[-1] == "kranto setup --github gh"


def test_no_login_and_no_client_id_says_how_to_get_gh(box):
    os.remove(box["fake"] / "gh")
    r, log = run(box, extra={"KRANTO_GITHUB_CLIENT_ID": ""})     # "" turns the device flow off
    assert r.returncode == 1
    assert "gh auth login" in r.stdout and "https://cli.github.com" in r.stdout
    assert "sudo apt install gh" in r.stdout
    assert "invitations" in r.stdout and "uv tool install" not in log


def test_a_release_without_setup_starts_kranto_up(box):
    rel = release_dir(box["tmp"])
    r, log = run(box, "--from", str(rel), extra={"NO_SETUP": "1"})
    assert r.returncode == 0, r.stderr
    assert log.splitlines()[-1] == "kranto up"


def test_fetch_gh_is_handed_to_setup(box):
    rel = release_dir(box["tmp"])
    r, log = run(box, "--from", str(rel), "--fetch-gh", "--", "--yes")
    assert r.returncode == 0, r.stderr
    assert log.splitlines()[-1] == "kranto setup --fetch-gh --yes"
    r, _ = run(box, "--help")
    assert "--fetch-gh" in r.stdout and "checksum-checked gh" in r.stdout


def test_macos_says_watcher_only_and_installs(box):
    """D12 with a faked uname (no Mac here): the note, then the same install and setup."""
    uname = box["tmp"] / "tools" / "uname"
    uname.unlink()
    uname.write_text("#!/bin/sh\necho Darwin\n")
    uname.chmod(0o755)
    rel = release_dir(box["tmp"])
    r, log = run(box, "--from", str(rel))
    assert r.returncode == 0, r.stderr
    assert "macOS: kranto installs the watcher only" in r.stdout
    assert "bwrap, systemd and the build checks are skipped" in r.stdout
    assert log.splitlines()[-1] == "kranto setup"


class FakeGitHub(http.server.BaseHTTPRequestHandler):
    """The device flow (pending once, then granted) and one private release's assets."""
    token = ""
    release: Path
    polls = 0
    seen_auth: list[str] = []

    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/login/device/code":
            return self._json({"device_code": "dc", "user_code": "ABCD-1234", "interval": 0,
                               "expires_in": 60,
                               "verification_uri": "https://github.com/login/device"})
        cls = type(self)
        cls.polls += 1
        if cls.polls == 1:
            return self._json({"error": "authorization_pending"})
        return self._json({"access_token": cls.token, "scope": "repo,workflow,read:org",
                           "token_type": "bearer"})

    def do_GET(self):
        cls = type(self)
        auth = self.headers.get("Authorization") or ""
        cls.seen_auth.append(auth)
        if auth != f"Bearer {cls.token}":
            return self._json({"message": "Not Found"}, 404)
        base = f"http://127.0.0.1:{self.server.server_address[1]}"
        files = sorted(cls.release.iterdir())
        if self.path.startswith("/repos/iddv/kranto/releases/"):
            return self._json({"tag_name": "v9.9.9", "assets": [
                {"name": f.name, "url": f"{base}/assets/{f.name}"} for f in files]})
        if self.path.startswith("/assets/"):
            body = (cls.release / self.path.rsplit("/", 1)[1]).read_bytes()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)
            return None
        return self._json({}, 404)


def test_the_device_flow_signs_in_once_and_hands_the_login_to_setup(box):
    token = "gho_" + secrets.token_hex(18)          # built at run time: no literal
    FakeGitHub.token, FakeGitHub.release, FakeGitHub.polls = token, release_dir(box["tmp"]), 0
    FakeGitHub.seen_auth = []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), FakeGitHub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    os.remove(box["fake"] / "gh")
    try:
        r, log = run(box, extra={"KRANTO_GITHUB_CLIENT_ID": "Iv1.test", "KRANTO_GITHUB_API": url,
                                 "KRANTO_GITHUB_WEB": url})
    finally:
        srv.shutdown()
    assert r.returncode == 0, r.stderr
    assert "ABCD-1234" in r.stdout and FakeGitHub.polls == 2
    kept = box["home"] / ".config" / "kranto" / "github" / "install-login.env"
    assert log.splitlines()[-1] == f"kranto setup --github-token-file {kept}"
    assert stat.S_IMODE(kept.stat().st_mode) == 0o600
    assert stat.S_IMODE(kept.parent.parent.stat().st_mode) == 0o700
    assert kept.read_text() == f"GH_TOKEN={token}\n"
    # the token is in its file and the download's Authorization header, nowhere else
    assert token not in r.stdout + r.stderr + log
    assert token not in Path(f"{box['log']}.kranto-env").read_text()
    assert not list(box["tmp"].glob("kranto-install.*"))     # the temporary folder is gone


def test_wider_scopes_than_asked_are_refused_and_nothing_is_kept(box):
    token = "gho_" + secrets.token_hex(18)
    FakeGitHub.token, FakeGitHub.release, FakeGitHub.polls = token, release_dir(box["tmp"]), 1

    class Wider(FakeGitHub):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            if self.path == "/login/device/code":
                return self._json(
                    {"device_code": "dc", "user_code": "WXYZ-0000", "interval": 0,
                     "expires_in": 60, "verification_uri": "https://github.com/login/device"})
            return self._json({"access_token": token, "scope": "repo,workflow,read:org,"
                                                               "delete_repo"})
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Wider)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}"
    os.remove(box["fake"] / "gh")
    try:
        r, log = run(box, extra={"KRANTO_GITHUB_CLIENT_ID": "Iv1.test", "KRANTO_GITHUB_API": url,
                                 "KRANTO_GITHUB_WEB": url})
    finally:
        srv.shutdown()
    assert r.returncode != 0 and "wider scopes" in r.stderr
    assert not (box["home"] / ".config" / "kranto" / "github").exists()
    assert "uv tool install" not in log and token not in r.stdout + r.stderr


def test_the_client_id_is_kranto_oauth_app():
    """D3: the owner registered the "kranto" OAuth App on 2026-10-17. Its client id is public;
    the page's tests pin the same value in github_user.CLIENT_ID, so the two cannot drift."""
    line = next(ln for ln in SCRIPT.read_text().splitlines() if ln.startswith("CLIENT_ID="))
    assert line == 'CLIENT_ID="Ov23lismfFcZrfTLDoxm"'


def test_without_gh_the_device_flow_is_offered_with_kranto_app(box):
    os.remove(box["fake"] / "gh")
    r, log = run(box)                   # the fake GitHub at 127.0.0.1:9 refuses the request
    assert r.returncode != 0
    assert "Signing in to GitHub" in r.stdout and "uv tool install" not in log


def test_every_release_carries_install_sh(tmp_path, monkeypatch):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "release_publish_wz", ROOT / "scripts" / "release" / "publish.py")
    publish = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publish)
    rel = release_dir(tmp_path)
    (rel / "manifest.json").write_text("{}")
    calls = []
    before = [{"tag_name": "v9.9.8", "draft": False, "assets": []}]
    monkeypatch.setattr(publish, "push_tag", lambda repo, tag: "pushed")
    monkeypatch.setattr(publish, "run", lambda *cmd, cwd=None: calls.append(cmd) or "")
    monkeypatch.setattr(publish.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(
        a, 1, "", "release not found"))
    publish.publish(rel, "9.9.9", "v9.9.9", "iddv/kranto", ROOT, tmp_path / "n", False,
                    known=before)
    create = next(c for c in calls if c[:3] == ("gh", "release", "create"))
    assert str(ROOT / "install.sh") in create


def test_the_rc_check_runs_a_fresh_home_install_first():
    """The owner's rule for install rcs (2026-10-17): a fresh-HOME run of install.sh and of
    'kranto setup --yes' with an answers file, as rc_check.sh's step 0."""
    rel = ROOT / "scripts" / "release"
    for name in ("fresh_install.sh", "rc_check.sh"):
        assert subprocess.run(["bash", "-n", str(rel / name)]).returncode == 0, name
    rc = (rel / "rc_check.sh").read_text()
    assert rc.index('step "0. a fresh HOME') < rc.index('step "1. install')
    fresh = (rel / "fresh_install.sh").read_text()
    assert "env -i HOME=" in fresh and "--answers" in fresh and "--yes" in fresh
    assert "127.0.0.1" in fresh and "0.0.0.0" not in fresh
