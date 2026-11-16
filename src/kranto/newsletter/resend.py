"""Resend (MAIL, the owner's choice and the default): a newsletter platform, connected with a
pasted API key, a from address on a verified domain, and an audience.

Everything here is from Resend's own documentation, read on 2026-10-21 (resend.com/docs; the
notes are in the track's report):

- base ``https://api.resend.com``, ``Authorization: Bearer <key>``, a ``User-Agent`` on every
  request (Kranto's HTTP client sends one); 10 requests a second per team, 429 above;
- an API key is ``full_access`` or ``sending_access`` ("can only send emails"). Broadcasts,
  segments, contacts and domains need **Full access**: a sending-only key is answered 401
  ``restricted_api_key``, which Save and test says in plain words;
- "Audiences are now called Segments" (November 2025): the audience is a segment
  (``GET /segments``, ``POST /segments {name}``); its subscribers are the contacts in it whose
  ``unsubscribed`` is false (``GET /contacts?segment_id=``, 100 a page, no total);
- a domain is ``not_started``, ``pending``, ``verified``, ``partially_verified`` (sending works),
  ``partially_failed``, ``failed`` or ``temporary_failure``; ``GET /domains/<id>`` lists its DNS
  records with each one's status;
- a broadcast is created as a draft (``POST /broadcasts {segment_id, from, subject, html, text,
  name}``), sent or scheduled once (``POST /broadcasts/<id>/send {scheduled_at?}``), and is
  ``draft``, ``scheduled``, ``queued``, ``sent`` or ``canceled``. A scheduled one can be cancelled
  (back to a draft, nothing sent); a queued one cancelled stops what is not delivered yet; a sent
  one cannot be recalled;
- ``{{{RESEND_UNSUBSCRIBE_URL}}}`` is the link Resend makes for each reader; Kranto puts it in
  every issue's footer;
- idempotency keys are offered on single emails, **not on broadcasts**. So "never sent twice" is
  Kranto's own: a ticket is confirmed once; a press sends the one broadcast its draft names, after
  reading that it is still a ``draft``; a press whose answer did not come is ``unknown`` and is
  never repeated.
"""

from __future__ import annotations

import re

from ..connections.base import Grant, Provider, need
from ..connections.oauth import OAuthError
from ..connections.secret import Secret
from ..sources.base import SourceError
from .platform import Check, Platform
from .render import to_html, to_text

ORDER = 10
API = "https://api.resend.com"
API_HOST = "api.resend.com"
SCOPES = ("full_access",)
UNSUBSCRIBE = "{{{RESEND_UNSUBSCRIBE_URL}}}"
SENDING = ("verified", "partially_verified")
ID = re.compile(r"[A-Za-z0-9-]{1,64}")
EMAIL = re.compile(r"[^\s@<>\"]{1,64}@([A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+)")
FROM = re.compile(r"\s*(?:([^<>\"\n]{1,80}?)\s*<([^<>\s]{3,254})>|([^<>\s]{3,254}))\s*")
PAGES = 20                                     # 100 contacts a page: counted up to 2,000
DEADLINE_S = 30.0
FULL_ACCESS = ("This key can only send emails. Newsletters (broadcasts) need a Full access "
               "key: in Resend open API Keys, click Create API Key, choose Permission: Full "
               "access, and paste that key here.")


