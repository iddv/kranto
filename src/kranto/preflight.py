"""What this machine has for Kranto, as data: the checks ``kranto setup``'s
first section prints and the fix for each missing piece in this distribution's words.

``run(host)`` gives one ``Item`` per check: ``status`` (ok, warn, FAIL), ``name``, ``detail``,
``fix`` (the command that installs or repairs it here, or None) and ``needs`` (what stays off
without it). Nothing here installs anything or runs sudo: the wizard prints the command and
waits (D14). The distribution comes from ``/etc/os-release`` (``ID``, ``ID_LIKE``); macOS from
``uname``. ``kranto doctor`` keeps its own lines (``kranto.prerequisite_checks``) and takes the
fix commands from here.
"""

from __future__ import annotations

import json
import os
import platform
import re
import socket
import sys
from dataclasses import dataclass
from pathlib import Path

OK, WARN, FAIL = "ok", "warn", "FAIL"
UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh"
CLAUDE_INSTALL = "curl -fsSL https://claude.ai/install.sh | bash"
# distribution family -> how a package is installed there
INSTALL = {"debian": "sudo apt install {}", "fedora": "sudo dnf install {}",
           "arch": "sudo pacman -S {}", "suse": "sudo zypper install {}",
           "darwin": "brew install {}"}
PACKAGE = {"bwrap": "bubblewrap", "gh": "gh"}


@dataclass(frozen=True)
class Item:
    status: str
    name: str
    detail: str
    fix: str | None = None
    needs: str = ""

    def as_dict(self) -> dict:
        return {"status": self.status, "name": self.name, "detail": self.detail,
                "fix": self.fix, "needs": self.needs}


def os_release(path: Path = Path("/etc/os-release")) -> dict[str, str]:
    out = {}
    try:
        for line in path.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep:
                out[k.strip()] = v.strip().strip('"')
    except OSError:
        pass
    return out


def family(osr: dict[str, str] | None = None, system: str | None = None) -> str | None:
    """debian, fedora, arch, suse or darwin; None when the package manager is not known."""
    if (system or platform.system()) == "Darwin":
        return "darwin"
    osr = os_release() if osr is None else osr
    ids = [osr.get("ID", "").lower(), *osr.get("ID_LIKE", "").lower().split()]
    for i in ids:
        if i in ("debian", "ubuntu", "linuxmint", "pop", "raspbian"):
            return "debian"
        if i in ("fedora", "rhel", "centos", "rocky", "almalinux"):
            return "fedora"
        if i in ("arch", "manjaro", "endeavouros"):
            return "arch"
        if i.startswith("opensuse") or i in ("suse", "sles"):
            return "suse"
    return None


def install_command(tool: str, fam: str | None) -> str | None:
    """The command that installs ``tool`` here (the distribution's package, or the tool's own
    installer for uv and Claude Code); None when Kranto does not know this system."""
    if tool == "uv":
        return UV_INSTALL
    if tool == "claude":
        return CLAUDE_INSTALL
    pkg = PACKAGE.get(tool)
    return INSTALL[fam].format(pkg) if pkg and fam in INSTALL else None


def claude_layout(resolved: str, home: Path) -> str:
    """How a ``claude`` binary was installed, from where its symlinks end."""
    r = str(resolved)
    if r.startswith(str(home / ".local" / "share" / "claude" / "versions")):
        return "native install"
    if r.startswith(str(home / ".claude" / "local")):
        return "local install"
    if "node_modules/@anthropic-ai/claude-code" in r:
        return "npm install"
    if r.startswith("/opt/homebrew") or "/Cellar/" in r:
        return "Homebrew install"
    return "install"


def _version_key(p: Path) -> tuple:
    return tuple(int(x) if x.isdigit() else -1 for x in re.split(r"[.\-+]", p.name))


def npm_global_prefix(home: Path, npm: str) -> Path:
    """npm's global folder as ``npm prefix -g`` would say it, without running npm (every npm run
    leaves a log under ``~/.npm/_logs``, a folder a person who never used npm did not have): the
    ``NPM_CONFIG_PREFIX`` variable, else ``prefix=`` in ``~/.npmrc``, else the folder npm itself is
    in (``<prefix>/bin/npm``, npm's default)."""
    env = os.environ.get("NPM_CONFIG_PREFIX")
    if env:
        return Path(env).expanduser()
    try:
        for line in (home / ".npmrc").read_text().splitlines():
            m = re.match(r"\s*prefix\s*=\s*(\S.*?)\s*$", line)
            if m:
                return Path(m.group(1).replace("${HOME}", str(home))).expanduser()
    except (OSError, UnicodeDecodeError):
        pass
    return Path(npm).parent.parent


