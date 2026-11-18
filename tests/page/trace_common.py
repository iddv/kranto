"""``kranto trace …`` as the command line runs it (``launcher.cmd_trace``): the trace group
under a parser of its own."""
from __future__ import annotations

import argparse

from kranto.page.host_api import add_trace_group


def main(argv: list[str]) -> None:
    p = argparse.ArgumentParser(prog="kranto")
    add_trace_group(p.add_subparsers(dest="cmd", required=True))
    ns = p.parse_args(argv)
    ns.fn(ns)