def headers_for(key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {key}"}


def error_name(r) -> str | None:
    """Resend's error type (``restricted_api_key``, ``validation_error``, ...) from a JSON
    reply, only when it is a short slug: never free text that may quote what was sent."""
    try:
        body = r.json()
    except ValueError:
        return None
    if not isinstance(body, dict):
        return None
    for key in ("name", "code", "type"):
        v = body.get(key)
        if isinstance(v, str) and 0 < len(v) <= 60 and re.fullmatch(r"[a-z0-9_.-]+", v):
            return v
    return None


def parse_from(value: str) -> tuple[str, str] | None:
    """``(display, address)`` from ``Name <you@news.example.com>`` or a bare address."""
    m = FROM.fullmatch(value or "")
    if not m:
        return None
    name, addr = (m.group(1) or "").strip(), (m.group(2) or m.group(3) or "").strip()
    if not EMAIL.fullmatch(addr):
        return None
    return name, addr


def _json(r) -> dict:
    try:
        body = r.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


# -- the reads both Save and test and Check again make ----------------------------------------


class _Reads:
    """GETs at Resend: with a pasted key before the connection exists (``headers``), or with a
    connection's ``http`` (authed). A 4xx reply is returned so its error type can be read."""

    def __init__(self, http, headers: dict | None = None) -> None:
        self.http, self.headers = http, headers

    def get(self, path: str, params: dict | None = None):
        return self.http.get(f"{API}{path}", params=params, headers=self.headers,
                             deadline=DEADLINE_S, errors=False)


def _segments(reads: _Reads) -> list[dict]:
    r = reads.get("/segments")
    data = _json(r).get("data") if 200 <= r.status_code < 300 else None
    return [s for s in data or [] if isinstance(s, dict) and isinstance(s.get("id"), str)]


def find_audience(segments: list[dict], wanted: str) -> dict | None:
    wanted = (wanted or "").strip()
    return next((s for s in segments if s.get("id") == wanted), None) or next(
        (s for s in segments if str(s.get("name") or "").strip().casefold()
         == wanted.casefold()), None)


def count_subscribers(get, segment_id: str) -> tuple[int | None, bool]:
    """The contacts in the segment that have not unsubscribed, paging 100 at a time up to
    ``PAGES`` pages: ``(count, more)``, ``more`` when there were more pages than that."""
    n, after = 0, None
    for _ in range(PAGES):
        params = {"segment_id": segment_id, "limit": 100, **({"after": after} if after else {})}
        try:
            r = get("/contacts", params)
        except SourceError:
            return None, False
        if not 200 <= r.status_code < 300:
            return None, False
        body = _json(r)
        rows = [c for c in body.get("data") or [] if isinstance(c, dict)]
        n += sum(1 for c in rows if c.get("unsubscribed") is not True)
        if not body.get("has_more") or not rows or not isinstance(rows[-1].get("id"), str):
            return n, False
        after = rows[-1]["id"]
    return n, True


def subscribers_words(n: int | None, more: bool = False) -> str:
    if n is None:
        return "subscribers not counted"
    return f"{n:,}{'+' if more else ''} subscriber{'' if n == 1 and not more else 's'}"


def _check(reads: _Reads, sender_from: str | None, audience: str | None) -> Check:
    said, missing, keep = [], [], {}
    r = reads.get("/domains")
    if r.status_code == 401 and error_name(r) == "restricted_api_key":
        return Check(False, missing=[FULL_ACCESS])
    if r.status_code in (401, 403):
        return Check(False, missing=[f"Resend refused this key (HTTP {r.status_code}): copy "
                                     "it again from API Keys."])
    if not 200 <= r.status_code < 300:
        return Check(False, missing=[f"Resend answered {r.status_code} when kranto read your "
                                     "domains; try again in a minute."])
    said.append("The key has Full access.")
    domains = [d for d in _json(r).get("data") or [] if isinstance(d, dict)]
    parsed = parse_from(sender_from or "")
    if parsed is None:
        missing.append("No from address yet: type one like Your Name <news@your-domain>, on "
                       "the domain you verify in Resend.")
    else:
        keep["from"] = f"{parsed[0]} <{parsed[1]}>" if parsed[0] else parsed[1]
        host = parsed[1].rsplit("@", 1)[1].lower()
        dom = next((d for d in domains if str(d.get("name") or "").lower() == host), None)
        if dom is None:
            missing.append(f"Your domain {host} is not in Resend yet: add it under Domains, "
                           "then add the DNS records Resend shows you at your DNS provider.")
        elif dom.get("status") not in SENDING:
            missing.append(_unverified(reads, dom))
        else:
            said.append(f"The domain {host} is verified.")
    segments = _segments(reads)
    found = find_audience(segments, audience or "") if audience else None
    if not audience:
        missing.append("No audience chosen: type the name of the audience (a segment in "
                       "Resend) the newsletter goes to.")
    elif found is None:
        missing.append(f"There is no audience named “{audience.strip()[:80]}” in "
                       "Resend: click Create the audience, or make it in Resend (Audience, "
                       "Segments) and add your subscribers to it.")
    else:
        keep["audience_id"] = found["id"]
        keep["audience_name"] = str(found.get("name") or found["id"])[:80]
        n, more = count_subscribers(reads.get, found["id"])
        said.append(f"The audience {keep['audience_name']} has {subscribers_words(n, more)}."
                    + (" Import your subscribers into it before you send (see the "
                       "newsletter guide)." if n == 0 else ""))
    return Check(not missing, said=said, missing=missing, sender=keep)


def _unverified(reads: _Reads, dom: dict) -> str:
    name, status = dom.get("name"), dom.get("status") or "not verified"
    lines = []
    if isinstance(dom.get("id"), str) and ID.fullmatch(dom["id"]):
        r = reads.get(f"/domains/{dom['id']}")
        if 200 <= r.status_code < 300:
            for rec in _json(r).get("records") or []:
                if isinstance(rec, dict) and rec.get("status") != "verified":
                    lines.append(" ".join(str(rec.get(k) or "")[:120] for k in
                                          ("type", "name", "value") if rec.get(k)))
    records = (": add these DNS records at your DNS provider, then click Verify DNS Records "
               "in Resend: " + "; ".join(lines[:8])) if lines else \
        ": add the DNS records Resend lists for it (Domains), then click Verify DNS Records"
    return f"Your domain {name} isn't verified yet ({status}){records}."


# -- the connection ---------------------------------------------------------------------------


class ResendProvider(Provider):
    key = "resend"
    name = "Resend"
    scopes = SCOPES
    default_instance = "resend.com"
    writes = True

    def api_host(self, instance: str, entry: dict) -> str:
        return API_HOST

    def headers(self, entry: dict, method: str, url: str) -> dict[str, str]:
        return headers_for(entry["key"])

    def paste(self, fields: dict) -> Grant:
        """Save and test: the key is kept only when Resend accepts it with Full access; what
        else is missing (the domain's records, the audience) is said, and kept for the next
        Check again."""
        key = Secret(need(fields, "key", "The API key"))
        sender_from = str(fields.get("from") or "").strip()[:300]
        audience = str(fields.get("audience") or "").strip()[:120]
        reads = _Reads(self.http, headers_for(key.reveal()))
        try:
            found = _check(reads, sender_from, audience)
        except SourceError as exc:
            raise OAuthError(f"Resend did not answer ({_why(exc)}); nothing was kept") from None
        if not found.said:                      # the key itself was refused
            raise OAuthError(found.missing[0] if found.missing else "Resend refused this key")
        if self.conns is not None:
            from . import keep_sender
            keep_sender(self.conns.store, PLATFORM, {**found.sender,
                                                     "last_check": found.kept()})
        account = found.sender.get("from") or "Resend"
        return Grant(account, SCOPES, {"key": key.reveal()}, note=found.words())

    def identify(self, http, instance: str, entry: dict) -> str:
        r = http.get(f"{API}/domains", deadline=DEADLINE_S, errors=False)
        if r.status_code == 401 and error_name(r) == "restricted_api_key":
            raise OAuthError(FULL_ACCESS)
        if not 200 <= r.status_code < 300:
            raise OAuthError(f"Resend answered {r.status_code}")
        from . import sender
        return (sender(self.conns.store).get("from") if self.conns is not None else None) \
            or "Resend"


INFO = {
    "key": "resend", "name": "Resend", "state": "available", "flow": "paste",
    "writes": True, "group": "newsletter",
    "blurb": "Your Resend account, for the newsletter: Kranto drafts an issue as a "
             "broadcast, and sends it to your audience with this key only when you approve "
             "that issue (Send now).",
    "scopes": ["Full access (broadcasts need it)"],
    "reads": "Your domains and whether they are verified, your audiences and how many "
             "subscribers each has, and the broadcasts Kranto drafted.",
    "never": "Never sends without your approval, and never while the newsletter is in practice "
             "(the default: nothing is sent) or stopped. Never adds, edits or removes a "
             "contact.",
    "revoke_at": "resend.com, API Keys: delete the key.",
    "expiry": "no expiry",
    "steps": ["Sign in at resend.com. Under Domains, add the domain you send from (a "
              "subdomain such as news.your-domain is what Resend recommends), add the DNS "
              "records it shows at your DNS provider, and click Verify DNS Records.",
              "Under Audience, make a segment for the newsletter (or use one you have) and "
              "import your subscribers into it (Add contacts, Import CSV).",
              "Under API Keys, click Create API Key, name it Kranto, Permission: Full access "
              "(a Sending access key cannot make broadcasts), and copy it.",
              "Paste the key, the audience's name and your from address below, and click Save "
              "and test. Kranto only reads: it says what is missing in plain words.",
              "Issues are practice (nothing is sent) until you turn on Send for real."],
    "fields": [{"key": "key", "label": "API key", "placeholder": "re_...", "secret": True},
               {"key": "audience", "label": "Audience (a segment's name)",
                "placeholder": "Newsletter"},
               {"key": "from", "label": "From", "placeholder": "Your Name <news@your-domain>"}],
    "sources": [],
}


# -- the platform -----------------------------------------------------------------------------


class Resend(Platform):
    id = "resend"
    name = "Resend"
    ref_prefix = "rs"
    about = ("An email platform: you paste a Full access API key, verify your sending domain, "
             "and choose the audience; issues go out as broadcasts, now or at a time.")
    docs = "docs/newsletter.md#resend"
    can_schedule = True
    connection = ResendProvider
    info = INFO

    def ready(self, sender: dict) -> str | None:
        if not sender.get("from") or not sender.get("audience_id"):
            return ("Resend needs a from address and an audience: Settings › Accounts › "
                    "Newsletter, Check again")
        return None

    def audience_words(self, sender: dict) -> str:
        name = sender.get("audience_name")
        return f"the audience {name}" if name else "no audience chosen yet"

    def footer(self) -> str | None:
        return "An unsubscribe link for each reader, which Resend makes and handles."

    def _body(self, content: dict, sender: dict) -> dict:
        footer = f'<a href="{UNSUBSCRIBE}">Unsubscribe</a>'
        return {"segment_id": sender["audience_id"], "from": sender["from"],
                "subject": content["subject"], "name": content["subject"][:200],
                "html": to_html(content["body"], footer=footer),
                "text": to_text(content["body"], footer=f"Unsubscribe: {UNSUBSCRIBE}")}

    def _fail(self, r, what: str):
        from ..core.cubs.brokers.base import BrokerError
        name = error_name(r)
        return BrokerError(-32008, f"Resend answered {r.status_code} {what}"
                           + (f" ({name})" if name else ""), status=r.status_code, code=name)

    def create_draft(self, ctx, content: dict, sender: dict) -> dict:
        r = ctx.send("POST", f"{API}/broadcasts", json=self._body(content, sender))
        if not 200 <= r.status_code < 300:
            raise self._fail(r, "to the draft")
        bid = str(_json(r).get("id") or "")
        if not ID.fullmatch(bid):
            from ..core.cubs.brokers.base import BrokerError
            raise BrokerError(-32008, "Resend's answer had no broadcast id")
        return {"external_id": bid, "url": None}

    def status(self, ctx, draft: dict) -> dict:
        r = ctx.send("GET", f"{API}/broadcasts/{draft['external_id']}")
        if not 200 <= r.status_code < 300:
            raise self._fail(r, "for the broadcast")
        st = _json(r).get("status")
        return {"status": st if isinstance(st, str) and len(st) <= 40 else "unknown",
                "url": None}

    def newsletter(self, ctx, sender: dict) -> dict:
        return {"name": sender.get("audience_name") or ctx.label,
                "subscriber_count": self.subscribers(ctx, sender)}

    def subscribers(self, ctx, sender: dict) -> int | None:
        if not sender.get("audience_id"):
            return None
        n, _ = count_subscribers(lambda path, params: ctx.send("GET", f"{API}{path}",
                                                               params=params),
                                 sender["audience_id"])
        return n

    def send(self, ctx, draft: dict, when: str, sender: dict) -> dict:
        from ..core.cubs.brokers.base import outcome_of
        later = None if when == "now" else when
        if draft["ref"].startswith(f"{self.ref_prefix}:"):
            bid = draft["external_id"]
            # Resend takes no idempotency key on a broadcast: read first, send only a draft
            try:
                r = ctx.send("GET", f"{API}/broadcasts/{bid}")
            except SourceError as exc:
                return {"state": "refused", "note": "refused: the broadcast's status could not "
                        f"be read at Resend ({_why(exc)}); nothing was sent"}
            if r.status_code == 404:
                return {"state": "refused", "note": "refused: the broadcast is no longer at "
                                                    "Resend (deleted there?); nothing was sent"}
            if not 200 <= r.status_code < 300:
                return {"state": "refused", "note": f"refused: Resend answered {r.status_code} "
                                                    "for the broadcast; nothing was sent"}
            now = _json(r)
            if now.get("status") != "draft":
                return {"state": "refused", "note": f"refused: the broadcast is "
                        f"{str(now.get('status') or 'not a draft')[:20]} at Resend; Kranto sends "
                        "a draft, once"}
            if now.get("subject") not in (None, draft["content"]["subject"]):
                return {"state": "refused", "note": "refused: the broadcast was changed at "
                                                    "Resend since the draft (its subject)"}
            try:
                r = ctx.send("POST", f"{API}/broadcasts/{bid}/send",
                             json={"scheduled_at": later} if later else {})
            except SourceError as exc:
                return outcome_of(exc, "Resend", sending="the issue was sent")
        else:
            try:
                r = ctx.send("POST", f"{API}/broadcasts",
                             json={**self._body(draft["content"], sender), "send": True,
                                   **({"scheduled_at": later} if later else {})})
            except SourceError as exc:
                return outcome_of(exc, "Resend", sending="the issue was sent")
            bid = None
        if not 200 <= r.status_code < 300:
            name = error_name(r)
            return {"state": "refused", "note": f"refused: Resend answered {r.status_code}"
                    + (f" ({name})" if name else "") + "; nothing was sent"}
        bid = bid or str(_json(r).get("id") or "")
        bid = bid if ID.fullmatch(bid) else None
        return {"state": "done", "note": self._result(ctx, bid, later), "external_id": bid}

    def _result(self, ctx, bid: str | None, later: str | None) -> str:
        """The broadcast's status read back after the send (best effort)."""
        status = None
        if bid:
            try:
                r = ctx.send("GET", f"{API}/broadcasts/{bid}")
                if 200 <= r.status_code < 300:
                    status = _json(r).get("status")
            except SourceError:
                status = None
        status = status if isinstance(status, str) and len(status) <= 20 else None
        name = bid or "the broadcast"
        if later or status == "scheduled":
            return (f"scheduled: {name} for {later or 'the time set'} ({status or 'accepted'}); "
                    "to stop it, cancel it at Resend (Broadcasts) before then: it goes back to "
                    "a draft and nothing is sent")
        return (f"sent: {name} ({status or 'accepted'}); a sent broadcast cannot be recalled. "
                "While it is queued, Cancel at Resend stops the emails not yet delivered")

    def check(self, http, sender: dict) -> Check:
        return _check(_Reads(http), sender.get("from"),
                      sender.get("audience_id") or sender.get("audience_name"))

    def create_audience(self, http, name: str) -> dict:
        """The owner's press of Create the audience (never a cub's): ``POST /segments``."""
        r = http.post(f"{API}/segments", json={"name": name}, deadline=DEADLINE_S,
                      errors=False)
        if not 200 <= r.status_code < 300:
            n = error_name(r)
            raise OAuthError(f"Resend answered {r.status_code}" + (f" ({n})" if n else ""))
        sid = str(_json(r).get("id") or "")
        if not ID.fullmatch(sid):
            raise OAuthError("Resend's answer had no audience id")
        return {"audience_id": sid, "audience_name": name}


def _why(exc: SourceError) -> str:
    return f"HTTP {exc.status}" if exc.status else "no answer"


PLATFORM = Resend()
