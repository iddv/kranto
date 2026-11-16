"""bears-cub-sdk: write a cub for Kranto.

A cub is a folder with ``cub.yaml`` and a Python file. Kranto runs it as its own sandboxed
process and speaks ``cub/1`` to it over its pipes; this package is the cub's side: ``Cub`` and
its decorators, the ``ctx`` each handler gets, ``fence`` for strangers' text, the errors, and
``bears_cub.testing.FakeHost`` to test a cub without Kranto.

    from bears_cub import Cub, fence

    cub = Cub()

    @cub.job("compose")
    def compose(ctx):
        ...
"""

__version__ = "1.4.0"

from .context import Context, Ticket  # noqa: E402
from .cub import Cub  # noqa: E402
from .errors import (  # noqa: E402
    CapReached,
    HostError,
    HostTooOld,
    NotConnected,
    NotGranted,
    RateLimited,
)
from .fence import fence, fenced_block  # noqa: E402

__all__ = ["CapReached", "Context", "Cub", "HostError", "HostTooOld", "NotConnected",
           "NotGranted", "RateLimited", "Ticket", "__version__", "fence", "fenced_block"]
