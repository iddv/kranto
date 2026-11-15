# DECISIONS

Why the server works the way it does. Most of these were learned the hard way
in Parallax, the experiment the server re-implements: about six months, twenty
numbered experiments, four watchers growing to sixty-six sources, and a
library of roughly eight thousand observations. Each entry says what we do,
what went wrong without it, and where to find it in the code. If you want to
change one, the evidence is the thing to argue with.

## Judging

**The model rates three things; code multiplies them.** The judge returns
`content_quality`, `durability` and `opportunity`, each in [0, 1]; the
signal is their product. Asked for a single score, the model collapsed: in
one run 46% of observations scored exactly 0.62 and only about ten distinct
values appeared across 251 observations, which made the score useless for
ranking. Decomposed, distinct values rose from 7% to 67% of observations and
the average moved closer to a human's grades without any correction factor.
`src/kranto/intern.py`, `prompts/judge.md`.

**Skip is the default answer.** Most items should produce nothing, and
`{"skip": true}` is a first-class reply. An item is kept when its signal
reaches 0.20, or when the model sets `override` and says why; an override
without a reason is ignored. The threshold came from a calibration set; the
override exists because a product of ratings cannot express "this is
strange and I cannot say why". Since #86 the override is bounded in code and
kept for one narrow case; see "Override is narrow" below.

**The prompt is part of the data.** The summary must carry concrete detail
because the library can only ever find what Kranto wrote down: retrieval
tests in Parallax failed on concepts that were in the source but not in the
summary. TENETS is included in every call. The line "You are not trying to be
interesting. You are trying to be honest." stays.

**Parse tolerantly.** Models ignore "no markdown fences" about a third of the
time; in Parallax, 51% of Haiku's recorded parse failures were a fenced
`{"skip": true}`, a correct answer miscounted. The parser strips fences and
takes the first balanced JSON object.

**Topics are context, not a rating.** The judge is told why a source is
watched, and told not to rate an item higher for matching a topic or lower
for missing one. Relevance is measured separately with embeddings, so a
substantive off-topic item can still enter the library. That is where
cross-pollination comes from.

## Auditability

**Every model call is recorded**: request, raw response, model, prompt
version, tokens, cost, outcome. Parallax threw raw responses away at first
and could not investigate why scores clustered; the investigation that
found the 0.62 collapse only became possible once responses were kept.
Observations point at their call. `llm_calls` in `src/kranto/store.py`.

**Append-only is enforced by the database.** Triggers reject UPDATE on every
library table, and DELETE except inside the recorded purge path. Changes of
mind are new rows with `supersedes`; changes of status are new
`status_events`. The only mutable table holds settings such as the pause
flag.

**Retention and compaction (2026-09-27).** Until this date DELETE was
forbidden outright and the library kept every observation, with its verbatim
excerpt and the full model request behind it, forever. Two things changed
that. Parallax's library "got big and slow really quick" (the operator's
words), and keeping third-party text indefinitely conflicts with sources'
terms (Reddit's Responsible Builder Policy, read on 2026-09-27) and with
people's ability to delete what they wrote. The operator decided: raw text
and the observations built on it are kept for a retention window (default
90 days, per source kind and per source overridable); when the window
passes, the observations are clustered into rollups (categories, summaries,
counts, source mix, a few representative URLs, a centroid embedding) and
removed together with the model calls that hold their raw text. Deletion is
still never silent: it happens only while a purge token exists, inside one
transaction, and writes a purge record. Nothing is edited in place. What
persists is the shape of what was seen. Design and implementation: #71.

**Prompt versions are content hashes**, so an edited prompt can never share a
version with its predecessor. `src/kranto/prompts/__init__.py`.

**Embed once, when writing, and record the model on every row.** The
embedding is nomic-embed-text-v1.5 truncated to 384 dimensions and
renormalised, with `search_document:` for stored text and `search_query:`
for queries and topics. Mixing the prefixes degrades retrieval without any
error. Parallax embeddings are bit-for-bit compatible, which is why
`afk import parallax` works.

**A verbatim excerpt and the source URL on every observation**, not only the
model's summary, so a reader can check the summary against the source. Only
http(s) URLs are stored or rendered.

## Measuring honestly

**Compare against a null that can fail.** Parallax's first headline result
was a signal-to-noise ratio of 356x on one theme. Against a proper
permutation null it was 1.4x. The theme was real; the number was not. A
null that everything beats is no null: shuffling cluster labels is beaten by
any clustering at all, so the server's null clusters structure-free data (each
embedding dimension permuted independently) and a test checks that it fails
on noise. `src/kranto/map/compute.py`.

