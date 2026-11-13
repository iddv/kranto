# OPERATING

The operator manual. It is written for whoever works on or runs the server
next, human or agent, and goes deeper than the README. It covers how the
system behaves, where each part lives, what must never be broken, what to do
when something goes wrong, and how work on the project is organised.

Read alongside:
- [VISION.md](design/VISION.md) and [TENETS.md](design/TENETS.md): what this is for, and how to think. They are unchanged from Parallax; TENETS is also sent to the model on every judge call.
- [DECISIONS.md](design/DECISIONS.md): why each mechanism exists, with the evidence behind it.
- [DESIGN.md](design/DESIGN.md): the original plan, and section 8, what changed while building.

Facts here were checked against the code on 2026-09-24. When they disagree
with the code, the code is right: fix this file. Its file map is older than the
code; CONTRIBUTING's "Where things are" is kept true by a test.

---

## 1. The system in one picture

```
            topics (plain language)
               |  scout (tier 2) proposes sources; each is test-fetched
               v
 sources ----> ingest, every 3h
 rss/hn/reddit   fetch -> drop seen -> cap (rest roll over)
                 -> an item marked as an ad, or linking to an ad or
                    affiliate URL: sponsored (no call)
                 -> tier-0 prefilter (local embedding vs topics)
                    + 5% exploration + broad/wildcard sources unfiltered
                 -> same URL judged before: duplicate; same text judged
                    recently: near_duplicate (no call); edited copy from
                    another source: judged, linked to its story
                 -> page chrome / consent wall: body blanked, noted
                 -> full text for thin link posts
                 -> tier-1 screen, lenient: clear junk is screened_out
                 -> look (no model): discussion, linked pages, repos,
                    capped per item and per run; never a link in sponsor
                    or ad context
                 -> tier-1 judge reads item + gathered sources:
                    quality x durability x opportunity; override only
                    within a floor
                 -> observation (append-only, embedded once), and the
                    gathered sources it kept as linked child observations
               |
               v
            snapshot, daily: re-cluster everything (UMAP 10d + k-means)
                 honest quality (both spaces, structure null)
                 lineages across snapshots; new-arrival counts;
                 Kleinberg bursts + BH-corrected binomial q-values -------+
               |                                                          |
               v                                                          |
            compact, after the snapshot: observations past their          |
                 retention age become weekly rollups, then are removed    |
               |                                                          |
               v                                                          |
            ideas, after a new map: candidates by arithmetic;             |
                 tier-2 card with five fitness ratings;                   |
                 tier-1 citation check -----------------------------------+
                                                                          |
            gate: per-origin threshold, stale, warm-up, refractory,       |
                  weekly cap; one recorded decision per candidate  <------+
               |
               v
            messages: strike | heartbeat (weekly) | alarm (any failed run, budget)
               |  /feed.xml, Health page, and Apprise targets if configured
               v
            a person grades them: worth waking / not worth it / missed / ...
```

Nothing in this picture acts on the world. The only outward effects are HTTP
fetches of public sources, model calls, and messages to targets the operator
configured.

## 2. Code map

