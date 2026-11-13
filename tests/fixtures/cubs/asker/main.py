"""S26: files a ticket; a long job that the STOP file must end."""
import time

from bears_cub import Cub

cub = Cub()


@cub.job("ask")
def ask(ctx):
    t = ctx.ticket("send.test", {"target": "a"})
    return {"summary": {"ticket": t.ticket_id}}


@cub.job("wait")
def wait(ctx):
    time.sleep(100)
    return {"line": "waited"}
