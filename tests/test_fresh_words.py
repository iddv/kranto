"""The words a fresh home shows of the server's own (the walk on the preview's fresh
home): the accounts' one-line blurbs on Settings › Watching and Posting carry no word of the
test ("Google Cloud project", "the Sanity project", "repositories you star" were the last)."""

from __future__ import annotations

import re

from kranto import connections
from kranto.newsletter import buttondown, resend

# the word test, and the nouns for a person (scripts/preview/acceptance.py's WORDS)
WORDS = re.compile(
    r"\b(build(?:s|ing)?|built|projects?|repos?|repositor(?:y|ies)|"
    r"publish(?:ing|ed)?|pitch(?:es)?|invest|radar|broker|extension|pairing|shop|"
    r"cubs?|tickets?|practice run|classic|arrange)\b",
    re.I,
)


def test_no_accounts_blurb_carries_a_word_of_builds_cubs_or_the_broker():
    rows = [*connections.PROVIDER_INFO, buttondown.INFO, resend.INFO]
    said = {r["key"]: r["blurb"] for r in rows if r.get("blurb")}
    assert {"github", "youtube", "sanity", "mastodon_post"} <= set(said)
    hits = {k: WORDS.findall(v) for k, v in said.items() if WORDS.search(v)}
    assert hits == {}, hits