| Path | Responsibility |
|---|---|
| `config.py` | Workspace config (`kranto.yaml`), `.env` loading, defaults, validation. Unknown keys are errors. |
| `store.py` | SQLite, numbered migrations, append-only triggers, the purge path, settings (the one mutable table), spend, JSONL export. |
| `llm.py` | The only way to call a model: pause and budget checks before each call, retry and error classes, cost from the provider or a pricing table, every call recorded. A provider's pause (a spend limit at the provider, a plan's usage window) is kept as the `watch_paused` setting with its end; calls before then are refused without a request. |
| `providers/` | How a request reaches a model: `base.py` (Request, Reply, ProviderError), `openai_compat.py` (an OpenAI-style endpoint; `openrouter` is the same provider by name). `llm.provider` picks one, `llm.tiers` puts one tier on another. |
| `pricing.py` | List prices (USD per million tokens, with cache reads and writes) for providers that report tokens but not dollars; `PRICES_AS_OF` is the pricing page's date. |
| `embed.py` | nomic-embed-text-v1.5 at 384-d with document and query prefixes; `StubEmbedder` for tests. |
| `sources/` | Adapters (`rss`, `hackernews`, `reddit`, `arxiv` (export API, 3 s per-host gap), `bluesky` (public feeds and lists; home timeline and search with a connection), `mastodon` (home timeline and lists, with a connection), `github_stars` (`github`: releases of starred repositories), `youtube` (subscriptions; kept at most 30 days), `producthunt` (launches by topic), `stackexchange` (search; uses the app key when connected), `x` (lists, home, an account, search, bookmarks and likes with the X connection; asks only for what a run consumes, `fetch_after`; every read in `api_spend`), `xai_search` (X search through Grok with an xAI key, one metered call a day)), the safe `HTTP` client (polite fetching through `pacing.HOSTS`: one request at a time per host with a minimum gap, Retry-After or exponential backoff with jitter on 429/503 and timeouts, then a transient error with `retry_at`; public addresses only, size cap, redirect re-checks, `with_auth` for a connected account: headers, a DPoP proof or a query key at send time, one retry for a server's DPoP nonce; httpx and httpcore loggers held at WARNING), `discover.py` (site to feed), `fulltext.py` (trafilatura on fetched HTML). |
| `sources/catalog.py` | The catalog of preconfigured sources: presets by provider, each a recipe from one or two fields to `(kind, params, label)`; access `public`, `login` or `not_offered`. Served at `/api/catalog`, listed on `/topics`, and the scout's vocabulary. |
| `source_health.py` | Source status (`source_fetches`), items a day, kept, a preview (one fetch, nothing saved), add from a preset, Fetch now. |
| `connections/` | Connected accounts: `vault.py` (encrypted secrets), `oauth.py` (state and PKCE; the device flow's state), `base.py` (`Provider`, `Grant`), the providers `mastodon.py`, `bluesky.py` (loopback OAuth with PAR and DPoP, `dpop.py`; app password), `github.py` (pasted token; device flow behind `connections.github_client_id`), `youtube.py` (the owner's Google client), `x.py` (the owner's X Native App: PKCE on 127.0.0.1, no secret; rotating refresh tokens refreshed under the vault's file lock; every reply's reads into `api_spend` through `observe`), `pasted.py` (Product Hunt, Stack Exchange), and `__init__.py` (`Connections`: `PROVIDER_INFO` with each provider's steps, the flows, `http_for`, refresh, needs-login, test, disconnect). One account per provider except Mastodon (one per instance). |
| `web/sources_api.py` | The JSON endpoints for sources, the catalog and connections (`/api/connections/<provider>/credentials` for a pasted token, key, app password or YouTube's client), and the sign-in routes `/connections/<provider>/start`, `/callback`, `/device` and `/device/poll`. |
| `intern.py`, `prompts/judge.md`, `prompts/screen.md` | The screen and the judge: prompts, tolerant parsers, decomposed ratings multiplied in code (the item's and each child's), the override backstop (`override_effect`, #86). |
| `look.py` | What is gathered for an item between screen and judge, with the per-item and per-run caps. |
| `sources/sponsors.py` | Sponsor and advertising context: links in sponsor sentences, sections and ad slots; ad, affiliate and ad-redirect URLs; items that announce themselves as ads. No model call. |
| `tick.py` | One ingest run: prefilter, exploration, backfill, duplicates (URL and text), no-content check, full text, screen, look, judge, record (with children), run status. |
| `textsig.py`, `stories.py` | Near-duplicates on pre-judge text (MinHash over word shingles), story links, templated-source detection, origins (registrable domains), the near-duplicate null check, signature expiry. |
| `library.py` | Domain queries: topics, sources, observations, exploration yield. |
| `sources/gather.py` | The gatherers `look.py` uses (HN thread, linked pages, GitHub repositories; Reddit comments only when turned on), and the per-item time box. |
| `retention.py`, `prompts/rollup.md` | Retention ages (config, per kind, per source) and compaction: weekly rollups of expired observations, then their removal through a recorded purge. |
| `scout.py`, `prompts/scout.md` | Topic to proposed sources (core and wildcard), each validated by fetching. |
| `resolve.py`, `prompts/resolve.md` | A pasted list or description to proposed sources, each validated by fetching; approving them by id. |
| `search.py` | Exact cosine search over an in-memory matrix fused (reciprocal rank) with FTS5/BM25 over `observations_fts`; off-topic line at 0.65. Rollups ranked separately (centroid plus `rollups_fts`). |
| `websearch/` | Live web search: `Searcher.search(query, recency, kind)` over the `search.provider` backend (Exa's API with `EXA_API_KEY`, else Exa's free hosted MCP; or Anthropic's web search tool on the watcher's Claude API key) and the free three by kind (Hacker News, GitHub, arXiv); dated `Hit`s, `Results.block` (numbered, fenced), `cited`/`uncited`, `fetch` through `sources.HTTP`; the day cache `search_cache`, one `api_spend` row a request with its `caller`, `search.monthly_usd` pausing paid search; with nothing answering, "no live search: results are from model memory and may be stale". `GET /api/websearch`, `afk websearch`, the doctor's `search` line. Backends: Exa (default; free mode without `EXA_API_KEY`), Brave (`BRAVE_API_KEY`; never cached: its terms allow only transient storage), Tavily (`TAVILY_API_KEY`), Anthropic's tool; `similar()` is a described search (Exa's find-similar is deprecated). `sources/websearch_source.py`: the `websearch` source kind (catalog `web.search`), a site without a feed read as one site-restricted search a run through `websearch.current()`, caller `sources`. |
| `map/compute.py` | Clustering, quality against a structure null, lineage matching, keywords, density. |
| `map/snapshot.py`, `map/bursts.py`, `map/read.py` | Taking a snapshot; new-arrival counts, Kleinberg bursts, BH q-values; read models for pages. |
| `ideate/explain.py`, `ideate/cards.py` | Explanations (cached); idea-card selection, generation, citation verification. |
| `notify.py` | Messages (strike, heartbeat, alarm), candidates, alarms, Atom feed. |
| `gate.py` | Candidate to strike decisions. |
| `delivery.py` | Apprise delivery, heartbeat ping. |
| `heartbeat.py` | The weekly heartbeat. |
| `grades.py` | Human verdicts (append-only, latest wins). |
| `taste.py` | What the owner's ▲ ▼ on cards and evidence do: the order of every card list and `/api/ideas[].rank` (`{position, taste, line, parts}`), a deterministic function of the stored grades, citations, themes, topics and embeddings (no model); `grading.*` in `kranto.yaml`; `GET /api/grades/summary` (Your grades). |
| `scheduler.py` | In-process jobs for `afk serve`; due-ness from the `runs` table. Second lanes (their own thread and interval) started and stopped with it. |
| `looplane.py` | What is left of the build loop's lane (builds left Kranto): `loop_home` and empty reads for `kranto.py` until its own cut; `kranto serve` runs no loop lane. Imports nothing of the page. |
| `kranto.py`, `packages/kranto/` | The `kranto` command (`up`, `serve`, `down`, `status`, `logs`, `doctor`, `adopt`) and the metadata-only `kranto` distribution that installs the server and the page together. |
| `progress.py` | "What is missing" messages for empty pages. |
| `packs.py`, `importers.py`, `bundle.py`, `doctor.py` | Topic packs, Parallax import, static bundle export, preflight checks. |
| `web/` | Starlette app: the JSON API and the host of the page (drawn at `/`; its files and calls under `/brb/`). the server's old page addresses redirect there; without the page they and `/` show an install notice (Kranto is one app, D5). The only Jinja pages left are the connection sign-in pages. |
| `core/cubs/` | The cub runtime: `sandbox.py` (bubblewrap under a systemd user scope, else rlimits), `process.py` and `host.py` (one process a cub, `cub/1` over its pipes, every call checked and written to `cub_calls`), `runtime.py` (start on demand, idle stop, the pause rules, the reaper, the STOP file, recovery, the daily gc), `install.py` and `inspect.py` (add, update, stop, remove; the tree's checks, the findings, the words), `brokers/` (the newsletter, through whichever platform `kranto/newsletter/` has connected, and Mastodon, with the owner's connection), `settings.py` (the `cubs:` section, read again when kranto.yaml changes), `cli.py` (`kranto cub`), `views.py`. |
| `bears_cub/` (a package of its own in `src/`) | The SDK a cub imports (and the `bears-cub-sdk` wheel): the decorators, `ctx`, the wire, `FakeHost` for tests, the template, `python -m bears_cub.check` and `.standard`. |
| `cubs/examples/` | The reference cubs, `newsletter`, `toot` and `blog`, installed like any cub (`kranto paths examples`); Kranto adds `blog` itself the first time a post is asked for. |
| `web/cubs_api.py` | `/api/cubs/*`: the list, one cub, fetch jobs, install, update, remove, live and dry, stop and resume, the log, the `cubs.*` settings. |
| `cli.py`, `runtime.py` | The `afk` command and object wiring. |

## 3. Data

One SQLite file per workspace: `<workspace>/data/kranto.db`, WAL mode.

**Stored JSON has one type per column**: every JSON column, every `settings`
key that holds an object and `activity.json` is declared in `src/kranto/stored/` (a
feature's in `features/<id>/stored.py`), and read and written only through it. The registry
(`stored.COLUMNS`, `SETTINGS`, `FILES`) is the data model's list of shapes; a reader gets a
typed value, and a value stored in another shape reads as the field's default (logged once as
"stored data not as declared ... (stored-<signature>)"), never a crash. the page's `loop.db`
has the same, in `src/kranto/page/stored/`. CONTRIBUTING's "Stored data" says how a shape changes.

**Append-only, with one recorded way out.** Triggers reject UPDATE on every
table except `settings` and `schema_meta`, always. They reject DELETE too,
except on the six purgeable tables (`observations`, `snapshot_points`,
`llm_calls`, `syntheses`, `item_signatures`, `observation_links`), whose DELETE triggers let a row go only while a
purge token row (`purge_token`) exists in `settings`. Only `Store.purge()`
writes that token, inside the one transaction that also deletes and records
each removal in `purges`, and removes the token before it commits; no other
connection ever sees it. Corrections are new rows (`supersedes` on
observations and topics), status changes are events (`status_events`,
`watch_events`, `source_retention`), and verdicts are rows whose latest one
counts (`grades`, and the older `verdicts`).

**What is deleted, and when.** An observation is kept for its retention
age: the latest `source_retention` override for its source (`afk sources
retention ID DAYS`), else `retention.by_kind` for its source's kind, else
`retention.default_days` (90); 0 means forever. Age is counted from
`created_at`. Compaction (`afk compact`, and the `compact` job) takes every
observation past its age, groups them by calendar week (Monday, UTC),
clusters each week by k-means on the stored embeddings (k chosen as the map
chooses it, at most one cluster per 5 observations; under 10 observations,
one), and writes one `rollups` row per cluster. Then, in one transaction per
week, it removes:

- the observations, and their rows in the full-text index;
- their `snapshot_points` (clusters keep their counts and shares, so trends survive; representatives that point at removed observations are skipped);
- the `llm_calls` rows behind them (the judge call, whose request and response hold the source's raw text), unless a remaining observation uses the same call;
- `syntheses` that cite them;
- links between observations (`observation_links`) with either end among them. The other end stays an ordinary observation until its own age.

It writes one `purges` row per table touched: what, how many, why, when, and
the rollup ids. A purge of `llm_calls` records the removed calls' cost per
day, and `Store.spend_since` adds it back, so compaction never lowers the
spend the budget is checked against. Idea cards written since #71 carry a
snapshot of each cited observation (derived summary, source, date, URL); for
earlier cards, compaction writes the same into `evidence_snapshots` before
removing what they cite. `items_seen` stays (dedup key and canonical URL, no
text), so an expired item is never fetched or judged again.

Model calls for items that were judged but not kept (`gated`, `skipped`,
`screened_out`, `parse_failed`, `item_error`), and every item's screen call
(`items_seen.screen_call_id`, #84; outcome `screen` in the purge's detail),
hold the same raw text and expire at the same age, by the item's source and
the `items_seen` time. No observation stands for
them, so no rollup is written: they are removed through the same purge, in a
`purges` row of their own (per-day cost and outcome counts in its detail).
Their `items_seen` rows stay. A call a remaining observation uses is never
removed.

Every other model call (failed calls, scout, cluster names, explanations,
cards, verification) also holds third-party text in its request. It is removed
once it is older than `retention.default_days`, unless something that remains
still references it: an observation, an `items_seen` row (those follow the
item's source age above), an idea's `gen_call_id` or `verify_call_id`, a
synthesis, a rollup's summary call, a cluster's `name_call_id`, or a source's
`origin_call_id`. One `purges` row per run, with per-day cost, purposes and
the number that had failed.

| Table | Holds |
|---|---|
| `topics`, `sources`, `topic_sources`, `status_events` | What is watched and why; source validation JSON (incl. scout role `core`/`wildcard`, `discovered_from`). |
| `topic_revisions`, `topic_source_events` (views `topics_now`, `topic_links`) | The owner's edits of a topic (migration 38): a topic keeps its id; each edit of its name or description is a `topic_revisions` row (the embedding made again from the new words, `changed`, `by` the door it came through: `ui`, `chat`, `mcp`, `cli`), the newest counting; a source added to or removed from one topic is a `topic_source_events` row (`link`, `unlink`), the newest of a pair counting. Every reader goes through `topics_now` (a topic with its newest words) and `topic_links` (the pairs linked now), so a rename is seen everywhere at once. A source removed from its last topic is retired (`status_events`), never left in the broad lane. Archiving a topic is a status (`archived`): not read, off the lists, its evidence, themes and cards readable. Append-only. |
| `run_marks` | A run's life as it goes (migration 39, ACT; `docs/activity.md`): `started` (the trigger, who, the subject, the process), `progress` (the stage in words, step of steps), `waiting` (it stopped for the owner, with the verb and the action), `stopping` (the owner clicked Stop), `ended` (its state), `dismissed` (the owner put a failing kind away). `runs` stays the end record and the scheduler's due-ness; a run's uuid is its `runs` row's, its model calls' and its marks'. Written by one buffered writer thread (`activity.py`); removed only through the recorded purge (`activity.keep_days`, `activity.max_rows`, at compaction). Migration 39 also adds `runs_finished` and `runs_kind_finished`, the indexes the scheduler's due-ness reads lacked. |
| `llm_calls` | Every model call: request, raw response, model, prompt version, tokens, cost, outcome. Migration 25 adds `provider`, `cache_read_tokens` and `cache_write_tokens` (`prompt_tokens` stays the whole prompt) and `equiv_usd` (a plan-billed call's list-price equivalent; its `cost_usd` is 0); null before it. |
| `items_seen` | Every consumed item and its terminal outcome. Outcomes: `contributed`, `gated`, `skipped`, `screened_out` (dropped by the screen, #84), `sponsored` (the item is an ad: its title says so or it links to an ad or affiliate URL; no model call, #86), `parse_failed`, `item_error`, `prefiltered`, `duplicate`, `near_duplicate`, `removed`, `stale`. `screen_call_id` (migration 16) is the screen's call for the item, whatever its outcome; for `screened_out` it is also `llm_call_id`. A gathered source kept as a child has a row of its own (`item_id` `look:<parent item id>:<hash>`). |
| `observations` | The library. Embedding BLOB (float32, 384), model name, ratings, excerpt, URL, `admitted_by`, `llm_call_id`. |
| `runs` | One row per job run: kind, status (`ok`/`degraded`/`failed`/`skipped`), summary JSON, error. An ingest run's summary has per-source counts and, since #86, `overrides` (`rated` replies, `set`, `lifted` below the gate, `refused` by the backstop, `rate` = set / rated; also on the Health page and in `afk run`), `sponsored` items and `sponsor_links` left out of gathering, with up to 10 reasons per source in `sponsor_reasons`. |
| `snapshots`, `snapshot_points`, `clusters` | Maps. Cluster numbers are per snapshot; `lineage_id` carries identity. Trajectory JSON per cluster holds shares, arrivals, burst state, p and q. Since migration 14, shares, source and topic mixes, arrivals and the cross-source size count distinct stories; clusters carry `stories`, `origin_mix` and `max_origin_share`, trajectory points `stories` and `new_max_origin_share`, and the snapshot's quality JSON `stories` (counts and the near-duplicate null check). |
| `syntheses` | Cached explanations. |
| `ideas`, `verdicts` | Idea cards and the original card verdicts. |
| `messages`, `deliveries` | What reached a person, and each delivery attempt. |
| `strike_candidates`, `strike_decisions` | What might deserve a strike, and the gate's one decision per candidate with its reason. |
| `watches`, `watch_events` | **Retired** (WT, 2026-10-23): saved questions and their status, no longer read or written (the setting `watch_matches_written_through` likewise). Kept one release with their rows; the next release drops both tables, `watches_topic` (migration 37) and the setting in a migration of its own, with a note here. Their old `strike_candidates` (origin `watch`) and decisions stay as history. |
| `grades` | Verdicts on messages, observations, clusters and ideas. |
| `item_signatures` | An item's pre-judge text (title and the first 1,000 characters of body) as a 128-value MinHash signature, with its method. Hash values only, no text. Written when an item is judged (`contributed`, `gated`, `skipped`) or consumed as `near_duplicate`; removed through a recorded purge once older than `stories.window_days` (30). Purgeable. |
| `story_links` | One row per item that repeats an earlier one: the item, the item it matched, the story's root (earliest member), the similarity, and whether it was judged (`judged = 0`: consumed as `near_duplicate`). Ids only; never purged. |
| `observation_links` | A child and its parent (`relation`: `discussion`, `link`, `repository`), written in the same transaction as the child: one a deep dive found before deep dives left Kranto (`deep_dive_id` set; child `admitted_by = 'deep_dive'`; still read like any other) or one gathered with its parent at ingest (#84; `deep_dive_id` NULL, `admitted_by = 'gathered'`, the parent's judge call). Purgeable: removed with either end. |
| `rollups` | What compaction keeps of a week's cluster of expired observations: period, size, source, platform and topic mix, mean signal, kind counts, keywords, a tier-1 name and 2-4 sentence summary (scrubbed), up to five URLs, the centroid with its embedding model, and the replaced observations as a count and a fingerprint. |
| `purges` | One row per table per compacted week: table, row count, reason, rollup ids, detail (period; per-day cost for `llm_calls`). |
| `source_retention` | Per-source retention overrides; latest wins; `days` NULL means back to the defaults. |
| `evidence_snapshots` | For idea cards written before #71: what a cited observation said, recorded when compaction removed it. |
| `settings` | Mutable: the pause flag, the purge token (only inside a purge), and similar. |
| `source_fetches` | One row per source per ingest run, and per "Fetch now" (`trigger` `run` or `manual`): `state` (`ok`, `paced`, `failing`, `needs_login`), `fetched`, `new`, and the scrubbed `error`. A source's status, last fetch and Fetches table read it (migration 17, S2). A paced fetch also records `retry_at`, when its host may be asked again; ingest defers the source until then (migration 21). |
| `connections`, `connection_events` | A connected account: provider, instance, account label, read-only scopes; and what happened to it (`connected`, `tested`, `needs_login`, `disconnected`; the latest of the first, third and fourth is its state). No secret: tokens and client secrets are encrypted in `data/secrets/connections.json` (`connections/vault.py`), keyed `conn:<id>` (migration 18). |
| `feedback` | Kranto UI's grades, pairs and confirmed actions (migration 19, `feedback.py`, `web/feedback_api.py`): `target` (observation, cluster by lineage, idea, build by the page's ledger id, source, topic, message, pair), `kind` (`grade`, `pair`, `action`, `implicit`), `value`, `reasons` (the "why" chips), `origin` (`ui`, `review`, `chat`...), `context` (route, the queue slot). The latest grade row on a target counts; a cleared grade is a `skip` row. Every grade is written here (`grades.add_grade` too, since #9); `grades.latest`/`history`, the one reader, also read the rows of `verdicts` and `grades` from before. The review queue asks only for builds and this week's cards. No CHECK constraints: the vocabulary is in `feedback.py`. A build's grade carries `context.card` (the card it was built from) and `context.idea` (the loop's idea), indexed by `feedback_card` (migration 36, CON L3). |
| `source_mutes` | A mute from Kranto UI's **mute…** (UI-v4 2.3): `muted_until` (not fetched until then) or `read_less` (read at half its items per run); latest row per source wins, and a row with neither is back to normal, so an undo is one more row (migration 20). |
| `archive_themes`, `archive_theme_members` | Themes of an imported archive (migration 22, `importers.import_parallax_themes`): one row per lineage of Parallax's clustering per bundle (the latest row per lineage is the theme), with its name, earlier names, keywords, whether it is alive, size, first and last epoch, and history (size and share per epoch); members are imported observations by id, no foreign key. `/api/archive/themes` reads them; `/api/observations?theme=<lineage>` lists the members. |
| `idea_topics`, `idea_citations` | A card's topic and its citations (migration 35, L2, `ideate/cards.insert_card`), each a child of its card written at the card's insert (the migration filled them for older cards): `idea_topics.topic_id` the user topic with the largest share of the card's evidence (NULL: none, as for a dispatch card's archive evidence) and `shares` the list the card's row shows (`[{id, name, kind, n, share}]`, user topics first), the newest row of a card counting; `idea_citations` one row per citation (`observation_id`, `n`, `role` evidence or demand), indexed by the observation ("which cards cite this"; no foreign key: retention may remove the observation, and the row stays). Append-only. |
| `outcomes` | What happened to an idea card after it was written (migration 24, `outcomes.py`, PLAN 4.7): `idea_id`, `kind` (`editor` first: the weekly editor's class for the card, with `detail.week` and `detail.why`; later `pitch`, `build`, `verdict` and the rest), `value`, `detail` JSON, `source` (`kranto.page`). Written by the page through `POST /api/ideas/{id}/outcome`; append-only; the latest row of a kind counts, and `/api/ideas` sends the latest (`outcome`) and the latest editor row (`editor`). |
| `api_spend` | What a paid API other than a model costs (migration 26, 5.3): one row per request that returned resources, X's reads first: `provider`, `source_id` and `run_uuid` (null for a preview or a Test), `kind` (`post_read`, `owned_read`, `user_read`, `list_read`, `xai_post`), `count`, `usd` at list price (`pricing.X_PRICES`). An estimate from above: the provider bills a resource read twice in one UTC day once. Ids and counts only; never purged. Live search adds `provider` `exa` (kind `search`, or `search_free` in Exa's free mode at 0), `anthropic_search`, and the free `hackernews`, `github`, `arxiv` at 0, and `caller` (migration 27: `scout`, `cards`, `editor`, `research`...; null for the owner's own). |
| `search_cache` | Mutable, like `oauth_states` (migration 27): live search's day cache, one row per backend, query (a SHA-256 of it) and recency, holding titles, links, dates and snippets only; rows older than `search.cache_hours` are removed when a search writes. |
| `events`, `event_cursors` | The feature core's bus (migration 30, `core/events.py`): one row per fact a feature or the core published (`kind` `<noun>.<verb>`, `feature`, `trust`, a payload of ids and small facts, never a document); a subscriber's cursor per kind is the newest `event_cursors` row. Append-only. See [features.md](features.md). |
| `cub_tickets`, `cub_ticket_states` | Tickets (migration 31, `core/tickets.py`): a feature's or a cub's request for one of the core's high-trust actions (`send.newsletter`, `post.mastodon`, `book.propose`; `trade.instruct` rows are Invest's, from before it left; an earlier release's name for one is an alias of it for one release), its typed fields, its provenance (`because`, `run_uuid`) and its expiry (`9999-12-31T00:00:00Z` for a draft's ask, which waits until answered); each state (`needs_confirm`, `confirmed`, `done`, `dry`, `declined`, `expired`, `refused`, `unknown`) is a new state row; an `expired` row with the note `replaced by #<id>` means a newer draft of its series replaced it. |
| `cub_pins`, `cub_calls`, `cub_orders` | The rest of the core's record: each feature's or cub's manifest hash (and a cub's tree hash) at a version; every call the core made for a feature or a cub; Invest's instruction steps (`cub_orders`, no longer written). Append-only. Migration 31 copied migration 30's `mod_pins`, `mod_calls` and `money_orders` into them with their ids; the `mod_*` tables stay, frozen, read by no code. |
| `cubs`, `cub_installs`, `cub_drafts`, `cub_dedupe`, `cub_kv` | The cub runtime (migration 31): the registry of installed cubs (a row per state change), every install step, the drafts a broker adapter holds, `events.publish`'s dedupe keys, and a cub's own key-value store (`cub_kv`, the one mutable table among them). |
| `invest_*`, `radar_*`, `browser_*`, `deep_dives`, `deep_dive_events` | The tables of the features that left Kranto (Invest, the trend radar, the browser extension, deep dives). Kept with every row, written by nothing, read only by `kranto archive` ([archive.md](archive.md)). `money_orders` and `broker_pins` (migration 30's, frozen) stay as they were, read by nothing. |
| `oauth_states` | Mutable, like `settings`: a sign-in in progress (provider, instance, a SHA-256 of the state, the callback URL, `used_at`). Marked used on the first callback; rows older than an hour are removed with their PKCE verifiers (in the vault) after each ingest run. Not exported. |

**Migrations** are `(number, script)` pairs in `store.py`; each applied
number is recorded as `migration:N` in `schema_meta`, so branches that own
different numbers can merge in any order. In use: 1-6, 8, 10, 11, 12, 13,
14 (stories, #35), 15 (deep dives, #67), 16 (`items_seen.screen_call_id`,
#84), 17 (`source_fetches`), 18 (`connections`, `connection_events`,
`oauth_states`), 19 (`feedback`, LEARNING.md track L1), 20 (`source_mutes`), 21 (`source_fetches.retry_at`, polite fetching), 22 (`archive_themes`, `archive_theme_members`), 23 (`topics.kind`, `topics.ref`, project topics), 24 (`outcomes`), 25 (`llm_calls.provider` and its cache and equivalent-cost columns), 26 (`api_spend`), 27 (`search_cache`, mutable; `api_spend.caller`), 28 (News's tables), 29 (Invest's tables), 30 (the feature core: `events`, `event_cursors`, `mod_pins`, `mod_requests`, `mod_request_states`, `mod_calls`, `broker_pins`, `money_orders`), 31 (the cub runtime and the rename: `cubs`, `cub_installs`, `cub_pins`, `cub_tickets`, `cub_ticket_states`, `cub_calls`, `cub_orders`, `cub_kv`, `cub_drafts`, `cub_dedupe`), 32 (the trend radar: `radar_trends`, `radar_series`, `radar_stages`, `radar_chains`,), 33 (the radar's call ledger: `radar_calls`, `radar_scores`, hash-chained), 34 (the radar watches the owner's topics: `radar_topics`, `radar_proposals`, `radar_trends.topic_id`,), 35 (a card's topic and citations: `idea_topics`, `idea_citations`, CON L2), 36 (`feedback_card`: a build's grade names its card, CON L3), 37 (`watches.topic_id`: a watch filed under a topic, CON L6), 38 (`topic_revisions`, `topic_source_events`, the views `topics_now` and `topic_links`: the owner edits a topic), 39 (`run_marks`, the indexes `runs_finished` and `runs_kind_finished`: background work you can see, ACT), 40 (`news_articles`, `news_article_pages`: News's articles). Numbers 7 and 9 were reserved for phase-2 branches that turned out not
to need them; they may be reused. The next unused number is 41. A migration may only add; it never rewrites rows or
rebuilds tables. Migration 13 also recreated the DELETE triggers of the
purgeable tables with their purge-token `WHEN` clause; migrations 14 and 15
create `item_signatures` and `observation_links` with that trigger from the
start.

**Full-text index.** `observations_fts` (migration 12) is an FTS5 index over
observations' title, summary, why_it_matters and tags, filled by a trigger on
every insert. It is derived data: it and its shadow tables
(`observations_fts_data`, `_idx`, `_docsize`, `_config`) are left out of the
append-only triggers, because FTS5 rewrites rows in them as it merges
segments (an append-only trigger there crashes the insert), and SQLite cannot
put triggers on the virtual table itself. A delete trigger (migration 13)
removes a purged observation's postings. `rollups_fts` (migration 13) is the
same over rollups' name, summary and keywords. If either is ever damaged,
rebuild it from its table: `INSERT INTO observations_fts(observations_fts)
VALUES ('rebuild')`, and likewise for `rollups_fts`.

**Project topics.** Migration 23 adds `topics.kind` (`user`, the default and
every row before it, or `project`) and `topics.ref` (null for user topics). A
project topic is one the page creates for one of its projects (a published
repo) through `POST /api/topics` with `kind: "project"` and
`ref: "project:<id>"` (`project:` then 1-40 lowercase letters and digits);
`kranto topics add --kind project --ref project:<id>` does the same. The kind
is set at insert and never updated. A POST with a ref that is already a topic
returns that topic with `"existing": true` and starts no scout. The body's
optional `approve` (`none`, the default; `core`; `all`) is what the scout
approves at once: `core` approves core proposals whose median similarity is at
or above `ingest.prefilter_min_similarity` (the scout's `--approve` rule),
`all` every core proposal with a similarity; wildcards always stay proposed.
A project topic gathers like any topic (ingest, the screen, the judge, the
map). It does not dilute the owner's: `GET /api/topics` and `kranto topics
list` take `kind=user|project|all` (default `user`); `/api/status`'s topics
and setup's topic count are the owner's; `/api/today` lists project topics
under `project_topics`, apart from `topics` and its totals; the source picker
(`/api/catalog`, `/api/sources`) lists both, with `kind`. The card writer
leaves out clusters that are at least half project topics' stories, and does
not count a project topic towards a bridge, while `ideas.project_topics` is
`skip` (the default); `cards` makes them candidates like any other. With no
project topic the candidates are the same either way. `feedback.TARGETS`
has `project` (the page's project id, like `build`).

**Sources described in a pasted text**. `POST /api/sources/from-text {text, topic?}` (202 and a job, key `fromtext`, one at
a time per install) and `afk sources describe FILE|-` (alias `afk sources add --from-text
FILE`) send the text to one tier-2 call (`purpose` `resolve`, `max_tokens` `resolve`,
8000), which names a catalog preset and fields for each source the text names. The text
is data: one user message inside a `<<<document` fence it cannot close; at most 16,000
characters are read and 50 proposals kept (`stopped_at` names where it stopped). Each
proposal is then checked as the scout's are (`scout.validate`, without a topic no
similarity) and recorded with `origin` `manual` (the person named it), `status`
`proposed` or `invalid`, and a validation record with `from` (the line) and `batch`
(`fromtext:<call id>`). Lines the model could not resolve, refused ones (Reddit,
Lobsters, X over its cap or past 5 checks a paste) and login presets without their
account connected (`connect_first`) are rows of the batch only. A source named twice, or
already proposed, is one source; one already approved is `already_watching`. X searches,
accounts and lists are checked with one 10-post fetch each and carry `cost_usd` `{check,
run, month}`. Nothing is approved by resolving: `POST /api/sources/approve {ids, topic?}`
and `afk sources approve ID... [--topic ID]` approve in one transaction. The batch is
kept as a job (`GET /api/sources/from-text`, `/api/sources/from-text/<call id>`).

**Backups.** Copy the workspace directory while no job is running, or use
`sqlite3 kranto.db ".backup copy.db"`. `afk export TABLE -o file.jsonl`
writes any table as JSONL.

## 4. Jobs

| Job | Default cadence | What it does | Refuses when |
|---|---|---|---|
| ingest | every 3h | Fetch, filter, screen, gather, judge, record. Gathering is bounded: `look.item_seconds` (30) of wall clock per item, each request cut at `look.request_seconds` (15), at most `look.max_per_run` (40) items gathered for | Paused, over budget, no key, no approved sources, another ingest holds the lock |
| snapshot | daily | Re-cluster, bursts, candidates | Fewer than 30 observations; library unchanged since the last snapshot; another snapshot holds the lock |
| ideas | daily | Idea cards from the latest map | No map; map unchanged since the last ideas run; another ideas run holds the lock |
| xrecheck | weekly (`x.recheck_days`; 0 or `x.recheck_max` 0: off) | Looks up at most `x.recheck_max` kept X posts (idea cards' first) and removes each one X no longer has through the recorded purge, no rollup; each post X returns is a read in `api_spend` | Skipped, at no cost, with no X posts, no connection, or the X cap reached |
| compact | daily (`retention.every_hours`), after the snapshot | Weekly rollups of observations past their retention age; removes them and the raw text behind them through a recorded purge | A snapshot or another compaction holds its lock. Nothing past its age is an `ok` run that removes nothing. Paused, over budget or no key: rollups are written without name and summary rather than keeping text past its age |
| heartbeat | weekly | Summary of the week, sent even with zero strikes | Never refused; a second run in the same ISO week records `ok` and sends nothing |
| cubs.gc | daily | Rotates cubs' logs, removes staged folders and work older than a day and removed cubs older than 30 days, expires open tickets past their time (a draft's ask has none) and files again the ask of an unseen draft that ran out of time under an earlier release, fails fetch jobs a crash left idle for an hour | Never refused |
| a cub's own jobs (`newsletter.weekly`, `toot.weekly`, …) | as each `cub.yaml` says (`every_hours`, or `at` and `days` in the host's zone) | Runs the cub's handler in its sandbox: a `runs` row and `job.finished` | The cub is paused, stopped or off, `cubs.enabled` is false, `cubs.STOP` exists, or the update's drain holds the scheduler: skipped and due again |

`afk serve` runs these in-process. A job is due when the last non-skipped run
of its kind finished more than its interval ago, computed from the `runs`
table, so restarts neither skip nor repeat work. A skipped run (an unchanged
map, a refused idea run) does not reset the interval but defers the next attempt
by an hour, or by the interval if shorter, so new data is picked up within
the hour and an unchanged library is checked hourly, not on every tick. After every job the gate
runs and pending messages are delivered. For cron instead: `afk serve
--no-scheduler` and schedule `afk run`, `afk snapshot`, `afk ideas`, `afk
compact`, `afk heartbeat`, `afk strikes --run`. The ingest file lock prevents overlaps
between cron and the server; snapshot and ideas take their own locks.
A stop (SIGTERM) ends within 10 s (`stopping.py`): open requests get 3 s, the
cub host's processes and scopes up to 4 s, a running job and the lanes' ticks
what is left less 2 s, then the server's own children (a terminal, a `claude -p`,
a `git`) get SIGTERM and, 2 s later, SIGKILL. Detached jobs (builds, fixes,
pre-push checks) keep running and the next start adopts them. A job cut off has
recorded no run, so it is due again at the start. A watchdog exits at 12 s
whatever is left; the unit's `TimeoutStopSec=15` is only the last resort. The
journal says how each stop went (`stop: done in 1.2 s, clean`, or what was cut
off), and `kranto update` reports a stop over 12 s as a warning with that line.

**`kranto serve`** is `afk serve` with the scheduler on by default (the old
`calibration.conf` drop-in is retired; `--no-scheduler` stays for cron) and
the page's build loop as a second lane, when `brb.enabled` and `builds.enabled`
are set, the page is installed and the server is on loopback.

**Builds are off unless set.** `brb.enabled` is the page at `/`; `builds.enabled`
(absent means off) is the half of it that builds: the loop lane and its maintenance
poll, Build, Projects and Repos, Settings › Building, Publishing and Tools, "Send to
build" on a card, Welcome's Building and Publishing steps, and the build loop's
actions as `b.*` verbs for the page, `kranto mcp` and the console. Off, none of these
is drawn or started, project topics are not read and are listed as paused (nothing
is written: turning builds on finds them as they were), `kranto status` has no loop
line, and `kranto doctor` checks only what the console needs. Nothing is deleted:
`loop.db`, the task folders and the project topics stay on disk, untouched.

```yaml
builds:
  enabled: true      # builds, projects and repo maintenance on
```

With builds on, every `tick_s` (30 s, the loop's
`loop.yaml`) the lane runs `Loop.tick()`, the step `brb loop run` repeats, with a
fresh `Loop` so settings apply on the next tick. It holds the loop's
`daemon.lock` and writes `daemon.pid`, so a stray `brb loop run` refuses to
start and the page's pages show the loop running; if a `brb loop run` already
holds the lock the lane waits and takes over when it exits. `brb loop stop`
ends the lane until the server restarts, as it ends the daemon. Builds are
detached: `kranto.service` has `KillMode=process`, so stopping it leaves them
running and the next start adopts them. The lane's state (`idle`, `waiting`,
`stopped`; ticks, errors, last tick) is `lanes.loop` on `/api/status` and
`/api/health`, and a line of `kranto status`. `afk serve` has no lane: run
`brb loop run` beside it, as before.

Run statuses: `ok` (everything worked), `degraded` (some sources or calls
failed, a reply came back empty or was declined, or the run stopped early on budget
or pause; the source's `empty_replies` and `refused` count them), `failed` (a fatal model
error, or every source failed; raises an alarm), `skipped` (nothing to do or
not allowed to spend).

**The health word and why**. The status bar's word (Healthy,
Degraded, Paused) and one line saying why are worked out on the server and served as
`ingest.health` on `/api/today` and `health` on `/api/activity`, `{word, tone, reason, at,
run, trace}`; the page, the phone and the console (`kranto_incidents`) read that answer.
Paused: watching paused, the provider paused it until a time, or the build loop paused.
Degraded: your sources not read yet, the last read failed or had problems ("The last read of your sources
failed at 12:42: a safety filter at OpenRouter declined one item"), more than one judge
call in five failed in 24 hours, or the build loop is not running. `trace` opens the run.

## 5. Money

| Tier | Model (default) | Used for |
|---|---|---|
| 0 | local embedding | Prefilter, search, clustering. Free. |
| 1 `judge` | anthropic/claude-haiku-5.5 (4.5 until 2026-10-08) | Screening and judging items, cluster names, rollup names and summaries. |
| 2 `reason` | anthropic/claude-sonnet-5.5 | Scout, explanations, idea cards and their citation checks. |

Both are set under Settings › Watching › Models in Kranto UI (`/api/settings/models`, which writes
`llm.models` in the config and applies from the next call). The list offered there is
the page's (`src/kranto/page/models.py`).

Every call is checked against the pause switch and `budget.monthly_usd`
(none by default, `null`: spend is uncapped unless a cap is set; Settings › Spend writes it) before it is sent, and alarms fire once a month at
`alarm_fraction` and at exhaustion.

Reply-length ceilings are per call (`config.MAX_TOKENS`, overridable under
`llm.max_tokens`): judge 3000, judge with gathered sources 4000, screen 1000, card 8000,
verify 4000, scout 8000, resolve 8000, explain 3000, rollup 2000, cluster name 1000. The judge's were 800
and 1800 until 2026-10-08, when 6 of about 740 live judge replies were cut off and marked
their ingests degraded. The same day the judge tier moved to Haiku 5.5, which reasons
before it answers, and the reasoning counts against the ceiling: its screen replies used
38-620 tokens (p99 517, 128 replays of the day's 64 live screens; the answer itself is
under 100), cluster names 168-372, judge replies up to 1418. At the old screen ceiling of
160, 26 of 64 live screens were cut off and 3 again at 320, which marked the 15:00 ingest
degraded. The judge, the screen, rollups and cluster names ask once more
with twice the room when a reply is cut off; only a second cut-off counts as an error. Measured reference points: Parallax
judged items at about $0.0027 each on Haiku (April 2026, partial logs);
the server's full-text fetching adds roughly 55% input tokens on the items it
applies to (live sample, 27 of 30 items). No the server run has been costed with
a real key yet; that is issue #21.

**Looking before judging** (#84, `look.enabled`, on) makes two calls per item
that passes the prefilter: the screen (`purpose = screen`, about 1,650 input
and 55 output tokens) and, unless the screen drops it, the judge, which also
reads up to `look.gathered_chars` (2,000) characters of each gathered source
(about 4,300 input and 580 output tokens). Measured with Haiku 4.5 on
2026-10-03: $0.0079 per item on the 30 graded #47 items (screen $0.0019,
judge $0.0072 for the 25 that passed), $0.0084 per item on 15 items from the
lab-tools pack, against about $0.0035 per judged item before. Gathering took
1.1 s per item on average, 4.2 s at most. `look.enabled: false` returns to
one judge call per item.


## 6. Runbooks

**Stop every cub now.** `touch ~/.config/kranto/cubs.STOP` (or `kranto cub stopfile --set`):
within ten seconds the reaper kills every cub's process, nothing spawns, and every action of a
cub's ticket resolves `dry` with the note "cubs.STOP exists". Remove the file to resume; the
page's Resume is refused while it exists. One cub: `kranto cub stop ID` (its open tickets are
expired) or `kranto cub dry ID KIND` for one of its kinds.

**A cub is paused.** `kranto cub inspect ID` says why: three failed runs in a row (the last
one's words), its files changed since you approved them (`kranto cub update ID` shows the change),
a refused hello, a ticket flood, its cap reached twice in a day. `kranto cub log ID` has the
runs. Fix the cause, then `kranto cub resume ID`. A cub's process and calls are in `cub_calls`
(`kranto cub log ID --calls`).

**Alarm: "ingest run failed" with HTTP 401/403.** The key is wrong, revoked
or missing. `afk doctor` verifies it against OpenRouter. Nothing was lost:
items are only marked seen after a real outcome. Fix the key; the next run
continues.

**Alarm with HTTP 402.** Out of provider credit. Top up; nothing was lost.

**HTTP 404 from the model endpoint.** The model slug no longer exists.
`afk doctor` compares configured models with the provider's list. This has
happened once already: `anthropic/claude-haiku-4-5` disappeared from
OpenRouter's list.

**Alarm: budget exhausted.** Model calls stop until the month rolls over or
the budget is raised. Check the Health page for which runs spent it; a broad
source without a topic sends every new item to the judge.

**Runs are `degraded` with fetch errors.** Look at the per-source detail on
the Health page. A throttled source (429, 503, a timeout) is *paced*, not
failing: it waits for the host's `Retry-After` or a backoff, is fetched once
more at the end of the run, else deferred ("paced, retrying at ..."), and never
marks a run degraded. Only a source that fails `fetch.failing_after_runs` runs
in a row (default 3: a 404, a feed that does not parse) does; it then backs off
by itself (`fetch.failing_backoff_hours`, doubling up to
`failing_backoff_max_hours`) and shows under Needs you: fix it (Fetch now on
its page shows the current error) or retire it. The per-host gap, retries and
the longest wait retried in a request are `fetch.*` in the config.

**No map.** Fewer than 30 observations. The Map page says how many are
missing. Backfill on a source's first run helps; so does a broader pack.

**No idea cards.** Needs a map, and a cluster that is cross-source (at least
10 members, no source above 70%), bridging (two topics each at least 20%),
or rising. The Ideas page says what is missing.

**A card on a theme you choose.** A theme's sheet has **Card this theme now…** (or `afk ideas
card LINEAGE`): one card call and its check, about $0.06, outside the daily selection, under
the same lock and budget (the owner's D-1 of). The card says it was asked for; the
same evidence is not carded twice; the daily run is not affected.

**No strikes.** Expected most weeks. Read the latest heartbeat: it lists the
candidates that came closest and why each was held back. `afk strikes -v`
shows every decision and reason. Thresholds are per origin in the `strike`
section of the config and are not calibrated yet.

**No heartbeat arrived this week.** The process is not running, or delivery
is failing. Check `afk messages --kind heartbeat` and the deliveries on the
Health page. For an external check, set `notify.heartbeat_ping_url` to a
healthchecks.io-style URL: it is pinged after every ok or degraded ingest,
and its absence alerts from outside the machine.

**Delivery targets configured but nothing arrives.** Apprise must be
installed (`pip install 'kranto[notify]'`); `afk doctor` and the Health page
say so if it is not. Each attempt is a row in `deliveries` with its error.

**A run is stuck as "another run holds the lock".** A crashed process can
leave the lock file, but the lock is an OS file lock, so it is released when
the process dies. If it persists, another `afk` process is running.

**Reaching the UI from another machine.** Keep `afk serve` on 127.0.0.1 and
forward the port: `ssh -N -L 8766:127.0.0.1:8765 host`, then open
http://127.0.0.1:8766. If you bind to a LAN address instead, requests are
accepted only for loopback names, the `--host` address and each
`--allow-host NAME`; anything else gets "unknown host" (a DNS-rebinding
defence). Scripts that POST to the API must send an `Origin` header matching
the address they use.

**Retention and compaction.** How long observations are kept is
`retention.default_days` (90), `retention.by_kind` (for example `{reddit:
30}`), and per source `afk sources retention ID DAYS` (`0` keeps a source
forever, `default` removes the override). `afk compact` runs it now; the
Health page shows the settings, the last compaction, rollups written and rows
removed per table, and Library › Rollups lists and searches the compacted weeks.
Before shortening retention on a real library, try it on a copy
(`sqlite3 kranto.db ".backup copy.db"` into a throwaway workspace): removal
cannot be undone. A compaction that failed rolled back its current week and
kept every earlier week it finished; the next run continues. A `degraded`
compaction wrote some rollups without a name and summary (a model call
failed); they keep their keywords, mixes and links. Measured on a copy of the
#63 benchmark library with a half-day window (2026-09-27): 393 of 546
observations compacted into 4 rollups, the vacuumed database went from 17.5 MB
to 10.6 MB, and the 4 summary calls cost $0.0084. On the Parallax import with a
120-day window: 6,696 of 7,113 observations into 53 rollups over 5 weeks, 37.6
MB to 11.3 MB, $0.116 in 53 calls (about $0.0022 each), 207 s.

**Moving or copying a workspace.** Stop jobs, copy the directory, keep `.env`
out of anything shared.

**Seeding from Parallax.** `afk import parallax PATH... [--snapshot DIR]` reads
Parallax `library.jsonl` files (`library/runs` and `experiments/05-first-intern`
between them hold every observation of the published snapshot). Embeddings are
identical to the server's (verified), so imports share the index. Imported sources
are labels, never polled. Records are taken oldest first and skipped, with a count
per reason, when their Parallax id is already imported, their canonical URL is
already in the library (the first observation of a URL is kept), they are a near
duplicate (the stories rule's text match at `stories.skip_at` on the item's own
excerpt and embeddings at least 0.88 alike; Polymarket is templated), or they have no
ratings. `--snapshot snapshots/latest` reports how the records and the bundle
reconcile and writes its themes (`archive_themes`: one per lineage of
`trajectories.json`, named by the latest name in the dated bundles'
`cluster_names.json`, else keywords; members are the imported observations of an
alive lineage's cluster). The archive is no flood: imported rows keep the time they
were observed, so they are never new on Today and sort below the library's own; they
are on the map but never arrivals, so no burst or rising theme comes from them; the
map's idea runs do not cite them (`parallax.card_evidence`); a topic's views leave
them out unless `parallax.topic_match` is set; the Library lists them with
`source=parallax`. Retention keeps them (`retention.by_kind.parallax` defaults to 0):
the default age would purge all of it at the next compaction.

`afk import parallax-dispatches DIR [--only ID] [--limit N]` writes one idea card per
pitch (OSS, commercial, founder) of each prose dispatch, no model call: the pitch
verbatim, the opening argument as thesis, the "My bet" paragraph as prediction, the
dispatch as provenance, and the dispatch's links matched by canonical URL to
observations as citations (`verified: "url_match"`); fewer than two matches leaves
the card `unsupported`. Run it after the observations. Cards have `origin` `dispatch`,
no score, are never strike candidates, and `/api/ideas` marks them `intake: manual`
(the page's automatic intake leaves them; `parallax.dispatch_auto_intake`). Dispatches
without the three pitches (the schema-1 data dumps) are listed, not carded.

**A hotfix**. A fix's pull request is open (its test in it):

    scripts/release/hotfix.sh the server 332 --dry-run      # says what it would do; changes nothing
    scripts/release/hotfix.sh the server 332                # merge, nightly cut, update, read back
    scripts/release/hotfix.sh the server 332 --stable       # and the fix for stable installs

It sets its own PATH (`~/.local/bin` first: a non-interactive ssh lacks it), merges with
`merge_when_green.sh` and the repo's required jobs (never `--admin`, never a skipped job), cuts
with `cut_local.sh --must-include <repo>@<merge commit>` (a nightly build; `rc_check.sh` on it
on `HOTFIX_RC_PORT` when `decide.py` asks, and the build withdrawn if that fails), runs `kranto
update --to <tag> --yes` here, and reads back `kranto --version` and the release's commit list,
which must hold the merge commit. With `--stable` it then finds the stable line (`release/X.Y`;
refused before the first promotion, for a PR already in it, and for a `big` PR), cherry-picks
the merge commit onto it as a pull request (a conflict stops it with the files named), merges
that on green, cuts the fix held (`cut_local.sh --line stable`), runs `rc_check.sh` against the
stable it patches and releases it (`gate.py promote --now`). The first step that fails stops
it, exit 1, with its reason and the log's path (`~/.cache/kranto-release/hotfix-<time>/`). Run
again after a failure: a merged PR is taken as it is. To stop one before a cut: `touch
~/.cache/kranto-release/hotfix.STOP`. **A release is not done until its commit list has been
read and contains the change it was cut for.**

**Stable and nightly** (the owner, 2026-10-24: "Stable is always a choice that we
make"). Every cut from main is a nightly build (`vX.Y.0-devN`, a prerelease); installs on the
nightly channel see it, stable installs and `install.sh` never do. The owner's install
(`update.channel: nightly`, `update.maintainer: true`) takes each with `kranto update --to <tag>
--yes`. The hourly `kranto-release-gate.timer` (installed from the maintainer's deployment
notes; `journalctl --user -u kranto-release-gate`) runs `gate.py tick`, which writes the
candidate to the owner's install (`update/candidate.json`): the build, the pull requests since the last stable with the `big`
ones named, the settings that stay off on stable, and the health checks that block the action
(a rollback of the build, a new error still occurring, `doctor --routes`, the odd installs).
It never promotes by itself, and nothing counts days. The owner actions **Promote to stable** in
Needs you; the action writes `update/promote.json` and starts the gate's unit, which clones
main, cuts `vX.Y.0` held from the build's commits (making `release/X.Y` in both repos), runs
`rc_check.sh` against the latest stable and releases it; a failure leaves it held, with a row
saying where it stopped. `gate.py status` says the candidate, each check's reading and what it
could not read; `gate.py known SIGNATURE --reason WHY` lifts an error the operator has looked
at; `gate.py withdraw TAG --reason WHY` withdraws a nightly; `gate.py promote --now --tag
vX.Y.Z --reason WHY` releases a held stable at once (a fix, or the operator's word). Every
promotion is a line in `~/.local/state/kranto-release/gate.jsonl`.

**Where it runs.** The operator's instances run on an always-on server, not the
operator's PC: one checkout of the repository (after a merge: `git pull`,
reinstall if `pyproject.toml` changed, run the tests), one workspace per purpose
(the local-first library, and a second one for the #63 benchmark), each served
by a systemd user unit bound to 127.0.0.1 and reached through an SSH tunnel.
Work that needs another branch uses a separate worktree, never the served
checkout. `kranto adopt` moves an install from before Kranto (by default the
workspace `~/kranto-kb`, the loop home `~/kranto-loop` and tasks in `~/tasks`;
`-w` and `--loop-home` for others) to `kranto.service` in place (backups next to
the workspace in `<workspace>-backups`, the `brb` section written, migrations,
then with a yes `kranto.service` and its drop-in replaced); `kranto adopt
--dry-run` prints the plan and changes nothing.

## 7. Invariants

Breaking any of these reintroduces a failure that already happened once.

1. Library tables are append-only, enforced in SQLite: UPDATE is refused on every one, always. DELETE is refused too, except on the purgeable tables inside a purge (the token exists only in the purge's own transaction), and every purge records what it removed, how many, why and when in `purges`.
2. An item is marked seen only after a terminal outcome; model errors never consume items (an item-level rejection is consumed only after a later call in the run succeeds; three in a row stop the run). Content is judged once: an item whose canonical URL was already judged is consumed as `duplicate` without a call, and one whose own text repeats an item judged in the last 30 days (another source, or the same source within 3 days) as `near_duplicate`.
3. Every model call goes through `LLMClient`; pause and budget are checked before each call; a call with tokens and no known cost is an error, never $0 (it is counted at a conservative estimate from its tokens and the run stops, the error naming the model and why). A call with no tokens and no reported cost has nothing to estimate from: it is stored at $0 and marked unpriced in its row, never at a made-up figure. A 200 with no content, no tokens and no cost is retried like a 5xx; still empty, its item waits for the next run and the run is `degraded`, never `failed`. A reply a safety filter or the model declined (OpenRouter's `content_filter`) is not retried: its item is consumed as `item_error` with its call (2026-10-29: one empty judge reply failed a whole ingest). The API key never appears in stored or raised errors.
4. 401, 402, 403 and 404 from the model endpoint stop the run and raise an alarm.
5. A source that cannot be fetched raises; it never returns an empty list.
6. The model rates; code multiplies. Skip is a first-class answer.
7. Embeddings are recorded with their model; different models never share an index. Stored text uses `search_document:`, queries and topics `search_query:`.
8. Quality claims are made against a null that can fail; movement is measured on new arrivals against the source mix, with a significance test.
9. Nothing is regenerated from unchanged data: snapshots, idea runs and repeated evidence are refused.
10. Strikes are rare by construction: per-origin threshold, staleness, warm-up, refractory period, weekly cap. Every decision is recorded with its reason.
11. The channel carries silence: a heartbeat every week, whatever happened.
12. Tests never call a model or the network.
13. A look before judging never edits the parent. What it reads is judged before anything is kept (by the parent's judge call, which rates each child it keeps on its own three ratings, multiplied and gated in code) and kept as an observation of its own with its own URL and excerpt, linked by an `observation_links` row in the same transaction; children are never dived, and the map does not count them as arrivals.
14. One voice counts once: copies of one text, and children (gathered, or found by a deep dive before deep dives left) with their parent, are one story in every count the map, movement and idea selection make, and no single origin (registrable domain) may supply more than 70% of a cross-source cluster's stories or of a rising lineage's new stories.
15. Sponsors and ads never enter the library: an item that marks itself as an ad or links to an ad or affiliate URL is consumed as `sponsored` without a model call, and gathering never follows a link in sponsor or advertising context. Override cannot lift an item with any rating below 0.3 or a signal below a quarter of the threshold, and every ingest run counts how often it was set.

## 8. How work on this project is run

- **GitHub issues are the only record of state.** Every piece of work is an
  issue. Decisions and progress are comments. PRs say `Closes #N`.
- **Tracking issues** hold a checklist of a phase: #22 (phase 2, built) and
  #28 (pre-public readiness). A new session starts from the newest open
  tracking issue.
- **Orchestrator and subagents.** Phase 2 was built by one orchestrating agent
  and four implementing agents. What worked:
  1. The orchestrator builds the shared foundation first (contracts,
     migration scheme, the notify API), so parallel work cannot diverge.
  2. Each issue is self-contained: why, scope, done-when tests, a
     pre-assigned migration number, rules.
  3. Each implementing agent works in its own git worktree
     (`../kranto-wt/<name>`, beside the checkout) and virtualenv, comments on its
     issue when it starts, records each non-obvious decision, rebases before
     pushing, and opens a PR without merging.
  4. The orchestrator reads the core diff against DECISIONS.md, re-runs the
     tests on the branch, waits for CI, merges one PR at a time, ticks the
     tracking issue, and runs an end-to-end check on anything its agent could
     not verify.
- **Doors.** Reversible changes are decided and recorded. One-way doors are
  asked: making the repository public, publishing to PyPI, committing
  third-party data, freezing a data contract other instances would depend
  on, sending anything to a target the operator did not configure.
- **Output discipline.** No emojis, no co-author trailers, no hyperbole, and
  never report something as working that was not run.

## 9. Open threads

- **#21 calibration.** One week on a real key: cost per judged item, keep
  rate, time to first map, bursts, candidates, strikes, grades. Then tune the
  prefilter, strike thresholds, burst parameters and card thresholds, and add
  a measured cost table to the README. Blocked on the operator's key.
- **#10 Reddit OAuth.** Optional credentials for reliable Reddit access.
- **#28 pre-public readiness.**
- **Considered and deliberately not built (2026-09-24):**
  - Topic "lenses" (per-topic map views, per-topic strike routing and
    budgets). One library with several topics is the intended way to get
    cross-pollination; separate workspaces are the way to run for someone
    else. Revisit if one library with many topics becomes hard to read.
  - A shared library written by many instances. If it is ever needed, the
    notes were: give each workspace an `instance_id` on every observation;
    start with a hub instance that pulls peers' append-only exports, rather
    than a shared server store; treat OpenSearch as a read-side index for
    search and dashboards, not as the system of record (no append-only
    enforcement, no transactions, heavy to run); decide duplicate handling,
    since two instances observing one post inflates clusters. The import
    format would become a contract between instances: a one-way door.
