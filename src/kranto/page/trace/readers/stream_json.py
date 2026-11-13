"""A Claude Code session's stream-json transcript (``claude -p --output-format stream-json``)
or its own session file (``<config>/projects/<cwd key>/<session>.jsonl``, ``native=True``)
into spans:

- **session** ← ``system/init`` (the native file: its first line) to ``result``;
- **turn** ← the ``assistant`` lines of one API response (one ``message.id``; a response with
  several blocks is several lines and **one** turn); its tokens from ``message.usage``; its
  input the ``user`` line before it;
- **tool** ← a ``tool_use`` block and the ``tool_result`` with the same id (``is_error`` makes
  it an error); an ``Agent``/``Task`` call is a **subagent** span, and every later line whose
  ``parent_tool_use_id`` is its id is its child;
- **event** ← ``api_retry``, ``permission_denied`` (which also marks its tool denied), a rate
  limit that is not "allowed", a compaction; ``task_started``/``task_notification`` are
  events on their sub-agent's span.

``stream_event`` deltas, ``tool_progress`` and ``thinking_tokens`` make no span. Unknown line
types are skipped, as ``docs/events.md`` asks of its own readers.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..model import PREVIEW, Span, span_id, tokens
from . import lines

AGENT_TOOLS = ("Agent", "Task")
EDIT_TOOLS = ("Edit", "MultiEdit", "Write", "NotebookEdit")


def iso(ts) -> float | None:
    if isinstance(ts, (int, float)):
        return float(ts) / (1000.0 if ts > 1e11 else 1.0)
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError):
        return None


def mcp_parts(name: str) -> tuple[str | None, str]:
    """``("rea", "open_binary")`` for ``mcp__rea__open_binary``; ``(None, name)`` else."""
    if name.startswith("mcp__"):
        rest = name[5:]
        server, sep, tool = rest.partition("__")
        if sep:
            return server, tool
    return None, name


def one_line(s, n: int = PREVIEW) -> str:
    s = " ".join(str(s or "")[:n * 8].split())          # a 20 MB output: its start only
    return s if len(s) <= n else s[:n - 1] + "…"


def tool_preview(name: str, inp) -> str:
    """The words a tool row shows: the command, the path, the pattern, the description."""
    if not isinstance(inp, dict):
        return one_line(inp)
    for k in ("command", "file_path", "notebook_path", "path", "url", "pattern", "query",
              "description", "skill", "prompt"):
        v = inp.get(k)
        if isinstance(v, str) and v.strip():
            if k == "pattern" and isinstance(inp.get("path"), str):
                return one_line(f"{v}  in {inp['path']}")
            return one_line(v)
    try:
        return one_line(json.dumps(inp, ensure_ascii=False)[:PREVIEW * 4])
    except (TypeError, ValueError):
        return ""


def result_text(content) -> str:
    """A ``tool_result``'s content as text (a string, or text blocks)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict) and b.get("type") == "text":
                out.append(str(b.get("text") or ""))
            elif isinstance(b, dict) and b.get("type") == "image":
                out.append("[an image]")
        return "\n".join(out)
    return "" if content is None else str(content)


def patch_counts(res) -> tuple[int, int] | None:
    """``(added, removed)`` lines from an Edit's ``structuredPatch``."""
    hunks = res.get("structuredPatch") if isinstance(res, dict) else None
    if not isinstance(hunks, list) or not hunks:
        return None                       # a new file's write has none: its content counts
    add = rem = 0
    for h in hunks:
        for ln in (h or {}).get("lines") or []:
            if isinstance(ln, str) and ln.startswith("+"):
                add += 1
            elif isinstance(ln, str) and ln.startswith("-"):
                rem += 1
    return add, rem


