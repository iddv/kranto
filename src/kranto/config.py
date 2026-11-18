"""Workspace configuration.

A workspace is a directory holding ``kranto.yaml`` and a ``data/`` directory
(the SQLite library plus caches). Secrets never live in the YAML: the config
names the environment variable that holds the API key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from . import legacy, product

CONFIG_FILENAME = product.HOME_FILE
# A home made before the rename keeps its settings file's old name; either is read, the new
# first (``legacy.HOME_FILES``).
KRANTO_CONFIG_FILENAME = product.HOME_FILE
CONFIG_FILENAMES = (product.HOME_FILE, *legacy.HOME_FILES)
WORKSPACE_ENV = "KRANTO_HOME"
KRANTO_HOME_ENV = "KRANTO_HOME"

DEFAULT_CONFIG_YAML = """\
# The server workspace configuration.
# Secrets are read from the environment variable named in llm.api_key_env,
# which may also be set in a .env file next to this one.

llm:
  # Which provider the tiers use: openrouter, anthropic (the Claude API, its key in
  # ANTHROPIC_API_KEY), openai_compat (any OpenAI-compatible endpoint), or claude_code (your
  # Claude Code login; shares your plan's usage windows). Left out: openai_compat with the
  # endpoint below. Settings › Watching and Welcome write it.
  # provider: openrouter
  # Any OpenAI-compatible chat completions endpoint.
  base_url: https://openrouter.ai/api/v1
  api_key_env: OPENROUTER_API_KEY
  # "provider": use the cost the provider reports per call (OpenRouter does).
  # "table": use the pricing table below. A model with no known cost is refused.
  cost_source: provider
  # Settings › Watching › Models in Kranto UI writes these. A "provider/" prefix routes the call
  # through the endpoint's provider (OpenRouter's names); a bare name goes to the endpoint as is.
  models:
    judge: anthropic/claude-haiku-5.5     # tier 1: judges every item that passes the prefilter
    reason: anthropic/claude-sonnet-5.5   # tier 2: scout, explain, idea cards
  # USD per million tokens, used when cost_source is "table".
  pricing: {}
  timeout_seconds: 60
  max_retries: 3
  # Ceilings on a reply's length, per call (tokens; only what is written is paid for). A
  # reply cut off at its ceiling is asked again once with twice the room before it counts
  # as a failure. Defaults: judge 3000, judge_gathered 4000, screen 1000, card 8000,
  # verify 4000, scout 8000, resolve 8000, explain 3000, rollup 2000, name 1000. Set any
  # of them here.
  max_tokens: {}
  # pricing, when cost_source is "table": {model: {input_per_mtok: 1.0, output_per_mtok: 5.0}}.
  # One tier on another provider: tiers: {reason: {provider: anthropic, model: ...}}.
  # The Claude API (provider anthropic): its key's variable, one prompt-cache breakpoint on the
  # system prompt, and per call (screen, judge, name) schema-enforced replies and the thinking
  # effort (low, medium, high; unset: the model's default). 'kranto watch provider replay'
  # measures both.
  # anthropic: {api_key_env: ANTHROPIC_API_KEY, base_url: https://api.anthropic.com,
  #             cache: true, structured: {}, effort: {}}
  # Claude Code's login (provider claude_code): per call a JSON schema for the reply, sandbox:
  # true runs 'claude -p' in bubblewrap (no tools either way), one call's limit, and the empty
  # folder calls run in (default <home>/data/claude-cwd).
  # claude_code: {structured: {}, sandbox: false, timeout_seconds: 180, cwd: ""}

budget:
  # The watcher's monthly budget (USD): model calls stop when it is reached. null: no cap,
  # the default (the owner's rule: spend is uncapped unless a cap is set; a $10 default
  # stopped gathering mid-month at a normal week's volume, #8). Settings › Spend in the
  # Kranto UI writes it.
  monthly_usd: null
  # Fraction of the monthly budget at which the health page starts warning.
  alarm_fraction: 0.8

ingest:
  every_hours: 3
  max_items_per_source: 10
  # The gate: an item is kept when its signal (the judge's three ratings multiplied) is at
  # least this. It belongs to the judge model: Haiku 4.5 was calibrated at 0.20; on 160 live
  # items (2026-10-08) Haiku 5.5 rated about four times lower, and 0.03 matched 4.5's keeps
  # best (86% agreement). Settings › Watching › Models sets the judge and this together.
  signal_threshold: 0.03
  # Items whose embedding similarity to every topic they could serve is below
  # this are skipped without an LLM call. Calibration (nomic, 2026-09-24):
  # on-topic items scored 0.55-0.74, an off-topic HN front page had median 0.505.
  # The prefilter is a cost saver, not a quality judge, so it errs toward recall...
  prefilter_min_similarity: 0.50
  # ...except for this fraction, sampled at random, which keeps the library
  # from collapsing onto the wording of your topics.
  exploration_fraction: 0.05
  # HN link posts and RSS items with under 300 characters of body that pass the
  # prefilter get the linked page fetched and its main text (up to 4000
  # characters) judged instead. Costs up to about 1000 more input tokens per item.
  fetch_full_text: true
  # On a source's first run the per-source cap is this instead, once, so a new
  # topic starts with some history. HN query sources reach back backfill_days
  # (a source parameter, default 14). Values below max_items_per_source have no effect.
  backfill_items: 40
  # Items published longer ago than this are recorded as stale and never judged:
  # an old or since-removed post is not news (0 turns the check off).
  max_age_days: 30

fetch:
  # Polite fetching. One request at a time per host, at least this many seconds apart
  # (end of one to start of the next); hosts lists hosts that ask for more (arXiv's
  # three seconds is built in).
  min_gap_seconds: 1.0
  hosts: {}
  # A 429 or 503 waits for the server's Retry-After, else backs off exponentially with
  # jitter; a timeout backs off too. Waits up to max_wait_seconds are retried in the
  # request, at most retries times; a longer one defers the source (Paced, retrying
  # at ...). Paced is never a failure and never marks a run degraded.
  retries: 2
  max_wait_seconds: 30
  # A source that fails this many runs in a row (a 404, a feed that does not parse)
  # backs off by itself, failing_backoff_hours doubling per further failure up to
  # failing_backoff_max_hours, and shows under Needs you: fix it or remove it.
  failing_after_runs: 3
  failing_backoff_hours: 24
  failing_backoff_max_hours: 168

stories:
  # One voice must not count as many. Before an item is judged, its title
  # and the start of its body are compared with what was judged in the last
  # window_days (word shingles, MinHash; no model call). Similarity is the
  # estimated share of shingles two texts have in common (Jaccard, 0 to 1).
  window_days: 30
  # At or above this an item from another source is the same text (a
  # crosspost): it is consumed as near_duplicate without a model call. The
  # same applies within one source to an item posted again within
  # same_source_days. On 138 labelled pairs from Parallax's items, every
  # pair at 0.9 or more under these rules was the same story.
  skip_at: 0.9
  # From here up to skip_at, an item from another source is judged as usual
  # and, if kept, joins the earlier item's story: movement, bursts, idea
  # candidates and the cross-source rule count it once.
  link_at: 0.5
  same_source_days: 3
  # Source ids whose items are never matched with each other: feeds whose items
  # share a template (prediction markets, release notes, status bots). Sources
  # whose items mostly look alike are detected without this list.
  templated_sources: []

map:
  every_hours: 24

ideas:
  # Idea cards are generated after a new map, at most this many per run, each
  # costing one tier-2 call plus one tier-1 verification call.
  every_hours: 24
  max_cards_per_run: 4
  # Project topics (topics the page created for its projects): skip leaves their
  # themes out of the candidates; cards lets them be carded like any other.
  project_topics: skip

strike:
  # The gate that decides which candidates interrupt you. Each origin scores on
  # its own scale, so each has its own absolute threshold:
  #   card:  product of the five fitness ratings, each in [0, 1]. 0.15 needs
  #          ratings averaging about 0.68 (geometric mean); all-0.5 cards score 0.03.
  #   burst: 1 - q, where q is the BH-corrected binomial q-value. Burst candidates
  #          already need q < 0.05 (score > 0.95); 0.99 asks for q < 0.01.
  min_card_score: 0.15
  min_burst_score: 0.99
  # min_watch_score: retired with watches; a file that still has it loads, and nothing reads it.
  # No second strike about the same subject (a lineage) within this many days.
  refractory_days: 7
  # At most this many strikes in any rolling seven days, across all subjects.
  max_per_week: 2
  # No strikes until the library has this many map snapshots behind it, and its
  # first map is at least warmup_days old.
  warmup_snapshots: 2
  warmup_days: 3

retention:
  # Observations older than this many days are compacted: clustered with the
  # rest of their week into rollups (a name, a short summary, keywords, source
  # mix and up to five links), then removed together with the model calls that
  # hold their source's raw text. Trends in the map survive; the text does not.
  # 0 keeps observations forever.
  default_days: 90
  # Per source kind (rss, hackernews, reddit, arxiv, bluesky, mastodon, github,
  # youtube, producthunt, stackexchange, x, parallax), e.g. {reddit: 30}. x is kept 30
  # days unless set here (stored X posts have to track X's; a default you may raise). A single
  # source can be set with 'kranto watch sources retention ID DAYS' or on its page;
  # newsletter publications added from the catalog are kept 30 days. youtube is
  # capped at 30 days (YouTube's policies for API data): more is refused.
  # parallax (an archive imported with 'kranto watch import parallax') is kept forever
  # unless set here: its observations are older than default_days when imported.
  by_kind: {}
  # How often compaction runs under 'kranto serve' (after the snapshot).
  every_hours: 24

