"""Search every payload of one trace ("Search every payload…", 
``api/trace/search``): the second step after the search over what the trace holds in memory (a
call's input to 4 KB, its output to 8 KB, the previews). This one reads the trace's own files:
every tool call's whole input and output, and every turn's words, thinking included, and the
owner's words before it.

Bounded: only the byte ranges the trace's spans point at, one open per file and in order; a
line bigger than ``trace.payload_max_mb`` is skipped; at most ``MAX_HITS`` spans. The words are
matched in the **redacted** text, so a search never says what redaction hides, and a tool whose
output is a credentials file's contents is never searched (``payload.hidden``). An afk trace's
calls are searched where they are held (``inline``)."""
from __future__ import annotations

import json

from .payload import _block, clean, hidden
from .readers.stream_json import result_text
from .redact import Redactor

MAX_HITS = 500
SNIP = 240


def _ranges(t) -> dict[str, list[tuple[int, int, str, str]]]:
    """``file -> [(from, to, span id, part)]``: each tool's input and output line, each turn's
    own lines and the owner's line before it."""
    out: dict[str, list[tuple[int, int, str, str]]] = {}

    def add(ref: dict | None, a, b, sid: str, part: str) -> None:
        if ref and ref.get("file") and a is not None and b is not None:
            out.setdefault(ref["file"], []).append((int(a), int(b), sid, part))
    for sp in t.spans.values():
        if sp.kind in ("tool", "subagent"):
            for part, ref in (("input", sp.inputs), ("output", sp.outputs)):
                add(ref, (ref or {}).get("from"), (ref or {}).get("to"), sp.id, part)
        elif sp.kind == "turn":
            o = sp.outputs or {}
            for a, b in o.get("lines") or []:
                add(o, a, b, sp.id, "output")
            i = sp.inputs or {}
            add(i, i.get("from"), i.get("to"), sp.id, "input")
    return out


def _text(obj: dict, sp, part: str) -> str:
    """The words of ``part`` of ``sp`` in its line ``obj``, as the page's tabs show them."""
    if sp.kind in ("tool", "subagent"):
        if part == "input":
            b = _block(obj, (sp.inputs or {}).get("block"), "tool_use") or {}
            inp = b.get("input")
            return json.dumps(inp, ensure_ascii=False) if inp is not None else ""
        res = obj.get("toolUseResult") or obj.get("tool_use_result")
        if isinstance(res, dict) and isinstance(res.get("stdout"), str):
            return (res.get("stdout") or "") + "\n" + (res.get("stderr") or "")
        b = _block(obj, (sp.outputs or {}).get("block"), "tool_result") or {}
        return result_text(b.get("content"))
    content = (obj.get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    words = []
    for blk in content or []:                   # a tool's result is its own span's, not the turn's
        if isinstance(blk, dict) and blk.get("type") == "text":
            words.append(str(blk.get("text") or ""))
        elif isinstance(blk, dict) and blk.get("type") == "thinking":
            words.append(str(blk.get("thinking") or ""))
    return "\n".join(words)


def _snip(text: str, at: int) -> str:
    a = max(0, at - SNIP // 3)
    s = " ".join(text[a:a + SNIP].split())
    return ("…" if a else "") + s + ("…" if a + SNIP < len(text) else "")


def search(t, q: str, max_bytes: int | None = None, limit: int = MAX_HITS) -> dict:
    """``{hits: [{span, part, preview}] in tree order, more, scanned}`` for the words of ``q``
    (all of them, any case) in the trace's payloads."""
    words = [w.lower() for w in str(q or "").split()][:8]
    if not words:
        return {"hits": [], "more": False, "scanned": 0}
    red = Redactor()
    # a quick look at the raw line first: a word that is plain ASCII with no quote or backslash
    # is in the line's bytes as it is in its text, so a line without it is skipped unread
    quick = [w for w in words if w.isascii() and '"' not in w and "\\" not in w]
    cap = max_bytes or getattr(t, "max_bytes", 2 * 1024 * 1024)
    found: dict[str, dict] = {}
    scanned = 0
    more = False

    def check(sid: str, part: str, text: str) -> bool:
        nonlocal more
        sp = t.spans[sid]
        low = text.lower()
        if not all(w in low for w in words):
            return False
        shown = red.text(clean(text))                 # matched as the page would show it
        sl = shown.lower()
        if not all(w in sl for w in words):
            return False
        if part == "output" and sp.kind in ("tool", "subagent") and hidden(t, sp, red):
            return False
        if len(found) >= limit:
            more = True
            return True
        found[sid] = {"span": sid, "part": part, "preview": _snip(shown, sl.find(words[0]))}
        return True

    for sid, held in (getattr(t, "inline", None) or {}).items():
        for part in ("input", "output"):
            if sid in t.spans and sid not in found and not more:
                scanned += len(held.get(part) or "")
                check(sid, part, str(held.get(part) or ""))
    for rel, rows in _ranges(t).items():
        if more:
            break
        try:
            path = t.path_of(rel)
            f = open(path, "rb")
        except (OSError, ValueError):
            continue
        lines: dict[tuple[int, int], list[tuple[str, str]]] = {}   # a line read once for all
        for a, b, sid, part in rows:                                 # the spans it holds
            lines.setdefault((a, b), []).append((sid, part))
        with f:
            for (a, b), who in sorted(lines.items()):
                who = [(sid, part) for sid, part in who if sid not in found]
                if not who or b - a > cap or b <= a:
                    continue
                f.seek(a)
                raw = f.read(b - a)
                scanned += len(raw)
                if quick and not all(w in raw.decode(errors="replace").lower() for w in quick):
                    continue
                try:
                    obj = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                for sid, part in who:
                    if sid not in found:
                        check(sid, part, _text(obj, t.spans[sid], part))
                    if more:
                        break
                if more:
                    break
    hits = sorted(found.values(), key=lambda h: t.spans[h["span"]].pos)
    return {"hits": hits, "more": more, "scanned": scanned}
