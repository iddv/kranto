"""The prose profile over HTTP, for Settings › Posting › Voice, the draft's
flags and Fix, and Welcome's "How you write" step (PROSE's PR 2), and for the verbs.

- ``GET /api/prose``: the profile (voice card, switches with their words, the checker's
  strictness and rules, guides per site, the lists, samples, disclosure, take, open proposals).
- ``POST /api/prose/check`` ``{text, site?, kind?, take?, limits?, strictness?}``: the flags
  (verb ``prose.check``, read).
- ``POST /api/prose/voice``: a change to the profile, ``profile.change``'s keys (verb
  ``prose.voice``, reversible).
- ``POST /api/prose/learn``: ``{draft, sent}`` gives proposals; ``{proposal, answer}`` a yes or
  a no (verb ``prose.learn``, reversible).
- ``POST /api/prose/voice/draft`` ``{samples?}``: one model call drafts a voice card from the
  samples given (else the saved ones); nothing is saved (``ROUTE_ALLOW``).
- ``POST /api/prose/revise`` ``{text, site?, kind?, take?, flags?}``: the text with only its
  flagged spans rewritten, at most two calls; nothing is saved (``ROUTE_ALLOW``).
- ``POST /api/prose/writer-key`` ``{key}``: the OpenAI key a post writer's own model uses (a
  writer only, never the watcher's), pasted on How you write. It goes to the server once, is
  tested (``GET /v1/models``, spending nothing), and only when it passes is kept as the command
  line keeps it (``OPENAI_API_KEY`` in the home's ``.env``, 0600). The answer is
  ``{ok, detail, set}``: never the key, and the key is in no log (verb ``prose.writer_key``,
  credential, the page only). ``GET /api/prose``'s ``writer_key`` says only whether one is set.

``docs/prose.md`` describes each answer. The guard is the server's: a known Host, a same-origin
POST, a JSON body under the limit.
"""

from __future__ import annotations

from typing import Any

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import prose
from ..prose import learner
from ..prose import profile as profile_mod

PURPOSE = "prose_revise"
VOICE_PURPOSE = "prose_voice"
TEXT_MAX = 100_000


