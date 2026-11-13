#!/usr/bin/env bash
# Merge a pull request only when every check on its exact head commit is green.
#
#   scripts/ci/merge_when_green.sh OWNER/REPO PR [--require a,b] [--rerun-once] [--timeout S]
#                                  [--merge-base]
#
# Waits while checks are queued or running (scripts/ci/checks.py wait), refuses when any is
# red, refuses when the PR's head moved during the wait, and merges with
# `gh pr merge --squash --match-head-commit <sha>`, so a push after the checks can never slip
# through. Never --admin. --rerun-once reruns the failed jobs once (a red check gets one
# rerun); if they fail again it stops: that is a flake to fix in its own PR, not to merge past.
# The runs it reran are remembered per head commit (under $MERGE_STATE_DIR, by default
# ~/.local/state/merge_when_green), so calling it again after an outer timeout waits on that
# rerun instead of rerunning a second time. A run whose red jobs never started (cancelled
# before any runner took them: checks.py unstarted) is rerun without counting, with or without
# --rerun-once, up to $MERGE_UNSTARTED_RERUNS (3) times: nothing ran, so nothing failed.
# --require names checks that must be present and must have succeeded, never skipped: for this
# repository, the eight jobs of ci.yml (test,fast,slow,browser,frontend,lint,gitleaks,sandbox).
# --merge-base: when the PR conflicts with its base, merge the base into the branch checked out
# here (it must be the PR's), make the generated files again (scripts/ci/merge_base.sh: the
# usage reports' field page), push, and wait on the new head's checks. Without it a conflicting
# PR stops with a hint.
# A merge never waits for a release: a stable release is cut from its rc's own commits
# (cut_local.sh --from-tag), so what merges meanwhile rides the next one.
# Needs gh (logged in) and python3. Exit 0 merged, 1 red, 2 usage or a moved head, 4 timeout.
set -euo pipefail

usage() { echo "usage: $0 OWNER/REPO PR [--require a,b] [--rerun-once] [--timeout S] [--merge-base]" >&2; exit 2; }
[ $# -ge 2 ] || usage
REPO="$1" PR="$2"; shift 2
REQUIRE="" RERUN="" MERGE_BASE="" TIMEOUT="${MERGE_TIMEOUT:-3600}" INTERVAL="${MERGE_INTERVAL:-30}"
while [ $# -gt 0 ]; do
  case "$1" in
    --require) REQUIRE="$2"; shift 2 ;;
    --rerun-once) RERUN=1; shift ;;
    --merge-base) MERGE_BASE=1; shift ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) usage ;;
  esac
done
HERE="$(cd "$(dirname "$0")" && pwd)"
STATE_DIR="${MERGE_STATE_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/merge_when_green}"
UNSTARTED_RERUNS="${MERGE_UNSTARTED_RERUNS:-3}"

head_of() { gh pr view "$PR" -R "$REPO" --json headRefOid -q .headRefOid; }
state_of() { gh pr view "$PR" -R "$REPO" --json state,isDraft -q '"\(.state) \(.isDraft)"'; }

read -r STATE DRAFT < <(state_of)
[ "$STATE" = "OPEN" ] || { echo "merge_when_green: $REPO#$PR is $STATE" >&2; exit 2; }
[ "$DRAFT" = "false" ] || { echo "merge_when_green: $REPO#$PR is a draft" >&2; exit 2; }
mergeable() { gh pr view "$PR" -R "$REPO" --json mergeable -q .mergeable; }
if [ "$(mergeable)" = "CONFLICTING" ]; then
  if [ -z "$MERGE_BASE" ]; then
    echo "merge_when_green: $REPO#$PR conflicts with its base; run again with --merge-base from" \
         "the PR's clone (generated files are made again), or merge the base in yourself" >&2
    exit 2
  fi
  read -r BRANCH BASE_REF < <(gh pr view "$PR" -R "$REPO" --json headRefName,baseRefName \
                                -q '"\(.headRefName) \(.baseRefName)"')
  if [ "$(git rev-parse --abbrev-ref HEAD)" != "$BRANCH" ]; then
    echo "merge_when_green: --merge-base needs $BRANCH checked out here" >&2
    exit 2
  fi
  bash "$HERE/merge_base.sh" "$BASE_REF" || exit 1
  git push -q origin "HEAD:$BRANCH"
  sleep 5                                            # let GitHub see the new head
