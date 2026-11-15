# DESIGN — the server

*the server (Kranto AFK): an open-source re-implementation of Parallax. The package is `kranto`, the command is `afk`. Interns are called Kranto in user-facing text; the code keeps the plain word "intern" where it describes the role.*
*Status: the original plan (September 2026), kept as written; the server has been built and has moved on since, so where this page and the code or [OPERATING.md](../OPERATING.md) disagree, they win. Section 2's principles still hold. Parallax, the earlier experiment, is not public.*

---

## 1. What we are building

A self-hosted system you point at topics you care about. It watches public sources for those topics with cheap LLM "interns", writes what they notice into an append-only knowledge base, organises that knowledge base into a map of emergent clusters, and helps a person browse it and generate ideas grounded in cited evidence.

One sentence to keep: **cheap patient attention, an honest append-only library, a map the reader explores, ideas that cite their evidence.**

What changed from the original, deliberately:

| Original (parallax + octo-owner-me + dispatch routine) | Re-implementation |
|---|---|
| Hand-written `firehoses.yaml` of 66 sources | Topic-first: describe a topic, a scout proposes sources, you approve |
| JSONL files spread over `library/runs/*/*/` | One SQLite file, append-only enforced by triggers; JSONL export |
| Map + search lived in a separate Next.js site fed by a private git repo | One process serves the UI; bundle export is optional |
| Free-text search impossible on the site (no query embedder) | Server holds the embedder; free-text semantic search is native |
| Ideas written by an external cloud routine with no repo-committed prompt | Idea cards are a first-class, versioned, tested pipeline stage |
| Eight fixed concept axes still required at runtime | Gone. Clusters are the only geometry |
| Silent failures (401s reported as success; posts lost) | Run health is data; failed calls never consume a post |

Target size: core ~2,500 lines Python, UI ~1,500 lines (templates + one map module). Original: ~8,700 lines `src/` + ~1,100 scripts + a separate site.

---

## 2. Principles carried over (the spirit)

These are not features. They are constraints every milestone is checked against. Each cites where it was earned in the original project so the reasoning survives.

**Judgment**
1. **Decomposed ratings, multiplied in code.** The LLM returns `content_quality`, `durability`, `opportunity` in [0,1]; code computes `signal = product`. A single self-reported scalar collapsed to 46% of observations at exactly 0.62 (exp 10); decomposition went from 7% to 67% distinct values.
2. **Skip is the default.** `{"skip": true}` is a first-class answer. Gate at `signal >= 0.20` (exp 04). `override` + mandatory `override_reason` bypasses the gate for things the ratings miss; since #86 only for an item rated at least 0.3 on every rating with a signal of at least a quarter of the gate, so override cannot empty it.
3. **The prompt is substrate.** TENETS are included in every intern call. "You are not trying to be interesting. You are trying to be honest." Summary must carry concrete detail: retrieval can only find what the intern wrote down (exp 14, Q7).
4. **Tolerant parsing over prompt coercion.** Strip fences, take the first balanced object; a fenced skip is a skip (exp 16: Haiku fences ~1/3 of replies despite instructions).
5. **Never score length or keywords** (exp 04).

