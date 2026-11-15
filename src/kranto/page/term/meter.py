"""What a session costs. The TUI has no stream-json, and Kranto keeps no price
table, so Claude Code's own figure is used: the session's status line command writes the JSON
it is given (``cost.total_cost_usd``, ``session_id``, ``model``) to ``meter/status.json``, and
the tokens are counted from the transcript's ``usage`` lines (one per message id). Kranto adds
the growth since its last reading to the loop's ledger, as chat's spend (``spend("chat", ...)``).
The figure comes from the sandboxed process: trust as chat's today.

A process's figure starts at 0 (a resumed session is a new process): ``Reading.base`` is reset
when Kranto starts one.

A request the Claude API refused reaches the transcript as Claude Code's own assistant message
with ``isApiErrorMessage`` (its text, "Credit balance is too low", "Invalid API key · …", "…usage
limit…"); ``refusal`` finds one about credit, the login or a usage limit when it is the last
assistant message, so the page can say why nothing happens."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# what a refusal that no retry fixes says: the account's credit, the credential, a usage limit
REFUSAL = re.compile(r"credit balance|billing|api key|x-api-key|authenticat|unauthori[sz]ed|"
                     r"oauth|log ?in|permission|usage limit|limit reached|quota", re.I)
REFUSAL_ERRORS = ("billing_error", "authentication_failed", "authentication_error",
                  "permission_error", "rate_limit")


def status(meter: Path) -> dict:
    try:
        d = json.loads((Path(meter) / "status.json").read_text())
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def usd(st: dict) -> float:
    try:
        return float(((st.get("cost") or {}).get("total_cost_usd")) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def scan(transcript: Path) -> tuple[int, int, str | None]:
    """``(in, out, refusal)``: the tokens over the transcript's assistant messages (cache reads
    and writes count as input), each message counted once, and the last assistant message's
    text when it is a refusal (``REFUSAL``) of the Claude API's, else None."""
    seen: dict[str, tuple[int, int]] = {}
    refused = None
    try:
        lines = Path(transcript).read_text(errors="replace").splitlines()
    except OSError:
        return 0, 0, None
    for i, ln in enumerate(lines):
        try:
            ev = json.loads(ln)
        except ValueError:
            continue
        msg = ev.get("message") if isinstance(ev, dict) else None
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        refused = _refusal(ev, msg) if ev.get("isApiErrorMessage") else None
        u = msg.get("usage")
        if not isinstance(u, dict):
            continue
        tin = sum(int(u.get(k) or 0) for k in ("input_tokens", "cache_creation_input_tokens",
                                                "cache_read_input_tokens"))
        seen[str(msg.get("id") or i)] = (tin, int(u.get("output_tokens") or 0))
    return sum(a for a, _ in seen.values()), sum(b for _, b in seen.values()), refused


def _refusal(ev: dict, msg: dict) -> str | None:
    content = msg.get("content")
    parts = [content] if isinstance(content, str) else \
        [c.get("text") for c in content or [] if isinstance(c, dict) and c.get("text")]
    text = " ".join(str(p) for p in parts).strip()
    err = str(ev.get("error") or "")
    if not (REFUSAL.search(text) or err in REFUSAL_ERRORS):
        return None
    return (text or err)[:300]


def tokens(transcript: Path) -> tuple[int, int]:
    """``(in, out)`` of ``scan``."""
    return scan(transcript)[:2]


def refusal(transcript: Path) -> str | None:
    """The refusal of ``scan``."""
    return scan(transcript)[2]


@dataclass
class Reading:
    """What was already counted for one process: the dollars (its own figure) and the
    session's tokens (the transcript holds every process's)."""
    usd: float = 0.0
    tin: int = 0
    tout: int = 0
    model: str | None = None
    refusal: str | None = None                   # the last reply's refusal (``scan``)
    seen: dict = field(default_factory=dict)

    def step(self, meter: Path, transcript: Path) -> dict | None:
        """The growth since the last step, ``{"usd", "in", "out"}``, or None; ``refusal`` is
        the transcript's, as of this step."""
        st = status(meter)
        now = usd(st)
        if st.get("model"):
            m = st["model"]
            self.model = m.get("id") if isinstance(m, dict) else str(m)
        tin, tout, self.refusal = scan(transcript)
        d = {"usd": max(0.0, now - self.usd), "in": max(0, tin - self.tin),
             "out": max(0, tout - self.tout)}
        self.usd, self.tin, self.tout = max(now, self.usd), max(tin, self.tin), \
            max(tout, self.tout)
        return d if (d["usd"] or d["in"] or d["out"]) else None
