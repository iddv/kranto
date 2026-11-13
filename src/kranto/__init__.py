"""Kranto: watches the sources you care about and turns what it notices into ideas and posts."""

from importlib.metadata import PackageNotFoundError, version

from . import legacy as _legacy
from . import product as _product

# A unit file, a drop-in or a shell written before the rename may still set the old variable
# names: they count as the new ones, before anything reads the environment.
_legacy.adopt_env()


def _version() -> str:
    for dist in (_product.DIST, *_legacy.DISTS):
        try:
            # the release tag (vX.Y.Z) for a release wheel, X.Y.Z+1.devN+g<commit> between tags
            return version(dist)
        except PackageNotFoundError:
            continue
    return "0.0.0+unknown"  # run from a source tree that was never installed


__version__ = _version()