**Report cluster quality in both spaces.** Clusters are found in a 10-d UMAP
projection, where they look well separated (silhouette 0.46 on the Parallax
library), but in the original embedding space they overlap heavily (0.046).
Both numbers are shown on the map page, next to the null (0.0024). They
are real structure with soft edges, and the page says so.

**Cross-source means no single source supplies more than 70% of a
cluster**, and a cluster needs at least ten members before the label means
anything. With the looser rule ("at least two sources"), five of eight
Parallax clusters qualified; with this one, three did.

**Movement is measured in shares, against what the sources explain.** In a
library that only grows, every cluster's count goes up, so a slope on counts
is always positive; Parallax's article generator made exactly this mistake.
Each cluster's share is compared with the share it would have if every
source had kept contributing to it at its previous rate; only the excess is
treated as movement. A theme that grows only because its one dominant
source posted more shows no excess.

**Movement is measured on new arrivals, tested, and smoothed (phase 2).**
The share comparison above dilutes new motion by the size of the library
and moves whenever old points are reassigned by re-clustering. Each
snapshot now also records, per lineage, how many of the observations added
since the previous snapshot landed in it, against how many the previous
per-source rates predict. A one-sided binomial test with Benjamini-Hochberg
correction across lineages says whether the difference is more than chance,
and Kleinberg's two-state burst model (2002, section 4) says whether the
lineage has moved into a higher arrival rate, with a cost for entering that
state so one lucky snapshot does not count. "Rising" means entering a burst,
significantly, cross-source; it feeds idea cards and strike candidates. The
share excess stays on the clusters page. `src/kranto/map/bursts.py`.

**Search fuses meaning and words; similarity only flags off-topic queries
.** Search ranks by cosine similarity and by SQLite FTS5/BM25, fused by
reciprocal rank. On 41 graded queries over the Parallax import (pooled
grading, 767 judgments, one grader) this raised P@10 from 0.50 to 0.59
(lenient; strict 0.40 to 0.47) and P@5 from 0.57 to 0.65, with top-1
relevance slightly lower (0.70 to 0.66 lenient). Cosine similarity is not a
relevance score: 54% of relevant items scored below 0.70, and 8 of 41
well-covered queries had a best match below 0.70, which the old 0.70
"no strong matches" line told users meant the library had seen little. It
does separate unrelated queries: their best match was 0.53-0.59 here and
0.64-0.66 in Parallax (exp 14), against 0.68 or more for every covered
subject. So only a best match below 0.65 is flagged, worded as "may not
cover this". The Library page drops results more than 0.15 below the
closest one and pages the rest 20 at a time. Watches default to the 5th
closest observation's similarity floored at 0.65, and the gate's
`min_watch_score` default is 0.65: at 0.70, 19 of 41 queries would have
been floored above their own 5th match.