fi
SHA="$(head_of)"
echo "merge_when_green: $REPO#$PR at $SHA"
# big: a diff that changes a default, removes a route, a page, a command or a
# help heading, or adds a migration that drops, is merged only once its author has said whether
# it is big (the label big, or not-big with a sentence in the body). Labels change without a
# commit, so this is checked here, at merge, and not in CI.
python3 "$HERE/../release/guards.py" big "$REPO" "$PR" || {
  rc=$?
  [ "$rc" -eq 3 ] && { echo "merge_when_green: not merging $REPO#$PR until it is labelled big or not-big" >&2; exit 2; }
  echo "merge_when_green: could not read $REPO#$PR's diff for the big check (exit $rc)" >&2
  exit 2
}

wait_checks() {
  python3 "$HERE/checks.py" wait "$REPO" "$SHA" --require "$REQUIRE" \
    --timeout "$TIMEOUT" --interval "$INTERVAL"
}

MARK="$STATE_DIR/${REPO//\//_}-$PR-$SHA.reran"   # one line per run already rerun at this head
reran() { [ -f "$MARK" ] && grep -qx "$1" "$MARK"; }

failed_runs() {
  gh run list -R "$REPO" --commit "$SHA" --json databaseId,conclusion \
    -q '.[] | select(.conclusion == "failure" or .conclusion == "timed_out" or .conclusion == "cancelled") | .databaseId'
}

rc=0
wait_checks || rc=$?
free=0
while [ "$rc" -eq 1 ]; do
  runs="$(failed_runs)"
  [ -n "$runs" ] || break
  ran=""
  for id in $runs; do
    python3 "$HERE/checks.py" unstarted "$REPO" "$id" >/dev/null 2>&1 || ran="$ran $id"
  done
  if [ -z "$ran" ] && [ "$free" -lt "$UNSTARTED_RERUNS" ]; then
    # no runner ever took the red jobs: nothing ran, so nothing failed. Rerun them; this is
    # not the one rerun a red check gets.
    free=$((free + 1))
    for id in $runs; do
      echo "merge_when_green: run $id: its red jobs never started (no runner took them); rerunning, not counted"
      gh run rerun "$id" -R "$REPO" --failed
    done
  elif [ -n "$RERUN" ]; then
    fresh=""
    for id in $runs; do
      if reran "$id"; then
        echo "merge_when_green: run $id was already rerun once at this head; not again"
      else
        fresh="$fresh $id"
      fi
    done
    if [ -z "$fresh" ]; then
      echo "merge_when_green: red again after one rerun: a flake to fix, not to merge past" >&2
      break
    fi
    mkdir -p "$STATE_DIR"
    for id in $fresh; do
      echo "merge_when_green: rerunning the failed jobs of run $id once"
      echo "$id" >> "$MARK"   # before the rerun: a timeout after it must not rerun twice
      gh run rerun "$id" -R "$REPO" --failed
    done
  else
    break
  fi
  sleep "$INTERVAL"
  rc=0
  wait_checks || rc=$?
done
[ "$rc" -eq 0 ] || { echo "merge_when_green: not merging $REPO#$PR (exit $rc)" >&2; exit "$rc"; }

NOW="$(head_of)"
if [ "$NOW" != "$SHA" ]; then
  echo "merge_when_green: the head moved to $NOW during the wait; run again" >&2
  exit 2
fi
gh pr merge "$PR" -R "$REPO" --squash --match-head-commit "$SHA"
echo "merge_when_green: merged $REPO#$PR at $SHA"
