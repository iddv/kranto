#!/usr/bin/env bash
# Cut a kranto release on this machine, with the owner's own gh login and git remotes: decide,
# build, smoke, notes, publish. This is the one way releases are cut (a GitHub workflow that
# did the same never ran green and was deleted; it is in git history for the day the repos
# go public).
#
#   scripts/release/cut_local.sh [--line nightly|stable] [--from-tag vX.Y.0-devN]
#                                [--shape final|compat] [--must-include kranto@SHA]...
#                                [--plan] [--dry-run]
#
# The two lines (the owner's decisions of 2026-10-24; decide.py numbers them):
#   (no flag)            a nightly build from main's newest green commits: vX.Y.0-devN, a GitHub
#                        prerelease. Installs on the nightly channel see it; stable never does.
#   --from-tag vX.Y.0-devN
#                        a promotion: the owner chose to make that nightly build stable. vX.Y.0
#                        from the dev tag's own commit, published held (a
#                        prerelease with its vX.Y.Z tag), and release/X.Y created
#                        at that commit (release branches older than the two newest are
#                        deleted; their tags stay). Time never decides it: the press does.
#   --line stable        a fix on the stable line: vX.Y.(Z+1) from release/X.Y's newest green
#                        commits (a cherry-pick merged there; hotfix.sh --stable), published held.
# A held release reaches stable installs when gate.py promote --now releases it, after
# rc_check.sh passed on it. When decide.py says rc_check is required (rc_check.required: the
# update, the install, the packaging, a migration, the unit, and always for a promotion), the
# cut prints the rc_check.sh line to run on the published build before the owner's install
# takes a nightly, or before a held release is released. Such a nightly is published unoffered
#: its notes open with "**Do not install:** being checked", so no install is
# offered it; rc_check.sh checks it by tag, the maintainer checks no one asked to hold it, and
# gate.py offer TAG (only after rc_check passed on it) removes the line. The rc tags
# (--prerelease rcN) are retired: every candidate is checked on itself.
#
# --shape (build.sh's): final (the default), the one wheel; compat, the three wheels of the one
# nightly that crosses an install made before the rename over (refused once a final release
# exists, and a final release is refused until the release before it carries the helper for
# both shapes: guards.py shape, checked here before the build and again by publish.py;
# RELEASES_JSON, a file of GitHub's release list, stands in for gh's).
#
# Clones the one repository (REPO, default public.toml's repo) into a fresh work dir
# (RELEASE_WORK, default ~/.cache/kranto-release/<time>), so nothing in a working checkout is
# touched, and cuts from the branch's newest commit whose
# checks are all green (checks.py newest-green), not from a head still being checked. --dry-run stops
# before publish: no tag or branch is pushed and no release is created; the wheels,
# SHA256SUMS, manifest.json and notes.md stay in the work dir. One cut at a time on this
# machine (a lock, RELEASE_LOCK): two cuts never take the same version. Needs git, gh (logged
# in, with write access to the repository), uv, python3 and flock; ~/.local/bin is put on PATH.
#
# The guards (guards.py):
# --must-include kranto@SHA (repeatable; OWNER/kranto@SHA too): wait, bounded
#   (RELEASE_MUST_INCLUDE_WAIT seconds, 2700 by default, saying so while it waits), until SHA is
#   in the branch being cut (main, or release/X.Y with --line stable) and every check on it is
#   green, then cut from a head that holds it; refuse when its checks fail, when the wait runs
#   out, or when the head (with --from-tag, the dev tag) does not hold it.
# An empty release is refused (decide.py): no commit since the previous tag.
# The release notes end with `git log --oneline <previous>..<tag>`, and the cut
# prints the same lists after publishing: a release is not done until its commit list has been
# read and holds the change it was cut for.
# --plan stops after decide.py: what would be cut, from which commits, and whether rc_check is
# required (hotfix.sh asks it).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

LINE=nightly DRY_RUN="" FROM_TAG="" PLAN="" PRERELEASE="" SHAPE=final
MUST=()
usage() {
  echo "usage: $0 [--line nightly|stable] [--from-tag vX.Y.0-devN] [--shape final|compat]" \
       "[--must-include kranto@SHA]... [--plan] [--dry-run]" >&2
  exit 2
}
while [ $# -gt 0 ]; do
  case "$1" in
    --line) LINE="$2"; shift 2 ;;
    --from-tag) FROM_TAG="$2"; shift 2 ;;
    --shape) SHAPE="$2"; shift 2 ;;
    --must-include) MUST+=("$2"); shift 2 ;;
    --plan) PLAN=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    --prerelease) PRERELEASE="$2"; shift 2 ;;
    --bump) echo "cut_local: --bump is retired: the line decides the number (nightly: the next" \
                 "minor's devN; --from-tag: its minor; --line stable: the next patch)" >&2; exit 2 ;;
    *) usage ;;
  esac
