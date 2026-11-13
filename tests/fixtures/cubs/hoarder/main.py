"""S25: 64 KiB values until refused; small keys until refused."""
from bears_cub import Cub, HostError

cub = Cub()


@cub.job("fill_bytes")
def fill_bytes(ctx):
    n, code = 0, None
    value = "x" * 65000
    while n < 200:
        try:
            ctx.kv.put(f"big:{n}", value)
            n += 1
        except HostError as exc:
            code = exc.code
            break
    return {"summary": {"puts": n, "code": code}}


@cub.job("fill_keys")
def fill_keys(ctx):
    n, code = 0, None
    while n < 1500:
        try:
            ctx.kv.put(f"k:{n}", 1)
            n += 1
        except HostError as exc:
            code = exc.code
            break
    return {"summary": {"puts": n, "code": code}}
