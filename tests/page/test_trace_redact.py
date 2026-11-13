"""Redact on read: one value of each secret shape goes in, none comes out.

Every secret-shaped value here is **made at runtime** from short fragments and random
characters, so the file holds none (the gitleaks job scans it) and no test output prints one:
the assertions say which kind survived, never the value."""
from __future__ import annotations

import base64
import json
import random
import string
from pathlib import Path
from urllib.parse import quote

import pytest

from kranto.page.trace.redact import Redactor, entropy

RNG = random.Random(20261020)
ALNUM = string.ascii_letters + string.digits


def rand(n: int, alphabet: str = ALNUM) -> str:
    """Random characters with every class present (so entropy rules see a real secret)."""
    while True:
        s = "".join(RNG.choice(alphabet) for _ in range(n))
        if alphabet != ALNUM or (any(c.islower() for c in s) and any(c.isupper() for c in s)
                                 and any(c.isdigit() for c in s)):
            return s


def j(*parts: str) -> str:
    return "".join(parts)


def shapes() -> dict[str, str]:
    """kind -> a made-up value of that shape, in the context a transcript would hold it."""
    up = string.ascii_uppercase + string.digits
    b64u = ALNUM + "_-"
    jwt = j("ey", "J", rand(20, b64u), ".", "ey", "J", rand(30, b64u), ".", rand(24, b64u))
    pem = j("-----BEGIN ", "RSA ", "PRIVATE", " KEY-----\n", rand(64), "\n", rand(64), "\n",
            "-----END ", "RSA ", "PRIVATE", " KEY-----")
    return {
        "Anthropic key": j("sk", "-ant-", "api03-", rand(40, b64u)),
        "API key": j("sk", "-proj-", rand(40)),
        "GitHub token": j("gh", "p_", rand(36)),
        "GitHub fine-grained token": j("github", "_pat_", rand(22), "_", rand(40)),
        "Slack token": j("xo", "xb-", rand(12, string.digits), "-", rand(24)),
        "AWS key": j("AK", "IA", rand(16, up)),
        "Google key": j("AI", "za", rand(35, b64u)),
        "Stripe key": j("sk", "_live_", rand(24)),
        "JWT": jwt,
        "authorization header": j("Authorization", ": Bearer ", rand(32)),
        "bearer token": j("curl -H 'x: y' --oauth2-bearer x; bearer ", rand(30)),
        "URL credentials": j("https://", "deploy", ":", rand(18), "@git.example.org/r.git"),
        "token parameter": j("GET /cb?code=1&access_token=", rand(28), "&x=1"),
        "private key": pem,
        "secret value": j("export DB_PASSWORD=", rand(24)),
        "email": j("someone.", rand(6, string.ascii_lowercase), "@", "example", ".org"),
        "phone": j("+44 ", rand(4, string.digits), " ", rand(6, string.digits)),
    }


def secret_part(kind: str, text: str) -> str:
    """The part of a shape's text that must not survive."""
    if kind == "token parameter":
        return text.split("access_token=", 1)[1].split("&", 1)[0]
    if kind in ("authorization header", "bearer token", "secret value"):
        return text.split("=")[-1].split()[-1]
    if kind == "URL credentials":
        return text.split("://", 1)[1].split("@", 1)[0].split(":", 1)[1]
    if kind == "private key":
        return text.splitlines()[1]
    return text


@pytest.mark.parametrize("kind", sorted(shapes()))
def test_each_shape_alone_is_redacted(kind):
    text = shapes()[kind]
    red = Redactor(env={})
    out = red.text(f"line before\n{text}\nline after")
    survived = secret_part(kind, text) in out           # a bool: a failure never prints it
    assert not survived, f"a {kind} survived"
    assert out.count("[redacted: ") >= 1
    assert out.startswith("line before\n") and out.endswith("\nline after")  # token level
    assert red.report(), "the kind that fired is counted"


def test_the_golden_every_shape_in_one_output_none_survive():
    s = shapes()
    blob = "\n".join(f"{i}: {v}" for i, v in enumerate(s.values()))
    red = Redactor(env={})
    out = red.text(blob)
    left = [k for k, v in s.items() if secret_part(k, v) in out]
    assert left == [], f"survived: {left}"
    assert sum(r["n"] for r in red.report()) >= len(s)
    for r in red.report():                                  # kinds only, never values
        assert set(r) == {"kind", "n"}
        assert all(secret_part(k, v) not in r["kind"] for k, v in s.items())


def test_a_value_inside_json_is_redacted_where_it_sits():
    key = shapes()["GitHub token"]
    red = Redactor(env={})
    out = red.value({"input": {"command": f"git push https://x:{key}@github.com/o/r"},
                     "list": [key, 3]})
    survived = key in json.dumps(out)
    assert not survived
    assert out["list"][1] == 3


def test_an_environment_value_is_hidden_as_written_url_and_base64():
    value = j(rand(10), "/+", rand(10))
    env = {"MY_SERVICE_TOKEN": value, "PATH": "/usr/bin:/bin", "SHORT_KEY": "abc"}
    red = Redactor(env=env)
    for form in (value, quote(value, safe=""),
                 base64.b64encode(value.encode()).decode().rstrip("=")):
        out = red.text(f"echo {form} done")
        survived = form in out
        assert not survived and out == "echo [redacted: environment value] done"
    assert red.text("/usr/bin:/bin") == "/usr/bin:/bin"     # not a secret-sounding name
    assert red.text("abc") == "abc"                           # too short to hide