activity:
  # What Kranto is doing, recorded as it goes (Settings › System › Activity): each run's
  # marks (started, how far it is, ended) are kept this many days, then removed by
  # compaction with a purge record. The runs themselves are kept as before.
  keep_days: 30
  # At most this many marks in all; the oldest go first (also with a purge record).
  max_rows: 20000

look:
  # Look before judging. Each item that passes the prefilter is first
  # screened: a short tier-1 call asks whether it is potentially worth a closer
  # look (lenient; what it drops is recorded as screened_out with its reason).
  # For items that pass, what is one step away is gathered (no model call): the
  # Hacker News discussion, pages the item and its comments link to, repositories
  # it names. The judge then reads the item with that material, and may keep
  # gathered sources that hold up as observations of their own, linked to the
  # item. false: every item goes straight to the judge, as before #84.
  enabled: true
  # Per item: pages linked from the item and its comments, and repositories.
  max_links: 2
  max_repos: 1
  # Comments read from a Hacker News thread for its discussion.
  max_comments: 20
  # Characters of each gathered source the judge reads.
  gathered_chars: 2000
  # Wall-clock seconds for one item's gathering, and for any one request in it.
  item_seconds: 30
  request_seconds: 15
  # Items gathered for in one ingest run; items past it are judged without
  # gathering (the run's summary counts them), so a run's length stays bounded.
  max_per_run: 40
  # GitHub's public API allows 60 requests an hour per address; each repository
  # read costs two.
  max_repo_lookups: 10
  # Reddit comments come from the post's public feed, paced like every Reddit
  # request (one a minute). Off: see RESPONSIBLE_USE.md before turning it on.
  reddit_comments: false
  # Short posts (X, Bluesky, Mastodon; under 600 characters, no comments) are screened this
  # many to one call: the screen's instructions are most of a short post's call. 1: one
  # call per item, as for every other kind.
  screen_batch: 20

notify:
  # Apprise URLs (https://github.com/caronc/apprise/wiki), e.g. "mailto://...",
  # "ntfy://...", "tgram://...". Needs: pip install 'kranto[notify]'.
  # Empty means nothing leaves this machine; messages stay on the Health page
  # and in the Atom feed at /feed.xml. URLs usually carry tokens: prefer
  # listing them (space or comma separated) in the environment variable named
  # by urls_env, which may be set in the .env file next to this one.
  urls: []
  urls_env: KRANTO_NOTIFY_URLS
  # Used to build links (grade this strike, open an observation) in delivered messages.
  base_url: http://127.0.0.1:8765
  # The weekly heartbeat: sent even when nothing struck, so quiet is not mistaken for broken.
  heartbeat_every_hours: 168
  # Optional healthchecks.io-style URL, fetched after every ingest run that is ok or degraded.
  heartbeat_ping_url: null

brb:
  # The page: Kranto's web UI with its console (kranto up turns it on). Served only when
  # the server is bound to loopback. loop_home: the page's own folder, its settings file
  # loop.yaml and its console sessions (default: $KRANTO_LOOP_HOME, else ~/kranto-loop; a
  # Kranto home sets its own loop/). root and harness were for an earlier release's builds:
  # still accepted in a file that has them, and left out of a new one.
  enabled: false

connections:
  # Sources read with your own account (Settings › Sources › Accounts): Mastodon,
  # Bluesky, GitHub, YouTube, Product Hunt and Stack Exchange. Only read-only
  # scopes are asked for. Tokens are kept encrypted in data/secrets/ (mode 0600),
  # never in this file, the library or an export. Needs: pip install
  # 'kranto[connections]'. On by default; 'enabled: false' turns connected
  # accounts off (their sources then report Needs login).
  # github_client_id: the client id of a GitHub OAuth app you registered with
  # device flow enabled (no secret). Turns on "Sign in with GitHub"; without it,
  # GitHub is connected with a pasted fine-grained token.

x:
  # X as a source, read with your own X developer app (Settings › Sources › Accounts › X). X bills
  # your developer account per post read ($0.005; your own bookmarks and likes $0.001), so
  # kranto reads only what it will judge, and every read is counted on Settings › Spend.
  # monthly_usd: X sources wait until next month once this month's reads reach it; null: no
  # cap, the default. A list's or your home timeline's posts a run, one account's, a
  # search's (searches run once a day), bookmarks and likes once a day.
  monthly_usd: null
  posts_per_fetch: 20
  profile_per_fetch: 10
  search_results: 10
  search_every_hours: 24
  owned_every_hours: 24
  # An account's own threads (a post and its author's replies) joined into one item.
  read_threads: true
  # Kept posts checked for deletion once a week, at most this many (0: off).
  recheck_days: 7
  recheck_max: 100
  # Whether the scout may propose X searches and accounts while X is connected, and how many
  # a run (each proposal is checked with one fetch of 10 posts, about $0.05).
  scout: true
  scout_max_proposals: 5

search:
  # Live web search for the callers that ask what exists, what is new or what is prior art
  # (the scout, idea cards, the weekly editor, the research desk). provider: exa | brave |
  # tavily | anthropic | none. exa with no EXA_API_KEY in the .env uses Exa's free mode
  # (rate-limited, no account); a key (a free Exa account has $10 of credit a month) gives you
  # your own limits. brave and tavily need BRAVE_API_KEY or TAVILY_API_KEY. anthropic uses the
  # watcher's Claude API key ($10 per 1,000 searches plus tokens). none: every caller says "no
  # live search: results are from model memory and may be stale".
  provider: exa
  # Hacker News (Algolia), GitHub (your connection when there is one) and arXiv: always free.
  free: true
  # The same query from any caller within this many hours is answered from the cache
  # (titles, links, dates and snippets only).
  cache_hours: 24
  # "Recent" in every grounded prompt: results dated in the last this many weeks.
  recent_weeks: 12
  # Searches pause for the month once paid searches reach this many USD; null: no cap.
  monthly_usd: null
  # Per caller: on, or off (that caller says "no live search" and runs from memory).
  callers:
    scout: on
    cards: on
    editor: on
    research: agent
    resolve: failed_lines
    pitch: on
    evolve: on
    # sites without a feed, watched through live search (a "Live search" source)
    sources: on

telemetry:
  # Usage reports (docs/privacy/what-kranto-sends.md). local: counted on this machine and
  # never sent, until you answer the question (kranto setup, Welcome or Settings › Privacy &
  # access).
  # off: nothing is counted. basic: one report a day with no identifier. detailed: the same
  # with a random id you can reset. Nothing is sent without an endpoint, and this release
  # has none by default. DO_NOT_TRACK=1 or KRANTO_TELEMETRY=off in the environment win.
  mode: local

parallax:
  # An archive imported from Parallax ('kranto watch import parallax', 'kranto watch import
  # parallax-dispatches'): its observations are browsable in the Library under
  # their "(Parallax)" sources and count in the map, but are never new on Today
  # and never arrivals in the map's movement.
  # topic_match: 0 keeps the archive out of every topic's views (its sources have
  # no topic). Above 0, a topic's evidence also lists archive observations at
  # least this similar to the topic (cosine; the prefilter uses 0.50), worked out
  # when the page is read: nothing is stored, so setting it back to 0 is instant.
  topic_match: 0
  # Whether the map's own idea runs may cite archive observations. Off: a card's
  # evidence is the library's own reading, and the archive's ideas arrive as the
  # dispatch cards.
  card_evidence: false
  # Whether the page's automatic intake may take cards made from your dispatches.
  # Off: they wait in Ideas until you click Build.
  dispatch_auto_intake: false

update:
  # Updates ('kranto update', Settings › System). channel: stable (what the maintainer made
  # stable, and fixes), nightly (every build from main; the old rc reads as nightly) or main
  # (each repo's main, from git). maintainer: true on the maintainer's install only, by hand
  # (Needs you offers Promote to stable there). check_every_hours: 0 never checks. download:
  # stage a new release's wheels as soon as it is seen. auto: off (you click Restart to update)
  # or idle (inside quiet_window, local time, when nothing runs). keep_backups: the update
  # backups and wheel sets kept. token_env_file: a 0600 file with GH_TOKEN= for a private repo
  # on a machine without a gh login. source: github-releases, or git for the main channel.
  # repo: the release repository.
  channel: stable
  check_every_hours: 24
  download: true
  auto: "off"
  quiet_window: "03:00-06:00"
  keep_backups: 3

api:
  # Every change made through the page or the API needs a kranto token (~/.config/kranto/tokens:
  # The page's sign-in cookie, or Authorization: Bearer), and the token says who acted. false:
  # the old way, by the request's origin; kranto doctor warns about it.
  require_token: true