def claude_places(host) -> list[Path]:
    """Where the installers put ``claude`` when PATH has none, in order: the
    native installer's ``~/.local/bin/claude`` (a symlink into ``~/.local/share/claude/
    versions/``) and, without the symlink, its newest version; the old local install; npm's
    global folder (``npm_global_prefix``), then the usual prefixes."""
    home = Path(host.home)
    out = [home / ".local" / "bin" / "claude"]
    versions = home / ".local" / "share" / "claude" / "versions"
    try:
        found = [p for p in versions.iterdir() if p.is_file() and os.access(p, os.X_OK)]
    except OSError:
        found = []
    out += sorted(found, key=_version_key, reverse=True)[:1]
    out.append(home / ".claude" / "local" / "claude")
    npm = host.which("npm")
    if npm:
        out.append(npm_global_prefix(home, npm) / "bin" / "claude")
    out += [home / ".npm-global" / "bin" / "claude", home / ".local" / "share" / "npm" / "bin" /
            "claude", Path("/usr/local/bin/claude")]
    return out


def find_claude(host, given: str | None = None) -> tuple[str | None, str]:
    """``(path, how)``: ``--claude PATH`` as given (``how`` "given"; None when it is not an
    executable file), else ``claude`` on PATH ("PATH"), else the first of ``claude_places``
    ("found": PATH does not have it, so Kranto records it in ``build.claude_command``)."""
    if given:
        p = Path(given).expanduser()
        return (str(p.absolute()) if p.is_file() and os.access(p, os.X_OK) else None), "given"
    on_path = host.which("claude")
    if on_path:
        return on_path, "PATH"
    for p in claude_places(host):
        if p.is_file() and os.access(p, os.X_OK):
            return str(p), "found"
    return None, "missing"


def shell_only(path: str, home: Path) -> bool:
    """A folder a version manager puts on PATH only in an interactive shell (nvm, volta, fnm):
    a systemd unit's PATH will not have it."""
    return any(part in path for part in ("/.nvm/", "/.volta/", "/.fnm/", "/fnm_multishells/"))


def _version(host, exe: str) -> str:
    r = host.sh(exe, "--version", timeout=15)
    first = ((r.stdout or "").strip().splitlines() or [""])[0]
    m = re.search(r"\d+\.\d+(\.\d+)?", first)
    return m.group(0) if m and r.returncode == 0 else ""


