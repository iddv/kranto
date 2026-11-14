"""What a feature's commands (``python -m kranto <id> ...``) stand on: a runtime and the feature's
context,
opened the way every ``afk`` command opens them. The command line is the owner's ``cli`` door."""

from __future__ import annotations


class CommandError(ValueError):
    """A command that cannot go on, said in words (``afk`` prints it and exits 2)."""


def context(args, fid: str):
    """The feature's ``FeatureContext`` on this workspace, with ``door = "cli"``."""
    from ..cli import _runtime
    from . import registry
    rt = _runtime(args)
    ctx = registry.context(rt, registry.by_id(fid))
    ctx.door = "cli"
    return ctx


def close(ctx) -> None:
    ctx.rt.close()
