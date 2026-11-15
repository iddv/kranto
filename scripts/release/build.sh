#!/usr/bin/env bash
# Build the release wheel (one distribution, kranto) and SHA256SUMS.
#
#   VERSION=0.7.0.dev1 TAG=v0.7.0-dev1 SRC=<checkout> DIST=<folder> build.sh
#
# Tags the checkout locally (annotated, tagger "kranto release"); publish.py pushes the tag.
# The version comes from the tag through hatch-vcs; SETUPTOOLS_SCM_PRETEND_VERSION makes it
# exact. The page's web UI is built first and the wheel carries its built files: users of the
# release never need Node.
set -euo pipefail

SRC="${SRC:-${AFK_DIR:-}}"
: "${VERSION:?}" "${TAG:?}" "${SRC:?}" "${DIST:?}"
mkdir -p "$DIST"
rm -f "$DIST"/*.whl "$DIST"/SHA256SUMS

export GIT_COMMITTER_NAME="kranto release" GIT_COMMITTER_EMAIL="release@kranto.invalid"
# the cut still hands a second checkout (BRB_DIR, a clone of the same repository): tag it too
for repo in "$SRC" ${BRB_DIR:+"$BRB_DIR"}; do
  if git -C "$repo" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
    if [ "$(git -C "$repo" rev-parse "$TAG^{commit}")" != "$(git -C "$repo" rev-parse HEAD)" ]; then
      echo "build: $repo has $TAG at another commit than HEAD" >&2
      exit 2
    fi
  else
    git -C "$repo" -c user.name="kranto release" -c user.email="release@kranto.invalid" \
      tag -a "$TAG" -m "kranto $VERSION"
  fi
done

if [ -f "$SRC/src/kranto/page/ui/web/package.json" ]; then
  python3 "$SRC/scripts/dev/build_ui.py"
fi

export SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION"
uv build --wheel --out-dir "$DIST" "$SRC"

(cd "$DIST" && sha256sum ./*.whl | sed 's#  \./#  #' > SHA256SUMS)
ls -l "$DIST"
cat "$DIST/SHA256SUMS"
