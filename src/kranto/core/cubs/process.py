"""One cub process and its pipes (protocol).

The host speaks ``cub/1`` on the process's stdin and stdout: one JSON object a line, at most
1 MiB. A reader thread takes every line the cub writes and counts the cub's unanswered
requests (more than 8 is a flood); a second reader takes stderr into the cub's log. The host
sends one request at a time (``request``) and, while it waits, answers the cub's own calls in
the order they came, each through ``dispatch``. A request has a deadline: past it the host sends
``cancel``, then SIGTERM 5 s later, SIGKILL 3 s after that.

What ends a run, and how it is said: ``crashed`` (the process exited; ``memory`` when
the scope counted an OOM kill, ``killed`` for a SIGKILL it did not count), ``deadline``,
``protocol`` (three lines that are not JSON, a line over 1 MiB, a malformed answer, an error
answer other than -32020), ``flood`` (nine unanswered calls, or 2,000 calls in one run),
``no hello``, ``hello refused``. A handler that raised is not a protocol failure: the run fails
with the handler's exception class.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import queue
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

LINE_BYTES = 1_048_576
ERR_PIECE = 65_536
IN_FLIGHT = 8
CALLS_PER_RUN = 2000
HELLO_S = 10
CANCEL_GRACE_S = 5
TERM_GRACE_S = 3
PARSE_STRIKES = 3
_EOF = ("eof",)


class RpcError(Exception):
    """An error a cub→host call is answered with (protocol)."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.data = code, message, data or {}

    def wire(self) -> dict:
        out = {"code": self.code, "message": self.message}
        if self.data:
            out["data"] = self.data
        return out


class HelloRefused(RpcError):
    """The host refuses the hello; ``pause`` says why the cub is paused (None: not paused)."""

    def __init__(self, code: int, message: str, data: dict | None = None,
                 pause: str | None = None) -> None:
        super().__init__(code, message, data)
        self.pause = pause


class CubFailed(Exception):
    """A run that failed: ``kind`` is one of crashed, deadline, protocol, flood, no hello,
    hello refused, handler, halted, busy; ``words`` what the run row and the page say."""

    COUNTS = ("crashed", "deadline", "protocol", "no hello", "flood")

    def __init__(self, kind: str, words: str, *, pause: str | None = None,
                 exception: str | None = None) -> None:
        super().__init__(words)
        self.kind, self.words, self.pause, self.exception = kind, words, pause, exception

    @property
    def counts(self) -> bool:
        """Whether it counts toward the three failures in a row that pause a cub."""
        return self.kind in self.COUNTS