**One voice counts once: stories and origins (#35, 2026-10-02).** A launch,
a crosspost or a repost put the same text in front of Kranto several
times, and each copy became an independent observation: one party speaking
several times read as several voices, inflated clusters, read as a rising
topic and passed the cross-source rule. Near-duplicates are found on the
item's own text before the judge sees it (title and the first 1,000
characters of body, word 3-shingles, a 128-value MinHash signature), not on
the observation embedding: the judge rewords the same item differently each
time, and a cosine of 0.95 on stored embeddings reached only 57% of
same-URL pairs and 44% of crossposts. On Parallax's 35,118 judged
items, 138 candidate pairs were labelled (by the implementing agent; the
operator has not graded them). Across sources, pairs at a similarity of 0.5
or more were the same story in 99% of the weighted sample; within one
source, pairs below 0.9 were mostly templated posts (status bots,
newsletters, changelogs) and pairs at 0.9 or more were reposts within days
or recurring threads a week or more apart. So: at 0.9 or more (across
sources, or within a source inside three days) the copy is consumed as
`near_duplicate` without a model call. The judge's own outcomes support
this: on pairs at 0.9 or more, the second copy was kept when the first was
not in 5.2% of pairs, the same rate as the judge disagreeing with itself on
the same URL (5.3%). From 0.5 to 0.9 across sources the copy is judged (an
edited crosspost can carry new detail) and linked to the earlier item's
story. Movement, bursts, idea evidence and the cross-source rule count
distinct stories. Templated feeds (Polymarket: different markets at
similarity 1.0) are detected by how many of a source's items look like
three or more of its others (26% for Polymarket, at most 1% for every other
Parallax source) and never matched with themselves; a source's own items are
compared only once it has 20 in the window. Origins are registrable domains
(public suffix list): no origin may supply more than 70% of a cross-source
cluster or of a rising lineage's new stories. The check against a null
compares the match rate with that of column-permuted signatures, which keep
shared boilerplate and break identity; it fails on boilerplate-dominated
text in tests and did not fire on the real data measured.
`src/kranto/stories.py`, `src/kranto/textsig.py`.

**Visuals say what they are.** The map's shading is a kernel density
estimate of the 2-d positions, and the page says it adds nothing the points
do not show.

## The map

**Re-cluster from scratch every time, and anchor on observations.** Cluster
numbers mean nothing outside one map. Lineages carry identity across maps,
matched on centroids in the original space, because UMAP coordinates move
whenever a single row changes. A split or merge shows up as an end and a
start, never as a silently continued identity.

**Refuse to redo work on unchanged data.** A map is not rebuilt when the
library has not changed, and idea cards are not regenerated from the same
map or the same evidence. Parallax kept writing weekly articles from a
library that had stopped growing and described three-month-old posts as
"last week".

**Choose methods by what a reader can use.** HDBSCAN, tried in Parallax,
put 335 of 477 observations into one cluster and a quarter into noise;
average-linkage clustering chained everything together. UMAP plus k-means
gave groups a person recognised. Fixed "concept axes" written in advance
were retired: they could only confirm themes someone had already named.

## Ideas

**Selection is arithmetic; writing is the model's job.** Candidates come
from the map (rising beyond what the sources explain, bridging topics,
cross-source), never from asking a model what is interesting. The card
prompt is built on the idea that recombination beats invention: a known
pattern whose preconditions now hold somewhere new.

**Citations are checked, and failures are kept.** A cited observation must
have been given to the model, and a second call checks each claim against
the text it cites. Dropped claims are stored with the reason; a card with
fewer than two supported citations is hidden, not deleted.

**Cards carry the five fitness terms from VISION** (pattern strength,
preconditions present, execution gap, validated demand, cheapness of a test)
as ratings multiplied in code, and a person grades them. The grades are the
data a later weight search needs; the server does not learn from them yet.

## Strikes

**Rare by construction, and every silence has a reason.** VISION: "an intern
that strikes weekly is broken". A strike needs a score over its origin's
absolute threshold, no strike about the same subject in the last seven days,
fewer than two strikes in the last seven days overall, and at least two map
snapshots behind the library (the rules of Huginn's peak detector:
threshold, refractory period, warm-up). Every candidate gets exactly one
recorded decision with its reason, so "why did it not tell me" has an
answer. `src/kranto/gate.py`.

**A heartbeat every week, even when nothing happened.** Parallax's dead key
looked like a quiet fleet for three months. The heartbeat says what ran,
what failed, what it cost and which candidates came closest, so quiet can be
told apart from broken. `src/kranto/heartbeat.py`.

**Nothing leaves the machine until a target is configured.** Delivery is an
optional extra (Apprise). Each attempt is a row; one failing target never
stops the others or the job. `src/kranto/delivery.py`.

**Grades are the training data, including what was missed.** Strikes are
graded worth waking or not; observations and clusters can be marked "missed:
should have told me". Append-only, latest wins. Nothing learns from them yet.
`src/kranto/grades.py`.

