"""S1: every open outside its view fails; it lists /; nothing it can read names the host's
paths (``escape_fs.needles``: the user's home, the interpreter's root, the Kranto home)."""
import os
import sys

from bears_cub import Cub

cub = Cub()
FIXED = ["/home", "/etc/passwd", "/etc/shadow", "/etc/hosts", "/etc/resolv.conf", "/run",
         "/var", "/root", "/proc/1/root/home", "/proc/self/mountinfo"]
SKIP = ("/usr", "/dev", "/proc", "/sys")
READ_MAX = 4 * 1024 * 1024


def leaks(needles):
    """Every path, link target and file under / (but the system's own) naming a needle."""
    found = []
    want = [n.encode() for n in needles if n]

    def note(where, what):
        if len(found) < 20:
            found.append(f"{where}: {what}")

    for top, dirs, names in os.walk("/"):
        dirs[:] = [d for d in dirs if os.path.join(top, d) not in SKIP]
        for name in dirs + names:
            path = os.path.join(top, name)
            if any(n in path.encode() for n in want):
                note(path, "path")
            if os.path.islink(path):
                if any(n in os.readlink(path).encode() for n in want):
                    note(path, "link")
                continue
            if name in dirs:
                continue
            try:
                if os.path.getsize(path) > READ_MAX:
                    continue
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                continue
            if any(n in data for n in want):
                note(path, "content")
    return found


@cub.job("probe")
def probe(ctx):
    opens = {}
    for path in FIXED + list(ctx.settings["escape_fs.paths"]):
        try:
            if os.path.isdir(path):
                opens[path] = "listed: " + ",".join(sorted(os.listdir(path)))[:200]
            else:
                with open(path, "rb") as f:
                    opens[path] = "read: " + str(len(f.read(4096)))
        except OSError as exc:
            opens[path] = exc.__class__.__name__ + ":" + str(exc.errno)
    try:
        with open("/proc/1/environ", "rb") as f:
            env1 = sorted(x.split(b"=", 1)[0].decode() for x in f.read().split(b"\0") if x)
    except OSError as exc:
        env1 = ["error " + str(exc.errno)]
    try:
        os.unshare(os.CLONE_NEWUSER)
        userns = "allowed"
    except OSError as exc:
        userns = "refused:" + str(exc.errno)
    py = {"executable": sys.executable, "prefix": sys.prefix, "base_prefix": sys.base_prefix,
          "exec_prefix": sys.exec_prefix, "path": sys.path}
    return {"summary": {"opens": opens, "root": sorted(os.listdir("/")), "userns": userns,
                        "env": sorted(os.environ), "proc1_env": env1, "uid": os.getuid(),
                        "python": py, "leaks": leaks(ctx.settings["escape_fs.needles"])}}
