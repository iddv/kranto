"""No tool names what left the product (A2: Invest and its broker, the trend radar, the
browser extension): every tool Kranto hands a model, in every profile (kranto mcp with and without
the verb registry, compact, a terminal session's, the researcher's), says none of those words in
its name or its description."""
import re

from kranto.page.mcp import tools as T

from .test_mcp_verbs import Fake

GONE = re.compile(r"\b(invest|radar|broker|extension)\b", re.I)


def _listed() -> dict[str, list[dict]]:
    return {"no registry": T.tools(), "compact": T.tools(compact=True),
            "registry, mcp": T.tools(Fake().client()), "registry, console": T.tools(Fake().client(door="console")),
            "terminal": T.term_tools(), "researcher": T.research_tools()}


def test_no_tool_names_invest_the_broker_the_radar_or_the_extension():
    bad = [f"{where}: {t['name']}: {t.get('description') or ''}"[:200]
           for where, listed in _listed().items() for t in listed
           if GONE.search(t["name"].replace("_", " ")) or GONE.search(t.get("description") or "")]
    assert bad == [], "\n".join(bad)


def test_every_profile_lists_tools():
    assert all(_listed().values())
