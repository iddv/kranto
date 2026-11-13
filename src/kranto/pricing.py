"""What a model call costs, for providers that report tokens but not dollars.

The one place list prices live. OpenRouter reports each call's cost itself
(``cost_source: provider``); Anthropic's API reports tokens, so its calls are priced here.
Prices are USD per million tokens from Anthropic's pricing page on ``PRICES_AS_OF``; the
doctor warns when the table is older than ``STALE_AFTER_DAYS``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

PRICES_AS_OF = "2026-10-17"
STALE_AFTER_DAYS = 90
LONG_PROMPT_TOKENS = 100_000


@dataclass(frozen=True)
class Price:
    """USD per million tokens. ``over_100k``: the prices a request pays when its whole prompt
    (cache reads and writes included) is over 100,000 tokens, for a model priced that way."""

    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float
    over_100k: Price | None = None


PRICES: dict[str, Price] = {
    "claude-haiku-5-5": Price(0.10, 0.50, 0.125, 0.20, 0.01,
                              over_100k=Price(0.50, 2.50, 0.625, 1.00, 0.05)),
    "claude-sonnet-5-5": Price(2.0, 10.0, 2.50, 4.0, 0.10),
    "claude-opus-5-5": Price(4.0, 20.0, 5.0, 8.0, 0.20),
    "claude-fable-5-1": Price(10.0, 50.0, 12.50, 20.0, 0.25),
    "claude-sonnet-5": Price(2.0, 10.0, 2.50, 4.0, 0.20),
    "claude-haiku-4-5-20251001": Price(1.0, 5.0, 1.25, 2.0, 0.10),
}
# The short name Anthropic's API also accepts for Haiku 4.5.
PRICES["claude-haiku-4-5"] = PRICES["claude-haiku-4-5-20251001"]


def price_for(model: str, table: dict | None = None) -> Price | None:
    """The price of ``model``: the user's own ``llm.pricing`` entry first (input and output
    only; cache tokens are priced as input), else the list price; None if neither knows it."""
    own = (table or {}).get(model)
    if own is not None:
        inp, out = float(own.input_per_mtok), float(own.output_per_mtok)
        return Price(inp, out, inp, inp, inp)
    return PRICES.get(model)


def cost(model: str, *, input_tokens: int | None, output_tokens: int | None,
         cache_read_tokens: int = 0, cache_write_tokens: int = 0, batch: bool = False,
         table: dict | None = None) -> float | None:
    """USD for one call. ``input_tokens`` is the whole prompt: uncached, cache writes (5-minute,
    the only kind Kranto asks for) and cache reads together. None when the model has no price
    or the tokens are unknown: the client then counts a conservative estimate, never zero."""
    price = price_for(model, table)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    if price.over_100k is not None and input_tokens > LONG_PROMPT_TOKENS:
        price = price.over_100k
    cache_read, cache_write = max(0, cache_read_tokens or 0), max(0, cache_write_tokens or 0)
    uncached = max(0, input_tokens - cache_read - cache_write)
    usd = (uncached * price.input + cache_write * price.cache_write_5m
           + cache_read * price.cache_read + output_tokens * price.output) / 1_000_000
    return usd / 2 if batch else usd


# X's pay-per-use rates (https://docs.x.com/x-api/getting-started/pricing, read on
# X_PRICES_AS_OF), USD per resource a reply returns. ``owned_read``: the person's own
# bookmarks and likes, read by an app the same person owns (each install registers its own).
# X bills a resource returned twice in one UTC day once; Kranto counts every one, so what it
# records is an estimate from above and the Developer Console is the bill.
X_PRICES_AS_OF = "2026-10-17"
X_PRICES: dict[str, float] = {
    "post_read": 0.005,
    "owned_read": 0.001,
    "user_read": 0.010,
    "list_read": 0.005,
}


def x_cost(kind: str, count: int) -> float:
    """USD for ``count`` resources of one X price line; an unknown line costs a post read."""
    return max(0, int(count)) * X_PRICES.get(kind, X_PRICES["post_read"])


# xAI (https://docs.x.ai/developers/pricing and /tools/x-search, read on X_PRICES_AS_OF): USD
# per million tokens for the model the x_search tool is documented with, and per 1,000 posts
# and user profiles the tool fetched, on top of the tokens.
XAI_PRICES: dict[str, tuple[float, float]] = {"grok-4.7": (2.0, 6.0)}
XAI_TOOLS = {"x_post": 5.0 / 1000, "x_user": 10.0 / 1000}


def xai_cost(model: str, input_tokens: int | None, output_tokens: int | None, *,
             posts: int = 0, users: int = 0) -> float | None:
    """USD for one xAI call with x_search; None for a model with no price here."""
    price = XAI_PRICES.get(model)
    if price is None or input_tokens is None or output_tokens is None:
        return None
    return (input_tokens * price[0] + output_tokens * price[1]) / 1_000_000 \
        + max(0, posts) * XAI_TOOLS["x_post"] + max(0, users) * XAI_TOOLS["x_user"]


# Live search backends (2, from the vendors' pages on SEARCH_PRICES_AS_OF), USD per
# request: Exa's search with up to 10 results and highlights ($7 per 1,000; its free mode, with
# no key, is not billed), Brave's Search plan ($5 per 1,000), Tavily's basic search pay as you
# go (one credit, $0.008), Anthropic's web search tool ($10 per 1,000, tokens on top). Hacker
# News, GitHub and arXiv are free and recorded at 0 so Spend can show what was free.
SEARCH_PRICES_AS_OF = "2026-10-17"
SEARCH_PRICES: dict[str, float] = {"exa": 7.0 / 1000, "brave": 5.0 / 1000,
                                   "tavily": 8.0 / 1000, "anthropic_search": 10.0 / 1000}


def search_cost(provider: str, count: int = 1) -> float:
    """USD for ``count`` searches on one backend; a free backend costs 0."""
    return max(0, int(count)) * SEARCH_PRICES.get(provider, 0.0)


def table_age_days(today: date | datetime | None = None) -> int:
    today = today or datetime.now()
    if isinstance(today, datetime):
        today = today.date()
    return (today - date.fromisoformat(PRICES_AS_OF)).days


def stale(today: date | datetime | None = None) -> bool:
    return table_age_days(today) > STALE_AFTER_DAYS
