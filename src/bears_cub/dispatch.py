"""How a host→cub request reaches its handler and how the handler's answer becomes the result
(protocol). The runner (over the pipe) and ``FakeHost`` (in-process) both call
``run_request``, so a cub behaves the same under test and under Kranto."""

from __future__ import annotations

from .cub import Cub
from .errors import INVALID_PARAMS, METHOD_NOT_FOUND, HostError

HOST_METHODS = ("job.run", "event.deliver", "action.run", "read.run", "stage.run")


class DispatchError(HostError):
    """The request could not reach a handler (not the handler's own failure)."""


def _handler(table: dict, name, what: str):
    fn = table.get(name) if isinstance(name, str) else None
    if fn is None:
        raise DispatchError(METHOD_NOT_FOUND, f"no {what} handler {name!r} in this cub")
    return fn


def subject_fields(cub_id: str, fields: dict, subject: dict | None) -> dict:
    """An action run on one of the cub's objects gets the object's id as a field named after
    the subject without the cub's prefix: subject ``newsletter_issue`` 7 → ``issue_id: 7``."""
    out = dict(fields or {})
    if isinstance(subject, dict) and subject.get("kind"):
        name = str(subject["kind"]).removeprefix(cub_id + "_")
        out.setdefault(f"{name}_id", subject.get("id"))
    return out


def run_request(cub: Cub, cub_id: str, method: str, params: dict, ctx) -> dict:
    """The result of one host→cub request; a handler's own exception propagates (the runner
    answers it with -32020)."""
    if method == "job.run":
        out = _handler(cub.jobs, params.get("method"), "job")(ctx)
        out = out if isinstance(out, dict) else {}
        result = {"status": out.get("status", "ok")}
        if out.get("summary") is not None:
            result["summary"] = out["summary"]
        if out.get("line") is not None:
            result["line"] = str(out["line"])[:200]
        return result
    if method == "event.deliver":
        fn = cub.events.get(params.get("method")) or cub.event_kinds.get(params.get("kind"))
        if fn is None:
            raise DispatchError(METHOD_NOT_FOUND, f"no event handler for {params.get('kind')}")
        batch = params.get("events") or []
        n = fn(ctx, batch)
        if not batch:
            return {"handled": 0}
        if n is None or n >= len(batch):
            return {"handled": int(batch[-1]["id"])}
        return {"handled": int(batch[n - 1]["id"]) if n > 0 else 0}
    if method == "action.run":
        fn = _handler(cub.actions, params.get("method"), "action")
        out = fn(ctx, subject_fields(cub_id, params.get("fields") or {}, params.get("subject")))
        out = out if isinstance(out, dict) else {}
        result: dict = {"ok": bool(out.get("ok", True))}
        if out.get("say") is not None:
            result["say"] = str(out["say"])[:200]
        if out.get("refresh"):
            result["refresh"] = [str(x) for x in out["refresh"]]
        return result
    if method == "read.run":
        out = _handler(cub.reads, params.get("name"), "read")(ctx, dict(params.get("params")
                                                                         or {}))
        if not isinstance(out, dict):
            raise DispatchError(INVALID_PARAMS, "a read answers an object")
        return out
    if method == "stage.run":
        out = _handler(cub.stages, params.get("id"), "stage")(ctx, params)
        return out if isinstance(out, dict) else {"status": "ok", "line": ""}
    raise DispatchError(METHOD_NOT_FOUND, f"no method {method}")