## Operations

**Stop on fatal errors; never consume what was not finished.** In June 2026
Parallax's API key stopped working. Every call returned 401 for three
months, the runner reported every run as a success, and each post it
touched was marked as seen and lost. In the server, 401, 402, 403 and 404 stop
the run and mark it failed, transient errors leave items for the next run,
and an item is marked seen only after a real outcome.

**All spend goes through one gate.** Pause and budget are checked before every
call. Parallax checked the budget once per run, let cluster naming bypass
it, and priced unknown models at $0, so the budget could not trip.

**Cheap first.** A local embedding comparison discards items unrelated to
every topic before any model is called; a fixed 5% of the rest are judged
anyway so the library does not shrink onto the wording of your topics. On
calibration data, on-topic items scored 0.55 to 0.74 and an off-topic front
page scored a median of 0.505, so the default threshold is 0.50: the
prefilter is there to save money, not to make judgements.

**Deep dives are a middle step, queued, and off until graded (#67, 2026-10-02).**
Grading the #63 benchmark, the operator scored several observations below what
their material deserved because the value was one step away from the post: in
the discussion, in the sources it linked, in the project it described. VISION's
step function had a cheap stage for every item and a strong stage only for
idea cards. A deep dive is the stage between: for an observation that scored
high, read the thread, the linked pages and the named repositories, and judge
each with the same tier-1 judge as an item of its own. What it keeps are new
observations with their own URL and excerpt, linked to the parent by a row,
so the library gains datapoints rather than a longer summary and nothing is
edited. It is queued, not inline: ingest appends one row and moves on, a
separate job works the queue within its own daily slice, and an interrupted
dive resumes from `items_seen`. Children are not counted as arrivals on the
map: they follow their parent into its neighbourhood, and one item's thread
would otherwise read as a theme gaining ground. Judge overrides do not queue a
dive: on the #63 benchmark library 172 of 546 observations (31%) carried one.
It ships off because its value is not yet measured; the operator's blind
grades of parent alone against parent plus children decide.
`src/kranto/deepdive.py`, `src/kranto/sources/gather.py`.

**Look before judging (#84, 2026-10-03).** The operator's grades changed the
picture twice. On #67 the gathered material added value in 4 of 5 pairs; on
#47 (30 items) the judge kept 4 of the operator's 14 keeps, and the misses were
thin posts whose substance was one link away (small Show HN tools, podcast
episodes with practitioners) plus two capture failures judged as if they were
the item (GitHub page chrome, a Google consent wall). A signal trigger reads
more only for items the judge already rates high, which is the wrong
population. So every item that passes the prefilter is now screened, gathered
for, then judged:

- *Screen.* A short tier-1 call with its own prompt (`prompts/screen.md`,
  versioned like every prompt; the TENETS are in it, as in every intern call)
  asks whether the item is potentially worth a closer look, and is told that
  recall matters more than precision. It sees the item cut short (1,500
  characters, three comments). Only an explicit `"pass": false` drops an
  item; an unreadable reply passes it on. A drop is the outcome
  `screened_out`, with the screen's call as its `llm_call_id`, whose response
  holds the reason. It counts as judged: a copy of it from another source is
  a duplicate or near-duplicate, as for a skip. A separate prompt rather than
  a mode of the judge, because the two questions differ ("worth a look?"
  against "worth keeping, and how much?") and a screen that carried the
  judge's whole rubric would cost the judge's input tokens on every item.
- *Look.* For a Hacker News, RSS or Reddit item that passes: the #81
  gatherers, no model call, through the safe HTTP client, bounded per item
  (`look.max_links` pages kept of at most twice as many fetched,
  `look.max_repos` repositories, `look.item_seconds` of wall clock shared by
  every request, each cut off at `look.request_seconds`) and per run
  (`look.max_per_run` items, `look.max_repo_lookups` GitHub lookups). Items
  past the run's cap are judged without gathering and counted; nothing fails
  for want of gathering. Pages the library has judged are not read again.
- *Judge.* One call sees the item and the gathered sources, numbered. When it
  keeps the item it may name gathered sources that hold up on their own, each
  with its own summary and three ratings, multiplied and gated in code like
  the item's. They become child observations (`admitted_by = 'gathered'`)
  from the same call, linked by `observation_links` in the item's own
  transaction. One call rather than a call per child (as #81 did): the judge
  sees the item and its sources together, so it can leave out a source that
  only restates the item (two of #67's seven children did), and the cost is
  one call per item rather than one per source. This changes invariant 13's
  wording, not its point: children are still observations of their own,
  with their own URL and excerpt, never edits of the parent. Children only
  come with a kept item. Gathered sources the judge does not name leave no
  row, so they can still arrive later as items of their own.
- *Children elsewhere.* They were matched against watches like any new
  observation until watches were retired (2026-10-23), are the
  parent's story in every count, and are not arrivals in movement. They
  expire with the parent's source.
- *No content.* A body that is only page chrome (GitHub's session banners), a
  cookie-consent wall or a bot check is blanked before any model reads it and
  the judge is told (`capture_note`); full text then gets its chance.
- *The screen's call* is recorded on the item's `items_seen` row
  (`screen_call_id`, migration 16), whatever the outcome, so it expires with
  the item at its source's retention age.

The judge prompt also keeps practitioner interviews and new tools in the
topics' field, by override with a reason when the item's text only describes
something richer (an episode's audio, a project's code); an ordinary app whose
only link to the topics is a label is not kept for that label. Measured on the
#47 sample, with the caveat that the prompt was revised twice on those same
30 items: agreement with the operator 16 of 30 (14 of 20 without Ink &
Switch), against 10 and 12 of 30 before, at $0.0079 per item against about
$0.0035. The same prompt sets `override` far more often than it needs to:
on 14 of the 25 items it judged in that run and 5 of the 12 it kept on the
lab-tools pack, though it changed the decision for only 3 (podcast episodes
below the gate). `override` is shown in the UI and used nowhere else.
Numbers and the per-version table are on #84.
`src/kranto/look.py`, `src/kranto/intern.py`, `src/kranto/prompts/screen.md`.

**Override is narrow, and bounded in code (#86, 2026-10-03).** The #84 judge
set `override` on 14 of 25 replies, and override kept an item whatever its
signal, so the gate could be emptied by it. Operator decision: tighten. The
judge prompt now gives override one case (an interview with named
practitioners about a named system, or a new tool whose approach shows, rated
modestly only because the text describes something richer) and an example
that does not qualify (a detailed write-up already rated 0.85, 0.8, 0.75).
Code backs it: an override lifts an item over the gate only when every rating
is at least 0.3 and the signal is at least a quarter of the threshold (0.05 at
0.20); otherwise it is refused and the item is gated
(`intern.override_effect`: `unneeded`, `lifted`, `refused`). Children get the
same rule. Why these bounds: a rating below 0.3 is the judge saying the item
is empty, unverifiable or of no consequence, which no reason makes up for;
the three #47 items the operator wanted kept by override (podcast episodes)
were rated 0.3 to 0.8 with signals of 0.084 to 0.168, so both bounds keep
them; and the floor follows the threshold if the threshold moves. Topicality
is not a rating, so "off-topic" cannot be a code check; the screen covers it.
Every ingest run's summary counts replies with ratings, overrides set, lifted
and refused, and the rate (`overrides`), shown on the Health page and by
`afk run`, so a rising rate is visible.

**Sponsors and ads are a hard no (#86, 2026-10-03).** On #84 a sponsor's
homepage (PowerSync, thanked in a localfirst.fm episode's show notes) was
kept as a child observation. Operator decision: sponsor links and ads are
rejected instantly, without a model call wherever that can be decided
deterministically.

- *Gathering* never follows a link in sponsor or advertising context
  (`sources/sponsors.py`). Detection is structural rather than a host list:
  a link is out when the innermost block around it says so ("Thank you to X
  and Y for supporting the podcast", "Sponsored by", "brought to you by",
  "promo code", "use code SAVE20", "affiliate links"), when it sits under a
  heading or a bare label such as "Sponsors", or in an element whose class or
  id names an ad or sponsor slot. Blocks over 600 characters are prose, not a
  sponsor line, so an article about sponsorship keeps its links. A URL in
  sponsor context anywhere on a page is left out everywhere on that page,
  so a sponsor thanked at the end is not followed from a list higher up.
  A short list of ad-network and affiliate-redirect hosts, and query
  parameters only affiliate or paid links carry (`aff_id`,
  `utm_medium=sponsored`, an Amazon `tag`), covers what structure cannot.
  This holds for HN post text and comments, linked articles and deep dives.
- *Items* whose title marks them as ads ("[Sponsor] ...", "Sponsored: ...")
  or that link to an ad or affiliate URL are consumed as `sponsored`, a new
  terminal outcome (no CHECK constraint on `items_seen.outcome`, so no
  migration), before the prefilter and with no model call. Ads that do not
  say so are the screen's: its prompt names adverts, sponsored and paid
  posts, promo-code and affiliate posts and vendors' promotional landing
  pages as spam, always dropped whatever their topic. The judge prompt says
  never to keep an ad, nor a sponsor's or vendor's page reached through a
  sponsor mention as a child.
- *Recorded*: per source, `sponsored` items, `sponsor_links` left out of
  gathering and `screened_spam` drops, with up to 10 reasons per source
  (`sponsor_reasons`, such as "link https://... : next to 'for supporting'")
  in the run's summary; deep dives keep the same line in their notes.

Screen strictness is unchanged (operator: stricter is generally better).
Measurements are on #86. `src/kranto/sources/sponsors.py`,
`src/kranto/intern.py`, `src/kranto/prompts/judge.md`,
`src/kranto/prompts/screen.md`.

**Failures are data.** Runs, per-source fetch errors and model errors by
class are tables, shown on the Health page, not lines in a log nobody reads.
A source that fails to fetch raises an error; it never returns an empty list
that looks like a quiet day.

**Memory is bounded and capped (MEM, 2026-10-20).** A stranger's first read grew
the server to 7.6 GB and, with an `afk run` beside it, took a shared 16 GB machine
down for eight hours. The embedder had embedded a first backfill's 40 texts (about
630 tokens each) in one model run, whose working memory grows with the batch times
the square of its longest text, and onnxruntime's CPU arena kept the peak for the
life of the process. It now embeds shortest first in runs of at most four under a
size budget, one run at a time, with the arena and weight prepacking off: the same
read peaks at 1.2 GB, vectors equal to 1e-7 (`src/kranto/embed.py`,
`tests/test_memory.py`). Defence in depth, because the next growth will be
somewhere else: `kranto.service` carries `MemoryHigh`/`MemoryMax` (4 GiB or half the
machine, a drop-in overrides) with `OOMPolicy=continue`; runs outside it put
themselves in a capped scope; past 80% of the cap the log says so once and
Settings › System shows it (`src/kranto/memory.py`, [memory.md](../memory.md)).

**Watches are retired (WT, 2026-10-23).** The owner: "I also don't understand why watches
exist. They should be removed completely; they serve no purpose." A watch was a saved search
checked against every new observation during ingest (`watches.Matcher`, one strike candidate
per watch per run, origin `watch`). Live had none (0 watches, 0 watch candidates, 0 watch
strikes since the feature shipped), and nothing else read them: the loop, the ideas job and
the cub SDK never did. Removed: `watches.py`, the matcher in `tick.run_ingest` (and the run
summary's `watch_candidates`), the gate's `watch` origin, `afk watch`, `/api/watches*`, the old
`/watches` form posts (the page address opens Watch), and every page and word in Kranto
UI. Kept for one release, unread and unwritten, so a rollback finds its rows: the tables
`watches` and `watch_events`, migration 37's `watches.topic_id`, the setting
`watch_matches_written_through`, and `strike.min_watch_score` (read so an older
`kranto.yaml` still loads, used by nothing). The next release drops them in a migration of
its own. The radar's per-topic "watch for trends" switch is a different thing and stays:
Invest keeps its words for it, and a topic's Edit sheet (under Watch, where watches were)
calls it Follow for trends.
