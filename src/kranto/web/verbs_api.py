"""The verbs' door (``core.verbs``): one way in for every caller.

``GET /api/verbs``: every verb, with what the ladder says for an assistant. ``POST
/api/verbs/<kind> {subject?, fields?, client?}``: run one. The order is the registry's: the
caller's door (its token, never the body), then the ladder (for every caller but the owner
pressing), then the route that performs it, called in this process exactly as the page calls
it. Under **Do it** the route runs and the answer carries the run, the page the change shows
on and the row to mark; under **Ask me in the UI** nothing happens: the press is *prepared*
(``GET /api/prepared``: it waits on its page and in Needs you until the owner presses it,
``POST /api/prepared/<uuid>/press``, or dismisses it); under **Never** the answer says which
setting and where. A model's ``confirm: true`` is not read: the confirm a route needs is the
owner's ladder choice (Do it) or the owner's own press.

Every verb an assistant runs or prepares is a run in Activity (kind ``verb``), with who did it
(``by``: ``console:claude``, ``mcp:codex``) and the subject, so the page can mark it.

``GET /api/settings/assistant`` and ``POST /api/settings/assistant {ladder}``: the ladder (the
owner's only: an assistant never changes what it may do).
"""

from __future__ import annotations

import json
import logging
import threading
import uuid as uuid_mod
from dataclasses import replace
from datetime import timedelta
from typing import Any
from urllib.parse import quote, urlencode

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Match, Route

from .. import config as config_mod
from ..core import verbs
from ..store import iso, utcnow
from ..stored.prepared import PreparedFields, VerbsMirror
from .auth import IDENTITY

log = logging.getLogger(__name__)

PREPARED_HOURS = 24
RECENT_FILE = "verbs.json"
RECENT_KEEP = 30
_MIRROR_LOCK = threading.Lock()
MAX_FIELDS_BYTES = 20_000


def _error(error: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"error": error, **extra}, status_code=status)


_SMALL = {"a", "an", "the", "kranto", "kranto'", "your", "this"}


def button_words(title: str) -> str:
    """A verb's title as a button: "File a Kranto issue" → "File issue", "Add a topic" → "Add
    topic", "Turn usage reports off" stays; a long title keeps its first word."""
    words = [w for w in str(title or "").rstrip("…. ").split() if w.lower() not in _SMALL]
    if not words:
        return "Approve"
    return " ".join(words) if len(words) <= 4 else words[0]


def why_of(status: int, answer: Any, title: str = "") -> str:
    """A route's refusal in words, for every caller (PAR: a failed verb reached the assistant
    as "b.publish: 409"): its ``error`` (or ``message``), an old page's text without its tags,
    or a sentence saying that Kranto gave none. Never a response body."""
    import re
    why: Any = None
    if isinstance(answer, dict):
        why = answer.get("error") or answer.get("message") or answer.get("text")
    elif isinstance(answer, str):
        why = answer
    if isinstance(why, (dict, list)):
        why = None
    text = " ".join(re.sub(r"<[^>]+>", " ", str(why or "")).split())
    # words that quote a response body keep the words before it (a model's error quoted its
    # provider's JSON answer)
    text = re.split(r"\s*[{\[]\s*\"", text, maxsplit=1)[0].rstrip(" :")[:300]
    if not text or text.startswith(("{", "[")):
        what = f"{title} did not happen" if title else "it did not happen"
        return f"{what}: Kranto answered {status} and gave no reason"
    return text


class VerbError(Exception):
    """A verb refused; ``refusal`` is its kind for the usage events (never its words)."""

    def __init__(self, message: str, status: int = 400, refusal: str = "fields", **extra: Any):
        super().__init__(message)
        self.status, self.extra, self.refusal = status, extra, refusal


def count(verb: str, door: str | None, by: str | None, outcome: str, rung: str,
          started: float, refusal: str | None = None) -> None:
    """One verb call in the usage events (``telemetry.assistant``: detailed only). Never
    raises."""
    import time

    from ..telemetry import assistant
    assistant.note_verb(verb, door or "ui", assistant.client_of(by), outcome, rung,
                        (time.perf_counter() - started) * 1000, refusal=refusal)


def rung_of(cfg, verb: verbs.Verb, door: str | None) -> str:
    """The ladder's rung in force for this caller: the owner pressing, or the choice (a lock
    as ``lock``)."""
    if door in verbs.OWNER_DOORS:
        return "owner"
    c = verbs.choice_for(cfg, verb)
    return "lock" if c.locked else c.choice


def check_fields(verb: verbs.Verb, fields: Any) -> dict[str, Any]:
    """The fields a caller gave, checked against the verb's: known names, the right types."""
    if fields is None:
        fields = {}
    if not isinstance(fields, dict):
        raise VerbError("fields is an object of the verb's fields")
    if len(json.dumps(fields, default=str)) > MAX_FIELDS_BYTES:
        raise VerbError(f"fields are over {MAX_FIELDS_BYTES} bytes")
    known = {f.name: f for f in verb.fields}
    unknown = sorted(set(fields) - set(known))
    if unknown:
        raise VerbError(f"{verb.kind} has no field {', '.join(unknown)} (its fields: "
                        f"{', '.join(known) or 'none'})")
    out: dict[str, Any] = {}
    for name, value in fields.items():
        f = known[name]
        if value is None:
            out[name] = None
            continue
        if not _typed(f, value):
            want = f"one of {', '.join(f.choices)}" if f.choices and f.type in (
                "enum", "line", "text") else f.type
            raise VerbError(f"{verb.kind}.{name} is {want}", refusal="fields")
        if isinstance(value, str) and f.type in ("line", "text") and value.strip():
            n = len(value.strip() if f.type == "text" else " ".join(value.split()))
            if f.max is not None and n > f.max:
                raise VerbError(f"the {name} is over {f.max} characters", refusal="fields")
            if f.min and n < f.min:
                raise VerbError(f"the {name} needs at least {f.min} characters",
                                refusal="fields")
        if f.type in ("int", "number", "usd") and (
                (f.lo is not None and value < f.lo) or (f.hi is not None and value > f.hi)):
            raise VerbError(f"{verb.kind}.{name} is from {f.lo:g} to {f.hi:g}"
                            if f.lo is not None and f.hi is not None else
                            f"{verb.kind}.{name} is out of its range", refusal="fields")
        out[name] = value
    # blank words and an empty list are missing, as every press reads them (PAR)
    missing = [f.name for f in verb.fields if f.required and _blank(out.get(f.name))]
    if missing:
        raise VerbError(f"{verb.kind} needs {', '.join(missing)}")
    if verb.one_of and all(_blank(out.get(n)) for n in verb.one_of):
        raise VerbError(f"{verb.kind} needs {' or '.join(verb.one_of)}")
    return out


