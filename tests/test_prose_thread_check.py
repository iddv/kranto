"""The checker on a thread and on figures: each post of a thread against the site's limit (never
their sum), a decimal point is not a sentence's end, and a month's short name is not a person."""

from __future__ import annotations

from kranto.prose import check
from kranto.prose.checker import people_not_in, sentences
from kranto.web.app import create_app

from .conftest import web_client
from .test_web import rt  # noqa: F401 - fixture

# a three-part Bluesky thread of 150, 181 and 216 characters, the seeded draft's shape
THREAD = [
    "Is the tariff you picked for your home battery really the cheapest one for you, or did a "
    "single blog or spreadsheet's break-even arithmetic decide it?",
    "The inputs differ a lot. On Octopus, Flexible is 34.46p by day and 9.9p overnight; "
    "Flexible Max is 38.62p and 6.5p. Which wins depends on how much of your load falls in "
    "each window.",
    "The data for a better answer exists: owners already replay their own system logs at about "
    "6.5-second intervals, and charge planners read tomorrow's prices. Would you trust your own "
    "logs over a stranger's spreadsheet?",
]
TEXT = "\n\n".join(THREAD)


def _length_flags(got: dict) -> list[dict]:
    return [f for f in got["flags"] if f["rule"] == "site.length"]


def test_the_seeded_thread_is_three_posts_each_under_the_limit():
    assert [len(p) for p in THREAD] == [150, 181, 216]
    # joined, the thread is over Bluesky's 300: checked as one post it is flagged
    assert _length_flags(check(TEXT, "bluesky"))
    # as a thread, each post is under the limit: no length flag
    assert _length_flags(check(TEXT, "bluesky", parts=THREAD)) == []


def test_a_post_over_the_limit_is_named():
    long = "Word " * 70                                  # 350 characters
    parts = [THREAD[0], long.strip(), THREAD[2]]
    flags = _length_flags(check("\n\n".join(parts), "bluesky", parts=parts))
    assert len(flags) == 1
    assert flags[0]["words"].startswith("part 2 of 3: 349 characters; the site takes 300")
    # two posts over: two flags, each naming its post
    parts = [long.strip(), THREAD[1], long.strip()]
    words = [f["words"] for f in _length_flags(check("\n\n".join(parts), "bluesky", parts=parts))]
    assert [w.split(":")[0] for w in words] == ["part 1 of 3", "part 3 of 3"]


def test_one_post_says_characters_not_graphemes():
    got = _length_flags(check("Word " * 70, "bluesky"))
    assert got and "characters" in got[0]["words"] and "grapheme" not in got[0]["words"]


def test_decimals_are_not_sentence_openings():
    s = THREAD[1]
    got = [s[a:b] for a, b in sentences(s)]
    assert got == ["The inputs differ a lot.",
                   "On Octopus, Flexible is 34.46p by day and 9.9p overnight; Flexible Max is "
                   "38.62p and 6.5p.",
                   "Which wins depends on how much of your load falls in each window."]
    rules = {f["rule"] for f in check(TEXT, "bluesky", parts=THREAD)["flags"]}
    assert "rhythm.openings" not in rules
    # a sentence that ends on a number still ends
    assert len(sentences("It cost 4.5. Then it rose.")) == 2


def test_a_month_short_name_is_not_a_person():
    text = "The 28 Oct Budget brought VAT on battery retrofits back to 0% from April."
    assert people_not_in(text, "VAT on home batteries returns in April 2027") == []
    # a real two-word name the sources lack is still flagged
    assert people_not_in("Jane Smith said it would.", "a budget") != []


def test_the_check_route_takes_a_threads_parts(rt):  # noqa: F811
    with web_client(create_app(rt), "http://127.0.0.1:8765") as client:
        r = client.post("/api/prose/check", json={"text": TEXT, "site": "bluesky",
                                                  "parts": THREAD})
        assert r.status_code == 200
        assert _length_flags(r.json()) == []
        assert client.post("/api/prose/check", json={"text": TEXT, "parts": "no"}
                           ).status_code == 400
        # the verb takes them too (an assistant checks a thread the same way)
        r = client.post("/api/verbs/prose.check", json={"fields": {"text": TEXT, "site": "bluesky",
                                                                   "parts": THREAD}})
        assert r.status_code == 200 and r.json()["ok"]
