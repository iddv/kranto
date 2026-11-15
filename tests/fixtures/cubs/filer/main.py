"""The Sanity broker's tests: a draft and a ticket to file it (test_sanity_broker.py)."""
from bears_cub import Cub

cub = Cub()


@cub.job("draft")
def draft(ctx):
    post = ctx.broker("sanity").call("documents.draft", doc="brief-12", title="A week",
                                     slug="a-week", body="Two items.", category="dispatch")
    t = ctx.ticket("draft.sanity", {"draft_ref": post["draft_ref"], "title": "A week",
                                    "slug": "a-week", "category": "dispatch"})
    return {"summary": {"ticket": t.ticket_id}}
