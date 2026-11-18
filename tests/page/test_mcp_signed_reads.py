"""kranto mcp's live search and page fetch are reads the server makes signed in only: its client
sends its own token on every request, a GET too, and a refusal says how to fix the token. A
loopback stand-in of the server checks the header as the guard does (no network, no model)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from kranto.page.mcp import tools as T
from kranto.tokens import Store


@pytest.fixture
def server():
    seen: list[dict] = []
    want = {"value": None}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append({"path": self.path, "auth": self.headers.get("Authorization")})
            ok = want["value"] and self.headers.get("Authorization") == f"Bearer {want['value']}"
            if not ok:
                body, code = {"error": "not signed in: it carries no kranto token."}, 401
            elif self.path.startswith("/api/websearch/fetch"):
                body, code = {"url": "https://page.example/a", "text": "A page."}, 200
            else:
                body, code = {"backend": "exa", "live": True, "note": None, "hits": [],
                              "backends": ["exa"], "query": "q"}, 200
            raw = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def log_message(self, *a):
            pass

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}", seen, want
    httpd.shutdown()


def test_the_search_and_the_fetch_carry_kranto_mcps_token(server):
    url, seen, want = server
    store = Store()
    store.ensure_doors()
    want["value"] = store.value("mcp")
    c = T.http_client(url)
    status, body = c.server_get("/api/websearch", {"q": "sync"})
    assert status == 200 and body["live"]
    status, body = c.server_get("/api/websearch/fetch", {"url": "https://page.example/a"})
    assert status == 200 and body["text"] == "A page."
    assert [s["auth"] for s in seen] == [f"Bearer {want['value']}"] * 2
    console = T.http_client(url, door="console")          # the console's own door
    want["value"] = store.value("console")
    assert console.server_get("/api/websearch", {"q": "x"})[0] == 200


def test_a_refused_read_says_how_to_fix_the_token(server):
    url, seen, want = server
    Store().ensure_doors()
    want["value"] = None                                   # the server knows no such token
    c = T.http_client(url)
    with pytest.raises(T.ToolError, match="Kranto refused kranto mcp's token"):
        c.server_get("/api/websearch", {"q": "sync"})
