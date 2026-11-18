#!/bin/sh
# Install Kranto from a GitHub release, then run its setup.
#
#   curl -fsSL https://github.com/iddv/kranto/releases/latest/download/install.sh | sh
#   sh install.sh [--version vX.Y.Z] [--from DIR] [--no-setup] [--fetch-gh] [-- SETUP-ARGS...]
#
# 1. uv: found on PATH or in ~/.local/bin, else installed with uv's own installer.
# 2. The release's SHA256SUMS and the wheel it names, from the release's download addresses
#    (https://github.com/<repo>/releases/latest/download/<file>, or
#    .../releases/download/<tag>/<file> with --version). No GitHub account, token or gh needed.
# 3. Every file checked against SHA256SUMS before anything installs. A release without a
#    kranto wheel is refused in one line.
# 4. uv tool install, the same install kranto update does.
# 5. kranto setup (its questions read the terminal, also under curl ... | sh).
#
# A release you can only see while signed in to GitHub (a pre-release of a private repository)
# is downloaded with your gh login instead, when gh is installed and logged in.
#
# It never runs sudo, writes nothing outside ~/.local (uv, the tool) and a temporary folder, and
# keeps no login. Environment: KRANTO_REPO (default iddv/kranto), KRANTO_VERSION (as --version),
# KRANTO_INSTALL_FROM (as --from), KRANTO_DOWNLOAD_BASE (default https://github.com; the tests
# point it at a stand-in on loopback).
#
# Everything runs from main at the bottom, so a download cut off half way runs nothing.
set -eu

REPO="${KRANTO_REPO:-iddv/kranto}"
BASE="${KRANTO_DOWNLOAD_BASE:-https://github.com}"
VERSION="${KRANTO_VERSION:-}"
FROM="${KRANTO_INSTALL_FROM:-}"
SETUP=1
FETCH_GH=0
NOT_FOUND=3        # the helper's exit status for "no such release or file" (HTTP 404)

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

usage() {
  say "usage: sh install.sh [--version vX.Y.Z] [--from DIR] [--no-setup] [--fetch-gh] [-- SETUP-ARGS...]"
  say "  --version   install this release (a tag from https://github.com/$REPO/releases);"
  say "              without it, the latest stable release"
  say "  --from      install from a folder holding the wheel and SHA256SUMS"
  say "  --no-setup  install only; run 'kranto setup' yourself later"
  say "  --fetch-gh  when gh is missing, kranto setup fetches a pinned, checksum-checked gh"
  say "              into Kranto's own folder (asked first; after -- add --yes to skip asking)"
}

distro_hint() {   # $1: a package name; prints the command for this machine's package manager
  if command -v apt-get >/dev/null 2>&1; then say "sudo apt install $1"
  elif command -v dnf >/dev/null 2>&1; then say "sudo dnf install $1"
  elif command -v pacman >/dev/null 2>&1; then say "sudo pacman -S $1"
  elif command -v zypper >/dev/null 2>&1; then say "sudo zypper install $1"
  elif command -v brew >/dev/null 2>&1; then say "brew install $1"
  else say "your package manager's $1 package"; fi
}

fetch() {   # $1 URL: to stdout, with curl or wget
  if command -v curl >/dev/null 2>&1; then curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then wget -qO- "$1"
  else die "neither curl nor wget is installed: $(distro_hint curl)"; fi
}

helper() {   # the download and the hashes, in uv's Python (3.12, fetched when missing)
  uv run --quiet --no-project --python 3.12 python -I - "$@" <<'PY'
import hashlib, sys, urllib.error, urllib.request
from pathlib import Path

NOT_FOUND = 3

def get(url):
    r = urllib.request.Request(url, headers={"User-Agent": "kranto-install"})
    try:
        with urllib.request.urlopen(r, timeout=120) as resp:      # follows GitHub's redirect
            return resp.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            print(f"not found: {url}", file=sys.stderr)
            sys.exit(NOT_FOUND)
        sys.exit(f"GitHub answered HTTP {exc.code} for {url}; try again in a few minutes")
    except OSError as exc:
        sys.exit(f"cannot reach {url}: {exc}")

def sums_of(text):
    out = {}
    for line in text.splitlines():
        h, _, name = line.strip().partition("  ")
        if h and name:
            out[name.lstrip("*")] = h
    return out

cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "download":            # SHA256SUMS, then every wheel it names
    base, repo, tag, dest = args
    where = f"{base}/{repo}/releases/" + (f"download/{tag}" if tag else "latest/download")
    sums = get(f"{where}/SHA256SUMS")
    (Path(dest) / "SHA256SUMS").write_bytes(sums)
    for name in sums_of(sums.decode()):
        if name.endswith(".whl") and "/" not in name:
            (Path(dest) / name).write_bytes(get(f"{where}/{name}"))
elif cmd == "verify":            # one kranto wheel, listed in SHA256SUMS, its hash matching
    dest = Path(args[0])
    sums = sums_of((dest / "SHA256SUMS").read_text())
    wheels = sorted(p.name for p in dest.glob("*.whl"))
    if not any(w.split("-", 1)[0] == "kranto" for w in wheels):
        sys.exit("this release has no kranto wheel (it only updates an install made before the "
                 "rename); install a newer release: sh install.sh --version <a later tag>")
    if len(wheels) != 1:
        sys.exit(f"the release must hold exactly one wheel, kranto's; found {wheels}")
    for n in wheels:
        h = hashlib.sha256((dest / n).read_bytes()).hexdigest()
        if sums.get(n) != h:
            sys.exit(f"{n}: its hash does not match SHA256SUMS; nothing was installed")
        print(f"{n}: OK")
PY
}

