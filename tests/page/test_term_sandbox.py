"""Open in Claude Code's limits, tested adversarially in real bubblewrap with a fake claude that
takes its token the way the product hands it over. Each test
plants canaries made at run time (a Claude token in Kranto's environment, a GitHub token, a Kranto
token file, an SSH key) and runs a probe as a tool command inside the session, then looks for
them in everything the session could print or keep.

CI runs this file in its ``sandbox`` job with ``KRANTO_BWRAP_REQUIRED=1``: there a missing
bubblewrap fails instead of skipping."""
from __future__ import annotations

import json
import socket
import threading
import time
from pathlib import Path

import pytest

from .term_common import Screen, canary, make_repo, make_term, needs_bwrap, run

PROBE = r"""echo "==ENV"; env
echo "==SELF"; tr '\0' '\n' < /proc/self/environ; echo
echo "==PROCS"; for p in /proc/[0-9]*; do echo "PID $p $(tr '\0' ' ' < $p/cmdline 2>/dev/null)"; tr '\0' '\n' < $p/environ 2>/dev/null; echo; done
echo "==FDS"; for f in /proc/[0-9]*/fd/*; do case "$(readlink $f)" in pipe:*) timeout 1 cat $f 2>/dev/null;; esac; done
echo "==HOME"; ls -a "$HOME" "$HOME/.config" "$HOME/.ssh" 2>&1
cat "$HOME/.config/kranto/tokens/index.json" "$HOME/.config/gh/hosts.yml" "$HOME/.ssh/id_ed25519" 2>&1
echo "==TEST"; python3 test_dump_env.py
echo "==MEM"; python3 memscan.py
echo "==END"
"""
NETPROBE = r'''import socket, sys, urllib.request
try:
    urllib.request.urlopen("http://example.org/x", timeout=10)
    print("PROXY reached")
except Exception as e:
    print("PROXY", getattr(e, "code", None), e.read().decode() if hasattr(e, "read") else e)
s = socket.socket()
s.settimeout(3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    print("LOOPBACK reached")
except OSError as e:
    print("LOOPBACK refused", e)
'''
# a planted "project test" that prints its whole environment (the review's third case)
DUMP = "import os\nprint('PLANTED', sorted(os.environ.items()))\n"
MEMSCAN = r'''import os
a, b = open(".needle").read().split()
needle = (a + b).encode()
hits, seen = 0, 0
for pid in [p for p in os.listdir("/proc") if p.isdigit() and int(p) != os.getpid()]:
    try:
        maps = open(f"/proc/{pid}/maps").read().splitlines()
        mem = open(f"/proc/{pid}/mem", "rb", 0)
    except OSError:
        continue
    seen += 1
    for ln in maps:
        rng, perm = ln.split()[:2]
        if "r" not in perm:
            continue
        lo, hi = (int(x, 16) for x in rng.split("-"))
        try:
            mem.seek(lo)
            hits += mem.read(hi - lo).count(needle)
        except (OSError, ValueError, OverflowError):
            pass
print(f"MEMSCAN readable={seen} hits={hits}")
'''


@pytest.fixture
def planted(tmp_path, monkeypatch):
    """Kranto's environment and HOME with every credential a session must never see."""
    needs_bwrap()
    home = Path.home()
    c = {"claude": canary("claude"), "gh": canary("gh"), "kranto": canary("kranto"),
         "ssh": canary("ssh")}
    monkeypatch.setenv("GH_TOKEN", c["gh"])
    monkeypatch.setenv("GITHUB_TOKEN", c["gh"])
    for rel, text in ((".config/kranto/tokens/index.json", c["kranto"]),
                      (".config/gh/hosts.yml", c["gh"]), (".ssh/id_ed25519", c["ssh"]),
                      (".claude/.credentials.json", c["claude"])):
        p = home / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    src = make_repo(tmp_path / "source", {"README.md": "# p\n", "probe.sh": PROBE,
                                         "test_dump_env.py": DUMP, "memscan.py": MEMSCAN,
                                         "netprobe.py": NETPROBE})
    term = make_term(tmp_path, monkeypatch, token=c["claude"], source=src)
    yield term, src, c
    for tid in list(term.live):
        term.end(tid, remove=False)


def open_session(term, kind="project", ref="p1"):
    out = term.open({"kind": kind, "id": ref}, cols=120, rows=40)
    scr = Screen()
    term.live[out["tid"]].pty.attach(scr)
    scr.wait("FAKE CLAUDE CODE")
    scr.wait("\n> ")
    return out, scr


