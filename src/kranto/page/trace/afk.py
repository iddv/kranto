"""the server's runs as traces: ``afk:<run_uuid>``, the analyst's cards,
explains and deep dives, News's briefs and a cub's runs. Read through
the server's own API (``GET /api/runs/<uuid>``, the owner's only), never its database file.

A run is the frame; each model call (an ``llm_calls`` row) is a **call** span whose payloads are
the call's request and answer as the server kept them (retention may have removed them: the span
says so); a cub's host call is a **tool** span with its op and nothing of its payload;
an event is an event. Costs are the calls' own (exact). The payloads are held in memory (a
run is a few calls), served redacted and paged like any trace's (``payload.py``)."""
from __future__ import annotations

import json
import time
from datetime import datetime

from .base import Trace
from .model import Span, add_tokens, span_id


def _ts(s) -> float | None:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def _answer(s) -> str:
    """A stored answer's words for the row's preview: the message's text when the answer is a
    chat completion (``choices[0].message.content``) or a messages reply (``content`` text
    blocks), else the answer as it was kept."""
    try:
        d = json.loads(s) if isinstance(s, str) else None
    except ValueError:
        d = None
    if isinstance(d, dict):
        ch = d.get("choices")
        if isinstance(ch, list) and ch and isinstance(ch[0], dict):
            msg = ch[0].get("message") or {}
            if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                return msg["content"]
        blocks = d.get("content")
        if isinstance(blocks, list):
            words = [b.get("text") for b in blocks if isinstance(b, dict)
                     and isinstance(b.get("text"), str)]
            if words:
                return "\n".join(words)
    return "" if s is None else str(s)


def _pretty(s) -> str:
    """A stored request or answer as text: JSON indented when it is JSON."""
    if s is None:
        return ""
    try:
        return json.dumps(json.loads(s), ensure_ascii=False, indent=2)
    except (TypeError, ValueError):
        return str(s)


