# The watcher

the server is the half of Kranto that watches: it reads public sources for the topics you choose,
with cheap language-model "kranto" that read each new post, article or discussion and write down
the few that are worth remembering. What they write goes into an append-only library on your
machine, organised into a map of themes that emerge from the data, and it proposes ideas grounded
in what Kranto saw, with every claim linked back to its source.

This page is the watcher in detail. To install Kranto, start with [setup.md](setup.md).

## What you get

- **Evidence** (Watch › Evidence): every observation, filterable by topic, source, kind and
  signal, with free-text semantic search. Each observation shows the three
  ratings behind its signal, a verbatim excerpt, the source link, and the raw
  model response that produced it.
- **Map** (Watch › Map): the whole library clustered by meaning and drawn in 2-d. Click a
  point to see its nearest neighbours and walk from one to the next. The page
  states how well separated the clusters really are.
- **Themes** (under the map): each theme with its keywords, its source mix, whether
  independent sources converged on it, and how its share of the library has
  moved beyond what the mix of sources explains.
- **Ideas**: cards proposing a known pattern whose preconditions now appear
  to hold somewhere new, citing the observations that suggest it. Every
  citation is checked against the observation it cites. You grade them.
- **Look before judging**: each item that passes the topic filter is first
  screened by a short, lenient model call that drops clear junk (spam, empty
  pages, chatter far from every topic). For what passes, the kranto read what
  is one step away before they judge: the Hacker News discussion, the pages
  the post and its comments link to, the repositories it names. The judge sees
  the item with that material, and a linked source that holds up on its own
  becomes an observation of its own, linked to the item. A body that is only
  page chrome or a cookie-consent wall is recognised as no content.
- **Strikes, heartbeats and alarms**: the few things worth interrupting you
  for (a cross-source theme rising faster than its sources explain, a strong
  idea card) pass a gate with a threshold, a quiet period per
  subject and a weekly cap. A weekly heartbeat arrives even when nothing
  struck, saying what came closest, so quiet is never mistaken for broken.
  Any failed run raises an alarm. All three appear in an Atom feed at
  `/feed.xml`, and optionally by email, ntfy, Telegram and others.
- **Health** (Settings › System): runs, failures, spend against your monthly
  budget, where new observations come from, and a pause switch.

Everything runs locally: one Python process, one SQLite file. Nothing is sent
anywhere except the model calls you configure, the source fetches, and
messages to delivery targets you configure (none by default).

## The watcher alone

