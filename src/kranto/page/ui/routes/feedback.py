"""Feedback: where the sheet's issue goes, and filing it as the person.

``GET /api/feedback/issue`` is what the sheet reads when it opens (``kranto.page.feedback.status``:
the repository, whether the person's own ``gh`` can file there, whether GitHub answers, what
the page's scrub needs; ``?fresh=1`` past the five-minute cache). ``POST
/api/feedback/issue`` ``{kind, title, body}`` files it through that ``gh``, after the page's
confirm showed exactly that title and body; only the page's own caller (``ui``) may, never an
agent's or MCP's token. A 409 carries the title and body the scrub would file instead; nothing
was filed. Kranto's own GitHub identities (its App, a token file) are never used here."""
from __future__ import annotations

from ..http import HttpError, _json
from .base import ok

PEOPLE = ("ui", "cli")


def _status(app, r):
    from ... import feedback as F
    return F.status(app.loop_cfg(), fresh=str(r.data.get("fresh") or "") in ("1", "true"))


def _file(app, r):
    from ... import feedback as F
    if r.who is not None and str(r.who.get("origin") or "") not in PEOPLE:
        raise HttpError(403, "feedback is filed by the person at the page, not by an agent")
    cfg = app.loop_cfg()
    login = F.status(cfg).get("login")
    try:
        out = F.file(cfg, r.data.get("title"), r.data.get("body"), r.data.get("kind"),
                     login=login)
    except F.FeedbackError as e:
        return _json(e.status, {"error": str(e), **e.extra})
    return _json(200, out)


ROUTES = [
    ("GET", "/api/feedback/issue", ok(_status)),
    ("POST", "/api/feedback/issue", _file),
]
