#!/usr/bin/env python3
"""A stand-in for the Claude Code TUI in Open in Claude Code's tests (no model, no network).

It takes its token the way Kranto hands it over (the ``*_FILE_DESCRIPTOR`` pipe; it reports
``auth=env`` if a token came in its environment instead), keeps it in memory, runs each tool
command the way Claude Code does (``$CLAUDE_CODE_SHELL_PREFIX '<command line>'``) and keeps a
transcript where Claude Code keeps it. Lines it understands, typed into its terminal:

    run <command line>    run it as a tool; its output goes to the terminal and the transcript
    status <usd>          run the status line command from --settings with that cost
    say <text>            an assistant message with usage
    exit                  exit 0
It prints ``[size COLSxROWS]`` on SIGWINCH and ``argv:`` / ``auth:`` lines at the start."""
import fcntl
import json
import os
import re
import signal
import struct
import subprocess
import sys
import termios

FD_VARS = ("CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR", "CLAUDE_CODE_API_KEY_FILE_DESCRIPTOR")


def out(s: str) -> None:
    sys.stdout.write(s.replace("\n", "\r\n"))
    sys.stdout.flush()


def arg(name):
    a = sys.argv
    return a[a.index(name) + 1] if name in a and a.index(name) + 1 < len(a) else None


TOKEN = None
how = "none"
for v in FD_VARS:
    if os.environ.get(v):
        fd = int(os.environ[v])
        chunks = []
        while True:
            b = os.read(fd, 4096)
            if not b:
                break
            chunks.append(b)
        os.close(fd)
        TOKEN = b"".join(chunks).decode()
        how = "fd"
if os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or os.environ.get("ANTHROPIC_API_KEY"):
    how = "env"

session = arg("--session-id") or arg("--resume") or "none"
resumed = "--resume" in sys.argv
cfg = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
key = re.sub(r"[^A-Za-z0-9]", "-", os.getcwd())
tdir = os.path.join(cfg, "projects", key)
os.makedirs(tdir, exist_ok=True)
transcript = os.path.join(tdir, f"{session}.jsonl")
settings = json.loads(arg("--settings") or "{}")
n_msg = [0]


def record(ev: dict) -> None:
    with open(transcript, "a") as f:
        f.write(json.dumps({"sessionId": session, **ev}) + "\n")


def winch(*_):
    try:
        rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(0, termios.TIOCGWINSZ, b"\0" * 8))
        out(f"[size {cols}x{rows}]\n")
    except OSError:
        out("[size ?]\n")


signal.signal(signal.SIGWINCH, winch)
out(f"FAKE CLAUDE CODE session={session} resumed={int(resumed)} auth={how} "
    f"len={len(TOKEN or '')}\n")
out("argv: " + json.dumps(sys.argv[1:]) + "\n")
out("> ")
for line in sys.stdin:
    line = line.strip()
    if line in ("exit", "/exit"):
        out("bye\n")
        sys.exit(0)
    if line.startswith("run "):
        cmd = line[4:]
        prefix = os.environ.get("CLAUDE_CODE_SHELL_PREFIX")
        argv = [prefix, cmd] if prefix else ["/bin/bash", "-c", cmd]
        record({"type": "assistant", "message": {"role": "assistant", "id": f"m{n_msg[0]}",
                "content": [{"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}})
        n_msg[0] += 1
        p = subprocess.run(argv, capture_output=True, text=True, stdin=subprocess.DEVNULL)
        res = p.stdout + p.stderr
        record({"type": "user", "message": {"role": "user", "content": [
            {"type": "tool_result", "content": res}]}})
        out(res + f"[exit {p.returncode}]\n")
    elif line.startswith("status "):
        cmd = (settings.get("statusLine") or {}).get("command")
        js = json.dumps({"session_id": session, "model": {"id": "fake-model"},
                         "cost": {"total_cost_usd": float(line.split()[1])}})
        p = subprocess.run(["/bin/sh", "-c", cmd], input=js, capture_output=True, text=True)
        out(f"[status {p.returncode}] {p.stdout}\n")
    elif line.startswith("say "):
        record({"type": "assistant", "message": {
            "role": "assistant", "id": f"m{n_msg[0]}",
            "content": [{"type": "text", "text": line[4:]}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}})
        n_msg[0] += 1
        out(line[4:] + "\n")
    elif line:
        out(f"you said: {line}\n")
    out("> ")
