"""The errors a cub's code sees, one per ``cub/1`` error code a call can end with (protocol).

A call outside the grants raises ``NotGranted`` before anything is written to the pipe; the
host refuses it again if it is sent anyway. A duplicate ticket is not an error: ``ctx.ticket``
returns ``Ticket(duplicate=True)``.
"""

from __future__ import annotations

PARSE = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL = -32603
NOT_GRANTED = -32001
CAP_REACHED = -32002
HALTED = -32003
RATE_LIMITED = -32004
SCHEMA_REJECTED = -32005
NOT_FOUND = -32006
DEADLINE = -32007
UPSTREAM = -32008
DUPLICATE = -32009
PROTOCOL = -32010
TOO_LARGE = -32011
FLOOD = -32012
NOT_CONNECTED = -32013
CANCELLED = -32014
HANDLER_FAILED = -32020


class HostError(Exception):
    """A call the host answered with an error: ``code``, ``message`` (one sentence in words),
    ``data`` (small and typed)."""

    def __init__(self, code: int, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data or {}


class NotGranted(HostError):
    """The approved grants do not cover the call (-32001)."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(NOT_GRANTED, message, data)


class CapReached(HostError):
    """The cub's monthly model cap, its calls a day, or its key-value quota (-32002)."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(CAP_REACHED, message, data)


class RateLimited(HostError):
    """A window is full; ``retry_after_s`` says when it has room (-32004)."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(RATE_LIMITED, message, data)
        self.retry_after_s = (data or {}).get("retry_after_s")


class NotConnected(HostError):
    """The broker operation needs the owner's credential and none is connected (-32013)."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(NOT_CONNECTED, message, data)


class HostTooOld(HostError):
    """This Kranto does not know the method (-32601): a newer SDK called it."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(METHOD_NOT_FOUND, message, data)


class Cancelled(HostError):
    """The host cancelled the call while it waited (-32014)."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(CANCELLED, message, data)


BY_CODE = {NOT_GRANTED: NotGranted, CAP_REACHED: CapReached, RATE_LIMITED: RateLimited,
           NOT_CONNECTED: NotConnected, METHOD_NOT_FOUND: HostTooOld, CANCELLED: Cancelled}


def from_wire(error: dict) -> HostError:
    """The exception for a JSON-RPC ``error`` object."""
    code = int(error.get("code", INTERNAL))
    message = str(error.get("message") or "the host refused the call")
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    cls = BY_CODE.get(code)
    return cls(message, data) if cls else HostError(code, message, data)