class AfkTrace(Trace):
    """``mirror``: the server's ``activity.json`` (None: not known here). While the run has no
    end the trace is **live**: a page that follows it watches the mirror, and
    each change re-reads the run's calls and marks; the follow ends when the run is over."""

    def __init__(self, fetch, uuid: str, mirror=None):
        from pathlib import Path
        super().__init__(Path("/"), uuid, 0, source="afk")
        self.id, self.n, self.key, self.fetch = f"afk:{uuid}", None, uuid, fetch
        self.mirror = mirror
        self.data: dict | None = None
        self.act: dict | None = None                    # its marks (the server's /api/activity)
        self.inline: dict[str, dict[str, str]] = {}      # span id -> {input, output}
        self._sig: tuple | None = None

    def files(self):
        return [self.mirror] if self.running and self.mirror is not None else []

    def _over(self) -> bool:
        r = (self.data or {}).get("run") or {}
        if r.get("finished_at"):
            return True
        a = self.act or {}
        return bool(a.get("over")) or (self.data is not None and not a)

    def refresh(self) -> bool:
        if self.data is not None and not self.running:  # a run is over once it is listed
            return False
        from .service import TraceError
        try:
            data = self.fetch(f"/api/runs/{self.key}")
        except TraceError as e:
            if e.code != 404:
                raise
            data = None
        try:
            act = self.fetch(f"/api/activity?run={self.key}")
        except TraceError as e:
            if data is None:                            # neither a run nor a run in progress
                raise
            act = None if e.code == 404 else self.act
        if data is None:
            data = {"run": {"run_uuid": self.key, "kind": ((act or {}).get("run") or {}).get(
                "kind")}, "calls": [], "cub_calls": [], "events": []}
        sig = (len(data.get("calls") or []), len(data.get("cub_calls") or []),
               len(data.get("events") or []), (data.get("run") or {}).get("finished_at"),
               len((act or {}).get("marks") or []), ((act or {}).get("run") or {}).get("words"))
        self.data, self.act = data, act
        self.running = not self._over()
        if sig == self._sig and self.spans:
            return False
        self._sig = sig
        self.assemble()
        return True

    def _steps(self, run: Span, spans: dict[str, Span]) -> None:
        """A ``stage`` span per step the run's marks said (a source, a trend's source, a
        topic's brief); the one in hand is running while the run runs."""
        marks = [m for m in (self.act or {}).get("marks") or []
                 if m.get("mark") == "progress" and m.get("words")]
        end = _ts(((self.data or {}).get("run") or {}).get("finished_at"))
        steps: list[tuple[float | None, str]] = []
        for m in marks:
            label = str(m["words"]).split(" · ")[0]
            if steps and steps[-1][1] == label:
                continue
            steps.append((_ts(m.get("ts")), label))
        for i, (t, label) in enumerate(steps):
            nxt = steps[i + 1][0] if i + 1 < len(steps) else end
            last = i + 1 == len(steps)
            s = Span(id=span_id(self.id, f"step:{i}"), trace=self.id, parent=run.id,
                     kind="stage", name=label, start=t, end=nxt, depth=1, seq=500 + i,
                     status="running" if last and self.running else "ok")
            s.attrs = {"step": i + 1}
            spans[s.id] = s

    def head_line(self, calls: int, usd: float | None) -> str | None:
        """The trace's plain head line: what the run is, its stage, its calls, its spend (the
        owner's D-1: dollars here)."""
        a = ((self.act or {}).get("run") or {})
        if not a:
            return None
        parts = [a.get("title")]
        if a.get("words"):
            parts.append(a["words"])
        parts.append(f"{calls} model call{'' if calls == 1 else 's'}")
        if usd:
            parts.append(f"${usd:.2f}")
        return " · ".join(p for p in parts if p)

    def assemble(self) -> None:
        d = self.data or {}
        r = d.get("run") or {}
        a = (self.act or {}).get("run") or {}
        start = _ts(r.get("started_at")) or _ts(a.get("started"))
        # the title is the run's words and time; its summary (the server's JSON) is the Overview's
        when = time.strftime("%d %b %H:%M", time.localtime(start)) if start is not None else None
        run = Span(id=span_id(self.id, "run"), trace=self.id, parent=None, kind="run",
                   name=" · ".join(x for x in (a.get("title") or r.get("kind") or "run", when)
                                   if x),
                   start=start, end=_ts(r.get("finished_at")), depth=0,
                   status="running" if self.running else {
                       "ok": "ok", "degraded": "ok", "failed": "error"}.get(
                       r.get("status"), "unset"))
        if r.get("error"):
            run.error = {"type": "run_failed", "message": str(r["error"])[:400]}
        run.attrs = {k: r.get(k) for k in ("kind", "status") if r.get(k)}
        if r.get("summary") not in (None, "", {}, []):
            run.attrs["summary"] = _pretty(r["summary"]) if isinstance(r["summary"], str) \
                else json.dumps(r["summary"], ensure_ascii=False, indent=2)
        spans: dict[str, Span] = {run.id: run}
        total = 0.0
        for i, c in enumerate(d.get("calls") or []):
            end = _ts(c.get("created_at"))
            lat = (c.get("latency_ms") or 0) / 1000.0
            s = Span(id=span_id(self.id, f"call:{c.get('id', i)}"), trace=self.id,
                     parent=run.id, kind="call",
                     name=f"{c.get('purpose') or 'call'} · {c.get('model') or ''}".strip(" ·"),
                     start=(end - lat) if end is not None else None, end=end, depth=1,
                     status="ok" if c.get("status") == "ok" else "error", seq=i)
            s.attrs = {k: c.get(k) for k in ("purpose", "tier", "model", "prompt_version",
                                             "attempts", "http_status") if c.get(k) is not None}
            if c.get("status") != "ok":
                s.error = {"type": "call_failed", "message": str(c.get("error") or "")[:400]}
            if isinstance(c.get("cost_usd"), (int, float)):
                s.usd, s.usd_kind = float(c["cost_usd"]), "exact"
                total += s.usd
            if c.get("prompt_tokens") is not None or c.get("completion_tokens") is not None:
                s.tokens = {"in": int(c.get("prompt_tokens") or 0),
                            "out": int(c.get("completion_tokens") or 0)}
            if c.get("expired"):
                s.preview = "the request and the answer were removed by retention"
                s.attrs["expired"] = True
            else:
                req, resp = _pretty(c.get("request")), _pretty(c.get("response"))
                self.inline[s.id] = {"input": req, "output": resp}
                s.preview = " ".join(_answer(c.get("response")).split())[:240]
                s.inputs = {"part": "input", "bytes": len(req)}
                s.outputs = {"part": "output", "bytes": len(resp)}
            spans[s.id] = s
        for i, c in enumerate(d.get("cub_calls") or []):
            end = _ts(c.get("created_at"))
            s = Span(id=span_id(self.id, f"cub:{i}"), trace=self.id, parent=run.id, kind="tool",
                     name=f"{c.get('cub')} · {c.get('service')}.{c.get('op')}", depth=1,
                     start=(end - (c.get("ms") or 0) / 1000.0) if end is not None else None,
                     end=end, status="ok" if c.get("status") == "ok" else "error",
                     seq=1000 + i)
            s.attrs = {"tool": f"{c.get('service')}.{c.get('op')}", "cub": c.get("cub"),
                       "bytes_in": c.get("bytes_in"), "bytes_out": c.get("bytes_out")}
            s.preview = "a cub's host call: its op, never its payload"
            spans[s.id] = s
        for e in d.get("events") or []:
            t = _ts(e.get("ts"))
            s = Span(id=span_id(self.id, f"ev:{e.get('id')}"), trace=self.id, parent=run.id,
                     kind="event", name=f"{e.get('feature')} · {e.get('kind')}", start=t, end=t,
                     depth=1, status="unset", seq=2000 + int(e.get("id") or 0))
            s.attrs = {"level": "info", "subject": f"{e.get('subject_kind')}:{e.get('subject_id')}"}
            spans[s.id] = s
        if run.usd is None and total:
            run.usd, run.usd_kind = round(total, 6), "exact"
        self._steps(run, spans)
        self._order(spans, run.id)
        self.spans = spans
        self.links = []
        self.summary = self._summary(spans, run.id)
        self.summary["usd"] = run.usd
        self.summary["usd_kind"] = "exact" if run.usd is not None else "none"
        # a run's work is model calls, not sessions: the head counts them and their tokens
        calls = [s for s in spans.values() if s.kind == "call"]
        self.summary["calls"] = len(calls)
        tok = None
        for s in calls:
            tok = add_tokens(tok, s.tokens)
        self.summary["tokens"] = tok
        self.summary["running"] = self.running
        line = self.head_line(len(calls), run.usd)
        if line:
            self.summary["line"] = line
        a = (self.act or {}).get("run") or {}
        if a.get("stoppable") and self.running:
            self.summary["stop"] = {"id": f"afk:{self.key}"}
        if not d.get("calls") and not d.get("cub_calls") and not self.running:
            self.summary["note"] = "This run made no model calls: there is nothing to trace but " \
                                   "the run itself, and its summary is in its Overview."

    def path_of(self, rel: str):
        raise ValueError("an afk trace has no files")
