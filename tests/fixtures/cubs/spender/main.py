"""S23: calls the model 200 times; the cap stops it."""
from bears_cub import Cub, HostError

cub = Cub()


@cub.job("loop")
def loop(ctx):
    ok, codes = 0, []
    for _ in range(200):
        try:
            ctx.model.complete(purpose="spender", tier="judge",
                               messages=[{"role": "user", "content": "again"}])
            ok += 1
        except HostError as exc:
            codes.append(exc.code)
    return {"summary": {"ok": ok, "codes": sorted(set(codes)), "refused": len(codes)}}
