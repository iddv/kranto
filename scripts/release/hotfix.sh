#!/usr/bin/env bash
# One safe step from a fix's pull request to the owner's install running it,
# and, with --stable, to every stable install (the owner's Q3: a fix on stable
# goes out right after its checks, fixes only, never features).
#
#   scripts/release/hotfix.sh REPO PR [--stable] [--dry-run] [--no-update]
#
# REPO is the one repository: kranto (public.toml's repo) or OWNER/kranto. In order, each step
# said as it starts, and the first that fails stops the run with exit 1 and its reason in plain
# words.
#
# The nightly half (always):
#   1. tools: its own PATH (~/.local/bin first: a non-interactive ssh lacks it), then git, gh,
#      uv, python3, flock, node and kranto;
#   2. merge on green: merge_when_green.sh with the repo's required jobs (guards.py jobs).
#      Never --admin, never a skipped required job. A PR already merged is taken as it is;
#   3. plan: cut_local.sh --plan --must-include REPO@<merge commit>: waits (bounded) until the
#      merge commit is in main and green, refuses an empty release, says whether rc_check is
#      required;
#   4. cut: a nightly build from main (cut_local.sh --must-include the merge commit);
#   5. rc_check.sh on the published nightly when decide.py asks (127.0.0.1:$HOTFIX_RC_PORT,
#      under a 3 GB cap); if it fails the nightly is withdrawn (gate.py withdraw: no install is
#      offered it) and the run stops;
#   6. read back: the release's commit list holds the merge commit;
#   7. update: kranto update --to <tag> --yes on this machine's install (the owner's), then
#      kranto --version and kranto doctor --routes.
#
# --stable, after the nightly half:
#   8. the stable line: release/X.Y from the newest stable tag; refused when the branch does not
#      exist yet, when the merge commit is already in it, or when the PR is labelled big (a big
#      change reaches stable by promotion only);
#   9. cherry-pick as a pull request: stable/<PR>-<short> from release/X.Y, git cherry-pick -x;
#      a conflict stops the run with the files named;
#  10. merge on green, as on main;
#  11. cut held: cut_local.sh --line stable --must-include REPO@<its merge commit>;
#  12. rc_check.sh <fix> <the stable it patches>;
#  13. release to stable at once: gate.py promote --now --tag <fix> --reason "hotfix REPO#PR";
#  14. read back: the fix's commit list holds the cherry-pick.
#
# --dry-run: no merge, no tag pushed, no release, no update, no cherry-pick pushed. It runs every
# check that changes nothing (the PR's checks, the plan, the cut with cut_local.sh --dry-run;
# with --stable, whether the cherry-pick applies) and says what each skipped step would do.
#
# Before each cut, touching $HOTFIX_STOP (~/.cache/kranto-release/hotfix.STOP) stops the run: the
# "a note addressed to you stops the cut" rule, for a script.
# Settings: HOTFIX_RC_PORT (8940), HOTFIX_WORK (~/.cache/kranto-release/hotfix-<time>),
# RELEASE_MUST_INCLUDE_WAIT (2700 s).
set -euo pipefail
export PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin:${PATH:-}"

usage() { echo "usage: $0 kranto|OWNER/kranto PR [--stable] [--dry-run] [--no-update]" >&2; exit 2; }
[ $# -ge 2 ] || usage
REPO_ARG="$1" PR="$2"; shift 2
DRY="" NO_UPDATE="" STABLE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) DRY=1; shift ;;
    --no-update) NO_UPDATE=1; shift ;;
    --stable) STABLE=1; shift ;;
    --promote-now) echo "hotfix: --promote-now is retired: a nightly is never promoted; a fix" \
                        "for stable installs is --stable (cherry-picked, checked, released)" >&2
                   exit 2 ;;
    *) usage ;;
  esac
