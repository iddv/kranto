"""S5: the public-address check refuses a declared name that resolves inside."""
from bears_cub import Cub, HostError

cub = Cub()


@cub.job("probe")
def probe(ctx):
    try:
        ctx.http.get("https://internal.example/admin")
        return {"summary": {"code": "fetched"}}
    except HostError as exc:
        return {"summary": {"code": exc.code, "message": exc.message}}