done
if [ -n "$PRERELEASE" ]; then
  echo "cut_local: --prerelease rcN is retired: a nightly is a prerelease and is checked on" \
       "itself (rc_check.sh TAG); cut it with no flag" >&2
  exit 2
fi
case "$LINE" in nightly|stable) ;; *) echo "cut_local: --line is nightly or stable, not '$LINE'" >&2; exit 2 ;; esac
case "$SHAPE" in final|compat) ;; *) echo "cut_local: --shape is final or compat, not '$SHAPE'" >&2; exit 2 ;; esac
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="$(python3 "$HERE/names.py" dist)"
for m in ${MUST[@]+"${MUST[@]}"}; do
  [[ "$m" =~ ^([A-Za-z0-9_.-]+/)?([A-Za-z0-9_.-]+)@[0-9a-fA-F]{7,40}$ ]] \
    && [ "${BASH_REMATCH[2]}" = "$NAME" ] || {
    echo "cut_local: --must-include takes $NAME@SHA, not '$m'" >&2; exit 2; }
done
for t in git gh uv python3 flock; do
  command -v "$t" >/dev/null || {
    echo "cut_local: '$t' is not on PATH ($PATH); nothing was cut" >&2; exit 2; }
done
if [ -n "$FROM_TAG" ]; then
  [[ "$FROM_TAG" =~ ^v[0-9]+\.[0-9]+\.0-dev[0-9]+$ ]] || {
    echo "cut_local: --from-tag takes a nightly build's tag (vX.Y.0-devN), not '$FROM_TAG'" >&2
    exit 2; }
  [ "$LINE" = nightly ] || { echo "cut_local: --from-tag is a promotion; drop --line" >&2; exit 2; }
fi
if [ "$SHAPE" = compat ] && { [ -n "$FROM_TAG" ] || [ "$LINE" != nightly ]; }; then
  echo "cut_local: the compat shape is the one nightly crossing; not a promotion or a fix" >&2
  exit 2
fi

REPO="${REPO:-$(python3 "$HERE/names.py" repo)}"
LOCK="${RELEASE_LOCK:-$HOME/.cache/kranto-release/lock}"
mkdir -p "$(dirname "$LOCK")"
exec 9>"$LOCK"
flock -w "${RELEASE_LOCK_WAIT:-900}" 9 || {
  echo "cut_local: another cut still holds $LOCK; nothing was cut" >&2; exit 2; }
WORK="${RELEASE_WORK:-$HOME/.cache/kranto-release/$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$WORK"
echo "work dir: $WORK"

gh auth status >/dev/null 2>&1 || { echo "cut_local: gh is not logged in ('gh auth login')" >&2; exit 2; }
BRANCH=main
SRC="$WORK/$NAME" DIST="$WORK/dist"
git clone --quiet "${RELEASE_GIT_BASE:-https://github.com}/$REPO" "$SRC"
git -C "$SRC" fetch --quiet --tags origin
if [ "$LINE" = stable ]; then
  # the stable line's branch, from the newest stable tag (release/X.Y)
  BRANCH="$(python3 "$HERE/decide.py" --src "$SRC" --stable-branch)" \
    || { echo "cut_local: no stable line to cut a fix on" >&2; exit 2; }
  git -C "$SRC" rev-parse -q --verify "origin/$BRANCH" >/dev/null || {
    echo "cut_local: $REPO has no $BRANCH yet (it is made by the first promotion to" \
         "${BRANCH#release/}.0); nothing was cut" >&2; exit 2; }