def test_ordinary_code_and_paths_are_left_alone():
    red = Redactor(env={})
    for s in ("@dataclass\nclass A: pass", "token = tokens[0]", "password = None",
              "see /home/someone/project/src/app.py:12",
              "commit 3f9a1c2e4b5d6f708192a3b4c5d6e7f8091a2b3c",
              "api_key=os.environ['X']", "def get_secret(name): ..."):
        assert red.text(s) == s, s
    assert red.report() == []


def test_a_low_entropy_value_after_a_secret_name_is_not_a_secret():
    red = Redactor(env={})
    assert red.text("password: aaaaaaaaaaaaaaaaaaaa") == "password: aaaaaaaaaaaaaaaaaaaa"
    assert entropy("aaaa") == 0


def test_share_hides_the_host_the_login_and_the_home(tmp_path):
    red = Redactor(env={}, home="/home/you", login="pat", host="lab-box", share=True)
    out = red.text("pat@lab-box:/home/you/tasks/x$ ls /home/someone/y; cc @someone")
    assert "/home/you" not in out and "lab-box" not in out and "/home/someone" not in out
    assert "<you>" in out and "<host>" in out and "~/tasks/x" in out and "[user]" in out
    page = Redactor(env={}, home="/home/you", login="pat", host="lab-box")
    assert page.text("/home/you/tasks/x") == "/home/you/tasks/x"   # the page keeps paths


@pytest.mark.parametrize("path,secret", [
    ("~/.ssh/id_ed25519", True), ("~/.config/gh/hosts.yml", True),
    ("~/.config/kranto/tokens/x", True), ("~/.config/kranto/brokers/ibkr.json", True),
    ("~/.claude/.credentials.json", True), ("/proc/12/environ", True),
    ("/srv/app/.env", True), ("/srv/app/.env.local", True), ("/srv/tls/server.pem", True),
    ("/srv/k/my.key", True), ("/x/aws_credentials", True), ("BH/.env", True),
    ("BH/data/secrets/a", True),
    ("/srv/app/environment.py", False), ("~/.ssh-notes.md", False), ("/srv/app/keys.py", False),
    ("BH/data/kranto.db", False)])
def test_known_token_paths(tmp_path, path, secret):
    bh = tmp_path / "bh"
    red = Redactor(env={}, home="/home/you", kranto_home=bh)
    assert red.secret_path(path.replace("BH", str(bh))) is secret


# -- rule 3 through the payload: what a tool read from a credentials file --------------------

def _kept(tmp: Path, lines: list[dict]) -> Path:
    """A kept stream-json file (``FileTrace``: a research run's, the same format a session
    writes)."""
    f = tmp / "1000000000-t.transcript.jsonl"
    f.write_text("".join(json.dumps(o) + "\n" for o in lines))
    return f


def _tool_pair(tid: str, name: str, inp: dict, result: str, t: int) -> list[dict]:
    ts = f"2001-09-09T01:47:{t:02d}.000Z"
    return [{"type": "assistant", "timestamp": ts, "message": {
                "id": f"m{tid}", "usage": {"input_tokens": 1, "output_tokens": 1},
                "content": [{"type": "tool_use", "id": tid, "name": name, "input": inp}]}},
            {"type": "user", "timestamp": ts, "message": {"content": [
                {"type": "tool_result", "tool_use_id": tid, "content": result}]},
             "tool_use_result": {"stdout": result, "stderr": ""} if name == "Bash" else None}]


def test_what_a_tool_read_from_a_token_file_is_never_shown(tmp_path, monkeypatch):
    from kranto.page.trace.file import FileTrace
    from kranto.page.trace.model import span_id
    from kranto.page.trace.payload import payload
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    plain = j("not-shaped-", rand(30))                     # a key no shape rule would catch
    lines = [{"type": "system", "subtype": "init", "session_id": "S", "uuid": "u", "model": "m"}]
    lines += _tool_pair("R1", "Read", {"file_path": str(home / ".ssh" / "id_ed25519")}, plain, 1)
    lines += _tool_pair("B1", "Bash", {"command": "cat .env | head"}, plain, 2)
    lines += _tool_pair("W1", "Write", {"file_path": "/srv/app/.env", "content": plain}, "ok", 3)
    lines += _tool_pair("B2", "Bash", {"command": "ls"}, "a\nb", 4)
    lines.append({"type": "result", "subtype": "success", "total_cost_usd": 0.1})
    t = FileTrace(_kept(tmp_path, lines), "research:1000000000-t", "t")
    t.refresh()
    red = Redactor(env={}, home=home)
    seen = []
    for tid in ("R1", "B1", "W1"):
        sid = span_id(t.id, f"tool:{tid}")
        for part in ("input", "output", "chat"):
            seen.append(json.dumps(payload(t, sid, part, red=Redactor(env={}, home=home))))
        if tid == "W1":
            seen.append(json.dumps(payload(t, sid, "diff", red=red)))
    for sp in t.spans.values():                    # a turn's input holds the results before it
        if sp.kind == "turn":
            for part in ("input", "output"):
                seen.append(json.dumps(payload(t, sp.id, part, red=red)))
    blob = "\n".join(seen)
    survived = plain in blob
    assert not survived
    assert "the contents of id_ed25519" in blob and "the contents of .env" in blob
    ok = payload(t, span_id(t.id, "tool:B2"), "output", red=red)
    assert ok["text"].startswith("a\nb")                    # an ordinary output is kept