done
HERE="$(cd "$(dirname "$0")" && pwd)"
NAME="${REPO_ARG##*/}"
DIST_NAME="$(python3 "$HERE/names.py" dist)"
[ "$NAME" = "$DIST_NAME" ] || { echo "hotfix: REPO is $DIST_NAME or OWNER/$DIST_NAME, not '$REPO_ARG'" >&2; exit 2; }
[[ "$PR" =~ ^[0-9]+$ ]] || { echo "hotfix: PR is a number, not '$PR'" >&2; exit 2; }
case "$REPO_ARG" in */*) FULL="$REPO_ARG" ;; *) FULL="$(python3 "$HERE/names.py" repo)" ;; esac
WORK="${HOTFIX_WORK:-$HOME/.cache/kranto-release/hotfix-$(date -u +%Y%m%dT%H%M%SZ)}"
STOP="${HOTFIX_STOP:-$HOME/.cache/kranto-release/hotfix.STOP}"
KRANTO="${KRANTO_BIN:-kranto}"
RC_PORT="${HOTFIX_RC_PORT:-8940}"
mkdir -p "$WORK"
STEP=0
step() { STEP=$((STEP + 1)); echo; echo "== hotfix $FULL#$PR, step $STEP: $*"; }
fail() { echo "hotfix: FAILED at step $STEP: $*" >&2; exit 1; }
dry() { echo "   (dry run: $*)"; }
json() {  # json FILE KEY...: one value of a JSON file
  python3 - "$@" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for k in sys.argv[2:]:
    d = d[k]
print(d)
PY
}
DONE_WORD="published"
[ -n "$DRY" ] && DONE_WORD="built and smoke-tested (dry run: not published)"

step "tools (PATH=$PATH)"
for t in git gh uv python3 flock node "$KRANTO"; do
  command -v "$t" >/dev/null || fail "'$t' is not on PATH"
done
gh auth status >/dev/null 2>&1 || fail "gh is not logged in (gh auth login)"
echo "   work dir: $WORK${DRY:+ (dry run: no merge, no tag, no release, no update)}"

merge() {  # merge REPO PR: merge on green; prints the merge commit
  local repo="$1" pr="$2" state sha head jobs
  read -r state sha head < <(gh pr view "$pr" -R "$repo" \
    --json state,mergeCommit,headRefOid -q '"\(.state) \(.mergeCommit.oid // "-") \(.headRefOid)"') \
    || { echo "cannot read $repo#$pr" >&2; return 1; }
  jobs="$(python3 "$HERE/guards.py" jobs "$repo" "$pr")" || { echo "cannot read $repo#$pr's files" >&2; return 1; }
  echo "   $repo#$pr is $state; required jobs: $jobs" >&2
  case "$state" in
    MERGED) echo "   already merged as $sha" >&2; echo "$sha" ;;
    OPEN)
      if [ -n "$DRY" ]; then
        python3 "$HERE/../ci/checks.py" green "$repo" "$head" --require "$jobs" >&2 \
          && echo "   its head is green" >&2 || echo "   its head is not green yet" >&2
        dry "would run merge_when_green.sh $repo $pr --require $jobs --rerun-once" >&2
        echo "-"
      else
        bash "$HERE/../ci/merge_when_green.sh" "$repo" "$pr" --require "$jobs" --rerun-once >&2 \
          || { echo "merge_when_green.sh did not merge $repo#$pr (its checks are red, a required job did not run, or its head moved)" >&2; return 1; }
        sha="$(gh pr view "$pr" -R "$repo" --json mergeCommit -q .mergeCommit.oid)"
        [ -n "$sha" ] || { echo "$repo#$pr merged but GitHub names no merge commit" >&2; return 1; }
        echo "   merged as $sha" >&2
        echo "$sha"
      fi ;;
    *) echo "$repo#$pr is $state, not open or merged" >&2; return 1 ;;
  esac
}

step "merge on green"
MERGED_SHA="$(merge "$FULL" "$PR")" || fail "the merge did not happen (see above)"
MUST=()
if [ "$MERGED_SHA" != "-" ]; then
  MUST=(--must-include "$NAME@$MERGED_SHA")
else
  echo "   (dry run: the PR has no merge commit yet, so the cut below runs without --must-include)"
fi

step "plan: is ${MERGED_SHA:0:10} in main and green, is anything new, is rc_check needed"
RELEASE_WORK="$WORK/plan" bash "$HERE/cut_local.sh" --plan ${MUST[@]+"${MUST[@]}"} 2>&1 \
  | tee "$WORK/plan.log" | grep --line-buffered -E "^(waiting|kranto|cut_local|decide|guards)|newest green|must include|carries|is in" \
  | sed -u 's/^/   /' || true
[ -f "$WORK/plan/decide.json" ] && grep -q "^plan: nothing built" "$WORK/plan.log" \
  || fail "the plan refused: $(grep -E '^(cut_local|decide|guards|pairing):' "$WORK/plan.log" | tail -1) (log: $WORK/plan.log)"
RC_CHECK="$(json "$WORK/plan/decide.json" rc_check required)"
PREVIOUS="$(json "$WORK/plan/decide.json" previous)"
echo "   since $PREVIOUS: $(json "$WORK/plan/decide.json" since); rc_check required: $RC_CHECK"

cut() {  # cut <work name> <cut_local args...>: the cut, its log kept, its tag printed
  local w="$WORK/$1"; shift
  RELEASE_WORK="$w" bash "$HERE/cut_local.sh" "$@" ${DRY:+--dry-run} \
    > "$w.log" 2>&1 || { tail -8 "$w.log" >&2; return 1; }
  json "$w/decide.json" tag
}
rc_check() {  # rc_check TAG PREVIOUS LOGNAME
  PORT="$RC_PORT" E2E_DIR="$WORK/$3" systemd-run --user --scope -q -p MemoryMax=3G -- \
    bash "$HERE/rc_check.sh" "$1" "$2" > "$WORK/$3.log" 2>&1 \
    || { grep -E "^(PASS|FAIL)" "$WORK/$3.log" | sed 's/^/   /'; return 1; }
  grep -E "^(PASS|FAIL)" "$WORK/$3.log" | sed 's/^/   /'
}

step "nightly: cut_local.sh from green main"
[ ! -e "$STOP" ] || fail "$STOP exists: someone stopped this hotfix (remove it to go on)"
TAG="$(cut nightly ${MUST[@]+"${MUST[@]}"})" || fail "the nightly cut failed (log: $WORK/nightly.log)"
CUT_DIR="$WORK/nightly"
VERSION="$(json "$CUT_DIR/decide.json" version)"
echo "   $TAG (kranto $VERSION) $DONE_WORD"

step "rc_check.sh $TAG $PREVIOUS (when the release touches what it checks)"
if [ "$RC_CHECK" != "True" ]; then
  echo "   not required: the cut's smoke (fresh wheels, every page, the odd installs) was the check"
elif [ -n "$DRY" ]; then
  dry "would run rc_check.sh $TAG $PREVIOUS on 127.0.0.1:$RC_PORT before the owner's install takes it"
else
  rc_check "$TAG" "$PREVIOUS" rc_check || {
    python3 "$HERE/gate.py" withdraw "$TAG" --reason "rc_check failed (hotfix $FULL#$PR)" || true
    fail "rc_check.sh failed on $TAG; it is withdrawn (log: $WORK/rc_check.log)"; }
  # cut_local published it unoffered for this check: it passed, so offer it
  python3 "$HERE/gate.py" offer "$TAG" || fail "gate.py offer $TAG refused; it stays unoffered"
fi

step "the release's commit list (read it: it must hold the fix)"
python3 "$HERE/guards.py" log "$PREVIOUS" "$TAG" "$NAME=$CUT_DIR/$NAME" | sed 's/^/   /' \
  || fail "cannot read $TAG's commit list"
if [ "$MERGED_SHA" != "-" ]; then
  python3 "$HERE/guards.py" contains "$CUT_DIR/$NAME" "$TAG" "$MERGED_SHA" | sed 's/^/   /'
  python3 "$HERE/guards.py" contains "$CUT_DIR/$NAME" "$TAG" "$MERGED_SHA" >/dev/null \
    || fail "$TAG does not hold $NAME@$MERGED_SHA"
fi

step "update the owner's install: $KRANTO update --to $TAG --yes"
if [ -n "$DRY" ] || [ -n "$NO_UPDATE" ]; then
  dry "would run $KRANTO update --to $TAG --yes, then read back $KRANTO --version (now: $("$KRANTO" --version 2>/dev/null || echo unreadable))"
else
  rc=0; "$KRANTO" update --to "$TAG" --yes || rc=$?
  [ "$rc" -eq 0 ] || fail "kranto update --to $TAG ended with exit $rc ($KRANTO status says why; a rollback or a stop warning means: stop and report)"
  have="$("$KRANTO" --version 2>/dev/null || true)"
  echo "   $have"
  [[ "$have" == "kranto $VERSION "* ]] || fail "after the update kranto --version says '$have', not kranto $VERSION"
  if "$KRANTO" doctor --help 2>/dev/null | grep -q -- "--routes"; then
    "$KRANTO" doctor --routes > "$WORK/doctor.log" 2>&1 \
      || { tail -5 "$WORK/doctor.log" >&2; fail "kranto doctor --routes found a failing route on $VERSION"; }
    echo "   kranto doctor --routes: passed"
  fi
fi

if [ -z "$STABLE" ]; then
  echo
  held=" holds $NAME@${MERGED_SHA:0:10}"
  [ "$MERGED_SHA" = "-" ] && held=""
  echo "hotfix $FULL#$PR: ${DRY:+dry run }done: nightly $TAG$held (stable installs: hotfix.sh $NAME $PR --stable)"
  exit 0
fi

# -- the stable half -------------------------------------------------------------------------
step "the stable line"
SRC="$CUT_DIR/$NAME"
BRANCH="$(python3 "$HERE/decide.py" --src "$CUT_DIR/$NAME" --stable-branch)" \
  || fail "no stable release yet, so no stable line to fix"
git -C "$SRC" fetch --quiet origin "+refs/heads/$BRANCH:refs/remotes/origin/$BRANCH" 2>/dev/null \
  || fail "$FULL has no $BRANCH yet: before the first promotion of ${BRANCH#release/}.0 there is no stable line (stable installs get the fix at the next promotion)"
labels="$(gh pr view "$PR" -R "$FULL" --json labels -q '[.labels[].name] | join(",")')"
[[ ",$labels," == *",big,"* ]] && fail "$FULL#$PR is labelled big: a big change reaches stable by promotion only, never as a fix"
if [ "$MERGED_SHA" != "-" ] && python3 "$HERE/guards.py" contains "$SRC" "origin/$BRANCH" "$MERGED_SHA" >/dev/null 2>&1; then
  fail "$NAME@${MERGED_SHA:0:10} is already in $BRANCH"
fi
echo "   $BRANCH; $FULL#$PR is not labelled big"

step "cherry-pick onto $BRANCH as a pull request"
TITLE="$(gh pr view "$PR" -R "$FULL" --json title -q .title)"
MINOR="${BRANCH#release/}"
if [ "$MERGED_SHA" = "-" ]; then
  dry "the PR is not merged yet: would cherry-pick its merge commit onto $BRANCH and open \"$TITLE (stable $MINOR)\""
  STABLE_SHA="-"
else
  PICK="stable/$PR-${MERGED_SHA:0:7}"
  git -C "$SRC" checkout --quiet -B "$PICK" "origin/$BRANCH"
  if ! git -C "$SRC" -c user.name="kranto release" -c user.email="release@kranto.invalid" \
      cherry-pick -x "$MERGED_SHA" > "$WORK/cherry-pick.log" 2>&1; then
    files="$(git -C "$SRC" diff --name-only --diff-filter=U | tr '\n' ' ')"
    git -C "$SRC" cherry-pick --abort 2>/dev/null || true
    fail "the cherry-pick of ${MERGED_SHA:0:10} onto $BRANCH conflicts in: ${files:-see $WORK/cherry-pick.log}. Resolve it on a branch from $BRANCH, open its pull request against $BRANCH, and run hotfix.sh $NAME <that PR> --stable --no-update"
  fi
  if [ -n "$DRY" ]; then
    dry "the cherry-pick applies cleanly; would push $PICK and open \"$TITLE (stable $MINOR)\" against $BRANCH"
    STABLE_SHA="-"
  else
    git -C "$SRC" push --quiet origin "$PICK"
    NEW_PR="$(gh pr create -R "$FULL" --base "$BRANCH" --head "$PICK" --title "$TITLE (stable $MINOR)" \
      --body "Cherry-pick of #$PR (${MERGED_SHA:0:10}) for stable $MINOR, by hotfix.sh --stable." | grep -oE '[0-9]+$')" \
      || fail "could not open the cherry-pick's pull request"
    echo "   opened $FULL#$NEW_PR"
    step "merge the cherry-pick on green"
    STABLE_SHA="$(merge "$FULL" "$NEW_PR")" || fail "the cherry-pick $FULL#$NEW_PR did not merge (see above)"
  fi
fi

step "stable: cut_local.sh --line stable (held)"
[ ! -e "$STOP" ] || fail "$STOP exists: someone stopped this hotfix before its stable cut (remove it to go on)"
SMUST=()
[ "$STABLE_SHA" != "-" ] && SMUST=(--must-include "$NAME@$STABLE_SHA")
if [ "$STABLE_SHA" = "-" ] && [ -n "$DRY" ]; then
  dry "would run cut_local.sh --line stable --must-include $NAME@<the cherry-pick's merge commit>, rc_check.sh against the stable it patches, then gate.py promote --now"
  echo; echo "hotfix $FULL#$PR: dry run done: nightly $TAG; stable fix on $BRANCH said, not cut"
  exit 0
fi
FIX="$(cut stable --line stable ${SMUST[@]+"${SMUST[@]}"})" || fail "the stable cut failed (log: $WORK/stable.log)"
FIX_PREV="$(json "$WORK/stable/decide.json" previous)"
echo "   $FIX $DONE_WORD, held"

step "rc_check.sh $FIX $FIX_PREV"
if [ -n "$DRY" ]; then
  dry "would run rc_check.sh $FIX $FIX_PREV"
else
  rc_check "$FIX" "$FIX_PREV" rc_check_stable || fail "rc_check.sh failed on $FIX; it stays held (log: $WORK/rc_check_stable.log)"
fi

step "release $FIX to stable at once"
if [ -n "$DRY" ]; then
  dry "would run gate.py promote --now --tag $FIX --reason 'hotfix $FULL#$PR for stable $MINOR'"
else
  python3 "$HERE/gate.py" promote --now --tag "$FIX" --reason "hotfix $FULL#$PR for stable $MINOR, after rc_check" \
    || fail "gate.py could not release $FIX"
fi

step "the fix's commit list (read it: it must hold the cherry-pick)"
python3 "$HERE/guards.py" log "$FIX_PREV" "$FIX" "$NAME=$WORK/stable/$NAME" | sed 's/^/   /' \
  || fail "cannot read $FIX's commit list"
if [ "$STABLE_SHA" != "-" ]; then
  python3 "$HERE/guards.py" contains "$WORK/stable/$NAME" "$FIX" "$STABLE_SHA" >/dev/null \
    || fail "$FIX does not hold $NAME@$STABLE_SHA"
fi
echo
echo "hotfix $FULL#$PR: ${DRY:+dry run }done: nightly $TAG; stable $FIX"
