"""Delivery: messages leave the machine only when a target is configured.

Targets are Apprise URLs (the optional extra ``kranto[notify]``).
With no target configured nothing is sent anywhere; messages stay on the
Health page and in the Atom feed.

Each attempt to send one message to one target is a ``deliveries`` row, sent
or failed. Targets are tried independently: an exception or a refusal from
one is recorded and the next target is still tried, and nothing here raises
into the job that triggered it. A failed attempt is retried after later jobs,
up to ``MAX_ATTEMPTS`` per message and target.

Apprise URLs usually carry tokens, so a target is recorded as its scheme and
a short hash of the URL, never the URL itself, and the URL is scrubbed from
recorded errors.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import httpx

from . import gate
from .config import Config
from .links import Links, kranto_mounted
from .store import Store, iso, utcnow
from .stored.misc import MessageEvidenceIds, MessageLinks

log = logging.getLogger("kranto.delivery")

MAX_ATTEMPTS = 3
# Messages older than this are not sent: configuring a target for the first
# time should not replay months of alarms.
WINDOW = timedelta(days=2)
INSTALL_HINT = "pip install 'kranto[notify]'"


def target_label(url: str) -> str:
    scheme = url.split("://", 1)[0] if "://" in url else "unknown"
    return f"{scheme}:{hashlib.sha256(url.encode()).hexdigest()[:10]}"


def _import_apprise():
    try:
        import apprise
    except ImportError:
        return None
    return apprise


def describe(cfg: Config, apprise_module=None) -> str:
    """One line on where messages go, for the Health page, the CLI and doctor."""
    targets = cfg.notify.targets()
    if not targets:
        return ("off: no notify targets are configured, so nothing leaves this machine. "
                "Messages are on the Health page and in the Atom feed.")
    if (apprise_module or _import_apprise()) is None:
        return (f"not sending: {len(targets)} notify target(s) are configured but Apprise is "
                f"not installed ({INSTALL_HINT}).")
    labels = ", ".join(target_label(u) for u in targets)
    return f"on: {len(targets)} target(s) ({labels})"


@dataclass
class DeliveryReport:
    attempted: int = 0
    sent: int = 0
    failed: int = 0
    note: str | None = None
    errors: list[str] = field(default_factory=list)


def compose(message: dict, base_url: str, *, kranto: bool = False) -> tuple[str, str]:
    """Title and plain-text body as delivered, with links back to the instance: into
    Kranto UI when it is mounted (``kranto``), else the server's own pages."""
    to = Links(kranto, base_url)
    lines = [message["body"]]
    links = [u for u in message["links"] if u.startswith(("http://", "https://"))]
    if links:
        lines.append("\nSources:\n" + "\n".join(links[:10]))
    if message["evidence_ids"]:
        lines.append("\nObservations:\n" + "\n".join(
            to.observation(i) for i in message["evidence_ids"][:10]))
    if message["kind"] == "strike":
        lines.append(f"\nWas this worth waking you? Grade it: {to.grade_message(message['id'])}")
    else:
        lines.append(f"\n{to.message(message['id'])}")
    return f"[the server {message['kind']}] {message['title']}", "\n".join(lines)


def _send(apprise_module, url: str, title: str, body: str) -> str | None:
    """None on success, else the reason it failed."""
    client = apprise_module.Apprise()
    if not client.add(url):
        return "Apprise did not accept this URL; check its format"
    if not client.notify(title=title, body=body):
        return "Apprise reported that the notification was not sent"
    return None


