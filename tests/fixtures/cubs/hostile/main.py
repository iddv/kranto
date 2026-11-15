"""S10 to S13: ignores cancel, forks until it cannot, allocates 2 GiB, spins."""
import os
import time

from bears_cub import Cub

cub = Cub()


@cub.job("hang")
def hang(ctx):
    while True:
        time.sleep(1)


@cub.job("fork")
def fork(ctx):
    n = 0
    err = None
    while n < 10000:
        try:
            pid = os.fork()
        except OSError as exc:
            err = exc.errno
            break
        if pid == 0:
            time.sleep(30)
            os._exit(0)
        n += 1
    return {"summary": {"forked": n, "errno": err}}


@cub.job("hog")
def hog(ctx):
    block = bytearray(2 * 1024 * 1024 * 1024)
    for i in range(0, len(block), 4096):
        block[i] = 1
    return {"summary": {"held": len(block)}}


@cub.job("spin")
def spin(ctx):
    end = time.monotonic() + 60
    x = 0
    while time.monotonic() < end:
        x += 1
    return {"summary": {"x": x}}
