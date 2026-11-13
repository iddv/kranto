"""S30: a read that takes 30 s once its store says so."""
import time

from bears_cub import Cub

cub = Cub()


@cub.action("slow_down")
def slow_down(ctx, fields):
    ctx.kv.put("slow", True)
    return {"say": "slow now"}


@cub.read("rows")
def rows(ctx, params):
    if ctx.kv.get("slow"):
        time.sleep(30)
    return {"rows": [{"id": 1}]}