# grading:
#   What your ▲ and ▼ on cards and evidence do (help: Grading). A card rises by how much it
#   resembles what you upvoted, minus what you downvoted; no model decides it. A source with
#   many downvotes is offered for removal in Needs you (never removed without your approval).
#   half_life_days: 90        # a grade counts half after this many days
#   observation_weight: 0.5   # an evidence grade, against a card grade's 1
#   cos_low: 0.30             # below this centred cosine nothing "reads alike"...
#   cos_high: 0.60            # ...and from this one it fully does
#   topic_weight: 0.25        # the same topic, read only when a side has no vector
#   strong_at: 0.25           # a part a card's line counts ("like 2 cards you upvoted")
#   theme_skip_below: -0.5    # a theme at or under this is not carded by the next ideas run
#   window_days: 90           # the source rule's window...
#   remove_after: 3           # ...this many downvoted posts in it...
#   remove_ratio: 0.25        # ...and at most this share as many upvoted

# ask:
#   What an assistant may do by itself (the console in Kranto, your own Claude Code or Codex
#   over kranto mcp, an agent's token): for each kind of action, do, ask (it prepares the action
#   and you approve it on the page) or never, and exceptions per verb. Empty: Kranto's defaults
#   (reads, changes you can undo and spending: do; what leaves Kranto and what cannot be undone:
#   ask). Keys, tokens and logins are yours on the page, whatever this says.
#   Settings › Assistant writes it. See docs/verbs.md.
#   ladder: {kinds: {spend: ask}, verbs: {topic.add: do}}

# Sections other parts of Kranto own, each checked by its owner and empty by default:
# features (news: and later ones: see docs/features.md and each feature's page), shell: (the
# home page's arrangement) and cubs: (the cubs' switches and limits: docs/cubs.md).
"""


class ConfigError(Exception):
    """The workspace or its configuration is missing or invalid."""


@dataclass(frozen=True)
class ModelPrice:
    input_per_mtok: float
    output_per_mtok: float


# Calls whose replies may be schema-enforced (``llm.anthropic.structured``); MAX_TOKENS' names.
STRUCTURED_CALLS = ("screen", "judge", "name")


@dataclass(frozen=True)
class AnthropicConfig:
    """``llm.anthropic``: the Claude API. ``cache``: one prompt-cache
    breakpoint on the system prompt (5-minute, refreshed on every hit). ``structured``: per
    call, whether the reply is schema-enforced JSON. ``effort``: per call, the thinking
    effort (``low``, ``medium``, ``high``); unset is the model's default."""

    api_key_env: str = "ANTHROPIC_API_KEY"
    base_url: str = "https://api.anthropic.com"
    cache: bool = True
    structured: dict[str, bool] = field(default_factory=dict)
    effort: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaudeCodeConfig:
    """``llm.claude_code``: the user's Claude Code login as the watcher's model,
    offered only as an explicit choice (the owner's D2). ``structured``: per call, a JSON schema
    for the reply (``--json-schema``). ``sandbox``: bubblewrap around ``claude -p`` (D11; no tools
    either way). ``timeout_seconds``: one call's limit. ``cwd``: the empty directory calls run
    in, ``<home>/data/claude-cwd`` when left out."""

    structured: dict[str, bool] = field(default_factory=dict)
    sandbox: bool = False
    timeout_seconds: float = 180.0
    cwd: str = ""
    home: str = ""


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    api_key_env: str
    cost_source: str
    models: dict[str, str]
    pricing: dict[str, ModelPrice] = field(default_factory=dict)
    timeout_seconds: float = 60.0
    max_retries: int = 3
    # Reply-length ceilings set in the config, by call (``MAX_TOKENS`` names them).
    max_tokens: dict[str, int] = field(default_factory=dict)
    # Which provider serves the tiers (``PROVIDERS``). None: ``openai_compat`` with the
    # endpoint above, which is every install from before providers.
    provider: str | None = None
    # One tier on another provider: {"reason": {"provider": ..., "model": ...}}.
    tiers: dict[str, dict[str, str]] = field(default_factory=dict)
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    claude_code: ClaudeCodeConfig = field(default_factory=ClaudeCodeConfig)

    def env_for(self, provider: str) -> str | None:
        """The environment variable holding ``provider``'s key (None: it needs none)."""
        if provider == "anthropic":
            return self.anthropic.api_key_env
        if provider in ("openrouter", "openai_compat"):
            return self.api_key_env
        return None

    @property
    def key_env(self) -> str | None:
        """The variable holding the key of the provider the tiers use."""
        return self.env_for(self.provider_name)

    def api_key(self) -> str | None:
        """The key of the provider the tiers use, from the environment."""
        env = self.key_env
        return (os.environ.get(env) or None) if env else None

    @property
    def provider_name(self) -> str:
        return self.provider or "openai_compat"

    def provider_for(self, tier: str) -> str:
        return (self.tiers.get(tier) or {}).get("provider") or self.provider_name

    def model_for(self, tier: str) -> str:
        """The tier's model, in its provider's names. KeyError for a tier with none."""
        override = self.tiers.get(tier) or {}
        return override.get("model") or self.models[tier]

    def providers_in_use(self) -> list[str]:
        names = [self.provider_name]
        for tier in self.tiers:
            name = self.provider_for(tier)
            if name not in names:
                names.append(name)
        return names


# The model providers ``llm.provider`` may name (``providers/``).
PROVIDERS = ("openrouter", "openai_compat", "anthropic", "claude_code")
EFFORTS = ("low", "medium", "high")


def _parse_claude_code(raw) -> ClaudeCodeConfig:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError("llm.claude_code must be a mapping")
    unknown = set(raw) - {"structured", "sandbox", "timeout_seconds"}
    if unknown:
        raise ConfigError(f"unknown keys in llm.claude_code: {', '.join(sorted(unknown))}")
    structured = raw.get("structured") or {}
    if not isinstance(structured, dict) or set(structured) - set(STRUCTURED_CALLS) or \
            not all(isinstance(v, bool) for v in structured.values()):
        raise ConfigError(f"llm.claude_code.structured maps calls "
                          f"({', '.join(STRUCTURED_CALLS)}) to true or false")
    sandbox = raw.get("sandbox", False)
    if not isinstance(sandbox, bool):
        raise ConfigError("llm.claude_code.sandbox must be true or false")
    timeout = raw.get("timeout_seconds", 180)
    if (isinstance(timeout, bool) or not isinstance(timeout, int | float)
            or not 10 <= timeout <= 1800):
        raise ConfigError("llm.claude_code.timeout_seconds must be from 10 to 1800")
    return ClaudeCodeConfig(structured={str(k): bool(v) for k, v in structured.items()},
                            sandbox=sandbox, timeout_seconds=float(timeout))


def _parse_anthropic(raw) -> AnthropicConfig:
    raw = raw or {}
    if not isinstance(raw, dict):
        raise ConfigError("llm.anthropic must be a mapping")
    unknown = set(raw) - set(AnthropicConfig.__dataclass_fields__)
    if unknown:
        raise ConfigError(f"unknown keys in llm.anthropic: {', '.join(sorted(unknown))}")
    structured = raw.get("structured") or {}
    effort = raw.get("effort") or {}
    if not isinstance(structured, dict) or set(structured) - set(STRUCTURED_CALLS) or \
            not all(isinstance(v, bool) for v in structured.values()):
        raise ConfigError(f"llm.anthropic.structured maps calls ({', '.join(STRUCTURED_CALLS)})"
                          " to true or false")
    if not isinstance(effort, dict) or set(effort) - set(MAX_TOKENS) or \
            not all(v in EFFORTS for v in effort.values()):
        raise ConfigError(f"llm.anthropic.effort maps calls to {', '.join(EFFORTS)}")
    env = str(raw.get("api_key_env") or AnthropicConfig.api_key_env)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", env):
        raise ConfigError("llm.anthropic.api_key_env must be a variable name")
    base = str(raw.get("base_url") or AnthropicConfig.base_url).rstrip("/")
    if not re.match(r"https?://", base):
        raise ConfigError("llm.anthropic.base_url must be an http(s) URL")
    cache = raw.get("cache", True)
    if not isinstance(cache, bool):
        raise ConfigError("llm.anthropic.cache must be true or false")
    return AnthropicConfig(api_key_env=env, base_url=base, cache=cache,
                           structured={str(k): bool(v) for k, v in structured.items()},
                           effort={str(k): str(v) for k, v in effort.items()})


# Reply-length ceilings per call (tokens), overridable under llm.max_tokens. The judge's
# were 800 and 1800 until 2026-10-08: verbose replies about rich items were cut off (6 of
# about 740 judge calls on the operator's instance), which marked ingests degraded.
# Haiku 5.5 reasons before it answers, and the reasoning counts against the ceiling: on
# 2026-10-08 its screen replies used 38-620 tokens (p99 517; the answer itself is under
# 100), so 160 cut off 26 of 64 live screens; cluster names used 168-372 against 200,
# judge replies up to 1418. Screen was 160, judge 2000, rollup 1000, name 200 until then.
MAX_TOKENS = {"judge": 3000, "judge_gathered": 4000, "screen": 1000, "card": 8000,
              "verify": 4000, "scout": 8000, "resolve": 8000, "explain": 3000, "rollup": 2000,
              "name": 1000}