fi
name="$NAME" repo="$REPO"
musts=()
for m in ${MUST[@]+"${MUST[@]}"}; do musts+=("${m#*@}"); done
{
  if [ -n "$FROM_TAG" ]; then
    git -C "$WORK/$name" checkout --quiet "$FROM_TAG^{commit}" || {
      echo "cut_local: $repo has no tag $FROM_TAG" >&2; exit 2; }
    echo "$name: $FROM_TAG = $(git -C "$WORK/$name" rev-parse --short HEAD)"
  else
    for m in ${musts[@]+"${musts[@]}"}; do
      echo "$name: must include $m: waiting until it is in $BRANCH and green (at most" \
           "${RELEASE_MUST_INCLUDE_WAIT:-2700}s)"
      python3 "$HERE/guards.py" wait "$repo" "$m" "$WORK/$name" --base "$BRANCH" \
        --timeout "${RELEASE_MUST_INCLUDE_WAIT:-2700}" \
        --interval "${RELEASE_MUST_INCLUDE_INTERVAL:-30}" || {
        echo "cut_local: $name@$m is not in $BRANCH and green; nothing was cut" >&2; exit 1; }
    done
    # the newest commit on the branch whose checks are all green: its head is often still
    # being checked while merges flow, and a pending run superseded by a newer push is cancelled
    git -C "$WORK/$name" checkout --quiet -B "$BRANCH" "origin/$BRANCH"
    sha="$(python3 "$HERE/../ci/checks.py" newest-green "$repo" "$WORK/$name")" || {
      echo "cut_local: no green commit among the last ones on $repo $BRANCH; nothing was cut" >&2
      exit 2; }
    git -C "$WORK/$name" checkout --quiet "$sha"
    echo "$name: $BRANCH's newest green commit is $(git -C "$WORK/$name" rev-parse --short HEAD)"
  fi
  for m in ${musts[@]+"${musts[@]}"}; do
    python3 "$HERE/guards.py" contains "$WORK/$name" HEAD "$m" || {
      echo "cut_local: the $name head being cut does not hold $m; nothing was cut" >&2; exit 1; }
  done
}

# Cut only from green commits: decide refuses when any check on the head is red, running
# or missing (CONTRIBUTING, "Merging and releasing").
python3 "$HERE/decide.py" --src "$SRC" --line "$LINE" \
  ${FROM_TAG:+--from-tag "$FROM_TAG"} --repo "$REPO" ${PLAN:+--plan} \
  > "$WORK/decide.json"
cat "$WORK/decide.json"
if [ -n "$PLAN" ]; then
  echo "plan: nothing built or published; the decision is $WORK/decide.json"
  exit 0
fi
read -r VERSION TAG PREVIOUS KIND HELD NEW_BRANCH RC_CHECK < <(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d["version"], d["tag"], d["previous"] or "-", d["kind"], int(d["held"]), d["branch"] or "-", int(d["rc_check"]["required"]))' "$WORK/decide.json")
[ "$PREVIOUS" = "-" ] && PREVIOUS=""

# the shape guard before the build (publish.py checks it again before it publishes)
python3 "$HERE/guards.py" shape "$SHAPE" "$TAG" --repo "$REPO" \
  ${RELEASES_JSON:+--releases "$RELEASES_JSON"} || {
  echo "cut_local: a $SHAPE release is refused at $TAG; nothing was built" >&2; exit 2; }
VERSION="$VERSION" TAG="$TAG" SRC="$SRC" DIST="$DIST" REPO="$REPO" \
  bash "$HERE/build.sh" --shape "$SHAPE"
VERSION="$VERSION" DIST="$DIST" WORK="$WORK/smoke" SHAPE="$SHAPE" bash "$HERE/smoke.sh"
# the non-interactive wizard on a bare HOME, served and stopped (a release with 'kranto setup')
if "$WORK/smoke/bin/kranto" setup --help > /dev/null 2>&1; then
  VERSION="$VERSION" DIST="$DIST" WORK="$WORK/smoke" SHAPE="$SHAPE" bash "$HERE/smoke.sh" setup
fi

# The regression corpus (docs/exam.md): with KRANTO_CORPUS set, the new page recomputes
# every check over every stored build, with no model and no network; an unexpected change
# stops the cut. KRANTO_CORPUS_EXPECT names the changes this release declares (a JSON list);
# KRANTO_CORPUS_RUN=1 also runs each exam (bwrap, loopback only; minutes per entry).
if [ -n "${KRANTO_CORPUS:-}" ]; then
  replay=(corpus replay --root "$KRANTO_CORPUS")
  [ -n "${KRANTO_CORPUS_EXPECT:-}" ] && replay+=(--expect "$KRANTO_CORPUS_EXPECT")
  [ -n "${KRANTO_CORPUS_RUN:-}" ] && replay+=(--run)
  "$WORK/smoke/bin/kranto" "${replay[@]}" || {
    echo "cut_local: the corpus replay found unexpected changes; nothing published" >&2
    exit 1
  }
fi

