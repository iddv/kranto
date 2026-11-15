#!/bin/sh
# Install kranto, then run its setup (the owner's D1 of 2026-10-17).
#
#   sh install.sh [--version vX.Y.Z | vX.Y.0-devN] [--from DIR] [--no-setup] [-- SETUP-ARGS...]
#
# 1. uv: found on PATH or in ~/.local/bin, else installed with astral's installer.
# 2. A GitHub login for the download, while the repositories are private: your logged-in gh
#    when there is one, else GitHub's device flow with kranto' OAuth App (a code you type at
#    github.com/login/device). Public: no login at all.
# 3. The release's three wheels and SHA256SUMS, every hash checked before anything installs.
# 4. uv tool install, as kranto update installs a release.
# 5. exec kranto setup, which keeps the device flow's login as kranto' own GitHub connection
#    (--github-token-file; the file is removed once read), so you sign in once.
#
# It never runs sudo, writes nothing outside ~/.local (uv, the tool) and a temporary folder,
# and prints no token. Environment: KRANTO_REPO (default iddv/kranto), KRANTO_VERSION,
# KRANTO_GITHUB_CLIENT_ID (overrides the client id below; "" for gh only),
# KRANTO_INSTALL_FROM (as --from);
# KRANTO_GITHUB_API and KRANTO_GITHUB_WEB point the tests at a fake GitHub on loopback.
set -eu

REPO="${KRANTO_REPO:-iddv/kranto}"
# kranto' OAuth App "kranto" (a client id is public by GitHub's definition; there is no client
# secret and none is ever used). Kept equal to src/kranto/page/github_user.py's CLIENT_ID by tests in
# both repositories. KRANTO_GITHUB_CLIENT_ID overrides it; set to "" it turns the device flow
# off, and the download then needs a logged-in gh.
CLIENT_ID="Ov23lismfFcZrfTLDoxm"
CLIENT_ID="${KRANTO_GITHUB_CLIENT_ID-$CLIENT_ID}"
SCOPES="repo workflow read:org"
VERSION="${KRANTO_VERSION:-}"
FROM="${KRANTO_INSTALL_FROM:-}"
SETUP=1
FETCH_GH=0

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || die "--version needs a tag"; VERSION="$2"; shift 2 ;;
    --from) [ $# -ge 2 ] || die "--from needs a folder"; FROM="$2"; shift 2 ;;
    --no-setup) SETUP=0; shift ;;
    --fetch-gh) FETCH_GH=1; shift ;;
    --) shift; break ;;
    -h|--help) say "usage: sh install.sh [--version vX.Y.Z | vX.Y.0-devN] [--from DIR] [--no-setup] [--fetch-gh] [-- SETUP-ARGS...]"
               say "  --fetch-gh  when gh is missing, kranto setup fetches a pinned, checksum-checked gh"
               say "              into kranto' own folder (asked first; after -- add --yes to skip asking)"
               exit 0 ;;
    *) die "unknown option $1 (setup's own options go after --)" ;;
  esac
done

case "$(uname -s)" in
  Linux) ;;
  Darwin) say "macOS: kranto installs the watcher only. Builds need Linux's bubblewrap sandbox, so"
          say "bwrap, systemd and the build checks are skipped; kranto serves in the foreground." ;;
  *) die "kranto runs on Linux (and macOS for watching only); this is $(uname -s)" ;;
esac

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

# -- 1. uv --------------------------------------------------------------------------------------
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
cleanup() { rm -rf "$WORK"; }
trap cleanup EXIT INT TERM
TOKEN_FILE=""
GITHUB_HOW=""