class StreamReader:
    """One transcript file's spans. ``file``: its path relative to the trace's root (for the
    payload references); ``parent``: the span a session hangs under (its stage's);
    ``purpose``: the session's name (``verify``, ``repair1``); ``rank``: the file's place in
    the trace, which orders ties."""

    def __init__(self, trace: str, file: str, parent: str | None, purpose: str,
                 stage: str | None = None, rank: int = 0, native: bool = False,
                 depth: int = 2):
        self.trace, self.file, self.parent, self.purpose = trace, file, parent, purpose
        self.stage, self.rank, self.native, self.depth = stage, rank, native, depth
        self.offset = 0
        self.line = 0
        self.spans: dict[str, Span] = {}
        self.session: Span | None = None
        self.turns: dict[str, int] = {}        # parent span id -> turns so far
        self.msg_turn: dict[str, str] = {}     # message id -> turn span id
        self.last_user: dict[str, dict] = {}   # parent span id -> the user line before a turn
        self.last_ts: float | None = None
        self.result: dict | None = None
        self.args: dict[str, dict] = {}        # tool span id -> its input (parsed)
        self.outs: dict[str, str] = {}         # tool span id -> its output's first 8 KB
        self.changed: set[str] = set()

    def text(self, sid: str) -> str:
        """A tool call's input and output as text, for search and the outcome's links."""
        inp = self.args.get(sid)
        try:
            head = json.dumps(inp, ensure_ascii=False)[:4000] if inp else ""
        except (TypeError, ValueError):
            head = ""
        return head + "\n" + self.outs.get(sid, "")

    @property
    def texts(self) -> dict[str, str]:
        """Every tool call's ``text`` (made now: for a search, the index, the links)."""
        return {sid: self.text(sid) for sid in list(self.args)}

    # -- feeding ----------------------------------------------------------------------------
    def read(self, path: Path) -> set[str]:
        """Read the lines past ``offset``; the ids of the spans made or changed."""
        self.changed = set()
        for start, end, obj in lines(path, self.offset):
            self.offset = end
            self.line += 1
            if obj is not None:
                try:
                    self.feed(obj, start, end)
                except (TypeError, ValueError, AttributeError, KeyError):
                    continue                  # an odd line is no span, never a failed read
        return self.changed

    def _add(self, s: Span) -> Span:
        s.seq = self.rank * 10_000_000 + self.line * 100 + len(self.spans) % 100
        self.spans[s.id] = s
        self.changed.add(s.id)
        return s

    def _touch(self, s: Span) -> None:
        self.changed.add(s.id)

    def feed(self, o: dict, start: int, end: int) -> None:
        t = o.get("type")
        ts = iso(o.get("timestamp"))
        if ts is not None:
            self.last_ts = ts
        if self.native and t in ("user", "assistant") and self.session is None:
            self._session(o.get("sessionId") or o.get("session_id") or "", o.get("uuid") or "",
                          {"cwd": o.get("cwd"), "version": o.get("version")}, start)
        if t == "system":
            self._system(o, start, end)
        elif t == "assistant":
            self._assistant(o, ts, start, end)
        elif t == "user":
            self._user(o, ts, start, end)
        elif t == "result":
            self._result(o)
        elif t == "rate_limit_event":
            info = o.get("rate_limit_info") or {}
            if info.get("status") not in (None, "allowed"):
                kinds = info.get("unifiedWindows") or {}
                worst = max(((k, (v or {}).get("utilization") or 0) for k, v in kinds.items()),
                            key=lambda kv: kv[1], default=(info.get("rateLimitType"), None))
                pct = f" {round(float(worst[1]) * 100)} %" if worst[1] else ""
                self._event(o, f"rate limit {worst[0] or ''}{pct}".strip(), "warning",
                            {"status": info.get("status")}, start, end)
        if self.session is not None and self.last_ts is not None:
            if self.session.start is None:
                self.session.start = self.last_ts
            if self.session.status == "running":
                self.session.end = None

    def _session(self, sid: str, uuid: str, attrs: dict, start: int) -> None:
        s = Span(id=span_id(self.trace, f"session:{sid}:{uuid}"), trace=self.trace,
                 parent=self.parent, kind="session", name=self.purpose, stage=self.stage,
                 status="running", depth=self.depth,
                 source={"file": self.file, "line": self.line, "from": start})
        s.attrs = {k: v for k, v in attrs.items() if v not in (None, [], {})}
        s.attrs["session_id"] = sid
        s.attrs["purpose"] = self.purpose
        s.inputs = {"file": self.file, "part": "chat", "bytes": None}
        self.session = self._add(s)

    def _system(self, o: dict, start: int, end: int) -> None:
        sub = o.get("subtype")
        if sub == "init" and self.session is None:
            mcp = [m.get("name") for m in o.get("mcp_servers") or [] if isinstance(m, dict)]
            self._session(o.get("session_id") or "", o.get("uuid") or "",
                          {"model": o.get("model"), "tools": len(o.get("tools") or []),
                           "mcp_servers": mcp,
                           "plugins": [p.get("name") for p in o.get("plugins") or []
                                       if isinstance(p, dict)],
                           "claude_code_version": o.get("claude_code_version"),
                           "permission_mode": o.get("permissionMode"), "cwd": o.get("cwd")},
                          start)
        elif sub == "api_retry":
            st = o.get("error_status")
            name = (f"api_retry {o.get('attempt') or '?'} of {o.get('max_retries') or '?'}"
                    + (f" · {st}" if st else "") + (f" {o.get('error')}" if o.get("error")
                                                     else ""))
            self._event(o, name, "warning", {k: o.get(k) for k in (
                "attempt", "max_retries", "error_status", "error", "retry_delay_ms")
                if o.get(k) is not None}, start, end)
        elif sub == "permission_denied":
            tid = o.get("tool_use_id")
            msg = one_line(o.get("message"), 400)
            self._event(o, f"permission_denied {o.get('tool_name') or ''}".strip(), "error",
                        {"tool": o.get("tool_name"), "reason": o.get("decision_reason_type")},
                        start, end, message=msg)
            sp = self.spans.get(span_id(self.trace, f"tool:{tid}")) if tid else None
            if sp is not None:
                sp.attrs["denied"] = True
                sp.status = "error"
                sp.error = {"type": "denied", "message": msg or "permission denied"}
                self._touch(sp)
        elif sub in ("task_started", "task_notification"):
            tid = o.get("tool_use_id")
            sp = self.spans.get(span_id(self.trace, f"tool:{tid}")) if tid else None
            if sp is not None:
                sp.events.append({"ts": self.last_ts, "name": sub,
                                  "attrs": {k: o.get(k) for k in ("task_id", "task_type",
                                                                  "status", "is_backgrounded")
                                            if o.get(k) is not None}})
                self._touch(sp)
        elif sub in ("compact_boundary", "compaction"):
            self._event(o, "compaction", "info", {}, start, end)

    def _event(self, o: dict, name: str, level: str, attrs: dict, start: int, end: int,
               message: str | None = None) -> None:
        if self.session is None:
            return
        key = o.get("uuid") or f"{self.file}:{self.line}"
        parent = self.session.id
        ptid = o.get("parent_tool_use_id")
        if ptid and span_id(self.trace, f"tool:{ptid}") in self.spans:
            parent = span_id(self.trace, f"tool:{ptid}")
        e = Span(id=span_id(self.trace, f"event:{key}"), trace=self.trace, parent=parent,
                 kind="event", name=name, stage=self.stage, start=self.last_ts,
                 end=self.last_ts, status="error" if level == "error" else "unset",
                 depth=self.spans[parent].depth + 1, preview=message or "",
                 source={"file": self.file, "line": self.line, "from": start, "to": end})
        e.attrs = {"level": level, **attrs}
        if level == "error":
            e.error = {"type": name.split(" ")[0], "message": message or name}
        self._add(e)

    def _owner(self, o: dict) -> Span | None:
        """The span a line's turn hangs under: its sub-agent's, else the session."""
        ptid = o.get("parent_tool_use_id")
        if ptid:
            sp = self.spans.get(span_id(self.trace, f"tool:{ptid}"))
            if sp is not None:
                return sp
        return self.session

    def _assistant(self, o: dict, ts: float | None, start: int, end: int) -> None:
        owner = self._owner(o)
        if owner is None:
            return
        msg = o.get("message") or {}
        mid = msg.get("id") or o.get("uuid") or f"{self.file}:{self.line}"
        tid = self.msg_turn.get(mid)
        turn = self.spans.get(tid) if tid else None
        if turn is None:
            n = self.turns.get(owner.id, 0) + 1
            self.turns[owner.id] = n
            turn = Span(id=span_id(self.trace, f"turn:{mid}"), trace=self.trace,
                        parent=owner.id, kind="turn", name=f"turn {n}", stage=self.stage,
                        start=ts, end=ts, status="ok", depth=owner.depth + 1,
                        source={"file": self.file, "line": self.line, "from": start})
            turn.attrs = {"n": n, "message_id": msg.get("id"), "request_id": o.get("request_id"),
                          "model": msg.get("model")}
            prev = self.last_user.get(owner.id)
            if prev:
                turn.inputs = {k: v for k, v in prev.items() if k != "ts"}
                if prev.get("ts") is not None and ts is not None and prev["ts"] <= ts:
                    turn.start = prev["ts"]     # from the input that fed it: the response time
            turn.outputs = {"file": self.file, "part": "turn", "lines": [], "bytes": 0}
            self.msg_turn[mid] = turn.id
            self._add(turn)
            if owner.kind == "session":
                owner.attrs["turns"] = n
                self._touch(owner)
        else:
            turn.end = ts or turn.end
            self._touch(turn)
        tok = tokens(msg.get("usage"))
        if tok:
            turn.tokens = tok                  # every line of a response repeats its usage
        if msg.get("stop_reason"):
            turn.attrs["stop_reason"] = msg["stop_reason"]
        turn.outputs["lines"].append([start, end])
        for b in msg.get("content") or []:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt in ("text", "thinking"):
                txt = b.get("text") if bt == "text" else b.get("thinking")
                turn.outputs["bytes"] += len(str(txt or ""))
                if bt == "text" and not turn.preview:
                    turn.preview = one_line(txt)
                if bt == "thinking":
                    turn.attrs["thinking"] = True
            elif bt == "tool_use":
                self._tool_use(b, turn, ts, start, end)

    def _tool_use(self, b: dict, turn: Span, ts: float | None, start: int, end: int) -> None:
        name = str(b.get("name") or "tool")
        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
        server, short = mcp_parts(name)
        agent = name in AGENT_TOOLS
        sp = Span(id=span_id(self.trace, f"tool:{b.get('id')}"), trace=self.trace,
                  parent=turn.id, kind="subagent" if agent else "tool",
                  name=(f"{name} {inp.get('subagent_type') or ''}".strip() if agent else name),
                  stage=self.stage, start=ts, status="running", depth=turn.depth + 1,
                  preview=tool_preview(name, inp),
                  source={"file": self.file, "line": self.line, "from": start, "to": end})
        sp.attrs = {"tool": name, "call_id": b.get("id"),
                    "type": "extension" if server else "function"}
        if server:
            sp.attrs.update(server=server, tool_short=short)
        if agent:
            sp.attrs["agent_type"] = inp.get("subagent_type") or "general"
        for k in ("file_path", "notebook_path"):
            if isinstance(inp.get(k), str):
                sp.attrs["file_path"] = inp[k]
        if name == "Write" and isinstance(inp.get("content"), str):
            sp.attrs["lines_added"] = inp["content"].count("\n") + 1
        sp.inputs = {"file": self.file, "from": start, "to": end, "block": b.get("id"),
                     "part": "input", "bytes": None}
        self.args[sp.id] = inp                 # made into text only when searched or linked
        self._add(sp)
        turn.attrs["tools"] = int(turn.attrs.get("tools") or 0) + 1

    def _user(self, o: dict, ts: float | None, start: int, end: int) -> None:
        owner = self._owner(o)
        msg = o.get("message") or {}
        content = msg.get("content")
        res = o.get("toolUseResult" if self.native else "tool_use_result")
        results = [b for b in content or [] if isinstance(b, dict)
                   and b.get("type") == "tool_result"] if isinstance(content, list) else []
        if owner is not None:
            self.last_user[owner.id] = {"file": self.file, "from": start, "to": end,
                                        "part": "user", "bytes": end - start, "ts": ts}
        for b in results:
            tid = b.get("tool_use_id")
            sp = self.spans.get(span_id(self.trace, f"tool:{tid}"))
            if sp is None:
                continue
            text = result_text(b.get("content"))
            sp.end = ts if ts is not None else self.last_ts
            err = bool(b.get("is_error"))
            if sp.attrs.get("denied"):
                err = True
            sp.status = "error" if err else "ok"
            if err and not sp.error:
                sp.error = {"type": "tool_error", "message": one_line(text, 400) or "error"}
            sp.outputs = {"file": self.file, "from": start, "to": end, "block": tid,
                          "part": "output", "bytes": len(text)}
            if isinstance(res, dict) and len(results) == 1:
                if res.get("interrupted"):
                    sp.attrs["interrupted"] = True
                pc = patch_counts(res)
                if pc:
                    sp.attrs["lines_added"], sp.attrs["lines_removed"] = pc
                if isinstance(res.get("stderr"), str) and res["stderr"]:
                    sp.attrs["stderr_bytes"] = len(res["stderr"])
            self.outs[sp.id] = text[:8000]
            if not sp.preview:
                sp.preview = one_line(text)
            self._touch(sp)

    def _result(self, o: dict) -> None:
        from .classify import classify
        s = self.session
        if s is None:
            return
        self.result = o
        s.end = self.last_ts
        bad = classify([(0, o)])
        s.status = "ok" if bad is None else ("error" if bad["status"] == "error" else "error")
        if bad is not None:
            s.error = {"type": bad["class"], "message": bad["detail"],
                       "stopped": bad["status"] == "stopped"}
        s.usd = o.get("total_cost_usd")
        s.usd_kind = "exact" if s.usd is not None else "none"
        u = tokens(o.get("usage"))
        if u:
            think = ((o.get("usage") or {}).get("output_tokens_details") or {}).get(
                "thinking_tokens")
            if think:
                u["thinking"] = int(think)
            s.tokens = u
        s.attrs.update({k: o.get(k) for k in (
            "subtype", "num_turns", "duration_ms", "duration_api_ms", "terminal_reason",
            "stop_reason") if o.get(k) is not None})
        if o.get("permission_denials"):
            s.attrs["permission_denials"] = len(o["permission_denials"])
        if isinstance(o.get("subagent_stats"), dict):
            s.attrs["subagents"] = o["subagent_stats"].get("spawned")
        if isinstance(o.get("modelUsage"), dict):
            s.attrs["models"] = sorted(o["modelUsage"])
        self._touch(s)

    # -- after the last line ----------------------------------------------------------------
    def close(self, running: bool) -> None:
        """The file will not grow (``running`` False): a session with no ``result`` stopped
        (``no-result``); a tool with no result never finished."""
        s = self.session
        if s is None or self.result is not None:
            return
        if running:
            s.status = "running"
            return
        s.status = "error"
        s.end = self.last_ts
        s.error = {"type": "no-result", "stopped": True,
                   "message": "the session ended without a result (killed, timed out or "
                              "crashed)"}
        for sp in self.spans.values():
            if sp.status == "running":
                sp.status = "error"
                sp.end = sp.end or self.last_ts
                sp.error = {"type": "no-result", "message": "no result: the session ended "
                                                            "first"}
