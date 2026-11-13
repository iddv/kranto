"""One terminal: a program on a pseudo-terminal of its own, its output kept in a ring and
fanned out to any number of viewers.

- **Viewers** are callables ``sink(bytes) -> bool`` the transport gives (``attach``). A sink
  must not block: it returns False when its viewer can't keep up, and that viewer is dropped
  (the page reattaches and gets the ring again). The program is never held up by a viewer.
- **Reattach:** ``attach`` first hands the viewer the ring (the last ``RING`` bytes), then the
  live output, with nothing lost or doubled in between.
- **Resize:** ``TIOCSWINSZ`` on the terminal, then SIGWINCH to every process of the program:
  bubblewrap's ``--new-session`` leaves it without a controlling terminal, so the kernel's own
  SIGWINCH never reaches it (measured: 0 bytes of redraw without the relay).
- **Kill:** SIGTERM to the tree, SIGKILL after ``KILL_GRACE_S``, then ``waitpid``: EOF on the
  terminal alone missed a sandbox killed during its setup (measured).
- **Start:** the program is forked by ``proc``'s spawner thread, never by the caller's: the
  sandbox's ``--die-with-parent`` fires when the forking *thread* exits, and the caller is a
  server's request thread that retires (live: SIGKILL, code -9, 27 s after Open).
- ``idle_s``: how long nobody has watched and nothing was printed (the service's reaper)."""
from __future__ import annotations

import errno
import fcntl
import os
import signal
import struct
import subprocess
import termios
import threading
import time

from .. import proc

RING = 256 * 1024
KILL_GRACE_S = 3.0
READ = 65536


