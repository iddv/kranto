#!/usr/bin/env bash
# Build a release's wheels, SHA256SUMS and manifest.json from one checkout.
#
#   VERSION=0.7.0.dev1 TAG=v0.7.0-dev1 SRC=<checkout> DIST=<folder> build.sh [--shape final|compat]
#
# --shape final (the default): one wheel, the product's distribution, from `uv build`.
# --shape compat: the three wheels an install made before the rename updates with (the one
#   nightly that crosses it over; compat_wheels.py builds them from temporary trees, the checkout
#   is never edited). Refused once a final release exists (guards.py shape: the releases come
#   from gh, or from RELEASES_JSON, a file of GitHub's release list, for a build with no gh).
#
# Tags the checkout locally (annotated; tagger RELEASE_TAGGER_NAME <RELEASE_TAGGER_EMAIL>, by
# default "<name> release"); publish.py pushes the tag.
# The version comes from the tag through hatch-vcs; SETUPTOOLS_SCM_PRETEND_VERSION makes it
# exact. The page's web UI is built first and the wheel carries its built files: users of the
# release never need Node. manifest.json is written by publish.py manifest (its one writer).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SHAPE=final
while [ $# -gt 0 ]; do
  case "$1" in
    --shape) SHAPE="${2:-}"; shift 2 ;;
    *) echo "usage: $0 [--shape final|compat]" >&2; exit 2 ;;
  esac
done
case "$SHAPE" in final|compat) ;; *) echo "build: --shape is final or compat, not '$SHAPE'" >&2; exit 2 ;; esac
: "${VERSION:?}" "${TAG:?}" "${SRC:?}" "${DIST:?}"
REPO="${REPO:-$(python3 "$HERE/names.py" repo)}"
NAME="$(python3 "$HERE/names.py" command)"

if [ "$SHAPE" = compat ]; then
  python3 "$HERE/guards.py" shape compat "$TAG" --repo "$REPO" \
    ${RELEASES_JSON:+--releases "$RELEASES_JSON"} || {
    echo "build: the compat shape is refused for $TAG; nothing was built" >&2; exit 2; }
fi

mkdir -p "$DIST"
rm -f "$DIST"/*.whl "$DIST"/SHA256SUMS "$DIST"/manifest.json

# the tag's tagger: RELEASE_TAGGER_NAME / RELEASE_TAGGER_EMAIL (the maintainer's public
# identity, e.g. a GitHub no-reply address), else "<name> release"; never the machine's own
TAGGER_NAME="${RELEASE_TAGGER_NAME:-$NAME release}"
TAGGER_EMAIL="${RELEASE_TAGGER_EMAIL:-release@$NAME.invalid}"
export GIT_COMMITTER_NAME="$TAGGER_NAME" GIT_COMMITTER_EMAIL="$TAGGER_EMAIL"
if git -C "$SRC" rev-parse -q --verify "refs/tags/$TAG" >/dev/null; then
  if [ "$(git -C "$SRC" rev-parse "$TAG^{commit}")" != "$(git -C "$SRC" rev-parse HEAD)" ]; then
    echo "build: $SRC has $TAG at another commit than HEAD" >&2
    exit 2
  fi
else
  git -C "$SRC" -c user.name="$TAGGER_NAME" -c user.email="$TAGGER_EMAIL" \
    tag -a "$TAG" -m "$NAME $VERSION"
fi

if [ -f "$SRC/src/kranto/page/ui/web/package.json" ]; then
  python3 "$SRC/scripts/dev/build_ui.py"
fi

if [ "$SHAPE" = final ]; then
  export SETUPTOOLS_SCM_PRETEND_VERSION="$VERSION"
  uv build --wheel --out-dir "$DIST" "$SRC"
else
  python3 "$HERE/compat_wheels.py" --src "$SRC" --dist "$DIST" --version "$VERSION"
fi

(cd "$DIST" && sha256sum ./*.whl | sed 's#  \./#  #' > SHA256SUMS)
python3 "$HERE/publish.py" manifest --dist "$DIST" --version "$VERSION" --tag "$TAG" \
  --repo "$REPO" --src "$SRC" --shape "$SHAPE" > /dev/null
ls -l "$DIST"
cat "$DIST/SHA256SUMS"
