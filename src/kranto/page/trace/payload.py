"""A span's payload: read from its file by byte range, never copied,
then redacted (``redact.py``), pretty-printed and paged.

Parts: ``input`` (a tool's arguments as key/value fields; a turn's input, the user line before
it), ``output`` (a tool's result, stdout and stderr; a turn's text and thinking; a session's
final answer), ``chat`` (a session's conversation as messages, from the session's file; for a
turn, the page that holds it) and ``diff`` (an edit's or a write's lines). Text comes back
``PAGE`` bytes at a time with ``next`` for the rest. ANSI escapes are dropped here; what a
tool read from a credentials file is replaced whole (redaction rule 3).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from .model import Span
from .readers import lines, read_line
from .readers.stream_json import result_text
from .redact import Redactor

PAGE = 64 * 1024
MAX_BYTES = 2 * 1024 * 1024          # trace.payload_max_mb: one span's payload at most
PARTS = ("input", "output", "chat", "diff")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
READERS = ("Read", "NotebookRead")
WRITERS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


class PayloadError(Exception):
    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code


def clean(s: str) -> str:
    return ANSI.sub("", s or "")


def _page(text: str, offset: int, trace=None) -> tuple[str, int | None]:
    """One page of ``text`` from ``offset`` (``trace.page_bytes``: ``trace.page_kb``)."""
    size = getattr(trace, "page_bytes", PAGE)
    offset = max(0, int(offset or 0))
    chunk = text[offset:offset + size]
    nxt = offset + size if len(text) > offset + size else None
    return chunk, nxt


def _line(trace, ref: dict) -> dict:
    if not ref or ref.get("from") is None:
        raise PayloadError(404, "this span has no such part")
    cap = getattr(trace, "max_bytes", MAX_BYTES)
    if ref["to"] - ref["from"] > cap:
        raise PayloadError(413, f"the line is bigger than {cap // (1024 * 1024)} MB; "
                                f"open {ref['file']} at byte {ref['from']}")
    try:
        obj = read_line(trace.path_of(ref["file"]), ref["from"], ref["to"])
    except OSError:
        raise PayloadError(410, f"the file {ref['file']} is not there any more") from None
    if obj is None:
        raise PayloadError(410, f"the line in {ref['file']} could not be read")
    return obj


def _block(obj: dict, bid: str, kind: str) -> dict | None:
    for b in ((obj.get("message") or {}).get("content") or []):
        if isinstance(b, dict) and b.get("type") == kind and (
                b.get("id") == bid or b.get("tool_use_id") == bid):
            return b
    return None


def _secret(sp: Span, red: Redactor) -> str | None:
    """The credentials path a tool read or wrote, when it did."""
    tool = sp.attrs.get("tool")
    fp = sp.attrs.get("file_path")
    if tool in READERS + WRITERS and fp and red.secret_path(fp):
        return fp
    return None


def hidden(trace, sp: Span | None, red: Redactor) -> str | None:
    """The credentials path whose contents this tool's **output** must not show: a Read of
    one, or a shell command that names one (``cat .env``). A write's output is only its
    confirmation; its input is hidden by ``_secret``."""
    if sp is None or sp.attrs.get("tool") in WRITERS:
        return None
    hide = _secret(sp, red)
    if hide is None and sp.attrs.get("tool") == "Bash":
        found = red.secret_paths_in(str(sp.preview or ""))
        if not found and sp.inputs and sp.inputs.get("from") is not None:
            try:
                cmd = (_block(_line(trace, sp.inputs), sp.inputs.get("block"), "tool_use")
                       or {}).get("input", {}).get("command", "")
                found = red.secret_paths_in(cmd)
            except PayloadError:
                found = []
        hide = found[0] if found else None
    return hide


def _fields(inp: dict, red: Redactor, hide: str | None) -> list[dict]:
    out = []
    for k, v in inp.items():
        if hide and k in ("content", "new_string", "old_string", "edits", "new_source"):
            out.append({"key": k, "value": red.contents_of(hide)})
            continue
        if isinstance(v, str):
            text = v
        else:
            text = json.dumps(v, ensure_ascii=False, indent=2)
        out.append({"key": k, "value": red.text(clean(text))})
    return out


def tool_input(trace, sp: Span, red: Redactor) -> dict:
    obj = _line(trace, sp.inputs)
    b = _block(obj, sp.inputs.get("block"), "tool_use") or {}
    inp = b.get("input") if isinstance(b.get("input"), dict) else {}
    hide = _secret(sp, red)
    return {"fields": _fields(inp, red, hide)}


def tool_output(trace, sp: Span, red: Redactor, offset: int = 0) -> dict:
    if not sp.outputs:
        return {"text": "", "running": sp.status == "running", "next": None}
    obj = _line(trace, sp.outputs)
    b = _block(obj, sp.outputs.get("block"), "tool_result") or {}
    res = obj.get("toolUseResult") or obj.get("tool_use_result")
    stdout = stderr = None
    if isinstance(res, dict) and isinstance(res.get("stdout"), str):
        stdout, stderr = res.get("stdout") or "", res.get("stderr") or ""
        text = stdout + (("\n" + stderr) if stderr else "")
    else:
        text = result_text(b.get("content"))
    hide = hidden(trace, sp, red)
    if hide is not None:
        text = red.contents_of(hide)
        stdout, stderr = (text, "") if stdout is not None else (None, None)
    text = red.text(clean(text))
    chunk, nxt = _page(text, offset, trace)
    out = {"text": chunk, "offset": int(offset or 0), "next": nxt, "bytes": len(text),
           "is_error": sp.status == "error"}
    if stderr:
        out["stderr"] = red.text(clean(stderr))[:PAGE]
        out["stderr_from"] = len(red.text(clean(stdout or "")))
    return out


def turn_text(trace, sp: Span, red: Redactor, offset: int = 0) -> dict:
    parts = []
    for a, b in (sp.outputs or {}).get("lines") or []:
        obj = _line(trace, {"file": sp.outputs["file"], "from": a, "to": b})
        for blk in (obj.get("message") or {}).get("content") or []:
            if not isinstance(blk, dict):
                continue
            if blk.get("type") == "text":
                parts.append(str(blk.get("text") or ""))
            elif blk.get("type") == "thinking":
                parts.append("(thinking)\n" + str(blk.get("thinking") or ""))
            elif blk.get("type") == "tool_use":
                parts.append(f"→ {blk.get('name')}")
    text = red.text(clean("\n\n".join(parts)))
    chunk, nxt = _page(text, offset, trace)
    return {"text": chunk, "offset": int(offset or 0), "next": nxt, "bytes": len(text)}


def _result_shown(trace, b: dict, red: Redactor) -> str:
    """A ``tool_result`` block's text as a chat or a turn's input shows it: the contents of a
    credentials file hidden, as the tool's own Output hides them."""
    from .model import span_id
    sp = trace.spans.get(span_id(trace.id, f"tool:{b.get('tool_use_id')}"))
    hide = hidden(trace, sp, red)
    return red.contents_of(hide) if hide is not None else result_text(b.get("content"))


