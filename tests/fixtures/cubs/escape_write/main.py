"""S2: every write outside /tmp fails; /tmp stops at its size."""
import contextlib
import os

from bears_cub import Cub

cub = Cub()


@cub.job("write")
def write(ctx):
    out = {}
    for path in ("/cub/src/x.txt", "/cub/src/main.py", "/opt/kranto/sdk/bears_cub/x.py",
                 "/usr/bin/x", "/etc/x", "/x"):
        try:
            with open(path, "w") as f:
                f.write("x")
            out[path] = "written"
        except OSError as exc:
            out[path] = exc.__class__.__name__ + ":" + str(exc.errno)
    n, err = 0, None
    chunk = b"\0" * (1024 * 1024)
    try:
        with open("/tmp/fill", "wb") as f:
            for _ in range(200):
                f.write(chunk)
                f.flush()
                n += len(chunk)
    except OSError as exc:
        err = exc.errno
    with contextlib.suppress(OSError):
        os.remove("/tmp/fill")
    return {"summary": {"writes": out, "tmp_bytes": n, "tmp_errno": err}}
