#!/usr/bin/env bash
# Merge the base branch into the branch checked out here, and make the generated files again
# instead of stopping on their conflicts.
#
#   scripts/ci/merge_base.sh [BASE]          (default: oss; run in the PR's clone, on its branch)
#
# Fetches origin, merges origin/BASE (a merge commit, never a rebase). When the only conflicts are
# in files that are made by a command (GENERATED below), it takes either side, runs the command,
# adds the result and finishes the merge. Any other conflict stops it with the merge left open
# for you to finish (or `git merge --abort`). Nothing is pushed: merge_when_green.sh --merge-base
# pushes, or you do. Exit 0 merged (or nothing to merge), 1 a conflict it cannot settle, 2 usage.
#
# docs/privacy/what-kranto-sends.md is linked from the product and the docs, so it stays in the
# tree; every PR that changes the usage reports' lists rewrites it, and two such PRs always
# conflicted there (five merges in wave 2). REGEN_PAGE overrides the command (tests).
set -euo pipefail

BASE="${1:-oss}"
[ $# -le 1 ] || { echo "usage: $0 [BASE]" >&2; exit 2; }
TOP="$(git rev-parse --show-toplevel)"
cd "$TOP"
PAGE="docs/privacy/what-kranto-sends.md"
REGEN_PAGE="${REGEN_PAGE:-uv run --no-sync python -c 'from kranto.telemetry import docs; print(docs.page(), end=\"\")'}"
GENERATED=("$PAGE")

[ -z "$(git status --porcelain --untracked-files=no)" ] || {
  echo "merge_base: the working tree has changes; commit or stash them first" >&2; exit 2; }
git fetch -q origin "$BASE"
if git merge --no-edit -q "origin/$BASE" >/dev/null 2>&1; then
  echo "merge_base: origin/$BASE merged (or nothing to merge)"
  exit 0
fi
mapfile -t conflicted < <(git diff --name-only --diff-filter=U)
[ "${#conflicted[@]}" -gt 0 ] || { echo "merge_base: the merge failed without a conflict" >&2; exit 1; }
for f in "${conflicted[@]}"; do
  generated=""
  for g in "${GENERATED[@]}"; do [ "$f" = "$g" ] && generated=1; done
  if [ -z "$generated" ]; then
    echo "merge_base: $f conflicts and is not a generated file; the merge is left open" >&2
    printf '  conflicted: %s\n' "${conflicted[@]}" >&2
    exit 1
  fi
done
for f in "${conflicted[@]}"; do
  if [ "$f" = "$PAGE" ]; then
    git checkout -q --theirs -- "$PAGE"
    bash -c "$REGEN_PAGE" > "$PAGE.new"
    mv "$PAGE.new" "$PAGE"
    git add "$PAGE"
    echo "merge_base: $PAGE made again after the merge"
  fi
done
git -c core.editor=true commit -q --no-edit
echo "merge_base: origin/$BASE merged; generated files made again"
