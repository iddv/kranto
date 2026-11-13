"""The watcher's prompts over HTTP, for Kranto UI's Settings › Prompts (``prompts``).

| Method and path                 | Does                                                     |
|---------------------------------|----------------------------------------------------------|
| GET  /api/prompts               | the registry: each prompt, what it does, editable, its   |
|                                 | version, whether the owner customised it                 |
| GET  /api/prompts/{id}          | one prompt: the default, the active text, the additions, |
|                                 | the override and its diff, the versions, placeholders,   |
|                                 | and the default-changed flag with the three-way view     |
| POST /api/prompts/{id}          | {additions} and/or {template}: a new version             |
| POST /api/prompts/{id}/reset    | {what: all|template|additions}: back to the default, as  |
|                                 | a new version                                            |
| POST /api/prompts/{id}/restore  | {version: N}: version N's content as a new version       |
| GET  /api/prompts/{id}/versions/{n} | version n's text, and its diff against the one in use |
| POST /api/prompts/{id}/versions/{n}/note | {note}: a short note on version n (<= 80)   |
| POST /api/prompts/preview       | {id, subject}: the text the model would get for a real   |
|                                 | observation, card or topic, scrubbed; no model is called |

the page's Settings › Prompts reads and writes these through this API (it proxies them), so
nothing but the server touches ``<home>/prompts/the server/``. The guard is the server's, as for
every other settings API: a known Host, a same-origin POST, a JSON body under the limit.
"""

from __future__ import annotations

import json
from collections import Counter

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import library, prompts, scrub
from ..store import utcnow
from ..stored.cards import Card, InputIds


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


class PromptsAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    def _store(self) -> prompts.Store:
        st = prompts.store()
        if st is None:              # a runtime made without open_runtime: this workspace
            prompts.configure(self.rt.cfg.root)
            st = prompts.store()
        return st

    async def _run(self, fn, *args):
        try:
            return JSONResponse(await run_in_threadpool(fn, *args))
        except prompts.PromptError as exc:
            return _error(str(exc), exc.code)

    async def _body(self, request: Request):
        from .app import MAX_JSON_BYTES, _json_body

        body = await _json_body(request)
        if body is None:
            return None, _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        return body, None

    def _list(self) -> dict:
        st = self._store()
        # a feature that is off lists no prompt (B, Codex 9: Invest and Radar's prompts on a
        # home where both are off), as /api/features leaves it out; its prompts stay readable
        from ..core import registry as core_registry
        off = {f.id for f in core_registry.first_party()
               if not core_registry.enabled(self.rt.cfg, f)}
        rows = [r for r in prompts.registry(st) if r.get("step") not in off]
        return {"prompts": rows, "defaults_only": prompts.defaults_only(),
                "store": str(st.dir(prompts.REPO))}

    async def list(self, request: Request):
        return await self._run(self._list)

    async def get(self, request: Request):
        return await self._run(lambda: prompts.detail(request.path_params["pid"],
                                                      self._store()))

    async def save(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        return await self._run(lambda: prompts.save(request.path_params["pid"], body,
                                                    self._store()))

    async def reset(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        return await self._run(lambda: prompts.reset(request.path_params["pid"], body,
                                                     self._store()))

    async def restore(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        return await self._run(lambda: prompts.restore(request.path_params["pid"], body,
                                                       self._store()))

    async def version(self, request: Request):
        p = request.path_params
        return await self._run(lambda: prompts.version_view(p["pid"], p["n"], self._store()))

    async def note(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        p = request.path_params
        return await self._run(lambda: prompts.set_note(p["pid"], p["n"], body, self._store()))

    async def preview(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        return await self._run(self._preview, body)

    # -- preview ------------------------------------------------------------------------------

    def _preview(self, body: dict) -> dict:
        """The text a call would send, from a real item; scrubbed (``scrub.scrub``: secrets
        and personal data become labels). Never calls a model."""
        e = prompts.entry(str(body.get("id") or ""))
        subject = body.get("subject")
        if isinstance(subject, dict):
            subject = subject.get("id")
        p = prompts.load(e.id)
        values, user, about = self._values(e, subject)
        system_like = e.id in ("judge", "screen")
        text = prompts.fill(e, p.template, values)
        counts: Counter = Counter()
        text = scrub.scrub(text, counts)
        messages = [{"role": "system" if system_like else "user", "content": text}]
        if user is not None:
            messages.append({"role": "user", "content": scrub.scrub(user, counts)})
        whole = "\n\n".join(f"--- {m['role']} ---\n{m['content']}" for m in messages) \
            if len(messages) > 1 else text
        return {"repo": prompts.REPO, "id": e.id, "version": p.version,
                "custom": p.version != prompts.load(e.id, defaults=True).version,
                "text": whole, "messages": messages, "chars": len(whole),
                "redactions": [{"kind": k, "count": n} for k, n in sorted(counts.items())],
                "filled": sorted(values), "subject": about, "model_called": False}

    def _values(self, e: prompts.Entry, subject) -> tuple[dict, str | None, dict]:
        store = self.rt.store
        if e.id in ("judge", "screen"):
            values = {"tenets": prompts.tenets()}
            if subject in (None, ""):
                return values, None, {}
            row = self._observation(subject)
            item = {"source": row["source_label"],
                    "item": {"title": row["title"], "url": row["source_url"],
                             "text": row["source_excerpt"] or row["summary"]}}
            note = ("(the item as the judge sees it, rebuilt from the stored observation: "
                    "its excerpt, not the full original text)\n")
            return values, note + json.dumps(item, ensure_ascii=False, indent=1), \
                {"kind": "observation", "id": row["id"]}
        if e.id == "explain" and subject not in (None, ""):
            from ..ideate.explain import _render
            row = self._observation(subject)
            return {"observations": _render([row])}, None, {"kind": "observation",
                                                            "id": row["id"]}
        if e.id in ("card", "verify") and subject not in (None, ""):
            from ..ideate.cards import _line, _render
            idea = store.query_one("SELECT * FROM ideas WHERE id = ?", (_int(subject),))
            if idea is None:
                raise prompts.PromptError(f"no idea card {subject}", 404)
            ids = InputIds.load(idea["input_ids"]).items
            by_id = library.observations_by_id(store, ids)
            rows = [by_id[i] for i in ids if i in by_id]
            about = {"kind": "idea", "id": idea["id"], "observations": len(rows)}
            if e.id == "card":
                return {"observations": _render(rows),
                        "today": utcnow().date().isoformat(),
                        "prior_art": "(live search results for what these observations are "
                                     "about, searched when the card is written)"}, None, about
            card = Card.load(idea["card"])
            pairs = [f"Claim {i}: {ev.claim}\nObservation: "
                     + (_line(by_id[ev.observation_id]) if ev.observation_id in by_id
                        else ev.summary or "(no longer in the library)")
                     for i, ev in enumerate(card.evidence, 1)]
            return {"pairs": "\n\n".join(pairs) or None}, None, about
        if e.id == "scout" and subject not in (None, ""):
            from ..scout import presets_text
            t = store.query_one("SELECT * FROM topics_now WHERE id = ?", (_int(subject),))
            if t is None:
                raise prompts.PromptError(f"no topic {subject}", 404)
            return {"name": t["name"], "description": t["description"],
                    "presets": presets_text(), "replacements": "(none)",
                    "results": "(live search results for the topic, searched when the scout "
                               "runs)", "today": utcnow().date().isoformat()}, None, \
                {"kind": "topic", "id": t["id"]}
        if e.id == "scout":
            from ..scout import presets_text
            return {"presets": presets_text()}, None, {}
        if e.id == "resolve":
            from ..resolve import MAX_LINES, connected_providers
            from ..resolve import presets_text as resolve_presets
            return {"presets": resolve_presets(connected_providers(self.rt.connections)),
                    "max_proposals": str(MAX_LINES)}, None, {}
        return {}, None, {}

    def _observation(self, subject):
        row = library.get_observation(self.rt.store, _int(subject))
        if row is None:
            raise prompts.PromptError(f"no observation {subject}", 404)
        return row

    def routes(self) -> list[Route]:
        return [
            Route("/api/prompts", self.list),
            Route("/api/prompts/preview", self.preview, methods=["POST"]),
            Route("/api/prompts/{pid}", self.get),
            Route("/api/prompts/{pid}", self.save, methods=["POST"]),
            Route("/api/prompts/{pid}/reset", self.reset, methods=["POST"]),
            Route("/api/prompts/{pid}/restore", self.restore, methods=["POST"]),
            Route("/api/prompts/{pid}/versions/{n:int}", self.version),
            Route("/api/prompts/{pid}/versions/{n:int}/note", self.note, methods=["POST"]),
        ]


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise prompts.PromptError(f"{value!r} is not an id", 400) from None
