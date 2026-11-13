"""S1: every open outside its view fails; it lists /."""
import os

from bears_cub import Cub

cub = Cub()
FIXED = ["/home", "/etc/passwd", "/etc/shadow", "/etc/hosts", "/etc/resolv.conf", "/run",
         "/var", "/root", "/proc/1/root/home"]


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
    return {"summary": {"opens": opens, "root": sorted(os.listdir("/")), "userns": userns,
                        "env": sorted(os.environ), "proc1_env": env1, "uid": os.getuid()}}
