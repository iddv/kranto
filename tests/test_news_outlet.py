""" D6: a news item never names the search backend as its outlet ("Exa, free mode
(rate-limited, no account)"); it names the item's own site, both for a brief written now and
for one stored before the change."""

from __future__ import annotations

import json

from kranto.features.news import api as news_api
from kranto.features.news import brief as news_brief
from kranto.websearch import EXA_FREE_LABEL, Hit, outlet


class _Results:
    labels = (EXA_FREE_LABEL,)

    def __init__(self, hits):
        self.hits = hits

    def numbered(self):
        return [(f"exa {i + 1}", h) for i, h in enumerate(self.hits)]


def test_a_search_hit_names_its_own_site():
    hit = Hit(url="https://www.reuters.com/tech/padel-1", title="t", date=None, snippet="s",
              backend="exa", query="q", rank=1)
    [line] = news_brief.search_lines(_Results([hit])).values()
    assert line.source == "reuters.com"
    assert outlet("not a url", "Exa") == "Exa" and outlet(None, None) is None


def test_a_brief_stored_with_the_backends_name_reads_as_the_site():
    item = {"headline": "h", "body": "b", "why": "w", "background": False, "sources": [
        {"label": "exa 1", "kind": "web", "url": "https://padelfip.com/news/x",
         "source": EXA_FREE_LABEL},
        {"label": "obs 3", "kind": "obs", "id": 3, "url": "https://a.example/y",
         "source": "a.example"}]}
    row = {"id": 1, "topic_id": 2, "status": "ok", "period_start": "2026-11-10",
           "period_end": "2026-11-11", "items": json.dumps([item]), "quiet": None, "error": None,
           "search": None, "checks": None, "cost_usd": 0, "equiv_usd": 0, "model": "m",
           "prompt_version": "v", "previous_id": None, "trigger": "schedule",
           "created_at": "2026-11-11T07:00:00Z"}
    got = news_api._brief(row)
    sources = got["items"][0]["sources"]
    assert [s["source"] for s in sources] == ["padelfip.com", "a.example"]
    assert EXA_FREE_LABEL not in json.dumps(got)
