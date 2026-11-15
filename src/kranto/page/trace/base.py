"""What every trace is: a tree of spans read from somewhere, refreshed with
what is new. ``Trace`` holds what the kinds share (the frame, the rollups, the order, the
summary); each kind reads its own source: a console or Open in Claude Code session
(``session.py``), a kept stream-json file (``file.py``), a server run (``afk.py``).

The build loop's traces (a build's, a maintenance fix's, a loop step's) left with it; their rows
in ``trace.db`` still list, drawn with their stored words."""
from __future__ import annotations

import os
from pathlib import Path

from .model import Span, add_tokens
from .readers.stream_json import StreamReader


class Trace:
    def __init__(self, taskdir: Path, key: str, n: int | None, source: str):
        self.taskdir = Path(taskdir)
        self.key, self.n = key, n
        self.id = f"{source}:{key}/{n}"
        self.events = None                             # a build's readers: none here
        self.ledger = None
        self.streams: dict[str, StreamReader] = {}     # rel path -> reader
        self.calls: dict = {}
        self.sizes: dict[str, tuple[int, int]] = {}    # rel -> (size, inode)
        self.spans: dict[str, Span] = {}
        self.summary: dict = {}
        self.links: list[dict] = []
        self.running = False

    # -- files ------------------------------------------------------------------------------
    def rel(self, p: Path) -> str:
        return Path(p).relative_to(self.taskdir).as_posix()

    def files(self) -> list[Path]:
        return []

    def _grew(self, p: Path, rel: str, reader) -> bool:
        """True when ``p`` has bytes ``reader`` has not read; a smaller or new file (a
        rewrite) resets the reader."""
        try:
            st = p.stat()
        except OSError:
            return False
        before = self.sizes.get(rel)
        self.sizes[rel] = (st.st_size, st.st_ino)
        if before is not None and (st.st_ino != before[1] or st.st_size < reader.offset):
            return None                                      # reset
        return st.st_size > reader.offset

    def refresh(self) -> bool:
        raise NotImplementedError

    # -- putting it together ----------------------------------------------------------------
    @staticmethod
    def _under(spans: dict[str, Span], sp: Span, anc: str) -> bool:
        p, hops = sp.parent, 0
        while p is not None and hops < 64:
            if p == anc:
                return True
            p = spans[p].parent if p in spans else None
            hops += 1
        return False

    @staticmethod
    def _shares(spans: dict[str, Span]) -> None:
        """A turn's estimated share of its session's exact cost: by ``output tokens + input
        tokens / 10`` (cache reads are cheap); labelled ``share``, never summed."""
        turns: dict[str, list[Span]] = {}
        for sp in spans.values():
            if sp.kind == "turn" and sp.parent in spans and spans[sp.parent].kind == "session":
                turns.setdefault(sp.parent, []).append(sp)
        for sid, ts in turns.items():
            s = spans[sid]
            if s.usd is None:
                continue
            w = [(t, (t.tokens or {}).get("out", 0) + (t.tokens or {}).get("in", 0) / 10 + 1)
                 for t in ts]
            total = sum(x for _, x in w) or 1
            for t, x in w:
                t.usd, t.usd_kind = round(float(s.usd) * x / total, 6), "share"

    @staticmethod
    def _order(spans: dict[str, Span], root: str) -> None:
        kids: dict[str | None, list[Span]] = {}
        for sp in spans.values():
            if sp.parent is not None and sp.parent not in spans:
                sp.parent = root if sp.id != root else None
            kids.setdefault(sp.parent, []).append(sp)
        for lst in kids.values():
            lst.sort(key=lambda s: (s.start is None, s.start or 0, s.seq))
        pos = 0
        stack = [(spans[root], 0)]
        seen = set()
        while stack:
            sp, d = stack.pop()
            if sp.id in seen:
                continue
            seen.add(sp.id)
            sp.depth, sp.pos = d, pos
            pos += 1
            ch = kids.get(sp.id, [])
            sp.children = len(ch)
            stack.extend((c, d + 1) for c in reversed(ch))
        for sp in spans.values():                      # a cycle or an orphan: at the end
            if sp.id not in seen:
                sp.pos, pos = pos, pos + 1

    def _summary(self, spans: dict[str, Span], root: str) -> dict:
        run = spans[root]
        sessions = [s for s in spans.values() if s.kind == "session"]
        tools = [s for s in spans.values() if s.kind in ("tool", "subagent")]
        errors = [s for s in tools if s.status == "error"] + \
            [s for s in sessions if s.status == "error"]
        stopped = any((s.error or {}).get("stopped") for s in [run, *sessions] if s.error)
        if self.running:
            state = "running"
        elif run.status == "error":
            state = "stopped" if (run.error or {}).get("stopped") else "error"
        elif stopped and run.status != "ok":
            state = "stopped"
        else:
            state = "ok" if run.status in ("ok", "unset") else "error"
        usd = run.usd
        if usd is None:
            st = [s.usd for s in spans.values() if s.kind == "stage" and s.usd is not None]
            usd = round(sum(st), 4) if st else None
        tok = None
        for s in sessions:
            tok = add_tokens(tok, s.tokens)
        failed_at = None
        held = next((lk for lk in self.links if lk["kind"] == "hold" and lk["span"]), None)
        if state in ("error", "stopped"):
            bad = [s for s in sessions if s.status == "error"]
            if bad:
                last = max(bad, key=lambda s: s.start or 0)
                errs = [t for t in tools if t.status == "error" and self._under(spans, t, last.id)]
                failed_at = max(errs, key=lambda s: s.start or 0).id if errs else last.id
            else:
                st = [s for s in spans.values() if s.kind == "stage" and s.status == "error"]
                failed_at = st[-1].id if st else None
        elif held is not None:
            failed_at = held["span"]
        ends = [s.end for s in spans.values() if s.end is not None]
        ended = None if self.running else (run.end or (max(ends) if ends else None))
        return {"id": self.id, "source": self.id.split(":", 1)[0], "key": self.key,
                "n": self.n, "title": run.name, "state": state,
                "outcome": "held" if held is not None or any(
                    lk["kind"] == "hold" for lk in self.links) else None,
                "started": run.start, "ended": ended,
                "wall_s": round(ended - run.start, 1) if ended and run.start else None,
                "usd": usd, "usd_kind": "exact" if usd is not None else "none", "tokens": tok,
                "sessions": len(sessions), "tools": len(tools), "errors": len(errors),
                "spans": len(spans), "failed_at": failed_at,
                "model": next((s.attrs.get("model") for s in sessions
                               if s.attrs.get("model")), None)}

    def path_of(self, rel: str) -> Path:
        p = (self.taskdir / rel).resolve()
        if not str(p).startswith(str(self.taskdir.resolve()) + os.sep):
            raise ValueError("outside the task")
        return p


    def path_of(self, rel: str) -> Path:
        p = (self.taskdir / rel).resolve()
        if not str(p).startswith(str(self.taskdir.resolve()) + os.sep):
            raise ValueError("outside the task")
        return p


def failed_label(t: Trace) -> str | None:
    """"verify › turn 31 › Bash" for the trace's failure point."""
    fid = t.summary.get("failed_at")
    if not fid or fid not in t.spans:
        return None
    first = t.spans[fid]
    parts, sp, hops = [], first, 0
    while sp is not None and sp.kind != "run" and hops < 16:
        if sp.kind != "session" or sp is first:        # a session is named by its stage
            parts.append(sp.name)
        sp = t.spans.get(sp.parent) if sp.parent else None
        hops += 1
    return " › ".join(reversed(parts))


__all__ = ["Trace", "failed_label"]