gh_ready() { command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; }

download() {   # into $DIST: the release's files, without a login, else with a logged-in gh
  if [ -n "$VERSION" ]; then what="$VERSION"; else what="the latest release"; fi
  say "Downloading $what of $REPO"
  status=0
  helper download "$BASE" "$REPO" "$VERSION" "$DIST" || status=$?
  [ "$status" = 0 ] && return 0
  [ "$status" = "$NOT_FOUND" ] || exit 1
  if gh_ready; then
    tag="$VERSION"
    if [ -z "$tag" ]; then
      tag="$(gh release view -R "$REPO" --json tagName --jq .tagName 2>/dev/null)" || tag=""
    fi
    if [ -n "$tag" ]; then
      say "Not found without a login; trying again with your gh login"
      if gh release download "$tag" -R "$REPO" -p '*.whl' -p SHA256SUMS -D "$DIST" 2>/dev/null; then
        return 0
      fi
    fi
  fi
  if [ -n "$VERSION" ]; then
    die "$REPO has no release $VERSION. The releases: https://github.com/$REPO/releases"
  fi
  die "$REPO has no stable release yet. Name one from https://github.com/$REPO/releases: sh install.sh --version <tag>"
}

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --version) [ $# -ge 2 ] || die "--version needs a tag"; VERSION="$2"; shift 2 ;;
      --from) [ $# -ge 2 ] || die "--from needs a folder"; FROM="$2"; shift 2 ;;
      --no-setup) SETUP=0; shift ;;
      --fetch-gh) FETCH_GH=1; shift ;;
      --) shift; break ;;
      -h|--help) usage; exit 0 ;;
      *) die "unknown option $1 (setup's own options go after --)" ;;
    esac
  done

  case "$(uname -s)" in
    Linux) ;;
    Darwin) say "macOS: Kranto installs the watcher only, and nobody has tested it on a Mac yet."
            say "The console and the post writers need Linux's bubblewrap sandbox, so they stay off;"
            say "Kranto serves in the foreground (no systemd)." ;;
    *) die "Kranto runs on Linux (and macOS for watching only); this is $(uname -s)" ;;
  esac

  # -- 1. uv ------------------------------------------------------------------------------------
  PATH="$HOME/.local/bin:$PATH"
  export PATH
  if ! command -v uv >/dev/null 2>&1; then
    say "Installing uv (https://docs.astral.sh/uv/) into ~/.local/bin"
    fetch https://astral.sh/uv/install.sh | sh
    command -v uv >/dev/null 2>&1 || die "uv did not install; see https://docs.astral.sh/uv/"
  fi
  say "uv: $(uv --version)"

  WORK="$(mktemp -d "${TMPDIR:-/tmp}/kranto-install.XXXXXX")"
  chmod 700 "$WORK"
  trap 'rm -rf "$WORK"' EXIT INT TERM

  # -- 2 and 3. the wheel -----------------------------------------------------------------------
  DIST="$WORK/dist"
  mkdir -p "$DIST"
  if [ -n "$FROM" ]; then
    say "Installing from $FROM"
    cp "$FROM"/*.whl "$FROM"/SHA256SUMS "$DIST"/
  else
    download
  fi
  helper verify "$DIST"

  # -- 4. install -------------------------------------------------------------------------------
  WHEEL="$(ls "$DIST"/kranto-*.whl)"
  uv tool install --force --python 3.12 "kranto[connections,notify,mcp] @ file://$WHEEL"
  command -v kranto >/dev/null 2>&1 || die "kranto is installed but not on PATH: open a new terminal (uv put ~/.local/bin on it)"
  kranto --version

  # -- 5. setup ---------------------------------------------------------------------------------
  if [ "$SETUP" = 0 ]; then
    say "Installed. Run 'kranto setup$([ "$FETCH_GH" = 1 ] && printf ' --fetch-gh')' when you are ready."
    exit 0
  fi
  rm -rf "$WORK"
  trap - EXIT INT TERM
  if ! kranto setup --help >/dev/null 2>&1; then     # a release from before the wizard
    say "This release has no 'kranto setup' yet; starting Kranto with 'kranto up'."
    exec kranto up
  fi
  if [ "$FETCH_GH" = 1 ]; then
    set -- --fetch-gh "$@"
  fi
  if [ ! -t 0 ] && (exec </dev/tty) 2>/dev/null; then
    exec kranto setup "$@" </dev/tty   # curl ... | sh: the questions read the terminal, not the pipe
  fi
  exec kranto setup "$@"
}

main "$@"