# a milestone's opening section (RELEASE_INTRO: a Markdown file, "What 0.4.0 is"), before the changes
intro=()
[ -n "${RELEASE_INTRO:-}" ] && intro=(--intro "$RELEASE_INTRO")
# the commit list (C4): `git log --oneline <previous>..<tag>`, in the notes too
extra=()
if [ -n "$PREVIOUS" ]; then
  python3 "$HERE/guards.py" log "$PREVIOUS" "$TAG" "$NAME=$SRC" --markdown > "$WORK/commits.md"
  extra+=(--commits "$WORK/commits.md" --previous "$PREVIOUS")
fi
if [ -n "$FROM_TAG" ]; then
  extra+=(--from-tag "$FROM_TAG")
  # what stays off on stable in the promoted build: each setting whose stable default keeps the
  # old behaviour (Setting(default_stable=...)), read from the smoke-tested wheels themselves
  if "$WORK/smoke/bin/kranto" settings stable-defaults --json > "$WORK/stable_defaults.json" \
      2>/dev/null; then
    extra+=(--stable-defaults "$WORK/stable_defaults.json")
  fi
fi
# a nightly that rc_check must check is published unoffered: its notes open with
# "Do not install", which pick() honours, until gate.py offer removes it after rc_check passed
[ "$KIND" = nightly ] && [ "$RC_CHECK" = 1 ] && extra+=(--checking)
# the notes list what the cut holds: up to its commit (a dev tag's, with --from-tag)
python3 "$HERE/notes.py" --tag "$TAG" --version "$VERSION" --repo "$REPO" \
  --out "$WORK/notes.md" --kind "$KIND" --shape "$SHAPE" "${intro[@]}" "${extra[@]}" \
  --until "$(git -C "$SRC" log -1 --format=%cI HEAD)"

# what the release holds, read before anyone calls it done (C4): the same lists as the notes',
# and each --must-include found in them
commit_list() {
  [ -n "$PREVIOUS" ] && python3 "$HERE/guards.py" log "$PREVIOUS" "$TAG" "$NAME=$SRC"
  for m in ${MUST[@]+"${MUST[@]}"}; do
    python3 "$HERE/guards.py" contains "$SRC" "$TAG" "${m#*@}" || return 1
  done
}

# a promotion makes the stable line's branch at the cut commit, and keeps the
# two newest release branches (older ones go; their tags stay)
release_branches() {
  for name in "$NAME"; do
    if [ -n "$DRY_RUN" ]; then
      echo "dry run: would push $name $(git -C "$WORK/$name" rev-parse --short HEAD) to $NEW_BRANCH"
      continue
    fi
    git -C "$WORK/$name" push --quiet origin "HEAD:refs/heads/$NEW_BRANCH"
    echo "$name: $NEW_BRANCH created at $(git -C "$WORK/$name" rev-parse --short HEAD)"
    git -C "$WORK/$name" ls-remote --heads origin 'release/*' | awk '{print $2}' \
      | sed 's#^refs/heads/##' | sort -t/ -k2 -V | head -n -2 | while read -r old; do
        git -C "$WORK/$name" push --quiet origin --delete "$old" \
          && echo "$name: deleted $old (older than the two newest; its tags stay)"
      done
  done
}

if [ -n "$DRY_RUN" ]; then
  commit_list
  [ "$KIND" = promotion ] && release_branches
  echo "dry run: nothing pushed or published; the set is in $DIST"
  exit 0
fi
how=(--prerelease)
[ "$HELD" = 1 ] && how=(--hold)
python3 "$HERE/publish.py" publish --dist "$DIST" --version "$VERSION" --tag "$TAG" \
  --repo "$REPO" --src "$SRC" --shape "$SHAPE" --notes "$WORK/notes.md" "${how[@]}"
echo "published $TAG; its commits:"
commit_list || { echo "cut_local: $TAG does not hold what it was cut for" >&2; exit 1; }
[ "$KIND" = promotion ] && release_branches
check_line="PORT=<your port> E2E_DIR=<scratch> scripts/release/rc_check.sh $TAG ${PREVIOUS:-}"
case "$KIND" in
  nightly)
    if [ "$RC_CHECK" = 1 ]; then
      echo "nightly: $TAG touches what rc_check checks: it is published unoffered (its notes" \
           "open with Do not install). Check it, make sure no one asked to hold it, then offer it:"
      echo "  $check_line"
      echo "  scripts/release/gate.py offer $TAG"
    fi
    echo "nightly: on the owner's install: kranto update --to $TAG --yes" ;;
  *)
    echo "held: $TAG is a GitHub prerelease until it is released to stable:"
    echo "  $check_line"
    echo "  then: scripts/release/gate.py promote --now --tag $TAG --reason '<why>'" ;;
esac
