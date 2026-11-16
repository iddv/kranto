"""The page: Kranto's web UI and the server side it talks to."""
# Kranto's one version (the installed distribution's, set from the tag; kranto/__init__.py). The
# page ships inside the same wheel: its scripts' address (static/v<version>/) and the live
# stream's "host" event (an open page reloads when it changes after an update) both use it.
from .. import __version__  # noqa: F401