def port_holder(port: int) -> str | None:
    """Who answers on 127.0.0.1:``port``: None when it is free."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return "something" if s.connect_ex(("127.0.0.1", port)) == 0 else None


CONSOLE_FIX = (f"{CLAUDE_INSTALL}, then run claude once to sign in")


def run(host, *, port: int = 8765, claude: str | None = None, port_check=port_holder,
        osr: dict[str, str] | None = None, system: str | None = None,
        proc_sys: Path = Path("/proc/sys"), builds: bool = False) -> list[Item]:
    """The machine's checks, in the order the wizard prints them. ``builds``: the install's
    ``builds.enabled``: off (the default, as on a fresh install), Claude Code is the
    console's only, so its absence is a warn ("Kranto works without it"), and ``gh`` (publishing's)
    is not checked."""
    from .launcher import BWRAP_PROBE, userns_reason

    system = system or platform.system()
    fam = family(osr, system)
    out: list[Item] = []
    osr = os_release() if osr is None else osr
    if system == "Darwin":
        out.append(Item(WARN, "macos", f"macOS {platform.mac_ver()[0]} ({platform.machine()}): "
                        "watching works; Open in Claude Code and the post writers need Linux's "
                        "bubblewrap sandbox", needs="Open in Claude Code and the post writers"))
    elif system == "Linux":
        out.append(Item(OK, "linux", f"{osr.get('PRETTY_NAME') or 'Linux'} ({platform.machine()})"))
    else:
        out.append(Item(FAIL, "system", f"{system}: Kranto runs on Linux (macOS: watching only)"))
    out.append(Item(OK, "python", f"{platform.python_version()} ({sys.executable})"))
    uv = host.which("uv")
    out.append(Item(OK, "uv", f"{_version(host, uv) or 'found'} ({uv})") if uv else
               Item(WARN, "uv", "not on PATH: 'kranto update' installs releases with it",
                    install_command("uv", fam), "kranto update"))
    if system != "Darwin":
        bw = host.which("bwrap")
        if not bw:
            out.append(Item(FAIL, "bwrap", "not installed. Open in Claude Code and the post "
                                           "writers run inside it; watching does not need it",
                            install_command("bwrap", fam),
                            "Open in Claude Code and the post writers"))
        else:
            r = host.sh(bw, *BWRAP_PROBE, timeout=20)
            out.append(Item(OK, "bwrap", f"{_version(host, bw) or 'found'}: a sandbox with its own "
                                         "/proc starts") if r.returncode == 0 else
                       Item(FAIL, "bwrap", f"installed but a sandbox cannot start here: "
                                           f"{userns_reason(proc_sys)}",
                            install_command("bwrap", fam) if fam == "debian" else None,
                            "Open in Claude Code and the post writers"))
    exe, found = (None, "skipped") if system == "Darwin" else find_claude(host, claude)
    if system == "Darwin":
        out.append(Item(OK, "sandbox", "skipped on macOS: no bubblewrap sandbox, so no Open in "
                                       "Claude Code; bwrap, Claude Code and systemd are not "
                                       "checked"))
    elif not exe and found == "given":
        out.append(Item(FAIL if builds else WARN, "claude",
                        f"--claude {claude}: not an executable file",
                        CLAUDE_INSTALL if builds else CONSOLE_FIX, "builds" if builds else
                        "the console"))
    elif not exe and not builds:
        out.append(Item(WARN, "claude", "Claude Code is not installed; Kranto works without it "
                                        "(the console beside every page uses it)",
                        CONSOLE_FIX, "the console"))
    elif not exe:
        out.append(Item(FAIL, "claude", "Claude Code is not installed (builds, the pitch and "
                                        "Open in Claude Code use it; watching does not)",
                        CLAUDE_INSTALL, "builds"))
    else:
        resolved = os.path.realpath(exe)
        how = claude_layout(resolved, host.home)
        r = host.sh(exe, "auth", "status", timeout=30)
        info = {}
        try:
            text = r.stdout or ""
            info = json.loads(text[text.index("{"):]) if "{" in text else {}
        except ValueError:
            info = {}
        method = str(info.get("authMethod") or "")
        signed = r.returncode == 0 and info.get("loggedIn", True)
        where = f"{_version(host, exe) or 'found'}, {how} at {exe}"
        if found in ("given", "found"):
            where += "; not on PATH: Kranto keeps this path (build.claude_command)"
        elif shell_only(resolved, host.home):
            where += "; that folder is on PATH only in your shell: Kranto puts it on the service's"
        out.append(Item(OK, "claude", where + (f"; signed in ({method})" if signed and
                                               re.fullmatch(r"[\w.-]{1,40}", method)
                                               else "; signed in" if signed else ""))
                   if signed else
                   Item(FAIL, "claude", where + "; not signed in", "claude auth login", "builds")
                   if builds else
                   Item(WARN, "claude", where + "; not signed in: Kranto works without it (the "
                        "console uses it)", "run claude once to sign in", "the console"))
    if builds:
        out += _gh(host, fam)
    if system != "Darwin":
        why = host.systemd()
        out.append(Item(OK, "systemd", "a user manager runs here: Kranto can start at boot and "
                                       "keep running after you log out") if why is None else
                   Item(WARN, "systemd", f"not usable: {why}; Kranto serves in the foreground"))
    holder = port_check(port)
    out.append(Item(OK, f"port {port}", "free") if holder is None else
               Item(WARN, f"port {port}", "in use (Kranto itself, when it already runs here)"))
    return out


def _gh(host, fam: str | None) -> list[Item]:
    """The GitHub CLI's lines: publishing's, checked only with builds on."""
    from . import ghfetch

    own = ghfetch.bin_dir(host.home) / "gh"
    gh = host.which("gh") or (str(own) if own.is_file() else None)
    if not gh:
        return [Item(WARN, "gh", "not installed. Kranto publishes and maintains through it",
                     install_command("gh", fam), "publishing")]
    out: list[Item] = []
    r = host.sh(gh, "auth", "status", timeout=30)
    m = re.search(r"account ([A-Za-z0-9-]{1,39})", (r.stdout or "") + (r.stderr or ""))
    if Path(gh) == own:
        note = ghfetch.age_note(host.sh(gh, "--version", timeout=15).stdout or "")
        if note:
            out.append(Item(WARN, "gh age", note, install_command("gh", fam)))
    out.append(Item(OK, "gh", f"{_version(host, gh) or 'found'} at {gh}; "
                    + (f"logged in as {m.group(1)}" if r.returncode == 0 and m else
                       "logged in" if r.returncode == 0 else
                       "no login yet (GitHub is asked below)")))
    return out
