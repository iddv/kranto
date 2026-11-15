"""A cub killed with SIGKILL is said as memory only when its scope counted an OOM kill.

Toot's "crashed before hello (exit 137, memory)" of 2026-10-21 was not memory: the journal says
"kranto-cub-b67819-toot-….scope: Sending signal SIGKILL to process … (bwrap) on client request",
and Kranto 0.4.11 (installed by a release check that minute) killed every ``kranto-cub-*`` scope of
the user every ten seconds. Kranto guessed "memory" from the exit code alone.

The scope is collected as soon as its process ends, often before its last count is read: then
its parent's count (hierarchical) since the scope's last read decides.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from kranto.core.cubs.process import CubProcess


def _killed(tmp_path: Path, *, oom: int) -> str:
    p = CubProcess(cid="toot", argv=["sh", "-c", "kill -9 $$"], env={}, preexec=None,
                   unit="kranto-cub-test-toot-1", mode="scope", hello=lambda params: {},
                   stderr=None, cwd=str(tmp_path))
    p.proc = subprocess.Popen(p.argv)
    p.proc.wait(timeout=10)
    p.cgroup = tmp_path                        # the scope was found while it lived
    (tmp_path / "memory.events").write_text(f"low 0\nhigh 0\nmax 0\noom 0\noom_kill {oom}\n")
    return p._crashed("crashed before hello").words


def test_an_uncounted_sigkill_is_killed_not_memory(tmp_path):
    assert _killed(tmp_path, oom=0) == "failed: crashed before hello (exit 137, killed)"


def test_a_counted_oom_kill_is_memory(tmp_path):
    assert _killed(tmp_path, oom=1) == "failed: crashed before hello (exit 137, memory)"


def _collected(tmp_path: Path, *, parent_after: int) -> str:
    """The scope was read once while it lived (its parent counted 3 kills then), and collected
    when its process ended, before the last read."""
    parent, scope = tmp_path / "app.slice", tmp_path / "app.slice" / "kranto-cub-test-toot-1.scope"
    scope.mkdir(parents=True)
    events = "low 0\nhigh 0\nmax 0\noom 0\noom_kill {}\n"
    (parent / "memory.events").write_text(events.format(3))
    (scope / "memory.events").write_text(events.format(0))
    p = CubProcess(cid="toot", argv=["sh", "-c", "kill -9 $$"], env={}, preexec=None,
                   unit="kranto-cub-test-toot-1", mode="scope", hello=lambda params: {},
                   stderr=None, cwd=str(tmp_path))
    p.cgroup = scope
    assert p._read_oom() and p.oom_kills == 0
    p.proc = subprocess.Popen(p.argv)
    p.proc.wait(timeout=10)
    (scope / "memory.events").unlink()
    scope.rmdir()
    (parent / "memory.events").write_text(events.format(parent_after))
    return p._crashed("crashed before hello").words


def test_a_collected_scope_whose_parent_counted_a_kill_is_memory(tmp_path):
    assert _collected(tmp_path, parent_after=4) == \
        "failed: crashed before hello (exit 137, memory)"


def test_a_collected_scope_whose_parent_counted_nothing_is_killed(tmp_path):
    assert _collected(tmp_path, parent_after=3) == \
        "failed: crashed before hello (exit 137, killed)"