def user_text(trace, ref: dict, red: Redactor, offset: int = 0) -> dict:
    obj = _line(trace, ref)
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        text = content
    else:
        rows = []
        for b in content or []:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                rows.append("[tool result] " + _result_shown(trace, b, red)[:4000])
            elif isinstance(b, dict) and b.get("type") == "text":
                rows.append(str(b.get("text") or ""))
        text = "\n\n".join(rows)
    text = red.text(clean(text))
    chunk, nxt = _page(text, offset, trace)
    return {"text": chunk, "offset": int(offset or 0), "next": nxt, "bytes": len(text)}


def chat(trace, sp: Span, red: Redactor, offset: int = 0) -> dict:
    """The session's conversation as messages: ``you`` (a prompt), ``claude`` (text,
    thinking folded), tool calls and results inline (results cut at 4 KB: the tool's span has
    the whole). For a turn, ``focus`` is the index of its first message."""
    sess = sp
    while sess is not None and sess.kind != "session":
        sess = trace.spans.get(sess.parent) if sess.parent else None
    if sess is None:
        raise PayloadError(404, "this span is not in a session")
    path = trace.path_of(sess.source["file"]) if sess.source else None
    if path is None or not path.is_file():
        raise PayloadError(410, "the session's file is not there any more")
    from .model import span_id
    msgs: list[dict] = []
    focus = None
    size = 0
    for _, _, o in lines(path, 0):
        if o is None or o.get("parent_tool_use_id"):
            continue
        t = o.get("type")
        msg = o.get("message") or {}
        ts = o.get("timestamp")
        if t == "assistant":
            tid = span_id(trace.id, f"turn:{msg.get('id')}")
            if sp.kind == "turn" and tid == sp.id and focus is None:
                focus = len(msgs)
            for b in msg.get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text":
                    msgs.append({"role": "claude", "kind": "text", "text": b.get("text") or "",
                                 "ts": ts, "span": tid})
                elif b.get("type") == "thinking":
                    msgs.append({"role": "claude", "kind": "thinking",
                                 "text": b.get("thinking") or "", "ts": ts, "span": tid})
                elif b.get("type") == "tool_use":
                    from .readers.stream_json import tool_preview
                    msgs.append({"role": "claude", "kind": "tool_call", "tool": b.get("name"),
                                 "text": tool_preview(str(b.get("name")), b.get("input")),
                                 "ts": ts, "span": span_id(trace.id, f"tool:{b.get('id')}")})
        elif t == "user":
            c = msg.get("content")
            if isinstance(c, str):
                msgs.append({"role": "you", "kind": "text", "text": c, "ts": ts})
            for b in c if isinstance(c, list) else []:
                if isinstance(b, dict) and b.get("type") == "tool_result":
                    tsid = span_id(trace.id, f"tool:{b.get('tool_use_id')}")
                    text = _result_shown(trace, b, red)
                    msgs.append({"role": "tool", "kind": "tool_result",
                                 "text": text[:4000], "cut": len(text) > 4000,
                                 "is_error": bool(b.get("is_error")), "ts": ts, "span": tsid})
                elif isinstance(b, dict) and b.get("type") == "text":
                    msgs.append({"role": "you", "kind": "text", "text": b.get("text") or "",
                                 "ts": ts})
        elif t == "result" and o.get("result"):
            msgs.append({"role": "claude", "kind": "result", "text": str(o.get("result")),
                         "ts": None})
    start = int(offset or 0)
    if not offset and focus is not None and focus > 40:
        start = focus - 5                              # the page that holds the turn
    page, size = [], 0
    i = start
    while i < len(msgs) and size < PAGE:
        m = dict(msgs[i])
        m["text"] = red.text(clean(str(m.get("text") or "")))
        size += len(m["text"]) + 64
        m["i"] = i
        page.append(m)
        i += 1
    return {"messages": page, "offset": start, "next": i if i < len(msgs) else None,
            "total": len(msgs), "focus": focus}