class Pty:
    def __init__(self, argv: list[str], *, env: dict, cwd, pass_fds=(), cols: int = 100,
                 rows: int = 30, on_exit=None, name: str = "term"):
        self.argv, self.env, self.cwd, self.pass_fds = argv, env, cwd, tuple(pass_fds)
        self.cols, self.rows = cols, rows
        self.on_exit = on_exit
        self.name = name
        self.ring = bytearray()
        self.sinks: dict[int, callable] = {}
        self.lock = threading.Lock()
        self.proc: subprocess.Popen | None = None
        self.master: int | None = None
        self.code: int | None = None
        self.started = time.time()
        self.last_output = self.last_seen = time.time()
        self.total = 0                              # bytes printed so far
        self._next = 0
        self._done = threading.Event()
        self._size_lock = threading.Lock()
        self._sized = 0                              # viewers' resizes so far (redraw's check)

    # -- life -----------------------------------------------------------------------------------
    def start(self) -> Pty:
        master, slave = os.openpty()
        _winsize(slave, self.cols, self.rows)
        try:
            self.proc = proc.spawn_terminal(self.argv, terminal=slave, cwd=self.cwd,
                                            env=self.env, pass_fds=self.pass_fds)
        finally:
            os.close(slave)
        self.master = master
        proc.thread(self._read, f"{self.name}-read")
        proc.thread(self._wait, f"{self.name}-wait")
        return self

    @property
    def pid(self) -> int | None:
        return self.proc.pid if self.proc else None

    @property
    def alive(self) -> bool:
        return self.proc is not None and self.code is None

    def _read(self) -> None:
        while True:
            try:
                data = os.read(self.master, READ)
            except OSError as e:
                if e.errno == errno.EINTR:
                    continue
                break                                  # EIO: the program closed the terminal
            if not data:
                break
            self._out(data)

    def _out(self, data: bytes) -> None:
        with self.lock:
            self.last_output = time.time()
            self.total += len(data)
            self.ring += data
            if len(self.ring) > RING:
                del self.ring[:len(self.ring) - RING]
            # a sink that says False is behind: it is dropped here, and its transport tells
            # its page to reattach
            for k in [k for k, s in list(self.sinks.items()) if not _send(s, data)]:
                self.sinks.pop(k, None)

    def _wait(self) -> None:
        code = self.proc.wait()                      # waitpid: also after a kill during setup
        self.code = code
        time.sleep(0.05)                             # let the reader drain the last bytes
        with self.lock:
            sinks = list(self.sinks.values())
            self.sinks.clear()
        for s in sinks:
            _send(s, None)                           # None: the program ended
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
        if self.on_exit:
            try:
                self.on_exit(code)
            except Exception:                        # noqa: BLE001 - the end is recorded anyway
                pass
        self._done.set()                             # after on_exit: a waiter sees it all done

    def wait(self, timeout: float | None = None) -> int | None:
        self._done.wait(timeout)
        return self.code

    def kill(self, grace_s: float = KILL_GRACE_S) -> int | None:
        """SIGTERM the whole tree, SIGKILL what is left after ``grace_s``, reaped."""
        if self.proc is None or not self.alive:
            return self.code
        procs = proc.signal_tree(self.proc.pid, signal.SIGTERM)
        if not self._done.wait(grace_s):
            proc.finish(proc.tree(self.proc.pid) + procs)
            self._done.wait(grace_s)
        return self.code

    # -- viewers --------------------------------------------------------------------------------
    def attach(self, sink) -> int:
        """Add a viewer: it gets the ring now, then everything new. Returns its key."""
        with self.lock:
            self._next += 1
            key = self._next
            self.last_seen = time.time()
            if self.ring and not _send(sink, bytes(self.ring)):
                return key
            if self.code is not None:
                _send(sink, None)
                return key
            self.sinks[key] = sink
        return key

    def detach(self, key: int) -> None:
        with self.lock:
            if self.sinks.pop(key, None) is not None:
                self.last_seen = time.time()

    @property
    def viewers(self) -> int:
        return len(self.sinks)

    def idle_s(self, now: float | None = None) -> float:
        """Seconds since anything was printed or anyone watched; 0 while someone watches."""
        if self.sinks:
            return 0.0
        now = now or time.time()
        return now - max(self.last_output, self.last_seen)

    # -- input ----------------------------------------------------------------------------------
    def write(self, data: bytes) -> None:
        if not self.alive or self.master is None:
            return
        view = memoryview(data)
        while view:
            try:
                n = os.write(self.master, view)
            except OSError as e:
                if e.errno in (errno.EINTR, errno.EAGAIN):
                    time.sleep(0.01)
                    continue
                return
            view = view[n:]

    def resize(self, cols: int, rows: int) -> None:
        """Set the size and tell every process of the program (SIGWINCH relay)."""
        with self._size_lock:
            self._sized += 1
            self._resize(cols, rows)

    def _resize(self, cols: int, rows: int) -> None:
        cols, rows = max(2, min(int(cols), 1000)), max(2, min(int(rows), 500))
        self.cols, self.rows = cols, rows
        if self.master is None or not self.alive:
            return
        try:
            _winsize(self.master, cols, rows)
        except OSError:
            return
        for p in proc.tree(self.proc.pid):
            try:
                os.kill(p["pid"], signal.SIGWINCH)
            except (ProcessLookupError, PermissionError):
                pass

    def redraw(self) -> None:
        """Make the program draw its whole screen again (a viewer just attached: the ring's
        replay starts mid-stream, and a TUI's relative moves don't rebuild the screen from it).
        A SIGWINCH at the same size is ignored, so the size steps one column and back. A
        viewer's own resize since the step wins (and redrew): the step back is skipped, under
        the size lock, so it can never put back a size from before the viewer's."""
        with self._size_lock:
            if not self.alive or self.cols < 3:
                return
            cols = self.cols
            self._resize(cols - 1, self.rows)
            mark = self._sized
        time.sleep(0.08)
        with self._size_lock:
            if self._sized == mark:
                self._resize(cols, self.rows)


def _send(sink, data) -> bool:
    if sink is None:
        return False
    try:
        return sink(data) is not False
    except Exception:                                # noqa: BLE001 - a broken viewer is dropped
        return False


def _winsize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))