def everything_kept(term, tid) -> str:
    """Every file the session's folder holds (the transcript, the meter, the config dir)."""
    d = term.store.dir(tid)
    parts = []
    for p in sorted(d.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            parts.append(p.read_bytes().decode(errors="replace"))
    return "\n".join(parts)


def test_the_claude_token_and_every_credential_stay_out_of_the_session(planted):
    term, src, c = planted
    out, scr = open_session(term)
    tid = out["tid"]
    # claude got the token, through the pipe, and only there
    assert f"auth=fd len={len(c['claude'])}" in scr.text
    ws = Path(out["cwd"])
    (ws / ".needle").write_text(c["claude"][:12] + " " + c["claude"][12:])
    probe = run(term, tid, scr, "sh probe.sh", timeout=90)
    assert "==END" in probe and "PLANTED" in probe and "MEMSCAN" in probe
    for name, value in c.items():
        assert value not in probe, f"the {name} canary is readable inside the session"
    assert "MEMSCAN readable=" in probe and " hits=0" in probe
    # the tool command saw only its own processes (nested pid namespace): not claude, not bwrap
    pids = [ln for ln in probe.splitlines() if ln.startswith("PID ")]
    assert pids and not any("claude" in ln or "bwrap" in ln or "netproxy" in ln for ln in pids)
    assert "No such file" in probe.split("==HOME")[1]
    term.end(tid, remove=False)
    kept = everything_kept(term, tid) + scr.text
    for name, value in c.items():
        assert value not in kept, f"the {name} canary reached the session's files or screen"


def test_the_session_reads_its_copy_and_cannot_touch_or_push_to_the_source(planted):
    term, src, c = planted
    out, scr = open_session(term)
    tid, ws = out["tid"], Path(out["cwd"])
    assert ws != src and (ws / "README.md").is_file()
    head = (src / ".git" / "HEAD").read_text()
    objects = src / ".git" / "objects"
    got = run(term, tid, scr, f"ls {src}; touch {objects}/x; echo edit >> README.md && "
                              f"git add -A && git commit -qm edit && git log --oneline | wc -l; "
                              f"git push {src} HEAD:main; git remote -v; echo DONE")
    assert "DONE" in got
    assert "Read-only file system" in got                     # the shared objects
    assert not (objects / "x").exists()
    assert (src / ".git" / "HEAD").read_text() == head
    heads = sorted(p.name for p in (src / ".git" / "refs" / "heads").iterdir())
    assert heads == ["main"]                                   # nothing pushed to the source
    # the commit is the copy's own, on the session's branch
    from kranto.page.term import workdir
    rec = term.store.get(tid)
    d = workdir.diff(ws, rec["work"]["base"], rec["work"]["branch"])
    assert len(d["commits"]) == 1 and "+edit" in d["diff"]


def test_the_network_is_an_allowlist_and_other_hosts_wait_for_the_owner(planted):
    term, src, c = planted
    # a service on the host's loopback that the session must not reach
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    hit = []
    threading.Thread(target=lambda: hit.append(srv.accept()), daemon=True).start()
    out, scr = open_session(term)
    tid = out["tid"]
    got = run(term, tid, scr, f"python3 netprobe.py {port}")
    assert "PROXY 403" in got and "not allowed for this session" in got
    assert "LOOPBACK refused" in got and not hit
    rec = term.store.get(tid)
    assert rec["net"]["asked"] == ["example.org"]
    log = (term.store.dir(tid) / "net.jsonl").read_text()
    assert '"refused"' in log and "example.org" in log
    # the owner allows it: from now on the proxy lets it through (no lookup here: tests never
    # touch the network, so the allowlist itself is what is checked)
    term.net(tid, "example.org", allow=True)
    assert term.store.get(tid)["net"] == {"allowed": ["example.org"], "asked": []}
    srv.close()


def test_the_session_runs_with_claude_codes_limits_on_its_command_line(planted):
    term, src, c = planted
    out, scr = open_session(term)
    argv = json.loads(scr.text.split("argv: ", 1)[1].split("\n", 1)[0])
    assert "--restricted" in argv and "--strict-mcp-config" in argv
    assert argv[argv.index("--permission-mode") + 1] == "default"
    tools = argv[argv.index("--tools") + 1].split(",")
    assert "Task" not in tools and "Agent" not in tools and "Bash" in tools
    st = json.loads(argv[argv.index("--settings") + 1])
    assert st["permissions"]["disableBypassPermissionsMode"] == "disable"
    assert st["permissions"]["disableAutoMode"] == "disable"
    assert {"Task", "Agent"} <= set(st["permissions"]["deny"])
    assert st["includeCoAuthoredBy"] is False
    assert c["claude"] not in " ".join(argv)


@pytest.mark.slow
def test_a_session_opened_on_a_request_thread_outlives_that_thread(tmp_path, monkeypatch):
    """bwrap's --die-with-parent is tied to the thread that forked it: a session opened by a
    server's worker thread was SIGKILLed when that thread retired (live, code -9 after 27 s)."""
    needs_bwrap()
    term = make_term(tmp_path, monkeypatch, token=canary("claude"),
                     source=make_repo(tmp_path / "source"))
    got = {}

    def request():                                # lives until the sandbox is up, then retires
        got["out"], got["scr"] = open_session(term)
    t = threading.Thread(target=request, name="request")
    t.start()
    t.join()
    tid = got["out"]["tid"]
    try:
        time.sleep(31)
        lv = term.live.get(tid)
        assert lv is not None and lv.pty.alive, f"ended: {term.store.get(tid).get('code')}"
        assert term.store.get(tid)["state"] == "running"
        assert "still-here" in run(term, tid, got["scr"], "echo still-here")
    finally:
        term.end(tid, remove=False)
