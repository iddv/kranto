"""brb: the page's command line. What is left since the factory went (cut 3): the
page on its own (``brb ui``) and Kranto's traces (``brb trace``). Kranto itself is ``kranto``."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__


def cmd_ui(args):
    from .ui.server import serve
    root = Path(args.root).resolve()
    if not root.is_dir():
        sys.exit(f"brb ui: {root} is not a directory")
    serve(root, args.port, "claude-code",
          Path(args.loop_home).expanduser() if args.loop_home else None)


def main(argv=None):
    av = sys.argv[1:] if argv is None else list(argv)
    p = argparse.ArgumentParser(
        prog="brb", description="Kranto's page on its own, and Kranto's traces. "
                                "'brb <command> --help' for one command.")
    p.add_argument("--version", action="version", version=f"brb {__version__} (the page)")
    sub = p.add_subparsers(dest="cmd", required=True)

    ui = sub.add_parser("ui", help="the page on its own (127.0.0.1 only)")
    ui.add_argument("root", nargs="?", default=".", help=argparse.SUPPRESS)
    ui.add_argument("--port", type=int, default=8790,
                    help="default 8790; if busy, the next free port is used and printed")
    ui.add_argument("--loop-home", default=None,
                    help="the page's settings folder (default: $KRANTO_LOOP_HOME, else ~/kranto-loop)")
    ui.set_defaults(fn=cmd_ui)

    from .trace.cli import add_trace_group
    add_trace_group(sub)           # `brb trace ...`: agent traces

    args = p.parse_args(av)
    args.argv = argv
    args.fn(args)


if __name__ == "__main__":
    main()