class CubProcess:
    """The process for one cub. ``dispatch(method, params) -> result`` answers its calls (and
    raises ``RpcError``); ``hello(params) -> result`` checks its hello (and raises
    ``HelloRefused``); ``stderr(text)`` takes its log lines."""

    def __init__(self, *, cid: str, argv: list[str], env: dict, preexec: Callable | None,
                 unit: str | None, mode: str, hello: Callable[[dict], dict],
                 stderr: Callable[[str], None], cwd: str | None = None) -> None:
        self.cid, self.argv, self.env, self.preexec = cid, argv, env, preexec
        self.unit, self.mode = unit, mode
        self._hello, self._stderr = hello, stderr
        self.cwd = cwd
        self.proc: subprocess.Popen | None = None
        self.inbox: queue.Queue = queue.Queue()
        self._write = threading.Lock()
        self._pending = 0                          # the cub's calls not yet answered
        self._pending_lock = threading.Lock()
        self._n = 0
        self.started_at = 0.0
        self.last_used = 0.0
        self.busy = False
        self.deadline_at: float | None = None
        self.host_said: str | None = None      # the host's last refusal in a request (its words)
        self.cgroup: Path | None = None
        self.oom_kills = 0
        self.hello_result: dict = {}
        self.dead = False

    # -- starting -------------------------------------------------------------------------------

    def start(self) -> dict:
        """Spawn the process and take its hello; the hello's result. Raises ``CubFailed``."""
        self.proc = subprocess.Popen(self.argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, env=self.env,
                                     preexec_fn=self.preexec, close_fds=True, cwd=self.cwd)
        self.started_at = self.last_used = time.monotonic()
        threading.Thread(target=self._read_stdout, name=f"cub-{self.cid}-out",
                         daemon=True).start()
        threading.Thread(target=self._read_stderr, name=f"cub-{self.cid}-err",
                         daemon=True).start()
        if self.mode == "scope":
            threading.Thread(target=self._watch_cgroup, name=f"cub-{self.cid}-cg",
                             daemon=True).start()
        try:
            msg = self.inbox.get(timeout=HELLO_S)
        except queue.Empty:
            self.kill()
            raise CubFailed("no hello", "failed: no hello (nothing in 10 s)") from None
        if msg is _EOF:
            raise self._crashed("crashed before hello")
        if not isinstance(msg, dict) or msg.get("method") != "hello" or "id" not in msg \
                or not isinstance(msg.get("params"), dict):
            self.kill()
            raise CubFailed("no hello", "failed: no hello (it said something else first)")
        self._answered()
        try:
            result = self._hello(msg["params"])
        except HelloRefused as exc:
            self._send({"jsonrpc": "2.0", "id": msg["id"], "error": exc.wire()})
            self.shutdown("hello")
            raise CubFailed("hello refused", f"failed: hello refused: {exc.message}",
                            pause=exc.pause) from None
        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": result})
        self.hello_result = result
        return result

    # -- the pipes ------------------------------------------------------------------------------

    def _send(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        with self._write:
            try:
                self.proc.stdin.write(line + b"\n")
                self.proc.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass                                   # the reader sees the end

    def _read_stdout(self) -> None:
        out = self.proc.stdout
        while True:
            try:
                line = out.readline(LINE_BYTES + 1)
            except (OSError, ValueError):
                line = b""
            if not line:
                self.inbox.put(_EOF)
                return
            if len(line) > LINE_BYTES or (len(line) == LINE_BYTES + 1
                                          and not line.endswith(b"\n")):
                self.inbox.put(("too_long",))
                return
            if not line.strip():
                continue
            try:
                msg = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, ValueError):
                self.inbox.put(("parse",))
                continue
            if isinstance(msg, list):
                self.inbox.put(("batch",))
                continue
            if not isinstance(msg, dict):
                self.inbox.put(("parse",))
                continue
            if "method" in msg and "id" in msg:
                with self._pending_lock:
                    self._pending += 1
                    flood = self._pending > IN_FLIGHT
                if flood:
                    self.inbox.put(("flood", msg.get("id")))
                    return
            self.inbox.put(msg)

    def _read_stderr(self) -> None:
        """Take stderr in pieces of at most ``ERR_PIECE`` bytes: a line's first piece goes to
        the log (cut to 4,000 characters), the rest of a longer line is read and dropped."""
        err = self.proc.stderr
        inside = False                                 # in a line whose start was logged
        while True:
            try:
                piece = err.readline(ERR_PIECE)
            except (OSError, ValueError):
                return
            if not piece:
                return
            if not inside:
                # a log line that cannot be written must never stop the reader
                with contextlib.suppress(Exception):
                    self._stderr(piece.decode("utf-8", "replace").rstrip("\n")[:4000])
            inside = not piece.endswith(b"\n")

    def _answered(self) -> None:
        with self._pending_lock:
            self._pending = max(0, self._pending - 1)

    def _reply(self, mid, result: dict | None = None, error: dict | None = None) -> None:
        obj: dict = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            obj["error"] = error
        else:
            obj["result"] = result if isinstance(result, dict) else {}
        self._send(obj)

    def _watch_cgroup(self) -> None:
        """Under a scope: find the process's cgroup and keep its ``oom_kill`` count, read
        while the scope exists (it is collected when the process ends)."""
        for _ in range(50):
            if self.proc.poll() is not None:
                return
            try:
                text = Path(f"/proc/{self.proc.pid}/cgroup").read_text()
                rel = text.strip().split("::", 1)[-1]
                if self.unit and self.unit in rel:
                    self.cgroup = Path("/sys/fs/cgroup") / rel.lstrip("/")
                    break
            except OSError:
                return
            time.sleep(0.02)
        while self.cgroup is not None and self.proc.poll() is None:
            self._read_oom()
            time.sleep(0.25)
        self._read_oom()

    def _read_oom(self) -> None:
        try:
            for line in (self.cgroup / "memory.events").read_text().splitlines():
                name, _, value = line.partition(" ")
                if name == "oom_kill":
                    self.oom_kills = max(self.oom_kills, int(value))
        except (OSError, ValueError, TypeError):
            pass

    # -- a request ------------------------------------------------------------------------------

    def _crashed(self, what: str) -> CubFailed:
        code = None
        if self.proc is not None:
            try:
                code = self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.kill()
                code = self.proc.returncode
        self.dead = True
        if self.cgroup is not None:
            self._read_oom()
        shown = 128 - code if code is not None and code < 0 else code
        # "memory" only when the scope counted an OOM kill. An exit 137 it did not count is a
        # SIGKILL from elsewhere as likely (Toot's "memory" failure of 2026-10-21 was an
        # older Kranto's reaper killing every kranto-cub-* scope of the user; the journal said
        # "SIGKILL ... on client request"), so it is said as killed, not guessed as memory
        memory = self.oom_kills > 0
        killed = not memory and shown == 137
        words = f"failed: {what} (exit {shown}{', memory' if memory else ''}" \
                f"{', killed' if killed else ''})"
        return CubFailed("crashed", words)

    def _protocol(self, why: str) -> CubFailed:
        self.kill()
        return CubFailed("protocol", f"failed: protocol ({why})")

    def request(self, method: str, params: dict, deadline_s: float,
                dispatch: Callable[[str, dict], dict], *, cancel_why: str = "deadline") -> dict:
        """Send one host→cub request and answer the cub's calls until its answer comes; the
        result. Raises ``CubFailed``."""
        if self.dead or self.proc is None or self.proc.poll() is not None:
            raise CubFailed("crashed", "failed: the process is gone")
        self._n += 1
        mid = f"h{self._n}"
        self.busy = True
        started = time.monotonic()
        self.deadline_at = started + deadline_s
        calls = strikes = 0
        cancelled = False
        self.host_said = None              # a new request: nothing refused in it yet
        try:
            self._send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
            while True:
                remaining = self.deadline_at - time.monotonic()
                if remaining <= 0:
                    if not cancelled:
                        cancelled = True
                        self._send({"jsonrpc": "2.0", "method": "cancel",
                                    "params": {"id": mid, "why": cancel_why}})
                        self.deadline_at = time.monotonic() + CANCEL_GRACE_S
                        continue
                    self.kill()
                    raise CubFailed("deadline", f"failed: deadline ({deadline_s:g} s)")
                try:
                    msg = self.inbox.get(timeout=min(remaining, 1.0))
                except queue.Empty:
                    continue
                if msg is _EOF:
                    raise self._crashed("crashed")
                if isinstance(msg, tuple):
                    if msg[0] == "too_long":
                        self._reply(None, error={"code": -32011,
                                                 "message": "a line over 1 MiB"})
                        raise self._protocol("a line over 1 MiB")
                    if msg[0] == "flood":
                        self._reply(msg[1], error={"code": -32012, "message": "more than 8 "
                                                                             "calls in flight"})
                        self.kill()
                        raise CubFailed("flood", "failed: flood (more than 8 calls in flight)")
                    if msg[0] == "batch":
                        self._reply(None, error={"code": -32600,
                                                 "message": "one message a line, never a batch"})
                        continue
                    strikes += 1
                    self._reply(None, error={"code": -32700, "message": "not JSON"})
                    if strikes >= PARSE_STRIKES:
                        raise self._protocol("three lines that were not JSON")
                    continue
                if "method" in msg:
                    if "id" not in msg:
                        continue                          # a notification from a cub: ignored
                    calls += 1
                    if calls > CALLS_PER_RUN:
                        self._reply(msg["id"], error={"code": -32012, "message":
                                                      f"more than {CALLS_PER_RUN} calls in a run"})
                        self.kill()
                        raise CubFailed("flood", f"failed: flood ({CALLS_PER_RUN} calls in a run)")
                    self._answer(msg, dispatch)
                    continue
                if msg.get("id") != mid:
                    continue                              # an answer to nothing: dropped
                if "error" in msg:
                    err = msg["error"] if isinstance(msg["error"], dict) else {}
                    if err.get("code") == -32020:
                        exc = str((err.get("data") or {}).get("exception") or "Exception")[:80]
                        # the cub says its exception's class only (it is not trusted for
                        # more); what Kranto itself last refused it in this request is said
                        # beside it, in Kranto's words: "the model did not answer: FatalLLMError:
                        # HTTP 401 …" makes a refused key one incident
                        after = (f" after Kranto answered: {self.host_said}"
                                 if self.host_said else "")
                        raise CubFailed(
                            "handler", f"failed: the handler raised {exc}{after}", exception=exc
                        )
                    raise self._protocol(f"an error answer {err.get('code')}")
                if not isinstance(msg.get("result"), dict):
                    raise self._protocol("an answer with no result")
                return msg["result"]
        finally:
            self.busy = False
            self.deadline_at = None
            self.last_used = time.monotonic()

    def _answer(self, msg: dict, dispatch) -> None:
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params")
        try:
            if isinstance(mid, bool) or not isinstance(mid, int) or mid < 1:
                raise RpcError(-32600, "a cub's ids are positive whole numbers")
            if method == "hello":
                raise RpcError(-32600, "hello is said once")
            if not isinstance(method, str):
                raise RpcError(-32600, "method is text")
            if not isinstance(params, dict):
                raise RpcError(-32602, "params is an object")
            result = dispatch(method, params)
        except RpcError as exc:
            self._answered()
            self.host_said = str(exc.message)[:400]
            self._reply(mid, error=exc.wire())
            return
        except Exception as exc:  # noqa: BLE001 - the host's own bug: logged by the caller
            self._answered()
            self._reply(
                mid, error={"code": -32603, "message": f"the host failed: {type(exc).__name__}"}
            )
            raise
        self._answered()
        line = json.dumps({"jsonrpc": "2.0", "id": mid, "result": result})
        if len(line.encode("utf-8")) >= LINE_BYTES:
            self._reply(mid, error={"code": -32011, "message": "the answer is over 1 MiB"})
            return
        self._reply(mid, result)

    def ping(self) -> bool:
        try:
            return self.request("ping", {}, 5, lambda m, p: {}).get("pong") is True
        except CubFailed:
            return False

    # -- ending ---------------------------------------------------------------------------------

    @property
    def alive(self) -> bool:
        return not self.dead and self.proc is not None and self.proc.poll() is None

    def shutdown(
        self, why: str, grace_s: float = CANCEL_GRACE_S, term_grace_s: float = TERM_GRACE_S
    ) -> None:
        """Ask it to exit; close its stdin; SIGTERM after ``grace_s`` (5 s), SIGKILL
        ``term_grace_s`` (3 s) later."""
        if self.proc is None:
            return
        self._send({"jsonrpc": "2.0", "method": "shutdown", "params": {"why": why}})
        with contextlib.suppress(OSError):
            self.proc.stdin.close()
        try:
            self.proc.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            self.kill(term_grace_s)
        self.dead = True

    def kill(self, grace_s: float = TERM_GRACE_S) -> None:
        """SIGTERM now (the whole sandbox goes with bwrap), SIGKILL after ``grace_s`` (3 s),
        and the scope's cgroup emptied if anything is left in it."""
        if self.proc is None:
            return
        if self.proc.poll() is None:
            try:
                self.proc.send_signal(signal.SIGTERM)
                self.proc.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                with contextlib.suppress(subprocess.TimeoutExpired):
                    self.proc.wait(timeout=TERM_GRACE_S)
            except OSError:
                pass
        if self.cgroup is not None:
            self._read_oom()
        if self.unit and self.mode == "scope":
            kill_unit(self.unit)
        self.dead = True


