"""An Open in Claude Code session's trace: ``session:<tid>``, read from
the session's own folder where it is: its record (``<loop home>/term/<tid>/session.json``:
state, reason, cost, tokens) and Claude Code's own transcript of the conversation
(``term/<tid>/claude/projects/<cwd key>/<session>.jsonl``, the native format: no ``init`` and no
``result`` line, so the session ends with its record).

An End removes the working copy and keeps this folder, so the transcript stays (decision D-5
holds as Kranto is). A session continued in the owner's own terminal (``outside``) says so: its
conversation went on in the owner's Claude Code, and the trace here stops at the hand-over."""
from __future__ import annotations

from pathlib import Path

from .base import Trace
from .model import Span, span_id
from .readers.stream_json import StreamReader

# a session with no conversation in its folder: still starting, or one from before the folder
# kept Claude Code's transcript (Kranto 0.5.0)
NO_TRANSCRIPT = {True: "The session has not said anything yet: its turns show here as they come.",
                 False: "This session kept no transcript: sessions that ended before Kranto 0.5.0 "
                        "kept none, so there is nothing to show but how it ended."}


def transcript_of(tdir: Path, rec: dict) -> Path | None:
    from ..box.claude_dirs import project_key
    try:
        return Path(tdir) / "claude" / "projects" / project_key(Path(rec["cwd"])) / \
            f"{rec['session']}.jsonl"
    except (KeyError, TypeError):
        return None


class SessionTrace(Trace):
    def __init__(self, tdir: Path, tid: str):
        super().__init__(tdir, tid, 0, source="session")
        self.id = f"session:{tid}"
        self.n = None
        self.rec: dict = {}

    def _record(self) -> dict:
        from ..term.store import Store
        return Store(self.taskdir.parent).get(self.key) or {}

    def files(self) -> list[Path]:
        t = transcript_of(self.taskdir, self.rec) if self.rec else None
        return [p for p in (t,) if p is not None and p.is_file()]

    def refresh(self) -> bool:
        before = (self.rec.get("state"), self.rec.get("reason"), self.rec.get("usd"))
        self.rec = self._record()
        changed = before != (self.rec.get("state"), self.rec.get("reason"), self.rec.get("usd"))
        self.running = self.rec.get("state") == "running"
        present = set()
        for p in self.files():
            rel = self.rel(p)
            present.add(rel)
            r = self.streams.get(rel)
            if r is None:
                r = self.streams[rel] = StreamReader(self.id, rel, None, "session", native=True,
                                                     rank=1, depth=1)
                self.sizes.pop(rel, None)
            g = self._grew(p, rel, r)
            if g is None:
                r = self.streams[rel] = StreamReader(self.id, rel, None, "session", native=True,
                                                     rank=1, depth=1)
                g = True
            if g:
                changed |= bool(r.read(p))
        for rel in [k for k in self.streams if k not in present]:
            del self.streams[rel]
            changed = True
        if changed or not self.spans:
            self.assemble()
        return changed

    def assemble(self) -> None:
        rec = self.rec
        run = Span(id=span_id(self.id, "run"), trace=self.id, parent=None, kind="run",
                   name=str(rec.get("title") or f"Session {self.key}"),
                   start=rec.get("created"), depth=0)
        run.attrs = {k: rec.get(k) for k in ("key", "subject", "reason", "state", "project")
                     if rec.get(k) not in (None, "", {}, [])}
        reason = rec.get("reason")
        if self.running:
            run.status = "running"
        else:
            run.end = rec.get("updated")
            run.status = "error" if reason == "cap" else "ok"
            if reason == "cap":
                run.error = {"type": "budget", "stopped": True,
                             "message": "the session reached its cap and was ended"}
        if reason == "outside":
            run.preview = ("continued in your own terminal: the conversation went on in your "
                           "own Claude Code, and this trace stops at the hand-over")
        if isinstance(rec.get("usd"), (int, float)):
            run.usd, run.usd_kind = float(rec["usd"]), "exact"
        spans: dict[str, Span] = {run.id: run}
        for r in self.streams.values():
            r.close(self.running)
            spans.update(r.spans)
            if r.session is not None:
                s = spans[r.session.id]
                s.parent, s.name = run.id, "conversation"
                # the native file has no result line: the record says how it ended
                if not self.running and (s.error or {}).get("type") == "no-result":
                    s.status, s.end, s.error = "ok", run.end or s.end, None
                if s.usd is None and run.usd is not None:
                    s.usd, s.usd_kind = run.usd, "exact"
                if isinstance(rec.get("tokens"), dict) and s.tokens is None:
                    s.tokens = {"in": int(rec["tokens"].get("in") or 0),
                                "out": int(rec["tokens"].get("out") or 0)}
        if not self.running:
            for sp in spans.values():           # a call the conversation never answered
                if sp.status == "running":
                    sp.status, sp.error = "error", {"type": "no-result",
                                                    "message": "no result: the session ended "
                                                               "first"}
        self._shares(spans)
        self._order(spans, run.id)
        self.spans = spans
        self.links = []
        self.summary = self._summary(spans, run.id)
        talked = any(r.session is not None for r in self.streams.values())
        self.summary["note"] = run.preview or (None if talked else NO_TRANSCRIPT[self.running])
