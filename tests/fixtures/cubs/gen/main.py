from bears_cub import Cub

cub = Cub()


@cub.job("say")
def say(ctx):
    return {"summary": {"event": ctx.events.publish("gen.thing", {"n": 1})}}