Kranto runs all of this for you. To run only the watcher, as `afk`, you need
Python 3.12 or newer, [uv](https://docs.astral.sh/uv/) and a key: the default is
[OpenRouter](https://openrouter.ai), which reports the cost of every call; an
Anthropic API key works too (`afk provider use anthropic --key-stdin`, which tests
the key and switches the watcher to the Claude API).

```
tag=$(gh release view -R iddv/kranto --json tagName --jq .tagName)
gh release download "$tag" -R iddv/kranto -p 'kranto-*.whl' -D "kranto-$tag"
uv tool install --python 3.12 "kranto-$tag"/kranto-*.whl
afk init ~/kranto
echo 'OPENROUTER_API_KEY=sk-or-...' > ~/kranto/.env
afk -w ~/kranto doctor
```

`afk doctor` checks the key, that the configured models exist, pricing, and
the embedding model. `afk provider show` says which keys it finds and `afk
provider test` tests one without spending anything. With an Anthropic key, `afk provider
replay` asks your newest screens and judges again through the Claude API three ways (no
cache, cache, cache with schema-enforced replies) and says whether turning on structured
outputs or low effort on screens keeps the verdicts; it spends at most `--max-usd` (default
$0.20) and changes nothing. (`structured` turns schemas on for the watcher's own calls; a post
writer's schema is always sent on the Claude API and the Claude Code login.) The embedding model (nomic-embed-text-v1.5, about 500MB)
downloads on first use and runs on your CPU. Set `KRANTO_HOME=~/kranto` to drop
the `-w` flag. (In a kranto install, `afk` finds the kranto home by itself.)

Then tell Kranto what to watch. Either describe a topic and let a scout
propose sources:

```
afk -w ~/kranto topics add "Local-first software" \
  "Software that keeps working offline and keeps data on the user's devices: CRDTs, sync engines, and the products built on them."
```

The scout makes one model call, test-fetches every source it proposes, and
shows how many items each has and how closely they match your topic. Nothing
is watched until you approve it (`afk sources approve ID`, or on the Topics
page); add `--approve` to accept the proposals that match well. The scout
also proposes three wildcards: sources unrelated to the topic that are likely
to carry the same patterns. They are never auto-approved; an approved
wildcard is watched without the topic prefilter.

Or start from a pack of hand-picked sources, with no model call (the packs are in this
repository's `examples/packs/`):

```
afk -w ~/kranto pack examples/packs/local-first.yaml
```

`examples/packs/broad.yaml` adds general feeds linked to no topic (the broad
lane). Their items skip the prefilter, which widens what the library sees and
costs more judge calls; the file says how many at most.

Then start it:

```
afk -w ~/kranto serve
```

and open http://127.0.0.1:8765. The UI is Kranto's (the page's pages at `/brb/`; the
old addresses such as `/library` redirect there); the server alone, without the page, is
not a supported way to run and its pages only show how to install Kranto
([setup.md](setup.md), step 2). The server fetches every 3 hours (a new
source's first run reaches further back), rebuilds the map daily once there
are at least 30 observations, compacts observations past their retention age
into weekly rollups after each map, proposes ideas after each new map, and
sends a heartbeat weekly. Empty pages say what they are waiting for. In Kranto, finishing
Welcome starts the first read; at any time, `afk run` reads now. If you prefer cron, run
`afk serve --no-scheduler` and schedule `afk run`, `afk snapshot`, `afk compact`,
`afk ideas`, `afk heartbeat` and `afk strikes --run` yourself; overlapping runs are
prevented with a lock.

To be notified outside the browser, install the extra and name the targets
(see the [Apprise URL formats](https://github.com/caronc/apprise/wiki)):

```
uv tool install --force --python 3.12 "kranto[notify] @ $(ls "$PWD/kranto-$tag"/kranto-*.whl)"
echo 'KRANTO_NOTIFY_URLS=ntfy://ntfy.sh/your-topic' >> ~/kranto/.env
```

(Kranto includes the notify extra.)

### Docker

The image runs the watcher alone. It is untested since 2026-10-08: CI's `docker` job runs
only when dispatched, and nobody has built the image since.

```
docker build -t kranto .
docker run -d --name kranto -p 127.0.0.1:8765:8765 -v kranto:/data \
  -e OPENROUTER_API_KEY=sk-or-... kranto
```

The image keeps the config, the library and the model cache in `/data`, and
creates a workspace there on first start. Add topics from the web UI, or run
commands in the container with `docker exec kranto afk ...`.

## Sources

| Kind | Value | Notes |
|---|---|---|
| `rss` | a feed URL | RSS 2.0, RSS 1.0 and Atom. Covers blogs, newsletters, arXiv listings, GitHub releases, YouTube channels, Bluesky profiles. |
| `hackernews` | `front`, `new`, `show`, `ask`, or a search query | Via the Algolia API. For items that reach the model, the top comments are included. |
| `reddit` | a subreddit name | With your own Reddit app connected (Settings › Accounts › Reddit: its client id, secret and refresh token), through Reddit's API as you: new posts with their scores, comment counts and the top comments of the 5 most scored, one request a second, removed posts left out. Without it, the public Atom feed, at most one request a minute, until Reddit stops it on 13 Nov 2026. **Reddit (via search)** in the catalog is a `websearch` source on `reddit.com`: no key. Read Reddit's [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy) and [RESPONSIBLE_USE.md](../RESPONSIBLE_USE.md) before adding one; the example packs include none. |

The `edgar` and `browser` kinds left Kranto; what they kept stays in the library (see
[archive.md](archive.md)).

The scout also proposes a few **wildcards**: sources unrelated to your topic
that are likely to carry the same patterns, so the library does not narrow to
your own wording. They are never approved automatically. Sources with no topic
at all form a **broad lane** that skips the topic filter (see
`examples/packs/broad.yaml`). Given a website instead of a feed, the scout
finds the site's feed. For link posts and very short feed items, the linked
page's main text is fetched and judged instead of the headline.

Source URLs are checked before every fetch: private, loopback and link-local
addresses are refused, because scout-proposed URLs come from a model.

## Costs and safety

- Every model call goes through one metered client. The pause switch and the
  monthly budget (`budget.monthly_usd`, none by default; set one under Settings ›
  Spend) are checked before
  each call, not once per run.
- A model whose cost cannot be determined is refused rather than counted as
  free.
- A rejected key, exhausted credit or missing model stops the run
  immediately and marks it failed on the Health page. Items Kranto had not
  finished are not marked as seen, so nothing is lost.
- Most items never reach a model: each is first compared with your topics
  using the local embedding model, and only similar ones (plus a small random
  sample, so the library does not narrow onto your wording) are judged.
- Fetching full text for thin link posts adds roughly 55% input tokens to the
  items it applies to (`ingest.fetch_full_text`, on by default).
- Looking before judging (`look.enabled`, on by default) is two model calls
  per item that passes the topic filter, a short screen and the judge, and
  the judge reads up to 2,000 characters of each gathered source. Measured
  with Haiku 4.5 (2026-10-03): $0.0079 per item on 30 items of the
  local-first library, $0.0084 per item on 15 items of the lab-tools pack;
  the judge alone was about $0.0035 per item before. Gathering is capped per
  item (2 pages, 1 repository, 30 seconds) and per run (40 items, 10 GitHub
  lookups); `look.enabled: false` goes back to one judge call per item.
- Spend passing 80% of the budget, and running out, each raise an alarm.

Costs depend on your sources and models; the Health page shows actual spend
per run. The tier-1 model (`llm.models.judge`) judges items; the tier-2 model
(`llm.models.reason`) scouts sources, explains clusters and writes idea
cards.

The web UI binds to 127.0.0.1 by default. Writes need a kranto token (the page
signs in once through the link `kranto open` prints); reads do not, so anyone
who can reach the port can read the library. See [SECURITY.md](../SECURITY.md).

## Commands

```
afk init DIR                 create a workspace
afk doctor                   check key, models, pricing, sources, embedder
afk topics add NAME DESC     add a topic and scout sources (--no-scout, --approve)
afk topics scout ID          propose more sources for a topic
afk topics edit ID           a new --name or --description (the id is kept)
afk topics archive ID        not read, off the lists, evidence kept (--restore)
afk sources add KIND VALUE   add a source by hand (--topic ID)
afk sources list|approve|retire
afk sources retention ID DAYS  keep one source's observations DAYS (0: forever, or default)
afk pack FILE                add topics and sources from a pack
afk run                      one ingest pass
afk snapshot                 rebuild the map
afk compact                  roll up and remove observations past their retention age
afk ideas                    idea cards from the latest map (list, grade ID useful|not_useful,
                             card LINEAGE: one card on that theme now)
afk messages                 strikes, heartbeats and alarms
afk strikes [-v] [--run]     candidates and why each was or was not sent
afk heartbeat [--now]        send the weekly heartbeat
afk grade TARGET ID GRADE    a card or evidence: grade idea 12 useful, grade observation 40
                             not_useful (skip clears); other targets are not graded
afk list | search QUERY | show ID | explain ID
afk pause [REASON] | resume
afk serve                    JSON API, scheduler, and the kranto UI at /brb/
afk export TABLE -o FILE     JSONL export of any table
afk export bundle -o DIR     static copy of the latest map
afk import parallax PATH     import a Parallax library
```

## Data

The library is append-only: SQLite triggers reject updates on every library
table, and deletes on all of them except through one recorded path. A
correction is a new row that points at the one it replaces. The only mutable
state is a handful of settings such as the pause flag. `afk export` writes any
table as JSONL.

Observations are kept for 90 days by default (`retention` in `kranto.yaml`,
per source kind or per source). After that they are compacted: each week's
expired observations are clustered, each cluster is kept as a rollup (a name,
a short summary, keywords, source mix and a few links), and the observations
and the model calls holding their source text are removed. Every removal is
recorded in the `purges` table. The map's trends and idea cards survive it.

Observations are model-written summaries of third-party content with links
back to it. Think about the terms of the sources you watch before you publish
a library or a bundle. [RESPONSIBLE_USE.md](../RESPONSIBLE_USE.md) covers source
terms, personal data, retention and what is left to you.
