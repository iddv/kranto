"""A trace of one kept stream-json file: a research run's session, ``research:<stem>``,
kept under ``<loop home>/research/transcripts/<stem>.transcript.jsonl`` by the researcher
(``harness.researcher.run(keep=…)``, gone with the build loop: the kept files still read). The run is the frame; the session, its turns and its tool
calls (``kranto_search``, ``kranto_fetch``) are the file's, as a build's session is read."""
from __future__ import annotations

import re
import time
from pathlib import Path

from .base import Trace
from .model import Span, span_id
from .readers.stream_json import StreamReader

STEM = re.compile(r"\d{9,11}-[a-z]{1,20}")
QUIET_S = 120              # a file without its result that grew this recently is still running


def transcripts_dir(loop_home: Path) -> Path:
    """Where research sessions kept their streams: ``<loop home>/research/transcripts``."""
    return Path(loop_home) / "research" / "transcripts"


def research_file(loop_home: Path, stem: str) -> Path | None:
    if not STEM.fullmatch(stem or ""):
        return None
    return transcripts_dir(loop_home) / f"{stem}.transcript.jsonl"


class FileTrace(Trace):
    def __init__(self, path: Path, tid: str, title: str):
        super().__init__(path.parent, path.name, 0, source=tid.split(":", 1)[0])
        self.id, self.n, self.path, self.title = tid, None, path, title
        self.key = tid.split(":", 1)[1]                  # the stem: what the route names

    def files(self) -> list[Path]:
        return [self.path] if self.path.is_file() else []

    def refresh(self) -> bool:
        changed = False
        rel = self.rel(self.path)
        r = self.streams.get(rel)
        if self.path.is_file():
            if r is None:
                r = self.streams[rel] = StreamReader(self.id, rel, None, "research", rank=1,
                                                     depth=1)
                self.sizes.pop(rel, None)
            g = self._grew(self.path, rel, r)
            if g is None:
                r = self.streams[rel] = StreamReader(self.id, rel, None, "research", rank=1,
                                                     depth=1)
                g = True
            if g:
                changed |= bool(r.read(self.path))
            self.running = r.result is None and time.time() - self.path.stat().st_mtime < QUIET_S
        if changed or not self.spans:
            self.assemble()
        return changed

    def assemble(self) -> None:
        run = Span(id=span_id(self.id, "run"), trace=self.id, parent=None, kind="run",
                   name=self.title, depth=0, status="running" if self.running else "unset")
        spans: dict[str, Span] = {run.id: run}
        for r in self.streams.values():
            r.close(self.running)
            spans.update(r.spans)
            if r.session is not None:
                s = spans[r.session.id]
                s.parent = run.id
                run.start, run.end = s.start, s.end
                run.usd, run.usd_kind = s.usd, s.usd_kind
                if not self.running:
                    run.status = "error" if s.status == "error" else "ok"
                    run.error = s.error
        self._shares(spans)
        self._order(spans, run.id)
        self.spans = spans
        self.links = []
        self.summary = self._summary(spans, run.id)
