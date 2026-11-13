#!/usr/bin/env python3
"""A ``claude -p`` stand-in for harness/print_call.py's tests (no model, no network): records its
argv, environment, cwd, stdin and what a ``*_FILE_DESCRIPTOR`` pipe held as one JSON line in
``$FAKE_CLAUDE_LOG``, then answers in stream-json as ``$FAKE_CLAUDE_MODE`` says:

- ``ok``: an init event (tools: StructuredOutput with ``--json-schema``, else none) and a result
  (``structured_output`` set with a schema);
- ``limit``: a result that is an error with the usage-limit words, exit 1;
- ``expired``: no result, "Login expired" on stderr, exit 1;
- ``tools``: an init event with Bash among the tools, then a result;
- ``mcp``: an init event with an MCP server;
- ``slow``: sleeps longer than any test's timeout."""
import json
import os
import sys
import time

FD_VARS = ("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR")

piped = {}
for v in FD_VARS:
    if os.environ.get(v):
        fd, chunks = int(os.environ[v]), []
        while True:
            b = os.read(fd, 4096)
            if not b:
                break
            chunks.append(b)
        os.close(fd)
        piped[v] = b"".join(chunks).decode()
stdin = sys.stdin.read()
argv = sys.argv[1:]
with open(os.environ["FAKE_CLAUDE_LOG"], "a") as f:
    f.write(json.dumps({"argv": argv, "env": dict(os.environ), "piped": piped, "stdin": stdin,
                        "cwd": os.getcwd(), "cwd_files": sorted(os.listdir("."))}) + "\n")
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
schema = "--json-schema" in argv
tools = ["StructuredOutput"] if schema else []
if mode == "slow":
    time.sleep(30)
if mode == "expired":
    print("Login expired · Please run /login", file=sys.stderr)
    sys.exit(1)
print(json.dumps({"type": "system", "subtype": "init", "session_id": "s-fake",
                  "model": argv[argv.index("--model") + 1] if "--model" in argv else None,
                  "tools": tools + (["Bash"] if mode == "tools" else []),
                  "mcp_servers": [{"name": "x", "status": "connected"}] if mode == "mcp" else [],
                  "permissionMode": "default"}))
result = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 2 if schema else 1,
          "result": "" if schema else '{"pass": true, "reason": "ok"}', "session_id": "s-fake",
          "total_cost_usd": 0.00048, "permission_denials": [],
          "usage": {"input_tokens": 1235, "output_tokens": 414, "cache_read_input_tokens": 2330,
                    "cache_creation_input_tokens": 0},
          "modelUsage": {"claude-haiku-5-5": {"inputTokens": 1235, "outputTokens": 414,
                                              "costUSD": 0.00048}}}
if schema:
    result["structured_output"] = {"pass": False, "reason": "prompt injection"}
if mode == "limit":
    result.update(is_error=True, subtype="error_during_execution",
                  result="You've hit your session limit · resets 3:45pm")
print(json.dumps(result))
sys.exit(1 if mode == "limit" else 0)
