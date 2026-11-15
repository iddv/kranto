"""S28: what a cub narrowed to one topic sees."""
from bears_cub import Cub, HostError

cub = Cub()


def code(fn):
    try:
        fn()
        return "ok"
    except HostError as exc:
        return exc.code


@cub.job("probe")
def probe(ctx):
    other = ctx.settings["reader.other_topic"]
    obs = ctx.settings["reader.other_obs"]
    return {"summary": {
        "topics": [t["id"] for t in ctx.read.topics()["topics"]],
        "other_topic": code(lambda: ctx.read.observations(topic_id=other)),
        "other_obs": code(lambda: ctx.read.object("observation", obs)),
        "mine": [o["id"] for o in ctx.read.observations(limit=100)["observations"]],
        "search": [o["id"] for o in ctx.read.search("solar", limit=20)["observations"]]}}