def _blank(v: Any) -> bool:
    return v is None or (isinstance(v, str) and not v.strip()) or v == []


def precheck(rt, verb: verbs.Verb, sid: Any, fields: dict) -> None:
    """The route's own check of what it is given, before the press (``PRECHECKS``: the same
    functions the routes call), so a press is prepared only when its press would take it."""
    if verb.kind.startswith("f."):
        _feature_on(rt, verb)
    fn = PRECHECKS.get(verb.kind)
    if fn is None:
        return
    try:
        fn(rt, sid, fields)
    except ValueError as exc:
        raise VerbError(str(exc), refusal="fields") from None


def _feature_on(rt, verb: verbs.Verb) -> None:
    """A feature that is off refuses its actions (``features_api.act``): said before a press is
    prepared, in the same words (PAR: Invest's and Radar's waited, then said "is off")."""
    from ..core import registry
    try:
        f = registry.by_id(str(dict(verb.fixed).get("feature")))
    except KeyError:
        return
    if not registry.enabled(rt.cfg, f):
        raise VerbError(f"{f.title} is off", 409, refusal="subject")


def _feedback(rt, sid, f) -> None:
    from .. import feedback
    feedback.validate(dict(f))


def _preset(rt, sid, f) -> None:
    if f.get("id") is not None:                # a proposal's review: no preset
        return
    from ..sources import catalog
    catalog.get(str(f.get("preset") or ""))


def _topic_sources(rt, sid, f) -> None:
    if not f.get("add") and not f.get("remove"):
        raise ValueError("send add or remove")


def _cubs_setting(rt, sid, f) -> None:
    from ..core.cubs import registry
    from ..core.cubs import settings as cub_settings
    key = str(f.get("key") or "")
    parts = key.split(".")
    r = registry.latest(rt.store, parts[1]) if len(parts) == 3 else None
    cub_settings.checked(key, f.get("value"), trust=r["trust"] if r else None)


def _feature_setting(rt, sid, f) -> None:
    from ..core import settings
    settings.checked(str(sid), str(f.get("key") or ""), f.get("value"))


def _explain(rt, sid, f) -> None:
    # the route reads a cluster when one is named (its id, a number), else the observation
    c = f.get("cluster")
    if c is not None:
        try:
            int(str(c).strip())
        except ValueError:
            raise ValueError("say which observation or cluster") from None
    elif f.get("observation_id") is None:
        raise ValueError("say which observation or cluster")


def _update_settings(rt, sid, f) -> None:
    if f.get("quiet_window") is not None:
        try:
            config_mod.quiet_window(str(f["quiet_window"]))
        except ValueError as exc:
            raise ValueError(f"update.quiet_window: {exc}") from None


def _telemetry(rt, sid, f) -> None:
    if f.get("dismiss") is True:
        return                                  # ends Today's reminder, whatever the mode
    if f.get("mode") not in verbs.TELEMETRY_MODES:
        raise ValueError(f"mode is one of {', '.join(verbs.TELEMETRY_MODES)}")


def _model(rt, sid, f) -> None:
    from .settings_api import MODEL_NAME, ROLES
    role = str(f.get("role") or "")
    if role not in ROLES:
        raise ValueError(f"no such role: {role or '(none)'} (judge or reason)")
    if not MODEL_NAME.fullmatch(str(f.get("model") or "").strip()):
        raise ValueError("a model is a name such as anthropic/claude-haiku-5.5 or "
                         "claude-haiku-5-5")
    gate = f.get("gate")
    if gate is not None and (role != "judge" or not 0 < gate <= 1):
        raise ValueError("the gate is the judge's: a signal above 0 and at most 1")


