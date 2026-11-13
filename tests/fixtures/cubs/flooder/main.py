"""S24: twenty send.buttondown tickets with different fields, each on its own draft."""
from bears_cub import Cub, HostError

cub = Cub()


@cub.job("flood")
def flood(ctx):
    codes = []
    for i in range(20):
        try:
            ref = ctx.broker("buttondown").call("emails.create_draft", subject=f"Issue {i}",
                                                body=f"Item {i}.")["draft_ref"]
            ctx.ticket("send.buttondown", {"draft_ref": ref, "subject": f"Issue {i}",
                                           "audience": "all"})
            codes.append("ok")
        except HostError as exc:
            codes.append(exc.code)
    return {"summary": {"codes": codes}}
