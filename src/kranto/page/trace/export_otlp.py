"""A trace as OpenTelemetry spans (decision D-10): OTLP/HTTP JSON, sent by a
command (``kranto trace export <trace> --otlp <url>``), never in the background, to the URL the
owner gives (``trace.export.otlp_url`` by default, empty: nothing is sent) and nowhere else.

The GenAI semantic conventions name the spans and their attributes: a run and a stage are
``invoke_workflow``, a session ``invoke_agent claude-code``, a turn ``chat <model>`` (CLIENT), a
tool ``execute_tool <name>``, a sub-agent ``invoke_agent <type>``, a one-shot call ``chat`` with
its cost as ``<prefix>.usd`` (the prefix is ``legacy.TRACE_PREFIX``: one series across the rename) (OTel has no cost attribute); a hook and an event become events on
their span. Content (a turn's messages, a tool's arguments and result) is opt-in, as the
conventions make it: only with ``content=True``, and then redacted like everything a trace
shows (``redact.py``, with ``share=True``: no host, login or home). The trace id is a UUIDv5 of
Kranto's trace id, so exporting the same trace twice sends the same ids."""
from __future__ import annotations

import json
import urllib.request
import uuid

from kranto import legacy

from .payload import PayloadError, payload
from .redact import Redactor

_P = legacy.TRACE_PREFIX   # the attribute keys keep one series across the rename
_KEY_TRACE, _KEY_KIND, _KEY_STAGE, _KEY_USD = (f"{_P}.{k}" for k in ("trace", "kind", "stage", "usd"))

INTERNAL, CLIENT = 1, 3
NS = uuid.UUID("6f1d5b2e-7a3c-5e8f-9b0d-1c2a3b4c5d6e")


def trace_id(tid: str) -> str:
    return uuid.uuid5(NS, tid).hex


def _v(x) -> dict:
    if isinstance(x, bool):
        return {"boolValue": x}
    if isinstance(x, int):
        return {"intValue": str(x)}
    if isinstance(x, float):
        return {"doubleValue": x}
    if isinstance(x, (list, tuple)):
        return {"arrayValue": {"values": [_v(i) for i in x]}}
    return {"stringValue": str(x)}


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": _v(v)} for k, v in d.items() if v not in (None, "", [], {})]


def _ns(t) -> str:
    return str(int(float(t) * 1e9)) if t is not None else "0"


def _name_kind(sp) -> tuple[str, int, dict]:
    a = sp.attrs
    if sp.kind in ("run", "stage"):
        name = sp.name if sp.kind == "stage" else a.get("flow") or a.get("pipeline") or "v5"
        return f"invoke_workflow {name}", INTERNAL, {"gen_ai.operation.name": "invoke_workflow",
                                                     "gen_ai.workflow.name": name}
    if sp.kind == "session":
        return "invoke_agent claude-code", INTERNAL, {
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "claude-code",
            "gen_ai.agent.version": a.get("claude_code_version"),
            "gen_ai.conversation.id": a.get("session_id"), "gen_ai.provider.name": "anthropic",
            "gen_ai.request.model": a.get("model")}
    if sp.kind == "turn":
        model = a.get("model") or ""
        return f"chat {model}".strip(), CLIENT, {
            "gen_ai.operation.name": "chat", "gen_ai.request.model": model or None,
            "gen_ai.response.model": model or None, "gen_ai.response.id": a.get("message_id"),
            "gen_ai.response.finish_reasons": [a["stop_reason"]] if a.get("stop_reason") else None}
    if sp.kind == "subagent":
        return f"invoke_agent {a.get('agent_type') or 'agent'}", INTERNAL, {
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": a.get("agent_type"),
            "gen_ai.agent.id": a.get("call_id")}
    if sp.kind == "tool":
        mcp = a.get("type") == "extension"
        extra = {"mcp.method.name": "tools/call"} if mcp else {}
        return f"execute_tool {a.get('tool') or sp.name}", INTERNAL, {
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": a.get("tool") or sp.name,
            "gen_ai.tool.call.id": a.get("call_id"),
            "gen_ai.tool.type": "extension" if mcp else "function", **extra}
    if sp.kind == "call":
        return f"chat {a.get('model') or ''}".strip(), CLIENT, {
            "gen_ai.operation.name": "chat", "gen_ai.request.model": a.get("model")}
    return sp.name, INTERNAL, {}


