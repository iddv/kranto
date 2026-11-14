"""Where links back to this instance point: the page (drawn at ``/``) when it is mounted, else
the server's old page addresses (which redirect to the page once it is mounted, and until then
show how to install Kranto).

Delivered messages, the Atom feed and the redirects after a form all link through
here, so moving a page is one change. The page routes on the URL fragment
(``/#/library/o/12``); a message to show after a redirect rides in the
fragment's query (``#/settings/health?msg=...``), which the UI shows as a notice.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from urllib.parse import urlencode

KRANTO = "/#/"


def kranto_mounted(cfg) -> bool:
    """Whether ``python -m kranto serve`` mounts Kranto UI for this config: ``brb.enabled`` and
    the page importable. Used where no server is at hand (delivery after a job)."""
    return bool(cfg.brb.enabled) and importlib.util.find_spec("kranto.page") is not None


@dataclass(frozen=True)
class Links:
    """Paths, or absolute URLs when ``base`` is set (``notify.base_url`` or the request's
    base). ``kranto`` picks Kranto UI's routes."""

    kranto: bool
    base: str = ""

    def _at(self, kranto_route: str, page: str, msg: str | None = None,
            query: dict | None = None) -> str:
        q = {**(query or {}), **({"msg": msg} if msg else {})}
        tail = f"?{urlencode(q)}" if q else ""
        if self.kranto:
            return f"{self.base.rstrip('/')}{KRANTO}{kranto_route}{tail}"
        anchor = ""
        if "#" in page:
            page, anchor = page.split("#", 1)
            anchor = "#" + anchor
        return f"{self.base.rstrip('/')}{page}{tail}{anchor}"

    def observation(self, obs_id: int, msg: str | None = None) -> str:
        return self._at(f"library/o/{int(obs_id)}", f"/obs/{int(obs_id)}", msg)

    def idea(self, idea_id: int) -> str:
        """A the server card. Kranto UI lists cards not yet taken into the loop as
        ``card:<id>``."""
        return self._at(f"ideas/card:{int(idea_id)}", f"/ideas#idea-{int(idea_id)}")

    def ideas(self, msg: str | None = None) -> str:
        return self._at("ideas", "/ideas", msg)

    def message(self, message_id: int) -> str:
        return self._at("settings/health", f"/health#message-{int(message_id)}",
                        query={"message": int(message_id)} if self.kranto else None)

    def grade_message(self, message_id: int) -> str:
        """Where a strike is graded: Kranto Health page has the grade buttons on each
        message; without it, ``/grade/message/<id>``, which redirects there once it is."""
        if self.kranto:
            return self.message(message_id)
        return f"{self.base.rstrip('/')}/grade/message/{int(message_id)}"

    def health(self, msg: str | None = None) -> str:
        return self._at("settings/health", "/health", msg)

    def topics(self, msg: str | None = None) -> str:
        return self._at("settings", "/topics", msg)

    def connections(self, msg: str | None = None) -> str:
        return self._at("settings/connections", "/connections", msg)

    def cluster(self, cluster: int, msg: str | None = None) -> str:
        return self._at(f"library/clusters/{int(cluster)}", f"/clusters#c{int(cluster)}", msg)

    def map(self) -> str:
        return self._at("library/map", "/map", query=None if self.kranto else {"started": 1})