def diff(trace, sp: Span, red: Redactor) -> dict:
    """An edit's hunks (its ``structuredPatch``, else old and new strings) or a write's lines
    as a new file."""
    tool = sp.attrs.get("tool")
    if tool not in WRITERS:
        raise PayloadError(404, "only an edit or a write has a diff")
    fp = sp.attrs.get("file_path") or ""
    hide = _secret(sp, red)
    if hide is not None:
        return {"file_path": red.text(fp), "hunks": [], "added": None, "removed": None,
                "hidden": red.contents_of(hide)}
    obj = _line(trace, sp.inputs)
    inp = (_block(obj, sp.inputs.get("block"), "tool_use") or {}).get("input") or {}
    hunks: list[dict] = []
    new_file = False
    res = None
    if sp.outputs and sp.outputs.get("from") is not None:
        try:
            ro = _line(trace, sp.outputs)
            res = ro.get("toolUseResult") or ro.get("tool_use_result")
        except PayloadError:
            res = None
    if isinstance(res, dict) and isinstance(res.get("structuredPatch"), list) \
            and res["structuredPatch"]:
        for h in res["structuredPatch"]:
            hunks.append({"header": f"@@ -{h.get('oldStart')},{h.get('oldLines')} "
                                    f"+{h.get('newStart')},{h.get('newLines')} @@",
                          "lines": [str(x) for x in h.get("lines") or []]})
    elif tool == "Write" and isinstance(inp.get("content"), str):
        new_file = True
        hunks.append({"header": "new file",
                      "lines": ["+" + x for x in inp["content"].split("\n")]})
    else:
        edits = inp.get("edits") if isinstance(inp.get("edits"), list) else [inp]
        for e in edits:
            if not isinstance(e, dict):
                continue
            old = str(e.get("old_string") or e.get("old_source") or "")
            new = str(e.get("new_string") or e.get("new_source") or "")
            hunks.append({"header": "edit",
                          "lines": ["-" + x for x in old.split("\n")] +
                                   ["+" + x for x in new.split("\n")]})
    add = sum(1 for h in hunks for x in h["lines"] if x.startswith("+"))
    rem = sum(1 for h in hunks for x in h["lines"] if x.startswith("-"))
    size = 0
    out_h = []
    for h in hunks:
        if size > PAGE:
            out_h.append({"header": "…", "lines": ["(the rest is longer than 64 KB)"]})
            break
        ls = [red.text(clean(x)) for x in h["lines"]]
        size += sum(len(x) for x in ls)
        out_h.append({"header": h["header"], "lines": ls})
    return {"file_path": red.text(fp), "hunks": out_h, "added": add, "removed": rem,
            "new_file": new_file}


