"""Updates and the drain, as JSON (sections 3 and 4.4).

| Method and path            | Does                                                          |
|----------------------------|---------------------------------------------------------------|
| GET  /api/update           | the check's cache, the apply state, the settings, the history, |
|                            | and ``busy``: the job running, builds and fixes running, hold |
| POST /api/update           | {to?, when}: stage if needed, start the helper (202); 409 when |
|                            | one runs, nothing is staged, or the set does not verify       |
| POST /api/update/cancel    | while it waits for builds: let go, change nothing             |
| POST /api/update/rollback  | start the helper with --to previous                           |
| POST /api/update/check     | check now; the refreshed view                                 |
| POST /api/update/settings  | {auto, quiet_window, channel}: the config's ``update:`` keys |
| POST /api/update/promote   | {tag}: the owner's press, Promote to stable (the maintainer's  |
|                            | install only): writes update/promote.json, starts the gate's  |
|                            | unit (202); 403 not the maintainer's, 409 no open candidate   |
| POST /api/hold             | {reason, stop_builds?}: no job starts, the loop lane is held |
| DELETE /api/hold           | release it                                                    |

Every write goes through the same guard as every route (an allowed Host, a same-origin
``Origin``). ``/api/status`` carries ``update`` (``check.summary``) for the header pill.
"""

from __future__ import annotations

import re

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .. import config as config_mod
from ..update import check

SETTABLE = ("auto", "quiet_window", "channel")
PREVIEW_OFF = ("Updates are off on the preview: it runs a branch, and kranto-preview refresh "
               "brings its newest commits")