@dataclass(frozen=True)
class BudgetConfig:
    """``monthly_usd`` None: no cap (model calls are never refused for spend)."""

    monthly_usd: float | None
    alarm_fraction: float = 0.8

    @property
    def capped(self) -> bool:
        return self.monthly_usd is not None

    def of(self) -> str:
        """``of $40.00`` or ``(no cap)``, to follow an amount spent."""
        if not self.capped:
            return "(no cap)"
        return f"of ${self.monthly_usd:.2f}"  # stored-shape: capped above

    def alarm(self, spent: float) -> bool:
        """Whether ``spent`` is past the alarm line (never without a cap)."""
        return self.capped and spent >= self.monthly_usd * self.alarm_fraction


@dataclass(frozen=True)
class IngestConfig:
    every_hours: float = 3
    max_items_per_source: int = 10
    signal_threshold: float = 0.03            # the template's value (Haiku 5.5's calibration)
    prefilter_min_similarity: float = 0.50
    exploration_fraction: float = 0.05
    fetch_full_text: bool = True
    backfill_items: int = 40
    # Items published longer ago than this are not judged (0 turns the check off).
    max_age_days: float = 30


@dataclass(frozen=True)
class FetchConfig:
    """Pacing per host, backoff, and when a failing source backs off (``sources.pacing``)."""

    min_gap_seconds: float = 1.0
    hosts: dict[str, float] = field(default_factory=dict)
    retries: int = 2
    max_wait_seconds: float = 30.0
    failing_after_runs: int = 3
    failing_backoff_hours: float = 24.0
    failing_backoff_max_hours: float = 168.0


@dataclass(frozen=True)
class StoriesConfig:
    """Near-duplicates on pre-judge text. Similarities are Jaccard estimates."""

    window_days: float = 30
    skip_at: float = 0.9
    link_at: float = 0.5
    same_source_days: float = 3
    templated_sources: tuple[int, ...] = ()


@dataclass(frozen=True)
class MapConfig:
    every_hours: float = 24


IDEAS_PROJECT_TOPICS = ("skip", "cards")


@dataclass(frozen=True)
class IdeasConfig:
    every_hours: float = 24
    max_cards_per_run: int = 4
    # ``skip``: no card candidate from a project topic's clusters (``cards.candidates``);
    # ``cards``: they are candidates like any other.
    project_topics: str = "skip"


@dataclass(frozen=True)
class StrikeConfig:
    """The strike gate. Thresholds are per origin because scores are on different scales."""

    min_card_score: float = 0.15
    min_burst_score: float = 0.99
    # Retired with watches: read so an older kranto.yaml still loads, used by
    # nothing. Removed in the release that drops the watches tables.
    min_watch_score: float = 0.65
    refractory_days: float = 7
    max_per_week: int = 2
    warmup_snapshots: int = 2
    warmup_days: float = 3

    def threshold(self, origin: str) -> float | None:
        """The absolute threshold for a candidate origin, or None if the gate has none."""
        return {"card": self.min_card_score, "burst": self.min_burst_score}.get(origin)


# Kinds a site's terms allow to be kept only so long: YouTube API data at most 30
# days (YouTube developer policies). A larger setting, or 0 (forever), is refused
# for these kinds, and the default is capped.
KIND_MAX_DAYS = {"youtube": 30.0}


def cap_days(kind: str | None, days: float) -> float:
    """``days`` within a kind's cap (0, forever, becomes the cap)."""
    cap = KIND_MAX_DAYS.get(kind or "")
    if cap is None:
        return float(days)
    return cap if days <= 0 else min(float(days), cap)


# Kinds kept forever unless retention.by_kind says otherwise: an imported archive is
# older than the default retention age the moment it arrives, so the default would
# purge all of it at the next compaction.
# X posts: 30 days by default (stored X content has to track X, and a short
# window is the cheapest way to); a default, not a cap, so retention.by_kind.x may raise it.
KIND_DEFAULT_DAYS = {"parallax": 0.0, "x": 30.0}


@dataclass(frozen=True)
class RetentionConfig:
    """How long observations are kept before compaction. 0 days: forever."""

    default_days: float = 90
    by_kind: dict[str, float] = field(default_factory=lambda: dict(KIND_DEFAULT_DAYS))
    every_hours: float = 24

    def days_for_kind(self, kind: str | None) -> float:
        return cap_days(kind, float(self.by_kind.get(kind or "", self.default_days)))


@dataclass(frozen=True)
class ActivityConfig:
    """How long a run's marks are kept (the owner's D-4)."""

    keep_days: float = 30
    max_rows: int = 20000


@dataclass(frozen=True)
class HomeConfig:
    """The home: after ``away_days`` days or more without a visit, it opens
    with While you were away (one list of five) instead of today's brief and ideas."""

    away_days: int = 3


HOME_AWAY_DAYS = (1, 60)


@dataclass(frozen=True)
class LookConfig:
    """Screen, gather, then judge."""

    enabled: bool = True
    max_links: int = 2
    max_repos: int = 1
    max_comments: int = 20
    gathered_chars: int = 2000
    item_seconds: float = 30
    request_seconds: float = 15
    max_per_run: int = 40
    max_repo_lookups: int = 10
    reddit_comments: bool = False
    # short posts screened together, this many to one call; 1: one each
    screen_batch: int = 20


@dataclass(frozen=True)
class DeepDiveConfig:
    """Deep dives on observations queued by hand. Off by default.

    ``min_signal`` is unused since #84 and kept so existing configurations load."""

    enabled: bool = False
    min_signal: float = 0.5
    daily_usd: float | None = 0.05
    every_hours: float = 3
    max_per_run: int = 10
    max_links: int = 3
    max_repos: int = 2
    max_comments: int = 20
    reddit_comments: bool = False
    max_attempts: int = 3
    max_queue_days: float = 7


@dataclass(frozen=True)
class NotifyConfig:
    urls: tuple[str, ...] = ()
    urls_env: str = "KRANTO_NOTIFY_URLS"
    base_url: str = "http://127.0.0.1:8765"
    heartbeat_every_hours: float = 168
    heartbeat_ping_url: str | None = None

    def targets(self) -> list[str]:
        """Configured Apprise URLs: the YAML list, then the environment variable."""
        out = [u.strip() for u in self.urls if u and u.strip()]
        env = os.environ.get(self.urls_env, "") if self.urls_env else ""
        out += [u for u in env.replace(",", " ").split() if u]
        return list(dict.fromkeys(out))


@dataclass(frozen=True)
class BrbConfig:
    """The page's builds UI, mounted at /brb/ by 'kranto serve' when the page is
    installed in
    the same environment. Off by default. ``root`` is the task folder it lists (default: the
    loop's tasks_dir, ~/tasks) and ``loop_home`` the loop's home (default: ~/kranto-loop)."""

    enabled: bool = False
    root: str | None = None
    loop_home: str | None = None
    harness: str = "claude-code"


@dataclass(frozen=True)
class BuildsConfig:
    """Builds, projects and repo maintenance (``builds:``; PR 1.1). Off unless
    set, and absent means off: no loop lane, no maintenance poll, no build pages or ``b.*``
    verbs, and project topics are not read (they are listed as paused; nothing is written).
    ``brb.enabled`` is the page at /brb/; this switch is the half of it that builds."""

    enabled: bool = False


@dataclass(frozen=True)
class ApiConfig:
    """Who may write (OI). ``require_token``: every state-changing request needs a token from
    ``~/.config/kranto/tokens`` (the page's session cookie, or ``Authorization: Bearer``), and
    the token, not the request, says who acts. Off: the old behaviour (the request's own
    ``origin``), which ``kranto doctor`` warns about."""

    require_token: bool = True


@dataclass(frozen=True)
class AskConfig:
    """What an assistant may do by itself (``ask:``; ``core.verbs``): the
    ladder, ``{"kinds": {kind: do|ask|never}, "verbs": {verb: do|ask|never}}``. Empty: Kranto's
    defaults (``verbs.DEFAULTS``); the locks are not settings."""

    ladder: dict = field(default_factory=dict)


@dataclass(frozen=True)
class UpdateConfig:
    """Updates (section 3). ``source``: where releases are looked for
    (``github-releases``, or ``git`` for the main channel's commits); ``repo``: the release
    repo; ``channel``: ``stable`` (what the maintainer promoted, and fixes), ``nightly`` (every
    build from main; the retired ``rc`` is read as ``nightly``) or ``main`` (git heads);
    ``check_every_hours``: 0 never checks; ``download``: stage a new release's wheels
    as soon as it is seen; ``auto``: ``off`` (a click: Restart to update) or ``idle`` (inside
    ``quiet_window``, local time, when nothing runs); ``keep_backups``: update backups and
    wheel sets kept; ``token_env_file``: a 0600 file with GH_TOKEN= for a private repo on a
    host without a gh login (null: gh's own login, or anonymous for a public repo);
    ``maintainer``: this is the maintainer's install, which offers Promote to stable (by hand
    only)."""

    source: str = "github-releases"
    repo: str = "iddv/kranto"
    channel: str = "stable"
    check_every_hours: float = 24
    download: bool = True
    auto: str = "off"
    quiet_window: str = "03:00-06:00"
    keep_backups: int = 3
    token_env_file: str | None = None
    # the maintainer's install: Needs you offers Promote to stable here, and
    # only here. Written by hand in kranto.yaml; no page sets it.
    maintainer: bool = False


