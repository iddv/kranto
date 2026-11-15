"""The cub's end of ``cub/1`` (protocol): newline-delimited JSON-RPC 2.0 over its own
stdin and stdout, one object per line, at most 1 MiB a line. The cub speaks first (``hello``),
then answers the host's requests one at a time.

A reader thread takes every line from the host as it arrives, so the host is heard while a
handler works: ``ping`` is answered at once, ``cancel`` sets ``ctx.cancelled``, ``shutdown``
lets the process exit when the handler returns. Everything else (the answers to the cub's own
calls, the host's next request) goes to the main thread in order. The handlers stay
synchronous: one call in flight, ids increasing from 1."""

from __future__ import annotations

import json
import platform
import queue
import sys
import threading
import time
import traceback
from typing import BinaryIO

from . import __version__
from .context import Context
from .cub import Cub
from .dispatch import HOST_METHODS, DispatchError, run_request
from .errors import (
    HANDLER_FAILED,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    TOO_LARGE,
    HostError,
    from_wire,
)

API = "cub/1"
LINE_BYTES = 1_048_576
_EOF = object()


class Closed(Exception):
    """The host closed the pipe."""


class Session:
    def __init__(self, cub: Cub, *, cub_id: str, version: str, manifest_hash: str,
                 rfile: BinaryIO, wfile: BinaryIO) -> None:
        self.cub, self.cub_id, self.version = cub, cub_id, version
        self.manifest_hash = manifest_hash
        self.rfile, self.wfile = rfile, wfile
        self.next_id = 0
        self.hello: dict = {}
        self.cancelled = threading.Event()
        self.stopping = threading.Event()
        self._inbox: queue.Queue = queue.Queue()
        self._write = threading.Lock()
        self._busy = threading.Event()          # a host request is being handled
        self._reader = threading.Thread(target=self._read_loop, name="cub-reader", daemon=True)

    # -- framing --------------------------------------------------------------------------------

    def send(self, obj: dict) -> None:
        line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        if len(line) >= LINE_BYTES:
            raise HostError(TOO_LARGE, f"a message of {len(line)} bytes is over the 1 MiB line",
                            {"limit": LINE_BYTES, "got": len(line)})
        with self._write:
            self.wfile.write(line + b"\n")
            self.wfile.flush()

    def _reply(self, mid, result: dict | None = None, error: dict | None = None) -> None:
        out = {"jsonrpc": "2.0", "id": mid}
        if error is not None:
            out["error"] = error
        else:
            out["result"] = result if isinstance(result, dict) else {}
        self.send(out)

    def _read_loop(self) -> None:
        while True:
            try:
                line = self.rfile.readline(LINE_BYTES + 2)
            except (OSError, ValueError):
                line = b""
            if not line:
                self._inbox.put(_EOF)
                return
            if not line.strip():
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                print("cub/1: a line from the host was not JSON", file=sys.stderr)
                continue
            if not isinstance(msg, dict):
                continue
            method = msg.get("method")
            if "id" not in msg and method == "cancel":
                self.cancelled.set()
            elif "id" not in msg and method == "shutdown":
                self.stopping.set()
                self._inbox.put(_EOF if not self._busy.is_set() else msg)
            elif "id" in msg and method == "ping":
                try:
                    self._reply(msg["id"], {"pong": True})
                except (OSError, ValueError):
                    return
            elif "id" in msg and method in HOST_METHODS and self._busy.is_set():
                # the host never sends a second request while one is open; say so
                try:
                    self._reply(msg["id"], error={"code": INVALID_REQUEST,
                                                  "message": "the cub is busy with a request"})
                except (OSError, ValueError):
                    return
            else:
                self._inbox.put(msg)

    def _take(self) -> dict:
        msg = self._inbox.get()
        if msg is _EOF:
            self._inbox.put(_EOF)               # every later take sees the end too
            raise Closed("the host closed the pipe")
        return msg

    # -- the cub's calls ------------------------------------------------------------------------

    def call(self, method: str, params: dict) -> dict:
        """One cub→host call; its result, or the error raised as its exception."""
        self.next_id += 1
        mid = self.next_id
        self.send({"jsonrpc": "2.0", "id": mid, "method": method, "params": params})
        while True:
            msg = self._take()
            if "method" in msg:
                if "id" in msg:
                    self._reply(msg["id"], error={"code": INVALID_REQUEST,
                                                  "message": "the cub is busy with a request"})
                continue
            if msg.get("id") != mid:
                continue
            if "error" in msg:
                raise from_wire(msg["error"] if isinstance(msg["error"], dict) else {})
            return msg.get("result") if isinstance(msg.get("result"), dict) else {}

    # -- the session ----------------------------------------------------------------------------

    def say_hello(self) -> dict:
        self.hello = self.call("hello", {
            "api": API, "id": self.cub_id, "version": self.version,
            "manifest_hash": self.manifest_hash, "sdk": __version__,
            "python": platform.python_version(), "handlers": self.cub.handlers()})
        self.hello_at = time.monotonic()                 # when hello.now was the host's time
        return self.hello

    def _context(self, method: str, params: dict) -> Context:
        mode = params.get("mode")
        return Context(self.call, cub_id=self.cub_id, version=self.version, hello=self.hello,
                       clock_at=getattr(self, "hello_at", None), run_uuid=params.get("run_uuid"),
                       mode=mode if isinstance(mode, dict) else None,
                       stage=method == "stage.run", cancelled=self.cancelled.is_set)

    def _handle(self, msg: dict) -> None:
        method, mid, params = msg.get("method"), msg.get("id"), msg.get("params")
        if not isinstance(params, dict):
            self._reply(mid, error={"code": INVALID_REQUEST, "message": "params is an object"})
            return
        if method not in HOST_METHODS:
            self._reply(mid, error={"code": METHOD_NOT_FOUND, "message": f"no {method}"})
            return
        self.cancelled.clear()
        self._busy.set()
        try:
            result = run_request(self.cub, self.cub_id, method, params,
                                 self._context(method, params))
        except Closed:
            raise
        except DispatchError as exc:
            self._reply(mid, error={"code": exc.code, "message": exc.message})
            return
        except Exception as exc:  # noqa: BLE001 - the handler's failure: its class only
            traceback.print_exc(file=sys.stderr)
            self._reply(mid, error={"code": HANDLER_FAILED,
                                    "message": f"the handler raised {type(exc).__name__}",
                                    "data": {"exception": type(exc).__name__}})
            return
        finally:
            self._busy.clear()
        try:
            self._reply(mid, result)
        except HostError as exc:                # the answer is over the line's size
            self._reply(mid, error={"code": HANDLER_FAILED, "message": exc.message,
                                    "data": {"exception": "TooLarge"}})

    def serve(self) -> int:
        """Answer the host's requests until it closes the pipe or sends ``shutdown``."""
        self._reader.start()
        try:
            self.say_hello()
        except HostError as exc:
            print(f"cub/1: the host refused the hello: {exc.message}", file=sys.stderr)
            return 3
        except Closed:
            return 0
        while not self.stopping.is_set():
            try:
                msg = self._take()
            except Closed:
                return 0
            if msg.get("method") == "shutdown":
                return 0
            if "id" not in msg or "method" not in msg:
                continue                        # a stray answer: nothing waits for it
            try:
                self._handle(msg)
            except Closed:
                return 0
        return 0