def payload(trace, span: str, part: str, offset: int = 0, red: Redactor | None = None
            ) -> dict:
    """``{…the part…, "redactions": [{kind, n}]}`` for one span."""
    if part not in PARTS:
        raise PayloadError(400, f"part must be one of {', '.join(PARTS)}")
    sp = trace.spans.get(span)
    if sp is None:
        raise PayloadError(404, "no such span in this trace")
    red = red or Redactor()
    held = (getattr(trace, "inline", None) or {}).get(sp.id)
    if held is not None and part in ("input", "output", "chat"):
        # a call's request and answer as its host kept them (an afk trace): no file to read
        if part == "chat":
            msgs = [{"role": "you", "kind": "text", "text": red.text(clean(held["input"])),
                     "ts": None, "i": 0},
                    {"role": "claude", "kind": "text", "text": red.text(clean(held["output"])),
                     "ts": None, "i": 1, "span": sp.id}]
            out = {"messages": msgs, "offset": 0, "next": None, "total": 2, "focus": 1}
        else:
            text = red.text(clean(held[part]))
            chunk, nxt = _page(text, offset, trace)
            out = {"text": chunk, "offset": int(offset or 0), "next": nxt, "bytes": len(text)}
        out["redactions"] = red.report()
        return out
    if part == "chat":
        out = chat(trace, sp, red, offset)
    elif part == "diff":
        out = diff(trace, sp, red)
    elif part == "input":
        if sp.kind in ("tool", "subagent"):
            out = tool_input(trace, sp, red)
        elif sp.kind == "turn" and sp.inputs:
            out = user_text(trace, sp.inputs, red, offset)
        else:
            out = {"fields": [{"key": k, "value": red.text(json.dumps(v, ensure_ascii=False)
                                                           if not isinstance(v, str) else v)}
                              for k, v in sp.attrs.items()]}
    else:
        if sp.kind in ("tool", "subagent"):
            out = tool_output(trace, sp, red, offset)
        elif sp.kind == "turn":
            out = turn_text(trace, sp, red, offset)
        else:
            out = {"text": red.text(sp.preview or ""), "next": None}
    out["redactions"] = red.report()
    return out


def raw_lines(trace, sp: Span) -> list[tuple[str, int, str]]:
    """``(file, byte from, the line)`` of the span's own lines, unredacted: the CLI's
    ``--raw`` only, at the owner's own terminal (decision D-3)."""
    out = []
    for ref in (sp.source, sp.inputs, sp.outputs):
        if not ref or ref.get("from") is None:
            continue
        p: Path = trace.path_of(ref["file"])
        to = ref.get("to")
        if to is None:
            continue
        with open(p, "rb") as f:
            f.seek(ref["from"])
            out.append((ref["file"], ref["from"],
                        f.read(to - ref["from"]).decode(errors="replace").rstrip("\n")))
    seen, uniq = set(), []
    for x in out:
        if (x[0], x[1]) not in seen:
            seen.add((x[0], x[1]))
            uniq.append(x)
    return uniq
