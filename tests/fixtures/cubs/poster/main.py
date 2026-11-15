"""The brokers' tests: a draft at each service and a ticket for each (test_brokers.py)."""
from bears_cub import Cub

cub = Cub()


@cub.job("draft")
def draft(ctx):
    issue = ctx.broker("buttondown").call("emails.create_draft", subject="Week 1",
                                          body="Two items this week.")
    post = ctx.broker("mastodon").call("statuses.draft", text="A pick of the week.")
    a = ctx.ticket("send.buttondown", {"draft_ref": issue["draft_ref"], "subject": "Week 1",
                                       "audience": "all"})
    b = ctx.ticket("post.mastodon", {"draft_ref": post["draft_ref"],
                                     "text": "A pick of the week.", "visibility": "public",
                                     "language": "en"})
    return {"summary": {"tickets": [a.ticket_id, b.ticket_id]}}