class ProseError(ValueError):
    def __init__(self, words: str, code: int = 400) -> None:
        super().__init__(words)
        self.words, self.code = words, code


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _guide_title(text: str, name: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return name


def read(rt) -> dict[str, Any]:
    """``GET /api/prose``."""
    p = prose.load(rt.cfg, rt.store)
    row = profile_mod.load_row(rt.store)
    shipped = profile_mod.shipped_guides()
    names = {**{k: ("kranto", v) for k, v in shipped.items()},
             **{k: ("yours", v) for k, v in p.own_guides.items()}}
    return {
        "voice": p.voice,
        "switches": p.switches,
        "switch_choices": {**{k: list(v) for k, v in profile_mod.SWITCHES.items()},
                           "grade": [3, 16]},
        "switch_words": profile_mod.SWITCH_WORDS,
        "strictness": p.strictness,
        "rules": [{"id": rid, "group": g, "words": w, "fix": f, "on": rid not in p.rules_off}
                  for rid, (g, w, f) in prose.RULES.items()],
        "guides": [{"name": n, "title": _guide_title(t, n), "from": src, "always": n == "floor"}
                   for n, (src, t) in sorted(names.items())],
        "sites": [{"site": s, "guides": list(p.guides_for(s)), "default": s not in p.guides,
                   "limits": profile_mod.SITE_LIMITS.get(s, {}),
                   "disclosure": p.disclosure.get(s, "")} for s in profile_mod.SITES],
        "writers": profile_mod.WRITER_SITE,
        # the model that writes each writer's posts (P-11); null: the reason tier's
        "writer_models": {w: p.writer_model(w) for w in profile_mod.WRITER_SITE},
        "writer_providers": list(profile_mod.WRITER_PROVIDERS),
        # whether an OpenAI key for a writer's own model is set: never the key itself
        "writer_key": {"set": writer_key_set(rt)},
        "disclosure_line": profile_mod.DISCLOSURE_LINE,
        # what a short post ends with where its site's disclosure is on and no words are set
        # (``kranto.social.disclosure_line``)
        "disclosure_default": _short_default(),
        "take": p.take,
        "never": list(p.never), "keep": list(p.keep), "always": list(p.always),
        "samples": [{"id": s.id, "site": s.site, "words": len(s.text.split()),
                     "start": s.text[:200]} for s in p.samples],
        "rhythm": p.rhythm(),
        "proposals": [x for x in learner.load(rt.store).proposals if isinstance(x, dict)],
        "migrated": row.migrated or {},
        "home": str(profile_mod.home_of(rt.cfg)),
    }


def _text(body: dict, key: str = "text", required: bool = True) -> str:
    v = body.get(key)
    if v is None and not required:
        return ""
    words = f"{key} is text of 1 to {TEXT_MAX:,} characters"
    if not isinstance(v, str) or (required and not v.strip()):
        raise ProseError(words)
    if len(v) > TEXT_MAX:  # stored-shape: a request body, checked as text above
        raise ProseError(words)
    return v


def _opt(body: dict, key: str, kind: type) -> Any:
    v = body.get(key)
    if v is not None and not isinstance(v, kind):
        raise ProseError(f"{key} is {'text' if kind is str else 'an object'}")
    return v


def check(rt, body: dict) -> dict[str, Any]:
    if body.get("strictness") not in (None, *profile_mod.STRICTNESS):
        raise ProseError("strictness is off, light or strict")
    return prose.check(_text(body), _opt(body, "site", str), prose.load(rt.cfg, rt.store),
                       kind=_opt(body, "kind", str), limits=_opt(body, "limits", dict),
                       take=_opt(body, "take", str), strictness=body.get("strictness"),
                       sources=_opt(body, "sources", str))


def voice(rt, body: dict) -> dict[str, Any]:
    try:
        return profile_mod.change(rt.cfg, rt.store, body)
    except profile_mod.ProfileError as exc:
        raise ProseError(str(exc)) from None


def learn(rt, body: dict) -> dict[str, Any]:
    if body.get("proposal") is not None:
        if body.get("answer") not in ("yes", "no"):
            raise ProseError("answer is yes or no")
        try:
            return learner.answer(rt.cfg, rt.store, str(body["proposal"]), body["answer"] == "yes")
        except learner.LearnError as exc:
            raise ProseError(str(exc), 404) from None
    draft, sent = _text(body, "draft"), _text(body, "sent")
    new = learner.observe(rt.store, prose.load(rt.cfg, rt.store), draft, sent)
    return {"ok": True, "proposals": new,
            "say": f"{len(new)} proposal{'s' if len(new) != 1 else ''}: each waits for your yes."
            if new else "Nothing to learn from this edit."}


def _complete(rt, purpose: str, max_tokens: int):
    def complete(messages: list[dict], schema: dict | None) -> dict:
        got = rt.llm.complete(tier="reason", purpose=purpose, messages=messages,
                              prompt_version="prose@1", max_tokens=max_tokens, temperature=0.2,
                              schema=schema)
        return {"text": got.text, "structured": got.structured}
    return complete


def draft_voice(rt, body: dict) -> dict[str, Any]:
    samples = body.get("samples")
    if samples is None:
        samples = [s.text for s in prose.load(rt.cfg, rt.store).samples]
    if not isinstance(samples, list) or not samples or not all(
            isinstance(s, str) and 20 <= len(s.strip()) <= profile_mod.SAMPLE_MAX
            for s in samples) or len(samples) > 10:
        raise ProseError("samples: 1 to 10 texts you wrote, each 20 to 6,000 characters (or "
                         "save samples first)")
    _key(rt)
    text = _complete(rt, VOICE_PURPOSE, 700)(prose.voice_card_messages(samples), None)["text"]
    card = str(text or "").strip()[:profile_mod.VOICE_MAX]
    if not card:
        raise ProseError("The model wrote nothing: try again.", 502)
    return {"ok": True, "voice": card,
            "say": "A draft of your voice card: read it, change what is wrong, then save."}


def revise(rt, body: dict) -> dict[str, Any]:
    text = _text(body)
    flags = body.get("flags")
    if flags is not None and not isinstance(flags, list):
        raise ProseError("flags is a list (from /api/prose/check), or leave it out")
    p = prose.load(rt.cfg, rt.store)
    kw = {"site": _opt(body, "site", str), "kind": _opt(body, "kind", str),
          "limits": _opt(body, "limits", dict), "take": _opt(body, "take", str)}
    if flags is None:
        flags = prose.check(text, kw["site"], p, kind=kw["kind"], limits=kw["limits"],
                            take=kw["take"])["flags"]
    if not any(isinstance(f, dict) and (f.get("scope", "span") == "span"
                                        or f.get("rule") == "site.length") for f in flags):
        return {"text": text, "flags": flags, "rounds": 0, "changed": [],
                "say": "Nothing to fix here."}
    _key(rt)
    out = prose.revise(text, flags, p, complete=_complete(rt, PURPOSE, 1500), **kw)
    n = len(out["changed"])
    return {**out, "say": f"Fixed {n} span{'s' if n != 1 else ''}." if n else
            "The model changed nothing: edit it yourself."}


def _short_default() -> str:
    from .. import product
    return f"Drafted with {product.NAME}."


def writer_key_set(rt) -> bool:
    """Whether the OpenAI key for a writer's own model is set (the environment, or a name in
    the home's ``.env``): the names only; the key is never read here."""
    import os

    from .. import providers
    from ..providers.openai import KEY_ENV
    if os.environ.get(KEY_ENV):
        return True
    root = getattr(getattr(rt, "cfg", None), "root", None)
    try:
        return root is not None and KEY_ENV in providers._dotenv_names(root)
    except OSError:
        return False


def writer_key(rt, body: dict, door: str | None) -> dict[str, Any]:
    """``POST /api/prose/writer-key``: test the pasted key and keep it only when it passes.
    From the page's own session only (a credential: never the command line's token, an agent,
    the console or a cub). The key is not echoed, logged or sent back; a refusal's words are
    scrubbed of it."""
    from .. import providers, setup
    if door != "ui":
        raise ProseError("The OpenAI key is pasted on the page only (Settings › Posting › How "
                         "you write), never by a token, an assistant or a cub.", 403)
    raw = body.get("key")
    if not isinstance(raw, str) or not raw.strip():
        raise ProseError("Paste the key first.")
    key = raw.strip()
    root = getattr(getattr(rt, "cfg", None), "root", None)
    if root is None:
        raise ProseError("This Kranto has no home to keep a key in.", 409)
    try:
        got = providers.openai_key(root, key)
    except setup.SetupError as exc:
        raise ProseError(setup.scrub_key(str(exc), key)) from None
    except OSError as exc:
        raise ProseError(setup.scrub_key(f"the key works but could not be kept: {exc}", key),
                         500) from None
    detail = setup.scrub_key(str(got.get("detail") or ""), key)
    if not got.get("ok"):
        return {"ok": False, "detail": detail, "set": writer_key_set(rt),
                "say": f"Not kept: {detail}" if detail else "Not kept: OpenAI refused the key."}
    return {"ok": True, "detail": detail, "set": True,
            "say": "Kept: OpenAI answered. Choose an OpenAI model for a writer below."}


def _key(rt) -> None:
    llm = getattr(rt, "llm", None)
    if llm is not None and not getattr(llm, "has_key", True):
        raise ProseError("No model key is set: add one on Settings › Watching.", 409)


class ProseAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def rt(self):
        return self.app.rt

    async def _run(self, fn, request: Request | None = None):
        body: dict = {}
        if request is not None:
            from .app import MAX_JSON_BYTES, _json_body
            got = await _json_body(request)
            if got is None:
                return _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
            body = got
        try:
            out = await run_in_threadpool(fn, self.rt, body) if request is not None else \
                await run_in_threadpool(fn, self.rt)
        except ProseError as exc:
            return _error(exc.words, exc.code)
        return JSONResponse(out)

    async def get(self, request: Request):
        """The owner's prose profile: voice card, switches, checker rules, guides per site,
        lists, samples, disclosure, and what Kranto proposes to learn from their edits."""
        return await self._run(read)

    async def check(self, request: Request):
        return await self._run(check, request)

    async def voice(self, request: Request):
        return await self._run(voice, request)

    async def learn(self, request: Request):
        return await self._run(learn, request)

    async def draft_voice(self, request: Request):
        return await self._run(draft_voice, request)

    async def revise(self, request: Request):
        return await self._run(revise, request)

    async def writer_key(self, request: Request):
        """``POST /api/prose/writer-key``: the OpenAI key for a writer's own model, tested and
        kept (``writer_key``); never echoed."""
        from ..core import tickets
        from .auth import IDENTITY
        door = tickets.door_of(request.scope.get(IDENTITY))
        return await self._run(lambda rt, body: writer_key(rt, body, door), request)

    def routes(self) -> list[Route]:
        return [Route("/api/prose", self.get),
                Route("/api/prose/check", self.check, methods=["POST"]),
                Route("/api/prose/voice", self.voice, methods=["POST"]),
                Route("/api/prose/learn", self.learn, methods=["POST"]),
                Route("/api/prose/voice/draft", self.draft_voice, methods=["POST"]),
                Route("/api/prose/revise", self.revise, methods=["POST"]),
                Route("/api/prose/writer-key", self.writer_key, methods=["POST"])]
