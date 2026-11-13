"""a cub's model call refused by the provider (live's newsletter, 2026-10-25): its
handler lets Kranto's HostError end the run, as the newsletter's does."""
from bears_cub import Cub

cub = Cub()


@cub.job("weekly")
def weekly(ctx):
    ctx.model.complete(purpose="refused", tier="judge",
                       messages=[{"role": "user", "content": "write the issue"}])
    return {"summary": {"line": "written"}}
