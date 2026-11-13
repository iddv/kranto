"""A fake of Resend's API for newsletters, from its documented shapes (resend.com/docs, read
2026-10-21; nothing here was recorded from a real account, and no test reaches the network).

What it answers, as the docs say: ``GET /domains`` and ``/domains/<id>`` (statuses, records),
``GET /segments`` and ``POST /segments``, ``GET /contacts?segment_id=&limit=&after=`` (pages of
100 at most, ``has_more``, no total), ``POST /broadcasts`` (a draft, or with ``send: true`` sent
or scheduled), ``GET /broadcasts/<id>``, ``POST /broadcasts/<id>/send``. A ``sending_access`` key
is refused everywhere here with 401 ``restricted_api_key``; a request without a ``User-Agent``
gets 403. A broadcast that is not a draft cannot be sent again (422 ``validation_error``: the
docs say a sent broadcast's only edit is its name; the exact status is this fake's choice).
"""

from __future__ import annotations

import json
import secrets
import uuid
from urllib.parse import parse_qs

import httpx

HOST = "api.resend.com"


def _id() -> str:
    return str(uuid.uuid4())


class FakeResend:
    def __init__(self) -> None:
        self.key = "re_" + secrets.token_urlsafe(24)
        self.sending_key = "re_" + secrets.token_urlsafe(24)
        self.domains = [{"id": _id(), "name": "news.example.org", "status": "verified",
                         "created_at": "2026-10-01 10:00:00.000000+00", "region": "us-east-1",
                         "capabilities": {"sending": "enabled", "receiving": "disabled"}}]
        self.records = [
            {"record": "SPF", "name": "send", "type": "MX", "ttl": "Auto",
             "status": "not_started", "value": "feedback-smtp.us-east-1.amazonses.com",
             "priority": 10},
            {"record": "SPF", "name": "send", "type": "TXT", "ttl": "Auto",
             "status": "not_started", "value": "\"v=spf1 include:amazonses.com ~all\""},
            {"record": "DKIM", "name": "resend._domainkey", "type": "TXT", "ttl": "Auto",
             "status": "verified", "value": "p=a-public-key"}]
        self.segments = [{"id": _id(), "name": "Newsletter",
                          "created_at": "2026-10-02 10:00:00.000000+00"}]
        self.contacts: list[dict] = []
        self.broadcasts: dict[str, dict] = {}
        self.requests: list[httpx.Request] = []
        self.reply = None        # (status, json) or an exception, for the next send
        self.add_contacts(self.segments[0]["id"], 150, unsubscribed=3)

    def add_contacts(self, segment_id: str, n: int, unsubscribed: int = 0) -> None:
        for i in range(n):
            self.contacts.append({"id": _id(), "email": f"reader{i}@example.net",
                                  "first_name": None, "last_name": None,
                                  "created_at": "2026-10-03 10:00:00.000000+00",
                                  "unsubscribed": i < unsubscribed, "segments": {segment_id}})

    def sends(self) -> list[httpx.Request]:
        """Every request that sends or schedules."""
        out = []
        for r in self.requests:
            if r.method != "POST":
                continue
            direct = r.url.path == "/broadcasts" and json.loads(r.content or b"{}").get("send")
            if r.url.path.endswith("/send") or direct:
                out.append(r)
        return out

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if not request.headers.get("user-agent"):
            return httpx.Response(403, json={"name": "validation_error",
                                             "message": "missing User-Agent", "statusCode": 403})
        auth = request.headers.get("authorization")
        if auth == f"Bearer {self.sending_key}":
            return httpx.Response(401, json={"name": "restricted_api_key", "statusCode": 401,
                                             "message": "This API key is restricted to only "
                                                        "send emails"})
        if auth != f"Bearer {self.key}":
            return httpx.Response(403, json={"name": "validation_error", "statusCode": 403,
                                             "message": "API key is invalid"})
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/domains" and method == "GET":
            return httpx.Response(200, json={"object": "list", "has_more": False,
                                             "data": self.domains})
        if path.startswith("/domains/") and method == "GET":
            d = next((d for d in self.domains if d["id"] == path.rsplit("/", 1)[-1]), None)
            if d is None:
                return httpx.Response(404, json={"name": "not_found", "statusCode": 404})
            return httpx.Response(200, json={"object": "domain", **d, "records": self.records})
        if path == "/segments" and method == "GET":
            return httpx.Response(200, json={"object": "list", "has_more": False,
                                             "data": self.segments})
        if path == "/segments" and method == "POST":
            s = {"id": _id(), "name": body["name"], "created_at": "2026-10-21 08:00:00+00"}
            self.segments.append(s)
            return httpx.Response(201, json={"object": "segment", "id": s["id"],
                                             "name": s["name"]})
        if path == "/contacts" and method == "GET":
            q = {k: v[0] for k, v in parse_qs(request.url.query.decode()).items()}
            limit = min(int(q.get("limit", 20)), 100)
            rows = [c for c in self.contacts if q.get("segment_id") in c["segments"]]
            if q.get("after"):
                at = next(i for i, c in enumerate(rows) if c["id"] == q["after"])
                rows = rows[at + 1:]
            page = rows[:limit]
            return httpx.Response(200, json={
                "object": "list", "has_more": len(rows) > limit,
                "data": [{k: v for k, v in c.items() if k != "segments"} for c in page]})
        if path == "/broadcasts" and method == "POST":
            if self.reply is not None and body.get("send"):
                return self._reply()
            if not any(s["id"] == body.get("segment_id") for s in self.segments):
                return httpx.Response(422, json={"name": "invalid_parameter", "statusCode": 422})
            bid = _id()
            status = "draft"
            if body.get("send"):
                status = "scheduled" if body.get("scheduled_at") else "queued"
            self.broadcasts[bid] = {"object": "broadcast", "id": bid, "name": body.get("name"),
                                    "segment_id": body["segment_id"],
                                    "audience_id": body["segment_id"], "from": body["from"],
                                    "subject": body["subject"], "reply_to": None,
                                    "preview_text": None, "html": body.get("html"),
                                    "text": body.get("text"), "status": status,
                                    "created_at": "2026-10-21 08:00:00+00",
                                    "scheduled_at": body.get("scheduled_at"), "sent_at": None,
                                    "topic_id": None}
            return httpx.Response(200, json={"object": "broadcast", "id": bid})
        if path.startswith("/broadcasts/"):
            parts = path.split("/")
            b = self.broadcasts.get(parts[2])
            if b is None:
                return httpx.Response(404, json={"name": "not_found", "statusCode": 404})
            if len(parts) == 3 and method == "GET":
                return httpx.Response(200, json=b)
            if len(parts) == 4 and parts[3] == "send" and method == "POST":
                if self.reply is not None:
                    return self._reply()
                if b["status"] != "draft":
                    return httpx.Response(422, json={"name": "validation_error",
                                                     "statusCode": 422})
                b["status"] = "scheduled" if body.get("scheduled_at") else "queued"
                b["scheduled_at"] = body.get("scheduled_at")
                return httpx.Response(200, json={"id": b["id"]})
        return httpx.Response(404, json={"name": "not_found", "statusCode": 404})

    def _reply(self) -> httpx.Response:
        reply, self.reply = self.reply, None
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply[0], json=reply[1])