UPDATE_SOURCES = ("github-releases", "git")
UPDATE_CHANNELS = ("stable", "nightly", "main")
UPDATE_AUTO = ("off", "idle")


def quiet_window(text: str) -> tuple[int, int]:
    """``"03:00-06:00"`` as minutes after midnight (start, end); the end may be past
    midnight (``"23:00-02:00"``). Raises ValueError."""
    m = re.fullmatch(r"\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*", str(text))
    if not m:
        raise ValueError(f"not HH:MM-HH:MM: {text!r}")
    a, b = int(m[1]) * 60 + int(m[2]), int(m[3]) * 60 + int(m[4])
    if not (0 <= a < 1440 and 0 <= b < 1440 and int(m[2]) < 60 and int(m[4]) < 60) or a == b:
        raise ValueError(f"not a window of the day: {text!r}")
    return a, b


@dataclass(frozen=True)
class ConnectionsConfig:
    """Connected accounts (section 3): sources read with your own login.
    Tokens are kept encrypted in data/secrets/, never here. Needs the cryptography
    package (pip install 'kranto[connections]'). ``github_client_id``: an OAuth
    app's client id (no secret), which turns on GitHub's device flow."""

    enabled: bool = True
    github_client_id: str | None = None


@dataclass(frozen=True)
class XConfig:
    """X as a source (5.2, 5.3; the plan's defaults D3, D4, D6, D8, D10). X bills
    per post read, so the adapters read only what ingest will consume. ``monthly_usd`` None:
    no cap (the owner's rule); reached, X sources wait until the first of next month.
    ``posts_per_fetch``: a list's or the home timeline's posts a run; ``profile_per_fetch``:
    one account's; ``search_results`` and ``search_every_hours``: a search's posts and how
    often it runs; ``owned_every_hours``: bookmarks and likes; ``read_threads``: an account's
    own threads joined into one item; ``recheck_days`` and ``recheck_max``: kept posts checked
    for deletion that often, at most that many (0: off); ``scout`` and
    ``scout_max_proposals``: whether the scout may propose X sources while X is connected."""

    monthly_usd: float | None = None
    posts_per_fetch: int = 20
    profile_per_fetch: int = 10
    search_results: int = 10
    search_every_hours: float = 24
    owned_every_hours: float = 24
    read_threads: bool = True
    recheck_days: float = 7
    recheck_max: int = 100
    scout: bool = True
    scout_max_proposals: int = 5


SEARCH_PROVIDERS = ("exa", "brave", "tavily", "anthropic", "none")
SEARCH_CALLERS: dict[str, tuple[str, ...]] = {
    "scout": ("on", "off"), "cards": ("on", "off"), "editor": ("on", "off"),
    "research": ("agent", "search", "off"), "resolve": ("failed_lines", "off"),
    "pitch": ("on", "off"), "evolve": ("on", "off"), "sources": ("on", "off"),
}
SEARCH_CALLER_DEFAULTS = {name: choices[0] for name, choices in SEARCH_CALLERS.items()}


@dataclass(frozen=True)
class SearchConfig:
    """Live web search. ``provider``: the web backend (``exa`` uses Exa's
    free mode without ``EXA_API_KEY``); ``free``: Hacker News, GitHub and arXiv as well;
    ``cache_hours``: one request a query a day; ``recent_weeks``: what the prompts call recent;
    ``monthly_usd`` None: no cap (the owner's rule); ``callers``: each caller on or off."""

    provider: str = "exa"
    free: bool = True
    cache_hours: float = 24
    recent_weeks: int = 12
    monthly_usd: float | None = None
    callers: dict[str, str] = field(default_factory=lambda: dict(SEARCH_CALLER_DEFAULTS))

    def caller(self, name: str) -> str:
        return self.callers.get(name, SEARCH_CALLER_DEFAULTS.get(name, "on"))


@dataclass(frozen=True)
class ParallaxConfig:
    """An archive imported from Parallax: how far it reaches into topics, cards and builds.
    ``topic_match``: 0 keeps archive observations out of topic views; above 0, a topic's
    evidence also lists those at least this similar to the topic (cosine, at query time).
    ``card_evidence``: whether the map's idea runs may cite them. ``dispatch_auto_intake``:
    whether the page's automatic intake may take the cards made from dispatches."""

    topic_match: float = 0.0
    card_evidence: bool = False
    dispatch_auto_intake: bool = False


@dataclass(frozen=True)
class GradingConfig:
    """What the owner's ▲ and ▼ do (``taste.py``,): a deterministic order,
    no model. ``half_life_days``: a grade's weight halves this often; ``observation_weight``:
    an evidence grade against a card's 1; ``cos_low``/``cos_high``: the centred cosine where
    two items start and finish "reading alike"; ``topic_weight``: the same topic, read only
    when a side has no vector; ``strong_at``: a part the card's line counts; ``theme_skip_below``:
    a theme at or under this taste is not carded by the next ideas run; ``window_days``,
    ``remove_after``, ``remove_ratio``: a source is recommended for removal when this many of
    its graded posts in the window were downvoted and at most this share as many upvoted."""

    half_life_days: float = 90.0
    observation_weight: float = 0.5
    cos_low: float = 0.30
    cos_high: float = 0.60
    topic_weight: float = 0.25
    strong_at: float = 0.25
    theme_skip_below: float = -0.5
    window_days: int = 90
    remove_after: int = 3
    remove_ratio: float = 0.25


@dataclass(frozen=True)
class Config:
    root: Path
    llm: LLMConfig
    budget: BudgetConfig
    ingest: IngestConfig
    map: MapConfig
    fetch: FetchConfig = FetchConfig()
    ideas: IdeasConfig = IdeasConfig()
    strike: StrikeConfig = StrikeConfig()
    notify: NotifyConfig = NotifyConfig()
    retention: RetentionConfig = RetentionConfig()
    activity: ActivityConfig = ActivityConfig()
    home: HomeConfig = HomeConfig()
    deep_dive: DeepDiveConfig = DeepDiveConfig()
    stories: StoriesConfig = StoriesConfig()
    look: LookConfig = LookConfig()
    brb: BrbConfig = BrbConfig()
    builds: BuildsConfig = BuildsConfig()
    connections: ConnectionsConfig = ConnectionsConfig()
    parallax: ParallaxConfig = ParallaxConfig()
    update: UpdateConfig = UpdateConfig()
    api: ApiConfig = ApiConfig()
    ask: AskConfig = AskConfig()
    x: XConfig = XConfig()
    search: SearchConfig = SearchConfig()
    grading: GradingConfig = GradingConfig()
    # The sections a feature owns (``news:``), as written: each feature's
    # manifest checks its own (``core.settings``), so a new feature needs no edit here.
    features: dict = field(default_factory=dict)
    # The home's arrangement (``shell:``, ``core.shell``): empty means its defaults.
    shell: dict = field(default_factory=dict)
    # The cubs' switches and limits (``cubs:``, ``core.cubs.settings``): empty means defaults.
    cubs: dict = field(default_factory=dict)
    # The sections of ``RETIRED`` the file still holds, in its order: never read, and ``kranto
    # doctor`` says one line each.
    retired: tuple[str, ...] = ()

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def db_path(self) -> Path:
        return legacy.db_file(self.data_dir)


def _require(mapping: dict, key: str, where: str):
    if key not in mapping:
        raise ConfigError(f"{where}.{key} is required")
    return mapping[key]


