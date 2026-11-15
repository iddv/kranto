from bears_cub import Cub

cub = Cub()


@cub.job("look")
def look(ctx):
    seen = ctx.events.read("gen.thing")
    return {"summary": {"seen": [e["id"] for e in seen]}}