def _error(message: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


GATE_UNIT = "kranto-release-gate.service"


def _start_gate() -> tuple[bool, str]:
    """Start the gate's unit now (it reads update/promote.json); when that cannot be done, its
    hourly timer reads the file within the hour."""
    import subprocess

    try:
        r = subprocess.run(["systemctl", "--user", "start", "--no-block", GATE_UNIT],
                           capture_output=True, text=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"could not start {GATE_UNIT} ({type(exc).__name__}); its hourly timer " \
                      "takes it within the hour"
    if r.returncode != 0:
        return False, f"could not start {GATE_UNIT} ({(r.stderr or '').strip()[:120]}); its " \
                      "hourly timer takes it within the hour"
    return True, f"{GATE_UNIT} started: cutting, then rc_check, about an hour"



class UpdateAPI:
    def __init__(self, app) -> None:
        self.app = app

    @property
    def home(self):
        return self.app.rt.cfg.root

    async def _body(self, request: Request):
        from .app import MAX_JSON_BYTES, _json_body

        body = await _json_body(request)
        if body is None:
            return None, _error(f"expected a JSON object under {MAX_JSON_BYTES} bytes")
        return body, None

    def busy(self) -> dict:
        """What an update waits for: the scheduler's job and the cubs' runs. ``builds`` and
        ``fixes`` stay in the answer for a page that reads them, always 0: builds are not part
        of Kranto any more."""
        sched = self.app.scheduler
        cubs = getattr(self.app.rt, "cubs", None)
        return {"job": sched.running if sched else None, "builds": 0, "fixes": 0,
                "hold": sched.hold if sched else None,
                "cubs": cubs.busy() if cubs is not None else []}

    def get(self, request: Request):
        return JSONResponse({**check.view(self.home), "busy": self.busy()})

    async def check_now(self, request: Request):
        # the preview never updates: it says so at once, never "Checking…" until a
        # network call gives up (10, Gemini 13)
        from .. import preview
        if preview.enabled(self.home):
            return JSONResponse({**check.view(self.home), "busy": self.busy(), "ok": False,
                                 "off": True, "error": PREVIEW_OFF})
        # a click is a run: its runs row is the update check's, so its Fix row goes when
        # it works and it counts as a try when it does not
        await run_in_threadpool(check.check_pressed, self.home, self.app.rt.store)
        return JSONResponse({**check.view(self.home), "busy": self.busy()})

    async def set_settings(self, request: Request):
        from ..launcher import set_in_section

        body, err = await self._body(request)
        if err:
            return err
        wanted = {k: body[k] for k in SETTABLE if k in body}
        if not wanted:
            return _error(f"nothing to set (one of {', '.join(SETTABLE)})")
        current = check.settings(self.home)
        merged = {f: getattr(current, f) for f in current.__dataclass_fields__}
        merged.update({k: str(v) for k, v in wanted.items()})
        try:
            config_mod.parse_update(merged)
        except config_mod.ConfigError as exc:
            return _error(str(exc))
        path = config_mod.config_path(self.home)
        text = path.read_text()
        for key, value in wanted.items():
            text = set_in_section(text, "update", key, f'"{value}"')
        tmp = path.with_name(path.name + ".update-tmp")
        tmp.write_text(text)
        tmp.chmod(path.stat().st_mode & 0o777)
        tmp.replace(path)
        return JSONResponse({**check.view(self.home), "busy": self.busy()})

    async def set_hold(self, request: Request):
        body, err = await self._body(request)
        if err:
            return err
        if self.app.scheduler is None:
            return _error("this server runs no scheduler: nothing to hold", 409)
        hold = await run_in_threadpool(
            self.app.scheduler.set_hold, str(body.get("reason") or "update")[:200],
            stop_builds=bool(body.get("stop_builds")))
        return JSONResponse({"hold": hold, "busy": self.busy()})

    def release_hold(self, request: Request):
        released = self.app.scheduler.release_hold() if self.app.scheduler else False
        return JSONResponse({"released": released, "busy": self.busy()})

    # -- restart to update (section 4) -----------------------------------------------------

    @staticmethod
    def _cannot():
        if not check.can_apply():
            return _error("this server cannot restart itself (not started by systemd, or no "
                          "systemd-run): run 'kranto update'", 409)
        return None

    def _launch(self, to: str, when: str):
        from .. import legacy
        from ..update import launch as launch_mod

        try:
            started = launch_mod.launch(self.home, to, when=when, port=self.app.port or 8765,
                                        unit=legacy.unit_name(),
                                        keep=check.settings(self.home).keep_backups)
        except launch_mod.LaunchError as exc:
            return _error(str(exc), 409)
        return JSONResponse({**started, "state": "requested"}, status_code=202)

    async def apply(self, request: Request):
        from ..update.apply import SetError, releases_dir, tag_version, verify_set
        from ..update.sources import SourceError

        body, err = await self._body(request)
        if err:
            return err
        if self._cannot():
            return self._cannot()
        when = str(body.get("when") or "after-build")
        if when not in ("after-build", "now"):
            return _error("when must be after-build or now")
        to = str(body.get("to") or "")
        if not to:
            view = check.view(self.home)
            staged = view.get("staged") or {}
            if not view.get("available") or staged.get("version") != view.get("available"):
                return _error("nothing staged to update to: Check for updates first", 409)
            to = staged["tag"]
        if not re.fullmatch(r"v\d+\.\d+\.\d+(-rc\d+|-dev\d+)?", to):
            return _error("to must be a release tag, vX.Y.Z or a nightly build's vX.Y.0-devN")
        try:
            if not (releases_dir(self.home) / to).is_dir():
                await run_in_threadpool(check.stage_tag, self.home, to)
            await run_in_threadpool(verify_set, releases_dir(self.home) / to, tag_version(to))
        except (SetError, SourceError) as exc:
            return _error(f"{to} cannot be installed: {exc}", 409)
        return self._launch(to, when)

    async def promote(self, request: Request):
        """The owner's press: stable is always a choice the owner makes. It
        writes ``update/promote.json`` and starts the gate's unit, which cuts, checks and
        releases; Kranto never cuts from inside the server."""
        from datetime import UTC, datetime

        from ..stored.release import PromoteAsk
        from .auth import IDENTITY, is_owner

        body, err = await self._body(request)
        if err:
            return err
        if not check.settings(self.home).maintainer:
            return _error("only the maintainer's install promotes to stable (update.maintainer: "
                          "true in kranto.yaml, written by hand)", 403)
        ident = request.scope.get(IDENTITY)
        if self.app.auth.require and not is_owner(ident):
            return _error("only the owner promotes to stable", 403)
        cand = check.candidate(self.home)
        tag = str(body.get("tag") or "")
        if cand is None or cand.state not in ("candidate", "blocked"):
            return _error("there is no candidate for stable now"
                          + (f" ({cand.state})" if cand is not None else ""), 409)
        if cand.blocking:
            return _error("a health check blocks it: " + "; ".join(cand.blocking), 409)
        if not cand.open or tag != cand.tag:
            return _error(f"the candidate is {cand.tag}, not {tag or 'nothing'}: read it again",
                          409)
        ask = PromoteAsk(tag=tag, by=str((ident or {}).get("origin") or "ui"),
                         at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
        path = check.promote_path(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(ask.to_json())
        tmp.replace(path)
        started, said = await run_in_threadpool(_start_gate)
        return JSONResponse({**check.view(self.home), "busy": self.busy(),
                             "promote": {"tag": tag, "asked": ask.at, "started": started,
                                         "said": said}}, status_code=202)

    def cancel(self, request: Request):
        from ..update.apply import cancel_path

        st = check.apply_state(self.home)
        if st.get("state") not in ("requested", "draining"):
            return _error("only an update that is still waiting can be cancelled", 409)
        cancel_path(self.home).touch()
        return JSONResponse({"cancelling": True, "state": st.get("state")})

    def rollback(self, request: Request):
        from ..update.apply import previous_path, read_json

        if self._cannot():
            return self._cannot()
        prev = read_json(previous_path(self.home), None)
        if not prev or prev.get("kind") not in ("wheels", "git"):
            return _error("there is no previous version recorded", 409)
        return self._launch("previous", "after-build")

    def routes(self) -> list[Route]:
        return [
            Route("/api/update", self.get),
            Route("/api/update", self.apply, methods=["POST"]),
            Route("/api/update/cancel", self.cancel, methods=["POST"]),
            Route("/api/update/rollback", self.rollback, methods=["POST"]),
            Route("/api/update/check", self.check_now, methods=["POST"]),
            Route("/api/update/settings", self.set_settings, methods=["POST"]),
            Route("/api/update/promote", self.promote, methods=["POST"]),
            Route("/api/hold", self.set_hold, methods=["POST"]),
            Route("/api/hold", self.release_hold, methods=["DELETE"]),
        ]