helper() {   # the download's HTTP, JSON and hashes, in uv's Python (3.12, fetched when missing)
  uv run --quiet --no-project --python 3.12 python -I - "$@" <<'PY'
import hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from pathlib import Path

API = os.environ.get("KRANTO_GITHUB_API", "https://api.github.com").rstrip("/")
WEB = os.environ.get("KRANTO_GITHUB_WEB", "https://github.com").rstrip("/")

def req(url, *, token=None, data=None, accept="application/vnd.github+json"):
    r = urllib.request.Request(url, data=data, headers={"Accept": accept, "User-Agent": "kranto-install"})
    if token:
        r.add_header("Authorization", f"Bearer {token}")
    return urllib.request.urlopen(r, timeout=60)

def release(repo, tag, token):
    path = f"tags/{tag}" if tag else "latest"
    with req(f"{API}/repos/{repo}/releases/{path}", token=token) as r:
        return json.load(r)

def want(name):
    return name.endswith(".whl") or name == "SHA256SUMS"

cmd, args = sys.argv[1], sys.argv[2:]
if cmd == "public":                       # exit 0: the release is readable without a login
    repo, tag = args
    try:
        release(repo, tag, None)
    except urllib.error.HTTPError:
        sys.exit(1)
    except OSError as exc:
        sys.exit(f"cannot reach GitHub: {exc}")
elif cmd == "device":                     # the device flow; the token goes to a 0600 file only
    client, scopes, out = args
    form = urllib.parse.urlencode({"client_id": client, "scope": scopes}).encode()
    with req(f"{WEB}/login/device/code", data=form, accept="application/json") as r:
        code = json.load(r)
    print(f"\nOpen {code['verification_uri']} and enter   {code['user_code']}\n"
          f"(waiting up to {int(code['expires_in']) // 60} minutes)", flush=True)
    interval, deadline = int(code.get("interval", 5)), time.monotonic() + int(code["expires_in"])
    form = urllib.parse.urlencode({"client_id": client, "device_code": code["device_code"],
                                   "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}).encode()
    while time.monotonic() < deadline:
        time.sleep(interval)
        with req(f"{WEB}/login/oauth/access_token", data=form,
                 accept="application/json") as r:
            got = json.load(r)
        err = got.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            sys.exit({"expired_token": "the code expired; run install.sh again",
                      "access_denied": "the sign-in was cancelled on GitHub"}.get(err, err))
        granted = set((got.get("scope") or "").replace(",", " ").split())
        if not granted <= set(scopes.split()):
            sys.exit("GitHub granted wider scopes than kranto asked for; nothing was kept")
        p = Path(out)
        p.touch(mode=0o600)
        # an OAuth App with expiring tokens also gives a refresh token: kranto setup keeps it
        # (0600), and kranto renews the eight-hour token with it
        extra = {"GH_REFRESH_TOKEN": got.get("refresh_token"),
                 "GH_TOKEN_EXPIRES_IN": got.get("expires_in"),
                 "GH_REFRESH_EXPIRES_IN": got.get("refresh_token_expires_in")}
        p.write_text(f"GH_TOKEN={got['access_token']}\n"
                     + "".join(f"{k}={v}\n" for k, v in extra.items() if v))
        print("Signed in to GitHub.", flush=True)
        sys.exit(0)
    sys.exit("the code expired; run install.sh again")
elif cmd == "download":                   # the wheels and SHA256SUMS of a release, by API
    repo, tag, dest, token_file = args
    token = None
    if token_file:
        token = next((ln.partition("=")[2].strip() for ln in Path(token_file).read_text().splitlines()
                      if ln.startswith("GH_TOKEN=")), None)
    rel = release(repo, tag, token)
    for a in rel.get("assets") or []:
        if want(a["name"]):
            with req(a["url"], token=token, accept="application/octet-stream") as r:
                (Path(dest) / Path(a["name"]).name).write_bytes(r.read())
    print(rel["tag_name"])
elif cmd == "verify":                     # every wheel listed in SHA256SUMS, every hash matching
    dest = Path(args[0])
    sums = {}
    for line in (dest / "SHA256SUMS").read_text().splitlines():
        h, _, name = line.strip().partition("  ")
        if h and name:
            sums[name.lstrip("*")] = h
    wheels = sorted(p.name for p in dest.glob("*.whl"))
    if len(wheels) != 1 or wheels[0].split("-", 1)[0] != "kranto":
        sys.exit(f"the release must hold exactly one wheel, kranto's; found {wheels}")
    for n in wheels:
        h = hashlib.sha256((dest / n).read_bytes()).hexdigest()
        if sums.get(n) != h:
            sys.exit(f"{n}: its hash does not match SHA256SUMS; nothing was installed")
        print(f"{n}: OK")
PY
}

# -- 2 and 3. the wheels ------------------------------------------------------------------------
DIST="$WORK/dist"
mkdir -p "$DIST"
if [ -n "$FROM" ]; then
  say "Installing from $FROM"
  cp "$FROM"/*.whl "$FROM"/SHA256SUMS "$DIST"/
elif helper public "$REPO" "$VERSION" 2>/dev/null; then
  say "Downloading the release from $REPO (public)"
  VERSION="$(helper download "$REPO" "$VERSION" "$DIST" "")"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  if [ -z "$VERSION" ]; then
    VERSION="$(gh release view -R "$REPO" --json tagName --jq .tagName)" ||
      die "gh cannot see $REPO's releases: accept the invitation at https://github.com/$REPO/invitations"
  fi
  say "Downloading $VERSION from $REPO with your gh login"
  gh release download "$VERSION" -R "$REPO" -p '*.whl' -p SHA256SUMS -D "$DIST"
  GITHUB_HOW="gh"
elif [ -n "$CLIENT_ID" ]; then
  say "Signing in to GitHub to download kranto ($REPO is private before launch)."
  say "Kranto asks for: $SCOPES (it publishes builds to your account and reads the repositories you pick)."
  TOKEN_FILE="$WORK/github.env"
  helper device "$CLIENT_ID" "$SCOPES" "$TOKEN_FILE"
  VERSION="$(helper download "$REPO" "$VERSION" "$DIST" "$TOKEN_FILE")"
else
  say "Kranto's repository is private before launch, so the download needs a GitHub login."
  if command -v gh >/dev/null 2>&1; then
    say "gh is installed but not logged in. Run:"
  else
    say "Install the GitHub CLI (https://cli.github.com):"
    say "  $(distro_hint gh)"
    say "then run:"
  fi
  say "  gh auth login"
  say "and accept the invitations at https://github.com/$REPO/invitations (and kranto.page's), then"
  say "run 'sh install.sh' again."
  exit 1
fi
helper verify "$DIST"

# -- 4. install ---------------------------------------------------------------------------------
WHEEL="$(ls "$DIST"/kranto-*.whl)"
uv tool install --force --python 3.12 "kranto[connections,notify,mcp] @ file://$WHEEL"
command -v kranto >/dev/null 2>&1 || die "kranto is installed but not on PATH: open a new terminal (uv put ~/.local/bin on it)"
kranto --version

# -- 5. setup -----------------------------------------------------------------------------------
if [ "$SETUP" = 0 ]; then
  say "Installed. Run 'kranto setup$([ "$FETCH_GH" = 1 ] && printf ' --fetch-gh')' when you are ready."
  exit 0
fi
if ! kranto setup --help >/dev/null 2>&1; then     # a release from before the wizard
  say "This release has no 'kranto setup' yet; starting kranto with 'kranto up'."
  exec kranto up
fi
if [ -n "$TOKEN_FILE" ]; then
  # kranto setup moves the login into its own store (0600) and removes this file
  KEEP="$HOME/.config/kranto/github"
  mkdir -p "$KEEP"
  chmod 700 "$HOME/.config/kranto" "$KEEP"
  mv "$TOKEN_FILE" "$KEEP/install-login.env"
  set -- --github-token-file "$KEEP/install-login.env" "$@"
elif [ "$GITHUB_HOW" = gh ]; then
  set -- --github gh "$@"
fi
if [ "$FETCH_GH" = 1 ]; then
  set -- --fetch-gh "$@"
fi
trap - EXIT INT TERM
cleanup
if [ ! -t 0 ] && (exec </dev/tty) 2>/dev/null; then
  exec kranto setup "$@" </dev/tty   # curl ... | sh: the questions read the terminal, not the pipe
fi
exec kranto setup "$@"
