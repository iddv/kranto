"""Kranto: watches the sources you care about and turns what it notices into ideas and posts."""

import warnings as _warnings
from importlib.metadata import PackageNotFoundError, version

from . import legacy as _legacy
from . import product as _product

# A unit file, a drop-in or a shell written before the rename may still set the old variable
# names: they count as the new ones, before anything reads the environment.
_legacy.adopt_env()

# trafilatura (the full-text reader) imports urllib3's SOCKS support, which warns at every start
# when the optional PySocks is not installed; Kranto never reads through a SOCKS proxy, so the
# warning was only noise in a newcomer's first log
_warnings.filterwarnings("ignore", message=r"SOCKS support in urllib3 requires")


def _version() -> str:
    for dist in (_product.DIST, *_legacy.DISTS):
        try:
            # the release tag (vX.Y.Z) for a release wheel, X.Y.Z+1.devN+g<commit> between tags
            return version(dist)
        except PackageNotFoundError:
            continue
    return "0.0.0+unknown"  # run from a source tree that was never installed


__version__ = _version()