def _parse_llm(raw: dict) -> LLMConfig:
    models = _require(raw, "models", "llm")
    if not isinstance(models, dict) or not {"judge", "reason"} <= models.keys():
        raise ConfigError("llm.models must define 'judge' and 'reason'")
    cost_source = raw.get("cost_source", "provider")
    if cost_source not in ("provider", "table"):
        raise ConfigError("llm.cost_source must be 'provider' or 'table'")
    pricing = {}
    for model, price in (raw.get("pricing") or {}).items():
        try:
            pricing[model] = ModelPrice(float(price["input"]), float(price["output"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ConfigError(
                f"llm.pricing.{model} needs numeric 'input' and 'output' (USD per million tokens)"
            ) from exc
    limits = raw.get("max_tokens") or {}
    if not isinstance(limits, dict):
        raise ConfigError("llm.max_tokens must map call names to token counts")
    unknown = set(limits) - set(MAX_TOKENS)
    if unknown:
        raise ConfigError(f"unknown calls in llm.max_tokens: {', '.join(sorted(map(str, unknown)))}"
                          f" (known: {', '.join(MAX_TOKENS)})")
    for name, value in limits.items():
        if isinstance(value, bool) or not isinstance(value, int) or not 16 <= value <= 64000:
            raise ConfigError(f"llm.max_tokens.{name} must be a whole number from 16 to 64000")
    provider = raw.get("provider")
    if provider is not None and provider not in PROVIDERS:
        raise ConfigError(f"llm.provider must be one of {', '.join(PROVIDERS)}")
    tiers = raw.get("tiers") or {}
    if not isinstance(tiers, dict):
        raise ConfigError("llm.tiers must map a tier to its provider and model")
    for tier, override in tiers.items():
        if tier not in models:
            raise ConfigError(f"llm.tiers.{tier}: not a tier (tiers: {', '.join(models)})")
        if (not isinstance(override, dict) or set(override) - {"provider", "model"}
                or override.get("provider") not in PROVIDERS
                or not isinstance(override.get("model"), str) or not override["model"]):
            raise ConfigError(f"llm.tiers.{tier} needs a provider ({', '.join(PROVIDERS)}) "
                              "and a model in that provider's names")
    return LLMConfig(
        provider=provider,
        anthropic=_parse_anthropic(raw.get("anthropic")),
        claude_code=_parse_claude_code(raw.get("claude_code")),
        tiers={str(t): {"provider": str(o["provider"]), "model": str(o["model"])}
               for t, o in tiers.items()},
        base_url=str(_require(raw, "base_url", "llm")).rstrip("/"),
        api_key_env=str(_require(raw, "api_key_env", "llm")),
        cost_source=cost_source,
        models={str(k): str(v) for k, v in models.items()},
        pricing=pricing,
        timeout_seconds=float(raw.get("timeout_seconds", 60)),
        max_retries=int(raw.get("max_retries", 3)),
        max_tokens={str(k): int(v) for k, v in limits.items()},
    )


def _with_home(llm: LLMConfig, root: Path) -> LLMConfig:
    """Claude Code's calls run in an empty directory of the home and know the home (what a
    sandboxed call hides)."""
    cc = llm.claude_code
    return replace(llm, claude_code=replace(
        cc, cwd=cc.cwd or str(root / "data" / "claude-cwd"), home=cc.home or str(root)))


def _section(cls, raw: dict | None, where: str):
    raw = raw or {}
    known = set(cls.__dataclass_fields__)
    unknown = set(raw) - known
    if unknown:
        raise ConfigError(f"unknown keys in {where}: {', '.join(sorted(unknown))}")
    return cls(**raw)


def load_dotenv(path: Path) -> None:
    """Load KEY=VALUE lines into the environment without overriding what is set.

    Lets a workspace keep its API key in ``<workspace>/.env`` instead of the
    shell profile. Values already in the environment win.

    The names it added (never a value) are kept in ``$KRANTO_DOTENV_VARS``: a process Kranto
    starts inherits them, so the page still tells the watcher's Claude API key (Settings ›
    Watching writes it here) from one Kranto's unit gave on purpose (BL: builds use it only with
    ``build.allow_api_key``).
    """
    if not path.is_file():
        return
    added = {n for n in os.environ.get(DOTENV_VARS, "").split(",") if n}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.removeprefix("export ").partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            added.add(key)
    if added:
        os.environ[DOTENV_VARS] = ",".join(sorted(added))


DOTENV_VARS = "KRANTO_DOTENV_VARS"


# The top-level sections whose feature left Kranto, each with the name a
# person knows it by. A file that still holds one loads without an error: the section stays in
# the file as written, is never read, and ``kranto doctor`` says one line about it. The data
# stays in its tables; ``kranto archive`` writes it out. Add a section here in the PR that
# removes its feature.
RETIRED: dict[str, str] = {"invest": "Invest", "radar": "The trend radar",
                           "browser": "The browser extension"}
# Sections of features that left, still read from a file that has them (their defaults when it
# does not) but no longer written into a new file (DEFAULT_CONFIG_YAML leaves them out).
FOR_OLD_FILES = ("deep_dive", "builds")


def config_path(root: Path) -> Path | None:
    """The workspace's config file: kranto.yaml, else an older name; None if there is none."""
    for name in CONFIG_FILENAMES:
        if (root / name).is_file():
            return root / name
    return None


def load(root: Path, *, dotenv: bool = True) -> Config:
    """``dotenv``: load ``<root>/.env`` into the environment first (the server and the
    commands that spend do; ``kranto status`` and ``kranto adopt`` do not read it)."""
    if dotenv:
        load_dotenv(root / ".env")
    path = config_path(root)
    if path is None:
        raise ConfigError(f"no {CONFIG_FILENAME} in {root}: 'kranto up' makes a Kranto home "
                          f"('kranto watch init {root}' a watcher-only workspace)")
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    retired = tuple(k for k in raw if k in RETIRED)
    raw = {k: v for k, v in raw.items() if k not in RETIRED}   # left as written, never read
    budget = _parse_budget(raw.get("budget"))
    ingest = _section(IngestConfig, raw.get("ingest"), "ingest")
    if not 0 <= ingest.exploration_fraction <= 1:
        raise ConfigError("ingest.exploration_fraction must be in [0, 1]")
    if not isinstance(ingest.fetch_full_text, bool):
        raise ConfigError("ingest.fetch_full_text must be true or false")
    if isinstance(ingest.backfill_items, bool) or not isinstance(ingest.backfill_items, int) \
            or ingest.backfill_items < 0:
        raise ConfigError("ingest.backfill_items must be a whole number, 0 or more")
    if isinstance(ingest.max_age_days, bool) or not isinstance(ingest.max_age_days, int | float) \
            or ingest.max_age_days < 0:
        raise ConfigError("ingest.max_age_days must be a number of days, 0 or more (0: off)")
    ideas = _section(IdeasConfig, raw.get("ideas"), "ideas")
    if ideas.project_topics not in IDEAS_PROJECT_TOPICS:
        raise ConfigError(f"ideas.project_topics must be one of {', '.join(IDEAS_PROJECT_TOPICS)}")
    from .telemetry.local import TelemetryError
    from .telemetry.local import parse as parse_telemetry

    try:                          # read again at each use (telemetry.local.settings)
        parse_telemetry(raw.get("telemetry"))
    except TelemetryError as exc:
        raise ConfigError(str(exc)) from exc
    strike = _section(StrikeConfig, raw.get("strike"), "strike")
    if (strike.refractory_days < 0 or strike.max_per_week < 0 or strike.warmup_snapshots < 0
            or strike.warmup_days < 0):
        raise ConfigError("strike.refractory_days, max_per_week, warmup_snapshots and "
                          "warmup_days must be >= 0")
    return Config(
        root=root.resolve(),
        llm=_with_home(_parse_llm(_require(raw, "llm", "config")), root.resolve()),
        budget=budget,
        ingest=ingest,
        fetch=_parse_fetch(raw.get("fetch")),
        map=_section(MapConfig, raw.get("map"), "map"),
        ideas=ideas,
        strike=strike,
        notify=_parse_notify(raw.get("notify")),
        retention=_parse_retention(raw.get("retention")),
        activity=parse_activity(raw.get("activity")),
        home=parse_home(raw.get("home")),
        deep_dive=_parse_deep_dive(raw.get("deep_dive")),
        stories=_parse_stories(raw.get("stories")),
        look=_parse_look(raw.get("look")),
        brb=_parse_brb(raw.get("brb")),
        builds=_parse_builds(raw.get("builds")),
        connections=_parse_connections(raw.get("connections")),
        parallax=_parse_parallax(raw.get("parallax")),
        update=parse_update(raw.get("update")),
        api=_parse_api(raw.get("api")),
        ask=parse_ask(raw.get("ask")),
        x=parse_x(raw.get("x")),
        search=parse_search(raw.get("search")),
        grading=parse_grading(raw.get("grading")),
        features=_feature_sections(raw),
        shell=_shell_section(raw),
        cubs=_cubs_section(raw),
        retired=retired,
    )


def _shell_section(raw: dict) -> dict:
    from .core import shell
    return shell.parse(raw.get("shell"))


def _cubs_section(raw: dict) -> dict:
    from .core.cubs import settings as cubs
    return cubs.parse(raw.get("cubs"))


def _feature_sections(raw: dict) -> dict:
    """The top-level sections that are a feature's (``kranto.features``), each checked
    against its manifest's settings; a bad value is a ConfigError like any other section's."""
    from .core import settings as feature_settings
    return feature_settings.parse_all(raw)


def feature_search_callers() -> dict[str, tuple[str, ...]]:
    """Each feature granted live search is a caller of its own name, on by default."""
    from .core.registry import features
    return {f.id: ("on", "off") for f in features() if f.permissions.search}


def parse_search(raw: dict | None) -> SearchConfig:
    raw = dict(raw or {})
    callers_raw = raw.pop("callers", None) or {}
    cfg = _section(SearchConfig, raw, "search")
    if cfg.provider not in SEARCH_PROVIDERS:
        raise ConfigError(f"search.provider must be one of {', '.join(SEARCH_PROVIDERS)}")
    if not isinstance(cfg.free, bool):
        raise ConfigError("search.free must be true or false")
    if isinstance(cfg.cache_hours, bool) or not isinstance(cfg.cache_hours, int | float) \
            or cfg.cache_hours < 0:
        raise ConfigError("search.cache_hours must be a number of hours, 0 or more (0: no cache)")
    if isinstance(cfg.recent_weeks, bool) or not isinstance(cfg.recent_weeks, int) \
            or not 1 <= cfg.recent_weeks <= 520:
        raise ConfigError("search.recent_weeks must be a whole number of weeks from 1 to 520")
    usd = cfg.monthly_usd
    if usd is not None and (isinstance(usd, bool) or not isinstance(usd, int | float) or usd < 0):
        raise ConfigError("search.monthly_usd must be USD, 0 or more, or null (no cap)")
    if not isinstance(callers_raw, dict):
        raise ConfigError("search.callers must map a caller to on or off")
    # a feature's caller is known here and on by default through SearchConfig.caller
    known = {**SEARCH_CALLERS, **feature_search_callers()}
    callers = dict(SEARCH_CALLER_DEFAULTS)
    for name, value in callers_raw.items():
        if name not in known:
            raise ConfigError(f"search.callers.{name}: not a caller (callers: "
                              f"{', '.join(known)})")
        # YAML 1.1 reads a bare on and off as true and false
        value = {True: "on", False: "off"}.get(value, value) if isinstance(value, bool) else value
        if name == "research" and value == "on":
            value = "agent"
        if name == "resolve" and value == "on":
            value = "failed_lines"
        if value not in known[name]:
            raise ConfigError(f"search.callers.{name} must be one of "
                              f"{', '.join(known[name])}")
        callers[name] = value
    return SearchConfig(provider=cfg.provider, free=cfg.free, cache_hours=float(cfg.cache_hours),
                        recent_weeks=cfg.recent_weeks,
                        monthly_usd=None if usd is None else float(usd), callers=callers)


# each grading.* number: (low, high), both inclusive
GRADING_RANGES: dict[str, tuple[float, float]] = {
    "half_life_days": (1, 3650), "observation_weight": (0, 1), "cos_low": (-1, 1),
    "cos_high": (-1, 1), "topic_weight": (0, 1), "strong_at": (0, 1),
    "theme_skip_below": (-100, 0), "window_days": (1, 3650), "remove_after": (1, 1000),
    "remove_ratio": (0, 1)}


def parse_grading(raw: dict | None) -> GradingConfig:
    cfg = _section(GradingConfig, raw, "grading")
    out: dict[str, int | float] = {}
    for name, (low, high) in GRADING_RANGES.items():
        value = getattr(cfg, name)
        whole = name in ("window_days", "remove_after")
        if isinstance(value, bool) or not isinstance(value, int | float) \
                or (whole and not isinstance(value, int)) or not low <= value <= high:
            kind = "a whole number" if whole else "a number"
            raise ConfigError(f"grading.{name} must be {kind} from {low:g} to {high:g}")
        out[name] = value if whole else float(value)
    if out["cos_high"] <= out["cos_low"]:
        raise ConfigError("grading.cos_high must be above grading.cos_low")
    return GradingConfig(**out)  # type: ignore[arg-type]


def parse_x(raw: dict | None) -> XConfig:
    cfg = _section(XConfig, raw, "x")
    usd = cfg.monthly_usd
    if usd is not None and (isinstance(usd, bool) or not isinstance(usd, int | float) or usd < 0):
        raise ConfigError("x.monthly_usd must be USD, 0 or more, or null (no cap)")
    for name, low, high in (("posts_per_fetch", 1, 100), ("profile_per_fetch", 5, 100),
                            ("search_results", 10, 100), ("recheck_max", 0, 1000),
                            ("scout_max_proposals", 0, 50)):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
            raise ConfigError(f"x.{name} must be a whole number from {low} to {high}")
    for name in ("search_every_hours", "owned_every_hours", "recheck_days"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ConfigError(f"x.{name} must be a number, 0 or more")
    for name in ("read_threads", "scout"):
        if not isinstance(getattr(cfg, name), bool):
            raise ConfigError(f"x.{name} must be true or false")
    return XConfig(**{**cfg.__dict__, "monthly_usd": None if usd is None else float(usd),
                      "search_every_hours": float(cfg.search_every_hours),
                      "owned_every_hours": float(cfg.owned_every_hours),
                      "recheck_days": float(cfg.recheck_days)})


def _parse_api(raw: dict | None) -> ApiConfig:
    cfg = _section(ApiConfig, raw, "api")
    if not isinstance(cfg.require_token, bool):
        raise ConfigError("api.require_token must be true or false")
    return cfg


_SAID: set[str] = set()


def _say_once(text: str) -> None:
    """One notice in the log per process (a config read several times says it once)."""
    if text not in _SAID:
        _SAID.add(text)
        import logging

        logging.getLogger("kranto.config").warning(text)


def parse_update(raw: dict | None) -> UpdateConfig:
    raw = dict(raw or {})
    if raw.get("auto") is False:  # YAML 1.1 reads a bare off as false
        raw["auto"] = "off"
    if raw.get("channel") == "rc":  # retired: every nightly is a prerelease
        raw["channel"] = "nightly"
        _say_once("update.channel: rc is read as nightly (the rc channel is retired); "
                  "Settings › System › Updates writes nightly")
    cfg = _section(UpdateConfig, raw, "update")
    if cfg.source not in UPDATE_SOURCES:
        raise ConfigError(f"update.source must be one of {', '.join(UPDATE_SOURCES)}")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", str(cfg.repo)):
        raise ConfigError("update.repo must be owner/name")
    if cfg.channel not in UPDATE_CHANNELS:
        raise ConfigError(f"update.channel must be one of {', '.join(UPDATE_CHANNELS)}")
    if cfg.auto not in UPDATE_AUTO:
        raise ConfigError("update.auto must be off or idle")
    if isinstance(cfg.check_every_hours, bool) or \
            not isinstance(cfg.check_every_hours, int | float) or cfg.check_every_hours < 0:
        raise ConfigError("update.check_every_hours must be a number of hours, 0 or more "
                          "(0: never)")
    if not isinstance(cfg.download, bool):
        raise ConfigError("update.download must be true or false")
    if isinstance(cfg.keep_backups, bool) or not isinstance(cfg.keep_backups, int) \
            or cfg.keep_backups < 1:
        raise ConfigError("update.keep_backups must be a whole number, 1 or more")
    try:
        quiet_window(cfg.quiet_window)
    except ValueError as exc:
        raise ConfigError(f"update.quiet_window: {exc}") from exc
    if cfg.token_env_file is not None and not isinstance(cfg.token_env_file, str):
        raise ConfigError("update.token_env_file must be a path or null")
    if not isinstance(cfg.maintainer, bool):
        raise ConfigError("update.maintainer must be true or false")
    return cfg


def _parse_parallax(raw: dict | None) -> ParallaxConfig:
    cfg = _section(ParallaxConfig, raw, "parallax")
    match = cfg.topic_match
    if isinstance(match, bool) or not isinstance(match, int | float) or not 0 <= match < 1:
        raise ConfigError("parallax.topic_match must be a similarity from 0 (off) to below 1")
    for name in ("card_evidence", "dispatch_auto_intake"):
        if not isinstance(getattr(cfg, name), bool):
            raise ConfigError(f"parallax.{name} must be true or false")
    return ParallaxConfig(topic_match=float(match), card_evidence=cfg.card_evidence,
                          dispatch_auto_intake=cfg.dispatch_auto_intake)


def _parse_fetch(raw: dict | None) -> FetchConfig:
    cfg = _section(FetchConfig, raw, "fetch")
    hosts = cfg.hosts or {}
    if not isinstance(hosts, dict):
        raise ConfigError("fetch.hosts must map host names to seconds")
    for name, value in (("min_gap_seconds", cfg.min_gap_seconds),
                        ("max_wait_seconds", cfg.max_wait_seconds),
                        ("failing_backoff_hours", cfg.failing_backoff_hours),
                        ("failing_backoff_max_hours", cfg.failing_backoff_max_hours),
                        *((f"hosts.{h}", s) for h, s in hosts.items())):
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ConfigError(f"fetch.{name} must be a number, 0 or more")
    for name, value in (("retries", cfg.retries), ("failing_after_runs", cfg.failing_after_runs)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"fetch.{name} must be a whole number, 0 or more")
    if cfg.failing_after_runs < 1:
        raise ConfigError("fetch.failing_after_runs must be 1 or more")
    return FetchConfig(min_gap_seconds=float(cfg.min_gap_seconds),
                       hosts={str(h).lower(): float(s) for h, s in hosts.items()},
                       retries=cfg.retries, max_wait_seconds=float(cfg.max_wait_seconds),
                       failing_after_runs=cfg.failing_after_runs,
                       failing_backoff_hours=float(cfg.failing_backoff_hours),
                       failing_backoff_max_hours=float(cfg.failing_backoff_max_hours))


def _parse_budget(raw: dict | None) -> BudgetConfig:
    raw = dict(raw or {"monthly_usd": None})
    if "monthly_usd" not in raw:
        raise ConfigError("budget.monthly_usd is required (USD a month, or null: no cap)")
    cfg = _section(BudgetConfig, raw, "budget")
    usd, frac = cfg.monthly_usd, cfg.alarm_fraction
    if usd is not None and (isinstance(usd, bool) or not isinstance(usd, int | float)
                            or usd < 0):
        raise ConfigError("budget.monthly_usd must be USD, 0 or more, or null (no cap)")
    if isinstance(frac, bool) or not isinstance(frac, int | float) or not 0 < frac <= 1:
        raise ConfigError("budget.alarm_fraction must be more than 0 and at most 1")
    return BudgetConfig(None if usd is None else float(usd), float(frac))


def _parse_connections(raw: dict | None) -> ConnectionsConfig:
    cfg = _section(ConnectionsConfig, raw, "connections")
    if not isinstance(cfg.enabled, bool):
        raise ConfigError("connections.enabled must be true or false")
    cid = cfg.github_client_id
    if cid is not None and (not isinstance(cid, str)
                            or not re.fullmatch(r"[A-Za-z0-9._-]{8,64}", cid)):
        raise ConfigError("connections.github_client_id must be an OAuth app's client id "
                          "(letters and digits, as GitHub shows it)")
    return cfg


def _parse_brb(raw: dict | None) -> BrbConfig:
    cfg = _section(BrbConfig, raw, "brb")
    if not isinstance(cfg.enabled, bool):
        raise ConfigError("brb.enabled must be true or false")
    for name in ("root", "loop_home"):
        if getattr(cfg, name) is not None and not isinstance(getattr(cfg, name), str):
            raise ConfigError(f"brb.{name} must be a path")
    if cfg.harness not in ("claude-code", "fake"):
        raise ConfigError("brb.harness must be claude-code or fake")
    return cfg


def _parse_builds(raw: dict | None) -> BuildsConfig:
    """``builds:``: absent, empty or null is off (a file written before the switch builds
    nothing until ``builds.enabled: true`` is set)."""
    cfg = _section(BuildsConfig, raw, "builds")
    if not isinstance(cfg.enabled, bool):
        raise ConfigError("builds.enabled must be true or false")
    return cfg


def builds_on(cfg: Config | None) -> bool:
    """Whether builds run for this config: ``builds.enabled`` and the page mounted
    (``brb.enabled``). Every builds gate reads this one function."""
    return bool(cfg is not None and cfg.brb.enabled and cfg.builds.enabled)


def _parse_look(raw: dict | None) -> LookConfig:
    cfg = _section(LookConfig, raw, "look")
    for name in ("enabled", "reddit_comments"):
        if not isinstance(getattr(cfg, name), bool):
            raise ConfigError(f"look.{name} must be true or false")
    for name in ("max_links", "max_repos", "max_comments", "gathered_chars", "max_per_run",
                 "max_repo_lookups"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"look.{name} must be a whole number, 0 or more")
    for name in ("item_seconds", "request_seconds"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
            raise ConfigError(f"look.{name} must be a number of seconds, more than 0")
    batch = cfg.screen_batch
    if isinstance(batch, bool) or not isinstance(batch, int) or not 1 <= batch <= 50:
        raise ConfigError("look.screen_batch must be a whole number from 1 (off) to 50")
    return cfg


def _parse_deep_dive(raw: dict | None) -> DeepDiveConfig:
    cfg = _section(DeepDiveConfig, raw, "deep_dive")
    for name in ("enabled", "reddit_comments"):
        if not isinstance(getattr(cfg, name), bool):
            raise ConfigError(f"deep_dive.{name} must be true or false")
    for name in ("max_per_run", "max_links", "max_repos", "max_comments", "max_attempts"):
        value = getattr(cfg, name)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ConfigError(f"deep_dive.{name} must be a whole number, 0 or more")
    for name in ("min_signal", "daily_usd", "every_hours", "max_queue_days"):
        value = getattr(cfg, name)
        if name == "daily_usd" and value is None:
            continue  # no daily cap: deep dives spend from the monthly budget only
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ConfigError(f"deep_dive.{name} must be a number, 0 or more")
    if cfg.min_signal > 1:
        raise ConfigError("deep_dive.min_signal must be in [0, 1]")
    return cfg


def _parse_stories(raw: dict | None) -> StoriesConfig:
    raw = dict(raw or {})
    templated = raw.pop("templated_sources", None) or []
    if isinstance(templated, str) or not isinstance(templated, list) or not all(
            isinstance(s, int) and not isinstance(s, bool) for s in templated):
        raise ConfigError("stories.templated_sources must be a list of source ids")
    cfg = _section(StoriesConfig, raw, "stories")
    values = {k: getattr(cfg, k) for k in ("window_days", "skip_at", "link_at",
                                            "same_source_days")}
    for key, value in values.items():
        if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
            raise ConfigError(f"stories.{key} must be a number, 0 or more")
    if not 0 < cfg.link_at <= cfg.skip_at <= 1:
        raise ConfigError("stories: need 0 < link_at <= skip_at <= 1")
    return StoriesConfig(**{k: float(v) for k, v in values.items()},
                         templated_sources=tuple(templated))


def _days(value, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or value < 0:
        raise ConfigError(f"{where} must be a number of days, 0 or more (0: keep forever)")
    return float(value)


ACTIVITY_KEEP_DAYS = (1, 365)
ACTIVITY_MAX_ROWS = (1000, 1_000_000)


def parse_activity(raw: dict | None) -> ActivityConfig:
    cfg = _section(ActivityConfig, raw, "activity")
    lo, hi = ACTIVITY_KEEP_DAYS
    if isinstance(cfg.keep_days, bool) or not isinstance(cfg.keep_days, int | float) \
            or not lo <= cfg.keep_days <= hi:
        raise ConfigError(f"activity.keep_days must be a number of days from {lo} to {hi}")
    lo, hi = ACTIVITY_MAX_ROWS
    if isinstance(cfg.max_rows, bool) or not isinstance(cfg.max_rows, int) \
            or not lo <= cfg.max_rows <= hi:
        raise ConfigError(f"activity.max_rows must be a whole number from {lo:,} to {hi:,}")
    return cfg


def parse_home(raw: dict | None) -> HomeConfig:
    cfg = _section(HomeConfig, raw, "home")
    lo, hi = HOME_AWAY_DAYS
    if isinstance(cfg.away_days, bool) or not isinstance(cfg.away_days, int) \
            or not lo <= cfg.away_days <= hi:
        raise ConfigError(f"home.away_days must be a whole number of days from {lo} to {hi}")
    return cfg


def parse_ask(raw: dict | None) -> AskConfig:
    """``ask:``: the ladder's choices (``core.verbs.check_ladder``). A verb's name is not
    looked up here (a cub's verb may be named before the cub is installed); a lock set in the
    file has no effect, as the locks are read first."""
    from .core import verbs
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - {"ladder"}:
        raise ConfigError("ask: has one key, ladder")
    try:
        ladder = verbs.check_ladder(raw.get("ladder"), lookup=False)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc
    return AskConfig(ladder=ladder)


def _parse_retention(raw: dict | None) -> RetentionConfig:
    from .sources import KINDS

    raw = dict(raw or {})
    by_kind = raw.pop("by_kind", None) or {}
    if not isinstance(by_kind, dict):
        raise ConfigError("retention.by_kind must map source kinds to days")
    known = set(KINDS) | {"parallax"}
    unknown = set(by_kind) - known
    if unknown:
        raise ConfigError(f"unknown source kinds in retention.by_kind: "
                          f"{', '.join(sorted(map(str, unknown)))} (known: "
                          f"{', '.join(sorted(known))})")
    for kind, cap in KIND_MAX_DAYS.items():
        days = by_kind.get(kind)
        if days is not None and not isinstance(days, bool) and isinstance(days, int | float) \
                and (days <= 0 or days > cap):
            raise ConfigError(f"retention.by_kind.{kind} must be between 1 and {cap:g} days: "
                              f"{kind} API data may be kept at most {cap:g} days")
    cfg = _section(RetentionConfig, raw, "retention")
    return RetentionConfig(
        default_days=_days(cfg.default_days, "retention.default_days"),
        by_kind={**KIND_DEFAULT_DAYS,
                 **{k: _days(v, f"retention.by_kind.{k}") for k, v in by_kind.items()}},
        every_hours=float(cfg.every_hours),
    )


def _parse_notify(raw: dict | None) -> NotifyConfig:
    raw = dict(raw or {})
    urls = raw.pop("urls", None) or []
    if isinstance(urls, str) or not all(isinstance(u, str) for u in urls):
        raise ConfigError("notify.urls must be a list of Apprise URL strings")
    cfg = _section(NotifyConfig, raw, "notify")
    return NotifyConfig(**{**cfg.__dict__, "urls": tuple(urls),
                           "base_url": str(cfg.base_url).rstrip("/")})


def init_workspace(root: Path) -> Path:
    """Create a workspace with the default config. Refuses to overwrite one."""
    root.mkdir(parents=True, exist_ok=True)
    path = root / CONFIG_FILENAME
    if path.exists():
        raise ConfigError(f"{path} already exists")
    path.write_text(DEFAULT_CONFIG_YAML, encoding="utf-8")
    (root / "data").mkdir(exist_ok=True)
    return path


def find_workspace(explicit: str | None = None) -> Path:
    """Resolve the workspace: explicit flag, then $KRANTO_HOME, then $KRANTO_HOME (a kranto home
    is a workspace), then the current directory, then the home ``kranto setup`` recorded
    (``~/.config/kranto/home``), so ``kranto watch`` works after an install without a flag."""
    candidate = (explicit or os.environ.get(WORKSPACE_ENV) or os.environ.get(KRANTO_HOME_ENV)
                 or os.getcwd())
    root = Path(candidate).expanduser()
    if config_path(root) is None and candidate == os.getcwd():
        from .paths import recorded_home
        found = recorded_home(Path.home())
        if found is not None and config_path(found) is not None:
            return found
    if config_path(root) is None:
        raise ConfigError(
            f"{root} is not a Kranto home (no {CONFIG_FILENAME}): 'kranto up' makes one; "
            f"'kranto watch -w DIR' names another, 'kranto watch init DIR' makes a "
            f"watcher-only workspace."
        )
    return root