def _seen(rt, sid, f) -> None:
    if f.get("at") is None:
        return
    from datetime import datetime
    try:
        datetime.fromisoformat(str(f["at"]).strip().replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("at must be an ISO time, or left out for now") from None


def _topic_edit(rt, sid, f) -> None:
    for k in ("name", "description"):
        if k in f and f[k] is not None and _blank(f[k]):
            raise ValueError("a topic needs a name and a description")


def _release(rt, sid, f) -> None:
    import re
    to = f.get("to")
    if to is not None and not re.fullmatch(r"v\d+\.\d+\.\d+(-rc\d+|-dev\d+)?", str(to)):
        raise ValueError("to must be a release tag, vX.Y.Z or a nightly build's vX.Y.0-devN")


def _prompt_preview(rt, sid, f) -> None:
    s = f.get("subject")
    if s is not None:
        try:
            int(str(s))
        except ValueError:
            raise ValueError(f"{s!r} is not an id") from None


def _prompt_save(rt, sid, f) -> None:
    from .. import prompts  # prompts.save's own checks, in its order
    try:
        e = prompts.entry(str(sid))
    except (KeyError, LookupError, prompts.PromptError):
        return                              # no such prompt: the press says so (404)
    adds = f.get("additions")
    if isinstance(adds, str) and len(adds) > prompts.MAX_ADDITIONS:
        raise ValueError(f"additions are at most {prompts.MAX_ADDITIONS} characters")
    t = f.get("template")
    if t is None:
        return
    if e.checker:
        raise ValueError(f"{e.title} is a checker: additions only, its rules can't be replaced")
    probs = prompts.check_template(e, str(t))
    if probs:
        raise ValueError("not saved: " + "; ".join(probs))


def _post_write(rt, sid, f) -> None:
    """Write a post's own checks (its route's): what it is about, and a model key. With no key
    an assistant's post.write is refused at once in those words, never prepared and then
    "done" (4, Codex 1)."""
    from .post_api import plan_write, preflight
    plan_write(f.get("about"), f.get("as"))
    preflight(rt)


# the routes' own checks of their input, run before a press is prepared (and before an
# assistant's run): the suite's validation parity test keeps each in step with its route
PRECHECKS = {"feedback.add": _feedback, "post.write": _post_write,
             "source.add": _preset, "source.preview": _preset,
             "topic.sources": _topic_sources, "cubs.settings": _cubs_setting,
             "feature.setting": _feature_setting,
             "library.explain": _explain, "settings.models": _model, "today.seen": _seen,
             "topic.edit": _topic_edit, "update.apply": _release,
             "prompt.preview": _prompt_preview, "prompt.save": _prompt_save,
             "settings.telemetry": _telemetry, "update.settings": _update_settings}


def _typed(f: verbs.Field, v: Any) -> bool:
    """Whether ``v`` is of the field's type (``core.verbs.FIELD_TYPES``)."""
    def whole(x: Any) -> bool:
        return isinstance(x, int) and not isinstance(x, bool)
    if f.type == "int":
        return whole(v)
    if f.type == "usd":                 # dollars: 0 or more (null: no cap)
        return isinstance(v, int | float) and not isinstance(v, bool) and v >= 0
    if f.type == "number":
        return isinstance(v, int | float) and not isinstance(v, bool)
    if f.type == "bool":
        return isinstance(v, bool)
    if f.type == "ids":
        return isinstance(v, list) and all(whole(x) for x in v)
    if f.type == "list":
        return isinstance(v, list)
    if f.type == "object":
        return True
    if f.type == "enum":
        return isinstance(v, str) and (not f.choices or v in f.choices)
    if f.choices and f.type in ("line", "text"):
        return isinstance(v, str) and v in f.choices    # a word of a few (a verdict)
    return isinstance(v, str)


class VerbsAPI:
    def __init__(self, app):
        self.app = app
        self.rt = app.rt
        self.starlette = None              # set by create_app once the routes are made

    # -- reads ------------------------------------------------------------------------------
    async def index(self, request: Request):
        table = await run_in_threadpool(verbs.table_view, self.rt.cfg)
        return JSONResponse({"verbs": table, "reads": self.reads(),
                             "kinds": list(verbs.LADDER_KINDS),
                             "choices": list(verbs.CHOICES), "defaults": verbs.DEFAULTS,
                             "locks": {k: {"choice": c, "why": w}
                                       for k, (c, w) in verbs.LOCKS.items()}})

    def reads(self) -> list[dict]:
        """the server's reads an assistant may make, as the page makes them: every ``GET
        /api/...`` with the first line of what it answers (not the owner's own: a run's trace,
        the tokens; not the post-update self-check's)."""
        from .auth import Auth
        out = []
        for r in getattr(self.starlette, "routes", ()):
            path = getattr(r, "path", "")
            if not isinstance(r, Route) or "GET" not in (r.methods or ()) or \
                    not path.startswith("/api/") or Auth.owner_read(path) or \
                    path.startswith(("/api/tokens", "/api/selfcheck")):
                continue
            doc = (getattr(r.endpoint, "__doc__", None) or "").strip()
            says = " ".join(doc.split("\n\n", 1)[0].split())[:200]
            out.append({"path": path, "says": says})
        return sorted(out, key=lambda x: x["path"])

    def _assistant(self) -> dict:
        setting = verbs.ladder_setting(self.rt.cfg)
        kinds = []
        for k in verbs.LADDER_KINDS:
            probe = verbs.Verb(f"_.{k}", k, "", k, "POST", "/")
            c = verbs.choice_for(self.rt.cfg, probe)
            kinds.append({"kind": k, "words": verbs.KIND_WORDS[k], "choice": c.choice,
                          "default": verbs.DEFAULTS[k], "locked": c.locked, "why": c.why})
        return {"ladder": setting, "kinds": kinds,
                "choices": [{"choice": c, "words": verbs.CHOICE_WORDS[c]}
                            for c in verbs.CHOICES]}

    async def assistant(self, request: Request):
        return JSONResponse(self._assistant())

    async def set_assistant(self, request: Request):
        from .. import setup
        from .app import _json_body
        body = await _json_body(request)
        if not isinstance(body, dict) or "ladder" not in body:
            return _error("send {ladder: {kinds, verbs}}")
        try:
            ladder = verbs.check_ladder(body["ladder"])
        except ValueError as exc:
            return _error(str(exc))
        path = config_mod.config_path(self.rt.cfg.root)
        if path is None:
            return _error("no config file to write", 500)
        try:
            await run_in_threadpool(setup.write_config_values, path, {("ask", "ladder"): ladder})
        except (OSError, setup.SetupError) as exc:
            return _error(f"could not save: {exc}", 500)
        self.rt.cfg = replace(self.rt.cfg, ask=config_mod.AskConfig(ladder=ladder))
        return JSONResponse(self._assistant())

    # -- prepared presses -------------------------------------------------------------------
    def _prepared_rows(self, prepared_uuid: str | None = None) -> list[dict]:
        """The newest row of each prepared press (one, by its uuid); an open one past its
        expiry reads as ``expired``.

        A row whose verb is not in Kranto any more (live holds six ``b.factory_issue``, from
        before builds left) reads ``available: false``: titled from its stored words with "(no
        longer available)", its one button Dismiss, locked (never pressed). Every stored
        column is read without assuming its shape (a null, a number, a stray string)."""
        where, args = ("WHERE prepared_uuid = ?", (prepared_uuid,)) if prepared_uuid else ("", ())
        rows = self.rt.store.query(
            "SELECT * FROM prepared WHERE id IN (SELECT MAX(id) FROM prepared "
            f"{where} GROUP BY prepared_uuid) ORDER BY id DESC LIMIT 200", args)
        now = iso(utcnow())
        out = []
        for r in rows:
            d = dict(r)
            expires = d.get("expires_at")
            if d.get("state") == "open" and isinstance(expires, str) and expires and \
                    expires < now:
                d["state"] = "expired"
            try:
                d["fields"] = PreparedFields.load(d.get("fields")).extra
            except (TypeError, ValueError):
                d["fields"] = {}
            kind = d.get("verb") if isinstance(d.get("verb"), str) else ""
            d["verb"] = kind
            v = verbs.get(kind) if kind else None
            d["available"] = v is not None
            d["by_words"] = verbs.by_words(d.get("by") if isinstance(d.get("by"), str) else None)
            if v is None:
                raw = d.get("words")
                words: str = raw if isinstance(raw, str) else ""
                name = words.split(":", 1)[0].strip()[:80] or kind or "an action"
                d["title"] = f"{name} (no longer available)"
                d["says"] = ("This action is not part of Kranto any more, so it cannot be "
                             "approved. Dismiss it.")
                d["button"] = "Dismiss"
                d["ladder"] = "outward"
                d["locked"] = True
            else:
                d["title"] = v.title
                # the row's one button says the action (File issue, Add topic), never a house
                # word (the owner read "Press" and did not know what it meant); a locked
                # kind (a key, consent) is approved in its own dialog only
                d["button"] = button_words(d["title"])
                d["says"] = v.says
                d["ladder"] = v.ladder
                d["locked"] = bool(verbs.choice_for(self.rt.cfg, v).locked)
            d["uuid"] = d.pop("prepared_uuid")
            out.append(d)
        return out

    async def prepared(self, request: Request):
        state = request.query_params.get("state") or "open"
        rows = await run_in_threadpool(self._prepared_rows)
        if state != "all":
            rows = [r for r in rows if r["state"] == state]
        return JSONResponse({"prepared": rows})

    def _prepared_mark(self, row: dict, state: str, run_uuid: str | None = None) -> None:
        self.rt.store.insert("prepared", {
            "prepared_uuid": row["uuid"], "state": state, "verb": row["verb"],
            "subject_kind": row.get("subject_kind"), "subject_id": row.get("subject_id"),
            "subject_name": row.get("subject_name"),
            "fields": PreparedFields(extra=row.get("fields") or {}).to_json(),
            "by": row.get("by"), "page": row.get("page"), "mark": row.get("mark"),
            "words": row.get("words"), "run_uuid": run_uuid,
            "expires_at": row.get("expires_at"), "created_at": iso(utcnow())})

    async def prepared_act(self, request: Request):
        """``press`` (the page's cookie only: the owner's own press, after the page's dialog)
        or ``dismiss`` (the owner)."""
        from .auth import is_owner
        what, pid = request.path_params["what"], request.path_params["uuid"]
        if what not in ("press", "dismiss"):
            return _error("not found", 404)
        identity = request.scope.get(IDENTITY)
        door = verbs.door_of(identity)
        if what == "press" and not (door == "ui" and (identity or {}).get("via") == "cookie"):
            return _error("a prepared action is approved on the page, by you", 403)
        if what == "dismiss" and not is_owner(identity) and self.app.auth.require:
            return _error("a prepared action is dismissed by you", 403)
        rows = await run_in_threadpool(self._prepared_rows, pid)
        if not rows:
            return _error("no such prepared action", 404)
        row = rows[0]
        if row["state"] != "open":
            return _error(f"this was {row['state']} already", 409, state=row["state"])
        import time
        started = time.perf_counter()
        asker = row.get("by")
        asked_door = str(asker or "").partition(":")[0] or None
        if what == "dismiss":
            await run_in_threadpool(self._prepared_mark, row, "dismissed")
            await run_in_threadpool(self._note_resolved, row, "dismissed")
            v = verbs.get(row["verb"])
            if v is not None:
                count(v.kind, asked_door, asker, "dismissed",
                      rung_of(self.rt.cfg, v, asked_door), started)
            return JSONResponse({"ok": True, "state": "dismissed"})
        verb = verbs.get(row["verb"])
        if verb is None:
            return _error("this verb is no longer in Kranto", 410)
        # the page's dialog read the press back and the owner pressed it: that is the confirm a
        # route asks for (PAR: a sensitive setting, prepared, was then refused "needs the
        # confirm dialog's answer")
        # the press is the owner's; what is pressed is the asker's (a route that records who
        # wrote it, ``post.edit``, reads ``verbs.asked_by``)
        with verbs.asked(asker):
            status, answer = await self._perform(verb, row.get("subject_id"), row["fields"],
                                                 identity, by="ui",
                                                 skind=row.get("subject_kind"), confirmed=True)
        ok = 200 <= status < 400
        if ok:
            await run_in_threadpool(self._prepared_mark, row, "pressed")
            await run_in_threadpool(self._note_resolved, row, "approved")
            count(verb.kind, asked_door, asker, "confirmed",
                  rung_of(self.rt.cfg, verb, asked_door), started)
            return JSONResponse({"ok": True, "state": "pressed", "answer": answer})
        # the refusal in words at the top (the page says it as a sentence, never the JSON)
        why = why_of(status, answer, verb.title)
        log.warning("prepared %s approved and then refused (%s): %s", verb.kind, status, why)
        return JSONResponse({"ok": False, "state": "open", "error": why, "answer": answer},
                            status_code=status)

    # -- running a verb ---------------------------------------------------------------------
    async def run(self, request: Request):
        kind = request.path_params["kind"]
        verb = await run_in_threadpool(verbs.get, kind)
        if verb is None:
            return _error(f"no verb {kind}: GET /api/verbs lists them", 404)
        from .app import _json_body
        body = await _json_body(request)
        if body is None:
            return _error("expected a JSON object: {subject?, fields?, client?}")
        identity = request.scope.get(IDENTITY)
        door = verbs.door_of(identity)
        if door is None and not self.app.auth.require:
            door, identity = "cli", {"origin": "cli", "name": "cli"}
        import time
        started = time.perf_counter()
        by = verbs.by_of(identity, body.get("client") if isinstance(body, dict) else None)
        try:
            out = await self._run(verb, door, identity, body)
        except VerbError as exc:
            count(verb.kind, door, by, "refused", rung_of(self.rt.cfg, verb, door), started,
                  exc.refusal)
            log.warning("verb %s by %s refused (%s): %s", verb.kind, by, exc.refusal, exc)
            if door not in (None, *verbs.OWNER_DOORS) and exc.refusal != "starting":
                await run_in_threadpool(self._refused, verb, by, body, str(exc))
            return _error(str(exc), exc.status, **exc.extra)
        outcome = "ok" if out.get("ok") else "prepared" if out.get("prepared") else "failed"
        count(verb.kind, door, by, outcome, rung_of(self.rt.cfg, verb, door), started)
        return JSONResponse(out, status_code=200 if out.get("ok") or out.get("prepared")
                            else out.get("status", 200))

    async def _run(self, verb: verbs.Verb, door: str | None, identity: dict | None,
                   body: dict) -> dict:
        page = verbs.fill(verb.page, None, {})
        if door is None:
            raise VerbError("not signed in", 401, refusal="signed_out")
        if door not in verb.doors:
            where = "on the page" if verb.doors == verbs.PAGE_ONLY else "by you"
            raise VerbError(f"{verb.title} ({verb.kind}) is done {where} only: open {page}",
                            403, refusal="door", page=page, choice="never", locked=True)
        subject = body.get("subject")
        sid = subject.get("id") if isinstance(subject, dict) else subject
        skind = subject.get("kind") if isinstance(subject, dict) else None
        if verb.needs_id() and sid in (None, ""):
            raise VerbError(f"{verb.kind} acts on a {verb.subject}: send subject {{id}}",
                            refusal="subject")
        if sid is not None and not isinstance(sid, str | int) or isinstance(sid, bool):
            raise VerbError("subject.id is a string or a number", refusal="subject")
        kinds = [k for k in (verb.subjects or (verb.subject,)) if k != "new"] or ["new"]
        if skind is not None and skind not in kinds:
            raise VerbError(f"{verb.kind} acts on a {' or '.join(kinds)}, not a {skind}",
                            refusal="subject")
        skind = skind or (kinds[0] if sid not in (None, "") else "new")
        fields = check_fields(verb, body.get("fields"))
        await run_in_threadpool(precheck, self.rt, verb, sid, fields)
        by = verbs.by_of(identity, body.get("client"))
        page = verbs.fill(verb.page, sid, fields)
        mark = verbs.fill(verb.mark, sid, fields)
        if door in verbs.OWNER_DOORS:
            status, answer = await self._perform(verb, sid, fields, identity, by=by, skind=skind)
            return self._answer(verb, status, answer, sid, fields, by, skind)
        if door == "mcp" and verb.ladder != "read" and await run_in_threadpool(self._reads_only):
            raise VerbError("kranto mcp reads only here (mcp.actions: false, Settings › "
                            "Building): your own assistant may read, not act", 403,
                            refusal="reads_only", page="#/settings/building", choice="never",
                            locked=False)
        choice = verbs.choice_for(self.rt.cfg, verb, fields)
        if choice.choice == "never":
            raise VerbError(f"{verb.title} ({verb.kind}) is off for assistants: "
                            f"{choice.why}. It is under Settings › Assistant "
                            "(#/settings/assistant), or do it yourself on " + page, 403,
                            refusal="locked" if choice.locked else "never",
                            page=page, choice="never", locked=choice.locked)
        if choice.choice == "ask":
            await self._check_as_press(verb, sid, fields, identity, skind)
            out = await run_in_threadpool(self._prepare, verb, sid, fields, by, page, mark,
                                          choice, skind)
        else:
            status, answer = await self._perform(verb, sid, fields, identity, by=by,
                                                 record=True, skind=skind)
            out = self._answer(verb, status, answer, sid, fields, by, skind)
        if out.get("ok") or out.get("prepared"):
            await run_in_threadpool(self._note, verb, out)
        return out

    def _refused(self, verb: verbs.Verb, by: str, body: Any, why: str) -> None:
        """An assistant's verb that Kranto refused is a run in Activity, ``skipped`` with why in
        words (PAR: the refusal was in the log and the usage count only, so "why did my
        assistant's press not happen" had no answer on the page). Skipped, not failed: nothing
        of Kranto's failed, and a skipped run with its reason makes no Fix row (``read._scan``).
        Never raises."""
        from .. import activity
        from ..core.context import record_run
        subject = body.get("subject") if isinstance(body, dict) else None
        sid = subject.get("id") if isinstance(subject, dict) else subject
        if not isinstance(sid, str | int) or isinstance(sid, bool):
            sid = None
        try:
            started = utcnow()
            with activity.run(self.rt.store, "verb", origin="press", by=by,
                              title=f"Refused: {verb.title}" + (f" · {sid}" if sid else ""),
                              subject=(verb.subject, sid, None) if sid is not None else None) \
                    as r:
                record_run(self.rt.store, "verb", "skipped", started,
                           {"verb": verb.kind, "refused": True}, why[:300], run_uuid=r.uuid)
        except Exception:  # noqa: BLE001 - a refusal is answered whether or not it is recorded
            log.exception("a refused verb could not be recorded in Activity")

    # -- what an assistant did, for the page's marks (reflection,) -------------------
    def _mirror(self):
        return self.rt.cfg.data_dir / RECENT_FILE

    def _note_resolved(self, row: dict, how: str) -> None:
        """A prepared item approved or dismissed: one line in ``verbs.json`` too, so every open
        page takes it out of Needs you and its toast at once, not only the page
        that approved it. It marks no row (``mark`` empty)."""
        v = verbs.get(row["verb"])
        self._note(v or verbs.Verb(row["verb"], row.get("title") or row["verb"], "", "outward",
                                   "POST", "/"),
                   {"prepared": row["uuid"], "page": row.get("page"), "by": "ui", "mark": ""},
                   resolved=how)

    def _note(self, verb: verbs.Verb, out: dict, resolved: str | None = None) -> None:
        """One more line in ``<data>/verbs.json``: the page's live feed sees the file change,
        reads ``GET /api/verbs/recent`` and marks the row the verb touched. ``resolved``: a
        prepared item's end (``approved`` or ``dismissed``)."""
        import os
        path = self._mirror()
        with _MIRROR_LOCK:
            cur = VerbsMirror.load(path.read_text()) if path.exists() else VerbsMirror()
            seq = int(cur.seq or 0) + 1
            at = iso(utcnow())
            line = {"seq": seq, "verb": verb.kind, "title": verb.title,
                    "subject": out.get("subject"), "page": out.get("page"),
                    "mark": out.get("mark") or "", "by": out.get("by"),
                    "by_words": verbs.by_words(out.get("by")),
                    "prepared": out.get("prepared"), "run": out.get("run"),
                    "button": button_words(verb.title), "resolved": resolved,
                    "locked": bool(verbs.choice_for(self.rt.cfg, verb).locked),
                    "at": at}
            recent = [line, *list(cur.recent or [])][:RECENT_KEEP]
            text = VerbsMirror(seq=seq, updated=at, recent=recent).to_json()
            tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp.write_text(text)
                tmp.replace(path)
            except OSError:
                log.warning("verbs.json could not be written")

    async def recent(self, request: Request):
        """``GET /api/verbs/recent?since=<seq>``: what assistants did lately, newest first."""
        try:
            since = int(request.query_params.get("since") or 0)
        except ValueError:
            since = 0
        path = self._mirror()

        def read() -> VerbsMirror:
            return VerbsMirror.load(path.read_text()) if path.exists() else VerbsMirror()
        cur = await run_in_threadpool(read)
        rows = [r for r in (cur.recent or []) if isinstance(r, dict)
                and int(r.get("seq") or 0) > since]
        return JSONResponse({"seq": int(cur.seq or 0), "recent": rows})

    def _reads_only(self) -> bool:
        """``mcp.actions: false`` in the page's settings (its ``loop.yaml``, read through
        the page's ``Config``): your own assistant over kranto mcp reads and does nothing."""
        try:
            from kranto.page.host_api import Config
            loop_home = getattr(self.rt.cfg.brb, "loop_home", None)
            data = Config(loop_home).data if loop_home else Config().data
        except Exception:  # noqa: BLE001 - no build loop here: nothing says reads only
            return False
        mcp = data.get("mcp") if isinstance(data, dict) else None
        return isinstance(mcp, dict) and mcp.get("actions") is False

    def _answer(self, verb, status: int, answer: Any, sid, fields, by,
                skind: str | None = None) -> dict:
        ok = 200 <= status < 400
        if isinstance(answer, dict) and sid is None and verb.subject == "new":
            got = answer.get(verb.id_from)
            sid = got if isinstance(got, str | int) and not isinstance(got, bool) else None
        page = verbs.fill(verb.page, sid, fields)
        why = None if ok else why_of(status, answer, verb.title)
        out: dict[str, Any] = {
            "ok": ok, "verb": verb.kind, "status": status,
            "subject": {"kind": skind or verb.subject, "id": sid},
            "page": page, "mark": verbs.fill(verb.mark, sid, fields), "by": by,
            "undo": verb.undo, "answer": answer,
            "say": (f"{verb.title}: done. It shows on {page}." if ok else
                    f"{verb.title} did not happen: {why}")}
        if not ok:
            out["error"] = why          # PAR: the words every client reads first
        if isinstance(answer, dict) and answer.get("_run"):
            out["run"] = answer.pop("_run")
        return out

    async def _check_as_press(self, verb: verbs.Verb, sid, fields: dict, identity,
                              skind: str | None) -> None:
        """A press is prepared only when the press would take its fields (a factory
        issue was prepared with a fingerprint its press then refused, in 5 ms). Kranto's own
        verbs were checked above (``check_fields``, the same as the press's). The build loop's
        verbs, which ran their own check through ``api/act``, left with builds (CUT): a verb
        of that kind is never sent to the page's server to be checked."""
        return

    def _same_open(self, verb: str, skind: str | None, sid: Any, fields: dict) -> dict | None:
        """An open press already prepared for the same verb, subject and fields (an assistant asked
        twice made two rows for one press)."""
        want = json.dumps(fields or {}, sort_keys=True, default=str)
        for r in self._prepared_rows():
            if r["state"] == "open" and r["verb"] == verb and \
                    r.get("subject_kind") == skind and \
                    r.get("subject_id") == (None if sid is None else str(sid)) and \
                    json.dumps(r["fields"] or {}, sort_keys=True, default=str) == want:
                return r
        return None

    def _prepare(self, verb, sid, fields, by, page, mark, choice, skind=None) -> dict:
        from .. import activity
        from ..core.context import record_run
        same = self._same_open(verb.kind, skind or verb.subject, sid, fields)
        if same is not None:              # one press waits once, however often it is asked
            return {"ok": False, "prepared": same["uuid"], "verb": verb.kind, "choice": "ask",
                    "why": choice.why, "page": page, "mark": mark, "by": by, "again": True,
                    "subject": {"kind": verb.subject, "id": sid}, "run": same.get("run_uuid"),
                    "say": f"Already prepared, and nothing has happened: {verb.title} waits for "
                           f"the owner's approval on {page} and in Needs you ({choice.why})."}
        pid = uuid_mod.uuid4().hex
        words = f"{verb.title}: prepared {verbs.by_words(by)}; waits for your approval on {page}"
        now = utcnow()
        row = {"uuid": pid, "verb": verb.kind, "subject_kind": skind or verb.subject,
               "subject_id": None if sid is None else str(sid), "subject_name": None,
               "fields": fields, "by": by, "page": page, "mark": mark, "words": words,
               "expires_at": iso(now + timedelta(hours=PREPARED_HOURS))}
        with activity.run(self.rt.store, "verb", origin="press", by=by,
                          title=f"Prepared: {verb.title}",
                          subject=(verb.subject, sid, None) if sid is not None else None) as r:
            self._prepared_mark(row, "open")
            r.waiting(words, {"verb": verb.title, "href": page, "words": words})
            record_run(self.rt.store, "verb", "ok", now,
                       {"verb": verb.kind, "prepared": pid}, run_uuid=r.uuid)
        log.info("prepared %s %s", verb.kind, by)
        return {"ok": False, "prepared": pid, "verb": verb.kind, "choice": "ask",
                "why": choice.why, "page": page, "mark": mark, "by": by,
                "subject": {"kind": verb.subject, "id": sid}, "run": r.uuid,
                "say": f"Prepared, and nothing has happened: {verb.title} waits for the owner's "
                       f"approval on {page} and in Needs you ({choice.why})."}

    async def _perform(self, verb: verbs.Verb, sid, fields: dict, identity: dict | None, *,
                       by: str, record: bool = False, skind: str | None = None,
                       confirmed: bool = False) -> tuple[int, Any]:
        """Call the verb's route in this process, as the page calls it. ``record``: the call is
        a run in Activity (kind ``verb``) with who did it. ``confirmed``: the owner pressed it
        after the page's dialog (a prepared press)."""
        if not record:
            with verbs.acting(None if by in ("ui", "cli") else by):
                return await self._call(verb, sid, fields, identity, skind,
                                        confirmed=confirmed)
        from .. import activity
        from ..core.context import record_run
        started = utcnow()
        title = verb.title + (f" · {sid}" if sid not in (None, "") else "")
        with activity.run(self.rt.store, "verb", origin="press", by=by, title=title,
                          subject=(verb.subject, sid, None) if sid is not None else None) as r:
            with verbs.acting(by):
                status, answer = await self._call(verb, sid, fields, identity, skind)
            ok = 200 <= status < 400
            err = None if ok else why_of(status, answer, verb.title)
            await run_in_threadpool(record_run, self.rt.store, "verb", "ok" if ok else "failed",
                                    started, {"verb": verb.kind, "status": status}, err,
                                    run_uuid=r.uuid)
        if isinstance(answer, dict):
            answer = {**answer, "_run": r.uuid}
        return status, answer

    async def _call(self, verb: verbs.Verb, sid, fields: dict, identity,
                    skind: str | None = None, check: bool = False,
                    confirmed: bool = False) -> tuple[int, Any]:
        if self.starlette is None:
            raise VerbError("Kranto is starting: try again", 503, refusal="starting")
        fixed = dict(verb.fixed)
        params: dict[str, Any] = {}
        rest = []
        for p in verb.params:
            if p in fixed:
                params[p] = fixed.pop(p)
            elif p in fields and fields[p] is not None:
                params[p] = fields[p]
            else:
                rest.append(p)
        if rest:
            params[rest[0]] = sid
        if any(params.get(p) in (None, "") for p in verb.params):
            raise VerbError(f"{verb.kind} acts on a {verb.subject}: send subject {{id}}",
                            refusal="subject")
        values = {k: v for k, v in fields.items() if k not in params and v is not None}
        values.update(fixed)
        if verb.subject_field and sid not in (None, "") and not rest:
            values[verb.subject_field] = sid        # the id where the route reads it
        import re
        path = re.sub(r"{(\w+)(?::(\w+))?}",
                      lambda m: quote(str(params[m.group(1)]),
                                      safe="/" if m.group(2) == "path" else ""), verb.path)
        if verb.body == "act":                      # the build loop's api/act
            payload: dict[str, Any] = {
                "kind": verb.kind.removeprefix("b."), "fields": values,
                "subject": {"kind": skind or "new", "id": None if sid in (None, "") else sid},
                "confirm": verb.click == "confirm" or confirmed,
                **({"check": True} if check else {})}
            raw = json.dumps(payload).encode()
            ctype = b"application/json"
        elif verb.body == "form":
            raw = urlencode({k: (json.dumps(v) if isinstance(v, dict | list) else
                                 ("true" if v is True else "" if v is False else v))
                             for k, v in values.items()}).encode()
            ctype = b"application/x-www-form-urlencoded"
        else:
            payload = {"fields": values} if verb.body == "fields" else values
            if verb.click in ("confirm", "house") or confirmed:
                # the owner's ladder choice (Do it) or the owner's own press after the page's
                # dialog is the confirm; a house verb never reaches here for an assistant
                payload = {**payload, "confirm": True}
            raw = json.dumps(payload).encode()
            ctype = b"application/json"
        scope = {"type": "http", "http_version": "1.1", "method": verb.method,
                 "scheme": "http", "path": path, "raw_path": path.encode(),
                 "root_path": "", "query_string": b"",
                 "headers": [(b"content-type", ctype), (b"accept", b"application/json"),
                             (b"content-length", str(len(raw)).encode()),
                             (b"host", b"127.0.0.1")],
                 "client": ("127.0.0.1", 0), "server": ("127.0.0.1", 0),
                 "app": self.starlette, "state": {},
                 IDENTITY: {**(identity or {}), "verb": verb.kind}}
        route = self._route(scope)
        if route is None:
            return 404, {"error": f"{verb.kind}'s route {verb.method} {verb.path} is not here"}
        status, body = 500, b""
        headers: list[tuple[bytes, bytes]] = []
        delivered = False

        async def receive():
            nonlocal delivered
            if delivered:
                return {"type": "http.disconnect"}
            delivered = True
            return {"type": "http.request", "body": raw, "more_body": False}

        async def send(message):
            nonlocal status, body, headers
            if message["type"] == "http.response.start":
                status = int(message["status"])
                headers = list(message.get("headers") or [])
            elif message["type"] == "http.response.body":
                body += message.get("body", b"")

        await route.handle(scope, receive, send)
        try:
            answer: Any = json.loads(body or b"null")  # stored-shape: a route's answer
        except ValueError:
            answer = {"text": body.decode(errors="replace")[:500]}
        if 300 <= status < 400:
            loc = next((v.decode() for k, v in headers if k.lower() == b"location"), "")
            answer = {"ok": True, "redirect": loc}
        return status, answer

    def _route(self, scope: dict):
        for r in getattr(self.starlette, "routes", ()):
            if not isinstance(r, Route):
                continue
            match, child = r.matches(scope)
            if match == Match.FULL:
                scope.update(child)
                return r
        return None

    # -- your own client, outside Kranto's folder (the owner's Q6 of 2026-10-25) --------------
    def _global(self, harness: str, which: Any = None) -> dict:
        """What adding Kranto to your own Claude Code or Codex changes, exactly as ``kranto
        assistant global`` shows it: its own commands, and Codex's skill files."""
        import shutil
        from pathlib import Path

        from .. import assistant as A
        which = which or shutil.which
        steps = A.global_steps(harness, which)
        files = A.codex_global_skills(Path.home()) if harness == "codex" else []
        missing = sorted({s[0] for s in steps if not which(s[0])})
        return {"harness": harness, "steps": [" ".join(s) for s in steps],
                "files": [{"path": str(c.path), "state": c.state} for c in files],
                "missing": missing,
                "says": "This changes your own configuration, outside Kranto's folder. Nothing "
                        "is changed until you click Add."}

    async def global_show(self, request: Request):
        """What adding Kranto to your own Claude Code or Codex would change (``harness=``),
        shown before anything is written."""
        harness = request.query_params.get("harness") or ""
        if harness not in ("claude", "codex"):
            return _error("harness is claude or codex")
        return JSONResponse(await run_in_threadpool(self._global, harness))

    def _global_apply(self, harness: str) -> dict:
        import subprocess

        from .. import assistant as A
        plan = self._global(harness)
        if plan["missing"]:
            raise VerbError(f"{', '.join(plan['missing'])} is not installed here", 409)
        for s in A.global_steps(harness):
            r = subprocess.run(s, capture_output=True, text=True, timeout=120, check=False)
            if r.returncode != 0:
                raise VerbError(f"{' '.join(s)} failed; nothing more was changed: "
                                f"{(r.stderr or r.stdout).strip()[-300:]}", 502)
        from pathlib import Path
        files = A.codex_global_skills(Path.home()) if harness == "codex" else []
        A.apply(files)
        return {**plan, "done": True,
                "says": "Done. Restart your own client to load Kranto."}

    async def global_apply(self, request: Request):
        """The owner's press: make the change ``GET /api/assistant/global`` showed."""
        from .app import _json_body
        body = await _json_body(request)
        harness = str((body or {}).get("harness") or "")
        if harness not in ("claude", "codex"):
            return _error("harness is claude or codex")
        try:
            return JSONResponse(await run_in_threadpool(self._global_apply, harness))
        except VerbError as exc:
            return _error(str(exc), exc.status, **exc.extra)

    def routes(self) -> list[Route]:
        return [Route("/api/assistant/global", self.global_show),
                Route("/api/assistant/global", self.global_apply, methods=["POST"]),
                Route("/api/verbs", self.index),
                Route("/api/verbs/recent", self.recent),
                Route("/api/verbs/{kind}", self.run, methods=["POST"]),
                Route("/api/prepared", self.prepared),
                Route("/api/prepared/{uuid}/{what}", self.prepared_act, methods=["POST"]),
                Route("/api/settings/assistant", self.assistant),
                Route("/api/settings/assistant", self.set_assistant, methods=["POST"])]
