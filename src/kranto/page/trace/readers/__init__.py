"""One reader per file kind. A reader is fed whole lines from a byte offset
(``lines``: a half-written last line is left for the next read, as ``events.read_events``
skips a torn one) and keeps the spans it made by id, so a later line can finish an earlier
span (a tool's result, a session's ``result``). Adding a source is one reader."""
from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

CHUNK = 1 << 20


def lines(path: Path, offset: int = 0, limit: int | None = None
          ) -> Iterator[tuple[int, int, dict | None]]:
    """``(byte from, byte to, the parsed object or None)`` for each whole line of ``path``
    from ``offset``; stops before a last line with no newline (still being written).
    ``limit``: stop after this many bytes (a page)."""
    with open(path, "rb") as f:
        f.seek(offset)
        pos, buf, read = offset, b"", 0           # pos: the file offset of buf[0]
        pending: list[bytes] = []                 # a long line's pieces, joined once
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                return
            read += len(chunk)
            if b"\n" not in chunk:
                pending.append(chunk)
                if limit is not None and read >= limit:
                    return
                continue
            buf = b"".join([buf, *pending, chunk]) if (buf or pending) else chunk
            pending = []
            at = 0                                # the next line's start in buf
            while True:
                nl = buf.find(b"\n", at)
                if nl < 0:
                    break
                raw = buf[at:nl]
                start = pos + at
                at = nl + 1
                obj = None
                if raw.strip():
                    try:
                        obj = json.loads(raw)
                    except ValueError:
                        obj = None
                yield start, pos + at, obj if isinstance(obj, dict) else None
            buf, pos = buf[at:], pos + at         # the half line waits for the next chunk
            if limit is not None and read >= limit:
                return


def read_line(path: Path, start: int, end: int) -> dict | None:
    """The one JSON object at ``[start, end)`` of ``path``."""
    with open(path, "rb") as f:
        f.seek(start)
        raw = f.read(max(0, end - start))
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    return obj if isinstance(obj, dict) else None
