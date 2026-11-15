"""Less cost baked into the UI (the owner's ruling, 2026-10-09): what one thing used shows in
tokens, dollars only on Settings › Spend and in cap fields; no price or estimate anywhere else.
Also the polish of the same day: a fix's page has no generic repo tile or README box, a paced
source reads "paced, retrying at …", and a long source name cannot widen the Library's filter."""
import re
from pathlib import Path

from .webui import SRC, css, everything, sources, src

UI = Path(__file__).resolve().parents[2] / "src" / "kranto" / "page" / "ui"
JS = everything()
CSS = css()




def test_dollars_only_on_spend():
    # Settings › Spend: from the cap fields to the breakdowns, and the watcher's line in it
    # Spend's own files are the page with dollars; everything else is outside it
    spend = ("pages/settings/SpendList.svelte", "pages/settings/SpendPane.svelte", "pages/settings/spend.svelte.ts")
    outside = "\n".join(p.read_text() for p in sources() if str(p.relative_to(SRC)) not in spend)
    # the formatters may exist; outside Spend only a configured cap is ever shown in dollars
    for line in outside.splitlines():
        if "money(" in line or "cents(" in line:
            assert line.lstrip().startswith(("const money", "const cents")), line
    prices = [outside[m.start() - 20:m.end() + 10] for m in re.finditer(r"\$\d", outside)
              if outside[m.start() - 1] != '"']           # "$1": a regex backreference
    assert not prices, "no hard-coded price or estimate"
    for gone in ("costLine", "costHint", "priceOf", "in_usd", "out_usd", "a few cents",
                 "usually costs", "OpenRouter list prices", "Prices are per million tokens"):
        assert gone not in JS, gone


def test_tokens_where_a_thing_used_some():
    # (a build's line, its page and its On GitHub box left with the factory, CUT)
    assert not (SRC / "pages" / "builds").exists()
    # W5: Health's runs are rows with their tokens in the meta; the month's tokens are a group row
    health = src("pages/settings/HealthList.svelte")      # moved
    assert "d.tokens_month" in health and "tokText(x.tokens || sm.tokens)" in health and "spend_usd" not in health
    # a topic's pane (moved,): its month in tokens
    card = src("pages/topics/TopicCard.svelte")
    # an observation's model call is the run's trace, under Activity: not on its sheet
    assert "call.prompt_tokens" not in src("pages/library/ObsPane.svelte") and "tokText(x.tokens_month)" in card and "spend_month_usd" not in card


def test_the_token_formatter():
    for part in ('"M"', 'Math.round(n / 1000) + "k"', '" tokens"', " in · ", " out`"):
        fmt = src("lib/format.ts")
        assert part in fmt[fmt.index("export const kTok"):fmt.index("export const n3")], part


def test_paced_sources_say_when_they_are_read_again():
    assert '"paced, retrying " +' in JS
    box = src("pages/settings/HealthList.svelte")         # moved
    assert "pacedWord(s.retry_at)" in box and "failing_runs" in box and "fix it or remove it" in box
    assert 'id="h-src"' in box
    assert "pacedWord(src.retry_at)" in src("pages/settings/HealthPane.svelte")


def test_a_long_source_name_cannot_widen_the_filter():
    rule = CSS[CSS.index(".bar select {"):].split("\n", 1)[0]
    assert "min-width: 0" in rule and "max-width: min(100%" in rule and "text-overflow: ellipsis" in rule