def deliver_pending(store: Store, cfg: Config, *, now: datetime | None = None,
                    apprise_module=None) -> DeliveryReport:
    now = now or utcnow()
    report = DeliveryReport()
    targets = cfg.notify.targets()
    if not targets:
        report.note = "no targets configured"
        return report
    module = apprise_module or _import_apprise()
    if module is None:
        report.note = (f"{len(targets)} notify target(s) configured but Apprise is not "
                       f"installed; nothing was sent ({INSTALL_HINT})")
        log.warning(report.note)
        return report
    kranto = kranto_mounted(cfg)
    messages = [
        {**dict(r), "links": MessageLinks.load(r["links"]).items,
         "evidence_ids": MessageEvidenceIds.load(r["evidence_ids"]).items}
        for r in store.query("SELECT * FROM messages WHERE created_at >= ? ORDER BY id",
                             (iso(now - WINDOW),))
    ]
    for message in messages:
        title, body = compose(message, cfg.notify.base_url, kranto=kranto)
        for url in targets:
            label = target_label(url)
            history = store.query(
                "SELECT status FROM deliveries WHERE message_id = ? AND target = ?",
                (message["id"], label))
            if any(h["status"] == "sent" for h in history) or len(history) >= MAX_ATTEMPTS:
                continue
            try:
                error = _send(module, url, title, body)
            except Exception as exc:  # one target's failure must not stop the others
                error = f"{type(exc).__name__}: {exc}"
            if error:
                error = error.replace(url, label)[:500]
            store.insert("deliveries", {
                "message_id": message["id"], "target": label,
                "status": "failed" if error else "sent", "error": error,
                "created_at": iso(now),
            })
            report.attempted += 1
            if error:
                report.failed += 1
                report.errors.append(f"message {message['id']} to {label}: {error}")
                log.warning("delivery of message %s to %s failed: %s", message["id"], label,
                            error)
            else:
                report.sent += 1
    return report


def delivery_summary(store: Store, message_ids: list[int]) -> dict[int, dict]:
    """Per message: targets sent to, and failed attempts with the last error."""
    if not message_ids:
        return {}
    marks = ",".join("?" * len(message_ids))
    out: dict[int, dict] = {}
    for r in store.query(
        f"SELECT message_id, target, status, error FROM deliveries WHERE message_id IN ({marks}) "
        "ORDER BY id", tuple(message_ids),
    ):
        d = out.setdefault(r["message_id"], {"sent": set(), "failed": 0, "last_error": None})
        if r["status"] == "sent":
            d["sent"].add(r["target"])
        else:
            d["failed"] += 1
            d["last_error"] = f"{r['target']}: {r['error']}"
    return out


def after_job(cfg: Config, store: Store, *, now: datetime | None = None,
              apprise_module=None) -> tuple[list[gate.Decision], DeliveryReport]:
    """Run the gate, then deliver. Never raises: a job has already finished by now."""
    decisions: list[gate.Decision] = []
    try:
        decisions = gate.run_gate(store, cfg.strike, now=now)
    except Exception:
        log.exception("strike gate failed")
    try:
        report = deliver_pending(store, cfg, now=now, apprise_module=apprise_module)
    except Exception as exc:
        log.exception("delivery failed")
        report = DeliveryReport(note=f"delivery failed: {type(exc).__name__}: {exc}")
    return decisions, report


def notifying(cfg: Config, store: Store, run: Callable[[], object]) -> Callable[[], object]:
    """Wrap a scheduler job so the gate and delivery follow it, whether it succeeded or not."""

    def job():
        try:
            return run()
        finally:
            after_job(cfg, store)

    return job


def ping_heartbeat(cfg: Config, status: str, *,
                   transport: httpx.BaseTransport | None = None) -> bool | None:
    """Fetch ``notify.heartbeat_ping_url`` after an ingest run that did its work.

    None when no URL is configured or the run was failed or skipped (the
    external monitor notices the missing ping), else whether the ping succeeded.
    """
    url = cfg.notify.heartbeat_ping_url
    if not url or status not in ("ok", "degraded"):
        return None
    try:
        with httpx.Client(transport=transport, timeout=10) as client:
            response = client.get(url)
        if response.status_code >= 400:
            log.warning("heartbeat ping returned HTTP %s", response.status_code)
            return False
    except httpx.HTTPError as exc:
        log.warning("heartbeat ping failed: %s", type(exc).__name__)
        return False
    return True