def kill_unit(unit: str) -> None:
    """SIGKILL whatever is left in a ``kranto-cub-*`` scope (a leak after a crash)."""
    from .sandbox import scope_env

    with contextlib.suppress(OSError, subprocess.TimeoutExpired):
        subprocess.run(
            ["systemctl", "--user", "kill", "--signal=SIGKILL", f"{unit}.scope"],
            capture_output=True,
            timeout=10,
            env=scope_env(),
        )


def scope_prefix(root: Path) -> str:
    """``kranto-cub-<home6>-``: the start of every scope one kranto home's cubs run in, from its
    cubs folder. Two Kranto on one account (the owner's, a scratch copy, a test run) share the
    user manager, so each kills only scopes with its own prefix."""
    tag = hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:6]
    return f"kranto-cub-{tag}-"


def leftover_units(prefix: str = "kranto-cub-") -> list[str]:
    """Running scopes whose name starts with ``prefix`` (the reaper kills the ones of its own
    prefix no process of the table owns)."""
    from .sandbox import scope_env

    try:
        out = subprocess.run(
            [
                "systemctl",
                "--user",
                "list-units",
                "--type=scope",
                "--no-legend",
                "--plain",
                f"{prefix}*",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            env=scope_env(),
        ).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [line.split()[0].removesuffix(".scope") for line in out.splitlines() if line.strip()]
