"""Agent traces: Kranto's own runs, shown as a tree of spans.

A console or Open in Claude Code session keeps Claude Code's own transcript in its folder
(``<loop home>/term/<tid>/``); a server run (a Watching run, a cub's) is read through
the server's API; a research run kept its stream-json file. This package **reads those where they
are** and makes one trace per run: run › session › turn › tool call, sub-agents nested, model
calls as leaves, events as moments. Nothing is copied; the index (``index.py``) is a rebuildable
cache of summaries and positions, never of payloads.

- ``model``: the span, the trace's summary, the id rules;
- ``readers/``: the stream-json reader, incremental from a byte offset, and ``classify`` (why a
  session stopped);
- ``base``: what every trace shares (the rollups, the order, the summary, its failure point);
- ``session``, ``file``, ``afk``: the kinds;
- ``redact``: every string a trace returns passes through it; the files never change;
- ``payload``: a span's input, output, chat or diff, read by byte range, redacted, paged;
- ``cli``: ``kranto trace list / show / follow``.

The build loop's traces (builds, maintenance fixes, the loop's steps) left with it: their rows in
the index still list as rows, with their stored words, and do not open.

Read-only and deterministic: no model, no network, nothing written except the index.
"""
