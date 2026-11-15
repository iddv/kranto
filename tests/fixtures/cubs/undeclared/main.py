"""S14: the model, a kind it did not declare, a core kind: refused by the SDK, and by the host
when the SDK is bypassed."""
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
    msgs = [{"role": "user", "content": "hi"}]
    out = {"model_sdk": code(lambda: ctx.model.complete(purpose="undeclared", tier="reason",
                                                        messages=msgs)),
           "model_host": code(lambda: ctx._transport("model.complete", {
               "purpose": "undeclared", "tier": "reason", "messages": msgs})),
           "publish_other": code(lambda: ctx._transport("events.publish", {
               "kind": "other.said", "payload": {}})),
           "publish_core": code(lambda: ctx._transport("events.publish", {
               "kind": "grade.given", "payload": {}})),
           "publish_own": code(lambda: ctx.events.publish("undeclared.said", {"n": 1}))}
    return {"summary": out}