def spans(trace, content: bool = False) -> dict:
    """The OTLP/HTTP JSON body (``resourceSpans``) for a read trace."""
    red = Redactor(share=True)
    tid = trace_id(trace.id)
    out = []
    by = trace.spans
    for sp in sorted(by.values(), key=lambda s: s.pos):
        if sp.kind in ("hook", "event"):
            continue
        name, kind, attrs = _name_kind(sp)
        t = sp.tokens or {}
        attrs.update({"gen_ai.usage.input_tokens": (t.get("in", 0) + t.get("cache_read", 0)
                                                    + t.get("cache_write", 0)) if t else None,
                      "gen_ai.usage.cache_read.input_tokens": t.get("cache_read") or None,
                      "gen_ai.usage.cache_write.input_tokens": t.get("cache_write") or None,
                      "gen_ai.usage.output_tokens": t.get("out") if t else None,
                      "gen_ai.usage.reasoning.output_tokens": t.get("thinking") or None,
                      _KEY_TRACE: trace.id, _KEY_KIND: sp.kind, _KEY_STAGE: sp.stage})
        if sp.usd is not None and sp.usd_kind == "exact":
            attrs[_KEY_USD] = float(sp.usd)
        if sp.error:
            attrs["error.type"] = str(sp.error.get("type") or "error")
        if content and sp.kind in ("tool", "subagent", "turn", "call"):
            for part, key in (("input", "gen_ai.tool.call.arguments" if sp.kind != "turn"
                               else "gen_ai.input.messages"),
                              ("output", "gen_ai.tool.call.result" if sp.kind != "turn"
                               else "gen_ai.output.messages")):
                try:
                    p = payload(trace, sp.id, part, red=red)
                except PayloadError:
                    continue
                text = p.get("text") if "text" in p else json.dumps(p.get("fields") or [])
                if text:
                    attrs[key] = text[:32_000]
        events = []
        for e in sp.events:
            events.append({"timeUnixNano": _ns(e.get("ts")), "name": str(e.get("name")),
                           "attributes": _attrs({k: red.text(v) if isinstance(v, str) else v
                                                 for k, v in (e.get("attrs") or {}).items()})})
        for ch in by.values():                      # hooks and events: events on their span
            if ch.parent == sp.id and ch.kind in ("hook", "event"):
                events.append({"timeUnixNano": _ns(ch.start), "name": red.text(ch.name),
                               "attributes": _attrs({_KEY_KIND: ch.kind,
                                                     "duration_ms": ch.attrs.get("ms"),
                                                     "denied": ch.attrs.get("denied")})})
        out.append({"traceId": tid, "spanId": sp.id,
                    "parentSpanId": sp.parent if sp.parent in by else "",
                    "name": red.text(name), "kind": kind,
                    "startTimeUnixNano": _ns(sp.start),
                    "endTimeUnixNano": _ns(sp.end if sp.end is not None else sp.start),
                    "attributes": _attrs(attrs), "events": events,
                    "status": {"code": 2 if sp.status == "error" else 1 if sp.status == "ok"
                               else 0}})
    return {"resourceSpans": [{
        "resource": {"attributes": _attrs({"service.name": "kranto", _KEY_TRACE: trace.id})},
        "scopeSpans": [{"scope": {"name": _KEY_TRACE}, "spans": out}]}]}


def send(body: dict, url: str, timeout: float = 30) -> int:
    """POST the body to ``<url>/v1/traces`` (OTLP/HTTP JSON); the HTTP status."""
    target = url.rstrip("/")
    if not target.endswith("/v1/traces"):
        target += "/v1/traces"
    req = urllib.request.Request(target, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status