**Audit**
6. **Every LLM call is recorded** — request, raw response, model, tokens, cost, outcome (`contributed | gated | skipped | parse_failed | llm_error`). Observations reference their call. Non-negotiable.
7. **Append-only is enforced, not conventional.** SQLite triggers reject UPDATE on library tables, and DELETE except inside the recorded purge path. Corrections are new rows with `supersedes`. The library never mints ids from content it has not seen. *(Amended 2026-09-27: observations and the raw third-party text behind them expire after a retention window and are compacted into rollups; each removal is recorded. The original forbade DELETE outright. See #71.)*
8. **Embed once at write time; record the model per row.** nomic-embed-text-v1.5, Matryoshka-truncated to 384-d and renormalised, `search_document:` / `search_query:` prefixes. Never mix models in one index; a model change is a new index, not a rewrite.
9. **A verbatim, non-LLM source excerpt and URL on every observation.**

**Measurement honesty**
10. **Permutation nulls, not convenient baselines.** (356x -> 1.4x, phase 2.5.) Check the null can fail before quoting it (exp 18).
11. **Report cluster quality in both spaces** — UMAP-10d silhouette looked like 0.40; native 384-d was 0.067 (exp 18).
12. **Cross-source means no single source > 70% of a cluster** (phase 3). Show source mix wherever a cluster is shown.
13. **Trajectories use shares, not counts,** with the artifact battery: proportional baseline, single-source dominance, source-mix shift (phase 4). In a library that only grows, raw-count slopes are always positive — the dispatch scorer's bug.
14. **Retrieval has a noise floor.** Off-topic queries scored 0.64–0.66 (exp 14); the UI labels weak matches as weak.
15. **Visuals say what they are.** The density layer is a KDE over 2-d coordinates, not a spectrum.

**Map**
16. **Re-cluster from scratch every snapshot.** Cluster ids are ephemeral; everything durable anchors on observation ids (exp 19).
17. **Identity across snapshots via raw-space centroids,** greedy match under cosine distance 0.15; never via UMAP coordinates.
18. **Pin determinism** (seeds, `n_init`), clamp parameters for tiny corpora, fingerprint the corpus (sha256 of sorted ids + model) on every derived artifact.

**Economics**
19. **Inference is a step function** (VISION). Tier 0: local embedding prefilter, free. Tier 1: cheap model judges. Tier 2: stronger model only for explain and idea cards, only on request or on a schedule with a budget.
20. **All spend goes through one metered client** — interns, naming, explain, ideas. Pause and budget are checked before every call, not once per run. Unknown pricing is an error, not $0.
21. **Posts over the per-run cap roll over, unmarked.** A post is marked seen only after a terminal outcome; `llm_error` never consumes a post.

**Shape**
22. **The library is shared; topics are lenses.** An observation belongs to the library, not to a topic. Cross-pollination between topics is the point (VISION, "Cross-pollination over depth").

---

## 3. Architecture

One Python package, one data directory, one process for the UI and scheduler, plus a CLI for everything.

```
                +--------------------------- afk serve -----------------------------+
 topics ------> | scout --> sources (approved)                                      |
                |                 |                                                 |
                |   scheduler --> tick: poll -> dedup/cap -> prefilter -> judge     |
                |                 |                              |                  |
                |                 v                              v                  |
                |            observations  <----- llm_calls (every call, raw)       |
                |                 |                                                 |
                |   scheduler --> snapshot: cluster -> lineage -> names/keywords    |
                |                 |                                                 |
                |   on request/scheduled --> explain, idea cards (+ verdicts)       |
                |                 |                                                 |
                |   HTTP: pages (list, search, map, clusters, ideas, topics, health) |
                |         JSON API mirroring the pages                              |
                +-------------------------------------------------------------------+
                                  data/  (SQLite file + model cache + exports)
```

### 3.1 Package layout

```
src/kranto/
  config.py        workspace config (YAML) + env for secrets
  store.py         SQLite schema, append-only triggers, queries, JSONL export
  llm.py           OpenAI-compatible client; metering, budget, pause, fail-fast
  embed.py         fastembed wrapper; document/query prefixes; in-memory matrix
  sources/         base.py + reddit.py, hackernews.py (Algolia search), rss.py
  scout.py         topic -> proposed sources -> validation
  intern.py        prefilter + judge prompt + parse + append
  tick.py          one ingest pass over all sources; run health
  map/             cluster.py, lineage.py, label.py (TF-IDF + LLM name), quality.py (nulls)
  ideate/          explain.py, select.py (candidate neighbourhoods), cards.py
  web/             app (Starlette/FastAPI), templates (Jinja + htmx), static/map.js
  cli.py           afk init | topics | sources | run | snapshot | serve | search | list | export | doctor
prompts/           versioned prompt files (intern, scout, name, explain, card); TENETS.md
```

### 3.2 Storage: SQLite, append-only by trigger

Why not JSONL (the original) or DuckDB (Bramble's plan): the requirement is now *listable* — filter, sort, paginate by topic/source/date/rating — which JSONL can't do without an index, and one file is simpler to back up and ship than thousands of run directories. At the target scale (<= 100k observations) vectors live in a numpy matrix in memory (100k x 384 x 4 bytes = 150 MB worst case; 10k = 15 MB), so SQLite's lack of array types does not matter. JSONL survives as an export (`afk export jsonl`) and as the audit-friendly interchange format.

Tables (all append-only unless marked):

| Table | Holds |
|---|---|
| `topics` | name, description, embedding, created_at. Edits are new versions |
| `sources` | kind, params, status (proposed/approved/retired), provenance (scout call id or manual) |
| `topic_sources` | many-to-many |
| `items_seen` | (source_id, item_id, outcome, ts) — the dedup set |
| `llm_calls` | request, raw response, model, prompt version, tokens, cost, outcome, error |
| `observations` | summary, why_it_matters, ratings, signal, override, kind, source url + excerpt, source_id, item_id, llm_call_id, embedding BLOB, embedding_model, supersedes |
| `runs` | tick start/end, per-source counts, errors, spend, status (ok/degraded/failed) |
| `snapshots` | fingerprint, params, quality metrics incl. null comparisons |
| `clusters`, `cluster_members` | per snapshot; lineage_id; name, keywords, source mix |
| `syntheses` | explain outputs: inputs (sorted ids), model, prompt version, text |
| `ideas` | idea cards: see 3.6 |
| `verdicts` | human grades on ideas/observations (append-only; latest wins in views) |
| `settings_kv` | mutable: pause flag, schedules (the one mutable table) |

### 3.3 Topic-first configuration

```
afk init ./my-kb
afk topics add "Small-scale solar and energy access in sub-Saharan Africa"
afk topics add "Local-first software and CRDTs"
afk serve            # review scout proposals in the UI, approve, done
```

**Scout** (one tier-2 call per topic, re-runnable): given the topic description and the list of supported source kinds, propose candidates (subreddits, HN Algolia queries, RSS/Atom URLs incl. arXiv, blogs, Substack, GitHub releases, Bluesky). Every proposal is then **validated by fetching it**: exists, recent volume, and median embedding similarity of recent items to the topic. The UI shows those numbers next to each proposal; the human approves. Hallucinated feeds die at validation, not in production.

**Prefilter** (tier 0): each polled item is embedded locally and compared with the embeddings of the topics its source serves. Below threshold it is recorded as `prefiltered` and skipped without an LLM call — *except* a fixed exploration fraction (default 5%) that goes to the intern anyway, so the library does not collapse onto the operator's phrasing of their topics. The exploration fraction is how cross-pollination survives a topic filter.

**Judge** (tier 1): the original intern prompt, adapted: TENETS, source name, the topic descriptions as *context for why this source is watched* (not as a relevance rating — the LLM judges substance, math judges relevance), the item, and the decomposed-rating schema. Stable prefix ordered for provider prompt caching.

### 3.4 LLM client

OpenAI-compatible chat completions (OpenRouter default; also works with OpenAI, Anthropic via OpenRouter, local Ollama/vLLM). Per-tier model config. Cost from provider-reported usage when available (OpenRouter `usage` accounting), otherwise from a pricing table; unpriced models refuse to run unless the config sets `allow_unpriced: true`. 401/403 abort the tick immediately and mark the run `failed`; 429/5xx, and a 200 with no content, no tokens and no cost, retry with backoff and jitter; nothing retried on 4xx other than 429, nor a reply a safety filter declined.

### 3.5 Map

Snapshot job (default daily, and on demand):
1. Load all current observation embeddings; fingerprint.
2. UMAP to 10-d (cosine, `n_neighbors=15`, seed pinned) -> k-means. k chosen from a small range by silhouette; the chosen k, silhouette in UMAP and native space, and each compared with a permutation null are stored on the snapshot and shown on the map page.
3. Separate 2-d UMAP for display only.
4. Lineage: match raw-space centroids to the previous snapshot (cosine distance <= 0.15), else new lineage.
5. Labels: TF-IDF keywords over summaries with prompt-vocabulary stopwords (the original keywords were dominated by "specific", "concrete", "signal"); one tier-1 naming call per *new or changed* lineage, cached by member-set hash.
6. Per-cluster: source mix, cross-source flag (max share <= 0.70), share trajectory across snapshots with artifact checks.

HDBSCAN and agglomerative-average are not offered (grab-bag / chaining at this scale, phase 3).

### 3.6 Ideation

**Explain / connect** (the example.com "summarize"): for a root observation + its top-k neighbours, or for a cluster's representative sample. Tier-2 call, prompt treats observation text as data, truncates inputs, cites by position; output validated (length, no markup). Cached in `syntheses` by `sha256(sorted ids + prompt version + model)`. Always user-triggered.

**Idea cards** (what the dispatch routine was trying to be, grounded in VISION's fitness function):
- *Selection* (math, no LLM): candidate neighbourhoods/clusters that are cross-source and either rising in share (passing artifact checks) or bridging two topics (members drawn from sources of different topics — the cross-pollination signal). Refuses to run if the corpus fingerprint is unchanged since the last card run; no stale re-framing of the same observations.
- *Generation* (tier 2): a card has — the pattern (a known thing that works elsewhere), where its preconditions now appear to hold, cited evidence (observation ids, rendered with source links and absolute dates), a falsifiable prediction with a date, the cheapest test, and five decomposed ratings mirroring VISION's fitness terms: `pattern_strength`, `precondition_presence`, `execution_gap`, `demand_validation`, `test_cheapness`. Code multiplies; cards sort by product.
- *Verification pass* (tier 1): every cited id must exist and the claim attached to it must be supported by that observation's text; unsupported citations are dropped and the card is marked accordingly. No card is shown with a citation that does not resolve.
- *Verdicts*: the reader can grade cards (useful / not / wrong). Stored append-only. v1 only collects them; weight search over the five terms (VISION's grading loop) is a later phase with data to learn from.

### 3.7 Web UI

Server-rendered (Jinja + htmx) plus one canvas module for the map. No Node toolchain needed to run or contribute.

| Page | What it does |
|---|---|
| Library | Paginated list; filter by topic, source, date, kind, signal; sort; full-text + semantic search box |
| Observation | Summary, why, ratings, excerpt, source link, the raw LLM call (audit is visible), top-k neighbours, explain |
| Map | 2-d scatter + contour density, zoom/pan, click -> popover (fixed at click, closes on pan) -> neighbours, pivot, explain; keyword filter dims non-matches; cluster labels at centroids |
| Clusters | Name, keywords, size, source mix, cross-source flag, share sparkline across snapshots, representative observations |
| Ideas | Cards with evidence, prediction, ratings; verdict buttons; filter by topic |
| Topics & sources | Add topic, review scout proposals with validation numbers, approve/retire, per-source health |
| Health | Runs, errors by class, spend this month vs budget, pause toggle |

UX decisions kept from example.com: popover first, side panel on request; explain is always an explicit action; heavy redraws pause during pan/zoom; optional data degrades silently; weak matches labelled weak.

`afk export bundle` writes the schema-versioned static bundle (manifest, observations, embeddings.bin, clusters) for anyone who wants a public read-only site; not required for normal use.

### 3.8 Running it

- `pip install kranto` / `uvx --from kranto afk`; one Dockerfile; `DATA_DIR` env var; secrets only from env.
- `afk serve` runs the scheduler in-process (ingest every 3h, snapshot daily by default). `afk run` / `afk snapshot` are one-shots for cron users; a file lock prevents overlap either way.
- `afk doctor`: checks key, model pricing, source reachability, budget headroom, embedder download.

---

## 4. Explicitly not in v1

- Federation / shared libraries between instances (Bramble v3).
- Push destinations (webhooks, email, Slack) — Bramble's push reframe. Designed-for (ideas and clusters are rows with timestamps) but not built.
- MCP server for agents to query the knowledge base. Strong v2 candidate; the JSON API makes it thin.
- Paid-API sources (X), HTML scrapers, Polymarket. The source interface allows them as plugins.
- Weight learning from verdicts.
- Auth / multi-user. Single operator, bind to localhost by default.
- Shipping any Reddit/HN-derived data in the repo. Example data is synthetic.

---

## 5. Milestones

Each milestone ends with tests green, the claim checked, and the issue closed. No milestone starts before the previous one closes.

| # | Milestone | Done when |
|---|---|---|
| M0 | Skeleton | Repo, Apache-2.0, CI, config, `store.py` with append-only triggers (tests prove UPDATE/DELETE fail), metered LLM client with budget/pause/fail-fast (tests with a fake server) |
| M1 | Ingest | reddit/hn/rss sources, prefilter, judge, `afk run`, `afk list`, `afk search`; run health; a dead key produces a `failed` run and consumes no posts (test) |
| M2 | Topics | `afk topics add`, scout + validation, approval flow in CLI |
| M3 | Browse | Web UI: library, observation, search, topics & sources, health |
| M4 | Map | Snapshot job, quality vs nulls, lineage, labels, map + clusters pages |
| M5 | Ideation | Explain, idea selection, cards with citation verification, verdicts |
| M6 | Release prep | README quickstart, 3 example topic packs, Docker, `DECISIONS.md` (the principles above with fuller citations), security pass, bundle export. Publishing is an operator decision |

**Validation claim for v1** (binary, in the original's style): *a new user stands up an instance on topics of their choosing in under 15 minutes, and after one week of unattended running, the idea cards contain at least one idea the user rates useful and could not have produced alone, with every cited claim traceable to its source.*

Cost is a measured result of M1, not a promise: the original ran ~25 sources on Haiku every 3h for roughly $48/month before any prefilter. The target for a default two-topic instance is under $10/month; M1 reports the real number.

---

## 6. Carrying over from the original repo

- **Code**: reference, not copied wholesale. Rewrite against these principles; lift specific pieces where they are already right (the intern prompt text, the tolerant parser, the Matryoshka embedding wrapper, the lineage matcher, the trajectory artifact checks).
- **Docs**: VISION and TENETS (TENETS is load-bearing — it is in the prompt). A new `DECISIONS.md` distils the principles with the experiment evidence summarised inline, since the private repo cannot be linked.
- **Data**: nothing committed. An importer (`afk import parallax-jsonl`) lets the operator seed a private instance from the old 7,951-observation library (same embedding model, so embeddings carry over).
- **Not carried**: concept axes, spectral layer, streamr, Sanity/dispatch plumbing, the example.com halo/click-count layer, host-specific deployment scripts, issue history.

---

## 7. Open decisions (operator)

1. **Name.** Resolved 2026-09-24: `kranto`, command `afk`.
2. **Default models.** Proposal: tier 1 `anthropic/claude-haiku-4-5` via OpenRouter; tier 2 a stronger model, configurable. Check current pricing at M1.
3. **Public demo instance.** Whether example.com/parallax is later re-pointed at an instance of this system (via bundle export).
4. **Publishing.** Making the repo public is a one-way door; decided at M6 after the security pass.

---

## 8. Changes while building (2026-09-24)

Recorded rather than edited into the sections above, so the plan and what
was built can both be read. Each change was a two-way door decided during
the milestone named.

- **No htmx (M3).** Plain HTML forms with POST-then-redirect cover every
  interaction on the list, detail, topics and health pages. The only
  JavaScript is the map. Nothing to vendor, nothing to build.
- **Reddit via its Atom feed (M1).** Reddit's JSON listing now returns 403 to
  unauthenticated clients; the Atom feed works but rate-limits hard (429 and
  403 seen during development). Reddit is documented as best-effort;
  optional OAuth is issue #10.
- **RSS 1.0 (RDF) support (M6).** Found while checking example feeds.
- **Topics are embedded as queries (M1).** A topic is a question asked of
  every item, so it takes nomic's `search_query:` prefix.
- **Prefilter threshold 0.50, not 0.55 (M1).** Calibrated on live feeds with
  the real embedding model: on-topic items 0.55-0.74, an off-topic front page
  median 0.505. The prefilter saves cost; it errs toward recall.
- **Default judge model slug corrected (M6).** `anthropic/claude-haiku-4-5`,
  inherited from Parallax, is not in OpenRouter's model list;
  `anthropic/claude-haiku-4.5` is. Found by `afk doctor`.
- **Parallax importer pulled forward (M3).** Needed a realistic library to
  build and measure the UI and map; the 7,113-observation Parallax library
  imports with identical embeddings (cosine 1.0 on a sample).
- **The structure null (M4)** is k-means on column-permuted embeddings. A
  label-shuffle null was rejected because any clustering beats it; the
  chosen null is tested to fail on noise.
- **k is chosen per snapshot (M4)** by silhouette in UMAP space over a range
  that grows with the library (k=14 on the Parallax library), instead of
  Parallax's fixed k=8.
- **Cross-source needs at least ten members (M4).** A six-member cluster from
  three sources passed the 70% rule on the real library; below ten, the
  label is sampling noise.
- **Map shading is banded KDE, not contour lines (M4).** Same information,
  no contouring code.
- **Display coordinates use percentile scaling (M4).** One six-point outlier
  cluster squashed the real map into a corner under min-max scaling.
- **Docker is verified in CI (M6)**, not locally: the build machine has no
  container runtime.
- **A `javascript:` link in a feed item would have rendered as a clickable
  href (M6).** Only http(s) URLs are stored, and templates re-check.
- **Watch status lives in `watch_events` (phase 2, #18; watches retired 2026-10-23, see DECISIONS).** The CHECK on
  `status_events.entity` admits only topics and sources, and a migration may
  not rebuild a table to widen it. A watch's default threshold is the 5th
  search result's score, but never below the weak-match line (0.70), so a
  watch on a topic the library barely covers does not fire on noise.
- **Movement on new arrivals, with bursts and significance (phase 2, #17).**
  Trajectory points gain `new_total`, `new_in_cluster`, `expected_new`,
  `burst`, `p_value` and `q_value`; "rising" moved from `excess > 0.005` to
  entering a Kleinberg burst with BH-corrected q < 0.05, cross-source. The
  per-source rates carry one pseudo-observation at the lineage's previous
  share, so a source not seen before is not infinitely surprising.
- **Aperture and cold start (phase 2, #19).** The scout proposes three
  wildcard sources per topic. They are recorded but not linked to the topic,
  so an approved wildcard skips the topic prefilter like a broad source;
  linked, the prefilter would discard nearly all of its items, which defeats
  the reason for proposing it. Wildcards are never auto-approved. Thin HN and
  RSS items that pass the prefilter get the linked page's main text
  (trafilatura, over the safe HTTP client) before judging. A source's first
  run takes up to `backfill_items` items once. Feed dates without a zone are
  read as UTC: Nature's feed made scout validation compare naive and aware
  datetimes.
- **Strike gate, delivery, heartbeat and grades (phase 2, #20).** Migration 10
  adds `strike_decisions` (one row per candidate, promoted or not, with the
  reason) and `grades`. Thresholds are per origin because the scores are on
  different scales: card 0.15 (product of five ratings), burst 0.99 (`1 - q`,
  so q < 0.01), watch 0.70 (cosine, the weak-match line; retired with watches). The weekly cap is a
  rolling seven days, not a calendar week, so it cannot be doubled across a
  boundary; candidates older than seven days when first gated are recorded as
  `stale`. A card's subject is its lineage, shared with bursts, so one theme
  cannot strike twice in the refractory period by arriving as both. Apprise
  targets may also come from `$KRANTO_NOTIFY_URLS`, so tokens can stay out of
  the YAML; targets are stored as scheme plus a hash, never the URL. Card
  verdicts are now written to `grades`; `verdicts` rows from before still
  count, and the latest across both wins.
- **Deep dives (#67, 2026-10-02).** The middle step of principle 19, between
  the tier-1 judge and tier-2 cards: a queued job that reads an observation's
  discussion, linked pages and named repositories and judges each with the
  tier-1 judge. Children are new observations linked by `observation_links`
  (migration 15), never edits; they are not counted as arrivals in movement
  (principle 13). Off by default, with its own daily budget slice, until the
  operator's blind grades show it is worth its cost.
- **Look before judging (#84, 2026-10-03).** Every item that passes the
  prefilter is screened by a short tier-1 call, then what is one step away is
  gathered (no model call, capped) and the judge reads both. The judge's
  call may keep gathered sources as children (`observation_links`, migration
  16 records the screen's call on `items_seen`). Deep dives are now queued
  only by hand. Within principle 19: the screen and the judge are both tier 1;
  gathering is free of model calls.
