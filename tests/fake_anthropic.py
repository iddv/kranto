"""A fake Claude API on loopback, for tests of the Anthropic provider: a real HTTP server on
127.0.0.1 (an ephemeral port) that records every request and answers ``/v1/messages`` and
``/v1/models`` as the API does. No test reaches Anthropic."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1"]


def message(text: str = '{"pass": true, "reason": "ok"}', *, model: str = "claude-haiku-5-5",
            stop: str = "end_turn", input_tokens: int = 300, output_tokens: int = 80,
            cache_read: int = 0, cache_write: int = 0, thinking: bool = True) -> dict:
    content = [{"type": "thinking", "thinking": "considering", "signature": "x"}] if thinking \
        else []
    content.append({"type": "text", "text": text})
    return {"id": "msg_test", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop,
            "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_input_tokens": cache_read,
                      "cache_creation_input_tokens": cache_write}}


def error(kind: str, text: str, **details) -> dict:
    err = {"type": kind, "message": text}
    if details:
        err["details"] = details
    return {"type": "error", "error": err}


class FakeAnthropic:
    """``replies``: what ``/v1/messages`` answers, in order (``(status, body, headers)``);
    once they run out, a default success. ``key``: the only key accepted on ``/v1/models``
    (None: any). ``requests``: every request seen as ``(method, path, headers, body)``."""

    def __init__(self):
        self.replies: list[tuple[int, dict, dict]] = []
        self.requests: list[tuple[str, str, dict, dict | None]] = []
        self.key: str | None = None
        self.models = list(MODELS)
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _answer(self, status: int, body: dict, headers: dict | None = None):
                raw = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(raw)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(raw)

            def _record(self, body):
                fake.requests.append((self.command, self.path,
                                      {k.lower(): v for k, v in self.headers.items()}, body))

            def do_GET(self):
                self._record(None)
                if not self.path.startswith("/v1/models"):
                    return self._answer(404, error("not_found_error", "no such path"))
                if fake.key is not None and self.headers.get("x-api-key") != fake.key:
                    return self._answer(401, error("authentication_error", "invalid x-api-key"))
                self._answer(200, {"data": [{"type": "model", "id": m} for m in fake.models],
                                   "has_more": False})

            def do_POST(self):
                length = int(self.headers.get("content-length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                self._record(body)
                if self.path != "/v1/messages":
                    return self._answer(404, error("not_found_error", "no such path"))
                if fake.replies:
                    status, reply, headers = fake.replies.pop(0)
                else:
                    status, reply, headers = 200, message(model=body.get("model", "")), {}
                self._answer(status, reply, {"anthropic-ratelimit-requests-remaining": "999",
                                             **headers})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def reply(self, status: int, body: dict, headers: dict | None = None) -> None:
        self.replies.append((status, body, headers or {}))

    @property
    def posts(self) -> list[dict]:
        return [body for method, _, _, body in self.requests if method == "POST"]

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
