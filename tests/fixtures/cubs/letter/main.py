"""The newsletter's tests (test_newsletter_resend.py): a draft and a ticket, named neutrally."""
from bears_cub import Cub

cub = Cub()


@cub.job("draft")
def draft(ctx):
    issue = ctx.broker("newsletter").call("emails.create_draft", subject="Week 1",
                                          body="Two items this week.")
    t = ctx.ticket("send.newsletter", {"draft_ref": issue["draft_ref"], "subject": "Week 1",
                                       "audience": "all", "when": "now"})
    return {"summary": {"tickets": [t.ticket_id]}}
