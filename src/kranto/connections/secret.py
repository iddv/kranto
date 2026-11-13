"""A string that does not print itself."""

from __future__ import annotations


class Secret:
    """A token or client secret. ``str``, ``repr`` and formatting give ``***``, so a
    secret that reaches a log line, an exception or a template shows nothing;
    ``reveal`` is the one way to the value, used where a request is sent."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        if not isinstance(value, str) or not value:
            raise ValueError("a secret must be a non-empty string")
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret(***)"

    def __str__(self) -> str:
        return "***"

    def __format__(self, spec: str) -> str:
        return "***"

    def __eq__(self, other) -> bool:
        return isinstance(other, Secret) and other._value == self._value

    def __hash__(self) -> int:
        return hash(("Secret", self._value))

    def __reduce__(self):
        raise TypeError("a Secret cannot be pickled")
