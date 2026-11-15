"""A fake Anthropic Messages API on 127.0.0.1 for the real Claude Code CLI (no model, no
network): it plays a scripted model. ``FakeAPI(steps)``: each step is ``(tool, input)``; a
request whose conversation holds ``n`` tool results gets step ``n`` as a ``tool_use`` (when the
request offers that tool), else a short text, so a run makes the calls in order and ends.
Every request's login headers are kept (``auth``: ``(bearer, x-api-key)`` pairs), so a test can
see which way the token arrived without printing it. Streaming (SSE) and plain JSON both."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _tool_results(body: dict) -> int:
    n = 0
    for m in body.get("messages") or []:
        c = m.get("content")
        if isinstance(c, list):
            n += sum(1 for x in c if isinstance(x, dict) and x.get("type") == "tool_result")
    return n


class FakeAPI:
    def __init__(self, steps=()):
        self.steps = list(steps)
        self.auth: list[tuple[str, str]] = []
        self.requests: list[dict] = []
        self.lock = threading.Lock()
        api = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                api._keep(self, None)
                self._send({"type": "error", "error": {"type": "not_found_error",
                                                       "message": "fake"}}, 404)

            def do_HEAD(self):
                self.send_response(200)
                self.end_headers()

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("content-length") or 0))
                try:
                    body = json.loads(raw or b"{}")
                except ValueError:
                    body = {}
                api._keep(self, body)
                if "count_tokens" in self.path:
                    return self._send({"input_tokens": 10})
                if not self.path.startswith("/v1/messages"):
                    return self._send({"type": "error", "error": {
                        "type": "not_found_error", "message": "fake"}}, 404)
                block, stop = api._answer(body)
                model = body.get("model") or "claude-haiku-5-5"
                usage = {"input_tokens": 11, "output_tokens": 7,
                         "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
                if not body.get("stream"):
                    return self._send({"id": "msg_fake", "type": "message", "role": "assistant",
                                       "model": model, "content": [block], "stop_reason": stop,
                                       "stop_sequence": None, "usage": usage})
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.end_headers()

                def ev(name, data):
                    self.wfile.write(f"event: {name}\ndata: {json.dumps(data)}\n\n".encode())

                ev("message_start", {"type": "message_start", "message": {
                    "id": "msg_fake", "type": "message", "role": "assistant", "model": model,
                    "content": [], "stop_reason": None, "stop_sequence": None,
                    "usage": {**usage, "output_tokens": 1}}})
                if block["type"] == "text":
                    ev("content_block_start", {"type": "content_block_start", "index": 0,
                                               "content_block": {"type": "text", "text": ""}})
                    ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "text_delta",
                                                         "text": block["text"]}})
                else:
                    ev("content_block_start", {"type": "content_block_start", "index": 0,
                                               "content_block": {**block, "input": {}}})
                    ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                               "delta": {"type": "input_json_delta",
                                                         "partial_json": json.dumps(
                                                             block["input"])}})
                ev("content_block_stop", {"type": "content_block_stop", "index": 0})
                ev("message_delta", {"type": "message_delta", "delta": {
                    "stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 7}})
                ev("message_stop", {"type": "message_stop"})
                self.wfile.flush()

            def _send(self, obj, code=200):
                b = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.port = self.server.server_address[1]
        self.url = f"http://127.0.0.1:{self.port}"

    def _keep(self, h, body) -> None:
        with self.lock:
            self.auth.append((h.headers.get("authorization") or "",
                              h.headers.get("x-api-key") or ""))
            if body is not None:
                self.requests.append(body)

    def _answer(self, body: dict):
        tools = {t.get("name") for t in body.get("tools") or [] if isinstance(t, dict)}
        n = _tool_results(body)
        if n < len(self.steps) and self.steps[n][0] in tools:
            name, inp = self.steps[n]
            return {"type": "tool_use", "id": f"toolu_fake{n}", "name": name,
                    "input": inp}, "tool_use"
        return {"type": "text", "text": "fake reply: done"}, "end_turn"

    def __enter__(self):
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.server.server_close()
