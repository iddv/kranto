"""``install.sh``, run for real in a scratch HOME with fake ``uv``, ``gh`` and ``kranto`` and a
stand-in for GitHub's release download addresses on loopback: no network, no model, nothing of
this machine's HOME touched."""

from __future__ import annotations

import hashlib
import http.server
import os
import shutil
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
           "KRANTO_DOWNLOAD_BASE": "http://127.0.0.1:9"}
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
    assert "macOS: Kranto installs the watcher only" in r.stdout
    assert "bubblewrap sandbox" in r.stdout and "Builds" not in r.stdout
    assert log.splitlines()[-1] == "kranto setup"


class StandIn(http.server.BaseHTTPRequestHandler):
    """GitHub's release download addresses as a public repository has them:
    ``/<repo>/releases/latest/download/<file>`` (the newest stable release) and
    ``/<repo>/releases/download/<tag>/<file>``, each answered with a redirect to the file, as
    github.com does. ``answer`` set to a status makes every address answer it instead."""
    release: Path
    tag = "v9.9.9"
    answer = 0
    seen: list[tuple[str, str]] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        cls = type(self)
        cls.seen.append((self.path, self.headers.get("Authorization") or ""))
        if cls.answer:
            self.send_response(cls.answer)
            self.end_headers()
            return
        for prefix in ("/iddv/kranto/releases/latest/download/",
                       f"/iddv/kranto/releases/download/{cls.tag}/"):
            if self.path.startswith(prefix) and (cls.release / self.path[len(prefix):]).is_file():
                self.send_response(302)
                self.send_header("Location", "/files/" + self.path[len(prefix):])
                self.end_headers()
                return
        if self.path.startswith("/files/"):
            body = (cls.release / self.path[len("/files/"):]).read_bytes()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()


@pytest.fixture
def standin(box):
    StandIn.release, StandIn.answer, StandIn.seen = release_dir(box["tmp"]), 0, []
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), StandIn)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    box["env"]["KRANTO_DOWNLOAD_BASE"] = f"http://127.0.0.1:{srv.server_address[1]}"
    yield StandIn
    srv.shutdown()


def test_public_the_latest_release_installs_with_no_login(box, standin):
    os.remove(box["fake"] / "gh")                     # no gh at all: a stranger's machine
    r, log = run(box, "--", "--yes")
    assert r.returncode == 0, r.stderr
    assert "Downloading the latest release of iddv/kranto" in r.stdout
    assert "kranto-9.9.9-py3-none-any.whl: OK" in r.stdout
    paths = [p for p, _ in standin.seen]
    assert paths[0] == "/iddv/kranto/releases/latest/download/SHA256SUMS"
    assert "/iddv/kranto/releases/latest/download/kranto-9.9.9-py3-none-any.whl" in paths
    assert all(auth == "" for _, auth in standin.seen)        # no login was ever sent
    assert log.splitlines()[-1] == "kranto setup --yes"
    assert not (box["home"] / ".config").exists()             # nothing kept: no login, no token
    assert not list(box["tmp"].glob("kranto-install.*"))      # the temporary folder is gone


def test_public_a_tag_installs_that_release(box, standin):
    r, log = run(box, "--version", "v9.9.9", "--no-setup")
    assert r.returncode == 0, r.stderr
    assert standin.seen[0][0] == "/iddv/kranto/releases/download/v9.9.9/SHA256SUMS"
    assert "gh " not in log and "kranto setup" not in log
    assert "Installed. Run 'kranto setup' when you are ready." in r.stdout


def test_no_stable_release_yet_names_the_way_on_and_asks_for_no_login(box, standin):
    standin.answer = 404
    os.remove(box["fake"] / "gh")
    r, log = run(box)
    assert r.returncode == 1 and "uv tool install" not in log
    assert "has no stable release yet" in r.stderr and "--version" in r.stderr
    said = (r.stdout + r.stderr).lower()
    for word in ("invitation", "token", "device", "sign in", "private"):
        assert word not in said, word


def test_a_release_only_a_signed_in_gh_can_see_downloads_with_gh(box, standin):
    """Before the repository is public, the owner's pre-release by tag: not found without a
    login, so the logged-in gh downloads it; setup is handed nothing of gh's."""
    standin.answer = 404
    side = box["tmp"] / "gh-side"
    side.mkdir()
    rel = release_dir(side)
    r, log = run(box, "--version", "v0.7.0-dev9", extra={"GH_LOGGED_IN": "1", "RELEASE": str(rel)})
    assert r.returncode == 0, r.stderr
    assert "gh release download v0.7.0-dev9 -R iddv/kranto" in log
    assert "trying again with your gh login" in r.stdout
    assert log.splitlines()[-1] == "kranto setup"


def test_gh_not_logged_in_is_not_asked_for(box, standin):
    standin.answer = 404
    r, log = run(box, "--version", "v1.2.3")
    assert r.returncode == 1
    assert "has no release v1.2.3" in r.stderr and "gh release download" not in log


def test_a_rate_limit_or_an_outage_says_so_and_asks_for_no_login(box, standin):
    standin.answer = 429
    r, log = run(box, extra={"GH_LOGGED_IN": "1"})
    assert r.returncode == 1 and "uv tool install" not in log
    assert "HTTP 429" in r.stderr and "try again in a few minutes" in r.stderr
    assert "gh release" not in log                     # an outage is not "needs a login"


def test_a_tampered_download_installs_nothing(box, standin):
    (standin.release / "kranto-9.9.9-py3-none-any.whl").write_bytes(b"tampered")
    r, log = run(box)
    assert r.returncode != 0 and "does not match SHA256SUMS" in r.stderr
    assert "uv tool install" not in log


def test_the_script_asks_for_no_login_and_names_no_app():
    """A public repository: no device flow, no OAuth App, no scopes, no invitation, and the
    words of the private time are gone."""
    text = SCRIPT.read_text()
    for gone in ("CLIENT_ID", "login/device", "read:org", "invitation", "github-token-file",
                 "OAuth", "publishes builds", "private before launch", "the owner"):
        assert gone not in text, gone


def test_the_script_runs_only_once_it_is_whole():
    """Under curl ... | sh a cut-off download must run nothing: every step is in main, called on
    the last line."""
    lines = [ln for ln in SCRIPT.read_text().splitlines() if ln.strip()]
    assert lines[-1] == 'main "$@"'


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
