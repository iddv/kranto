"""The page: the build side of Kranto."""
try:                                     # the installed distribution's (set from the tag)
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as _version
    __version__ = _version("kranto.page")
except PackageNotFoundError:             # a git checkout that isn't installed
    __version__ = "0.0.0+unknown"
