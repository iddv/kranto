# Responsible use

This page says what the server is for, what it does to avoid collecting
personal data, how long it keeps what it reads, and what is left to the
person running it. It describes the code as it is; it is not a legal
promise, and it does not make any use of the server compliant on its own.

## What the server is for

the server is a personal app that anyone can run from source. It watches public
sources (feeds, Hacker News, and similar) for topics the person running it
chooses, keeps short model-written observations about what it reads, and
organises them into trends. It is meant to keep trends, not people: it is not
a tool for tracking, profiling or contacting individuals, and should not be
used as one.

## Respect each source's terms

Every source has its own terms, and they apply to you when the server fetches
from it on your behalf. Read them before you add a source.

**Reddit.** Reddit's
[Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)
requires Reddit's prior approval of any app that reads Reddit data through its
API. This project ships no Reddit key and seeks no approval of its own, and
runs no service. **With your own app** (you request access from Reddit in your own
name, register the app, and paste its client id, secret and refresh token under
Settings › Accounts › Reddit), the server's Reddit adapter
(`src/kranto/sources/reddit.py`) reads your subreddits through Reddit's API as
you: new posts, their scores and comment counts, the top comments of the most
scored few, one request a second, with a user agent that names the app, its version
and your account, unmasked (the Data API Terms, 2.8). What it reads stays in your
library under your retention; nothing is republished or used for training, and a
post or comment Reddit removed is never kept. Whether a personal research tool is
"commercial" use is Reddit's to say: its terms do not define it, and the setup page
says so and links Reddit's form. **Without an app**, the adapter reads a
subreddit's public Atom feed, paced to one request a minute, with no comments
unless `look.reddit_comments` is set. On 30
September 2026 Reddit announced that new access requests end on 31 October 2026,
its RSS and Atom feeds stop on 13 November 2026, unregistered apps lose access
from 12 January 2027 and public Data API access closes in March 2027. The catalog
also offers **Reddit (via search)**: Reddit posts on a topic's words through your
live search provider's index, no Reddit key (the provider's terms apply). The
example packs in `examples/packs/` contain no Reddit sources.

**Lobsters.** Lobsters publishes its feeds to the public, but its robots.txt
signals `ai-input=no, ai-train=no` for bots other than named search engines.
the server shows what it reads to a model, so the catalog leaves Lobsters out. A
feed URL you add by hand is your decision.

**arXiv.** An arXiv search reads the export API, paced to one request every three
seconds across the process, as arXiv's terms of use ask. Thank you to arXiv for
use of its open access interoperability.

**Newsletters.** Substack's terms forbid storing a significant portion of its
content. A publication added from the catalog is kept 30 days, not the default
90; full-text fetching (`ingest.fetch_full_text`) reads a post's page when its
feed item is thin. Posts you pay for are not read: there is no per-subscriber
feed.

**Stack Exchange.** Content is CC BY-SA. the server keeps a link to each post and
never its author; if you publish anything built from it, attribute it as the
licence asks.

**Looking before judging.** For each item that passes the
topic filter and a first screen (`look.enabled`, on by default), the server fetches its Hacker News
thread through the Algolia API, the page it links to, the pages linked from
the item, that page and its comments, and GitHub repositories they name,
through GitHub's public API. A few requests per item, capped per item (two
pages kept, at most four fetched, one repository, 30 seconds) and per run (40
items, 10 repository lookups), through the same HTTP client as everything
else (public addresses only, size and time limits). The text read is
scrubbed like every item's before a model sees it, and is kept only in the
model call that read it, which expires with the item.

Requests identify themselves with the user agent
`kranto/0.1 (+https://github.com/iddv/kranto)`.

## Connected accounts

Some sources read with your own account (Settings › Sources › Accounts; or
`/connections` on the server's own pages): Mastodon (your home timeline and lists),
Bluesky (your home timeline, and search, which Bluesky serves only to a
signed-in account), GitHub (releases of the repositories you star), YouTube
(your subscriptions), Product Hunt (launches by topic), Stack Exchange (an app
key that raises the API's daily allowance for search; not a login) and X (your
own developer app; see X below).

- **Read-only, fixed in code.** Each provider's scopes are fixed in code and
  shown on its connection page; a grant wider than asked for is revoked and
  refused. Mastodon: `read:accounts`, `read:statuses`, `read:lists`. Bluesky:
  `atproto` and `rpc:` permissions for four read calls on the Bluesky AppView
  (`getTimeline`, `searchPosts`, `getFeed`, `getListFeed`); never
  `transition:generic`, `repo:` or `blob:`. YouTube: `youtube.readonly`. GitHub:
  a fine-grained token with read-only access to public repositories and no
  permissions (a classic token whose scopes go beyond `read:user` is refused;
  a fine-grained token's permissions cannot be read back, so the page says what
  to choose); the device flow asks for `read:user`. Product Hunt: a developer
  token, whose default scope is `public`. the server never posts, likes, stars,
  follows, subscribes or changes anything on a site. It reads only what your
  account can already see, never keeps author fields (channel names and makers
  included), and scrubs what it reads like every other item.
- **Bluesky's app password** is the fallback for a server without loopback
  OAuth. It is used once to start a session and never stored; only the session
  is kept. An app password is not limited by scopes: the server only calls the
  read endpoints above, but OAuth is the read-only way. An account password, or
  an app password allowed to read direct messages, is refused and its session
  ended.
- **Sign-ins.** Browser sign-ins use the authorization code flow with PKCE
  (S256) and a single-use state that expires in ten minutes, with a loopback
  callback (`http://localhost:8765/connections/<provider>/callback` or the
  `127.0.0.1` form; Bluesky only `127.0.0.1`). Mastodon: the server registers
  itself on your instance. Bluesky: the server is a loopback client (nothing
  registered), uses pushed authorization requests, and binds the token to a
  key of its own with DPoP. YouTube: your own Google Cloud project's Desktop
  client, whose id and secret you paste and which are kept like a token.
  GitHub's device flow needs an OAuth app you register
  (`connections.github_client_id`); until then GitHub takes a pasted token.
- **YouTube API data is kept at most 30 days**, as YouTube's developer policies
  require: the `youtube` kind cannot be set longer (or forever), in
  `kranto.yaml` or per source. Disconnect revokes Google's grant.
- **Stack Exchange's key** is sent as the API's `key` query parameter. It is
  added when the request is sent and never part of a URL an error names, and
  the HTTP client's own request logging is held at WARNING so no URL with it
  is logged.
- **Where tokens are kept.** Encrypted (AES-256-GCM) in
  `<workspace>/data/secrets/connections.json`, with a key derived from this
  machine's `/etc/machine-id` and a random salt file next to it; files `0600`,
  directory `0700`. Never in `kranto.yaml`, the library database, an export, a
  bundle, a log line, an event or a page. A copy of `data/` on another machine
  cannot decrypt them. This protects against copies and backups, not against root
  on the machine. `afk doctor` checks the modes and that the file decrypts.
- **Disconnect** revokes the token at the site where the site has a revoke
  endpoint (Mastodon, Bluesky, Google), then deletes it here. GitHub tokens,
  Product Hunt tokens and Stack Exchange keys cannot be revoked by the server:
  Disconnect deletes them here and the page names where to delete them on the
  site. A token the site refuses marks its sources "Needs login"; nothing fails
  silently.
- **Not offered:** LinkedIn (no permitted way to read a feed). Reddit only with
  your own approved app, or through live search (above). X is read only through its official API (below); Nitter, RSS mirrors
  and the cheap "X API" resellers are not offered, because they read X through
  real account sessions, against X's terms. Product Hunt's API is for
  non-commercial use. A paid newsletter would only ever be read from your own
  mailbox, if that source is added.

## X

X is off until you connect it (Settings › Sources › Accounts › X), and it is
read only through the official X API with **your own** developer account and
app, so its terms bind you as the developer: the Developer Agreement (last
updated 2026-04-27), the Developer Policy and the Display Requirements.

- **What is read.** The sources you add: your lists, your home timeline, one
  account's posts, recent searches, your bookmarks and your likes. Scopes,
  fixed in code: `tweet.read users.read list.read bookmark.read like.read
  offline.access`. A wider grant is revoked and refused. Nothing is posted,
  liked, followed or sent; direct messages are never asked for.
- **What it costs, and who pays.** X bills your developer account per resource
  a reply returns: $0.005 a post, $0.001 for your own bookmarks and likes read
  by your own app, $0.010 a user (Kranto asks for none but your own, once per
  sign-in and Test). Kranto asks only for what it will judge (`max_results`, and
  `since_id` where X takes it; searches, bookmarks and likes once a day) and
  counts every read in `api_spend`, shown on Settings › Spend. That is an
  estimate from above: X bills a post returned twice in one UTC day once, which
  Kranto cannot see. Your Developer Console is the bill, and its spending limit
  is the one X itself enforces. `x.monthly_usd` (none by default) holds Kranto's
  X sources until the next month once its estimate reaches it.
- **What is kept, and for how long.** An observation keeps a short excerpt of
  the post's text, the post's URL without its author
  (`https://x.com/i/status/<id>`), Kranto's own summary and the post's engagement
  counts. Authors are never asked for (no `author_id`, no `user.fields`) and
  never kept. X posts are kept **30 days** by default (`retention.by_kind.x`;
  you may raise it), then compacted like every other observation.
- **Deleted posts leave.** The Developer Policy asks stored content to follow
  X's: deletions within 24 hours of a request. Once a week Kranto asks X about
  up to 100 kept posts (the ones idea cards cite first) and removes each one X
  no longer has, through the recorded purge, with no rollup made from it.
  **Remove this post** (`POST /api/observations/<id>/remove`, or `afk sources
  forget <post URL>`) removes one at once: that is how a deletion request you
  receive is honoured. Its `items_seen` row stays, so it is never read again.
- **Nothing is displayed to anyone else or redistributed.** Kranto shows one
  person their own notes; a bundle (`afk export bundle`) leaves an X post's text
  out and keeps the URL and Kranto's summary.
- **X through Grok** (off until `XAI_API_KEY` is set): for a person with an xAI key and
  no X developer app, xAI's `x_search` tool searches X once a day and lists the posts it
  read in Grok's own words, with their links. Kranto asks for no post's text and keeps
  none: an item is Grok's gist under the post's author-less URL, marked "a Grok digest,
  not the post". xAI bills $5 per 1,000 posts the tool reads plus tokens; each call is a
  model call, in the watcher's budget. xAI's own terms apply to the key.
- **No training, no sensitive inferences.** Posts are classified by a model for
  your notes (inference); no model is trained or fine-tuned on them. Kranto
  derives nothing about the people who wrote them.
- **Analysis.** The Agreement permits you to "conduct analysis of the X
  Content, as explicitly approved by X" (section II.A.1), and the use-case
  description you give when you create the app is binding on you. The
  connection page offers this description: *"A personal reading tool. Reads
  posts from my own lists, searches, bookmarks and likes, has a language model
  sort them for my own research notes, keeps them on my machine for a limited
  time, never displays or redistributes them, never trains a model."* Read the
  clause yourself before you rely on it; X's Policy Support form is the place
  to ask.

## No personal data

- **Authors are never collected.** The sources do not read author fields.
  Where a feed puts the author in the text (Reddit's "submitted by" line),
  the scrubber replaces the name and the adapter drops the line.
- **A deterministic scrubber** (`src/kranto/scrub.py`) runs on every item's
  title, body and comments when the item is built (a looked-at item's discussion,
  pages and repositories included), before anything reaches a
  model, a table or a log. It replaces secrets (private keys, common API key
  and token formats, JWTs), email addresses, card numbers (only those that
  pass the Luhn check), US social security numbers, IBANs, phone numbers, and
  handles in the forms `@name`, `u/name` and `/u/name` with a label such as
  `[email]`. Only the count of each kind replaced is kept, never the content.
  The model's own summary and reasoning are scrubbed again before they are
  stored, and so are compaction summaries.
- **The judge prompt** tells the model not to record names of private
  individuals, usernames, contact details or identifiers, and to skip content
  whose subject is an identifiable person's health, politics, sexuality,
  religion, finances or similar traits.

The scrubber is a set of patterns and is not perfect. Known limits:

- It does not recognise personal names written in plain text, postal
  addresses, or national identifiers other than US social security numbers.
- Phone numbers are caught only in common grouped or international formats;
  handles only in the forms listed above (a name after "by", for example, is
  not caught).
- It does not scrub URLs. A source link can itself contain a name, such as a
  profile or repository owner.
- Anything it misses is left to the judge prompt, which a model can fail to
  follow.

## Retention

Observations are a working set, not a permanent archive.

- Each observation is kept for its retention age: 90 days by default
  (`retention.default_days` in `kranto.yaml`), overridable per source kind
  (`retention.by_kind`, for example `{reddit: 30}`) and per source
  (`afk sources retention ID DAYS`; `default` removes the override). `0` keeps
  observations forever; setting it is your choice and your responsibility.
- Past that age, compaction (`afk compact`, and a daily job under `afk serve`,
  set by `retention.every_hours`) clusters each week's expired observations
  into rollups: a name, a short summary, keywords, source mix and up to five
  links. It then removes the observations and the model calls that hold their
  source's raw text. Model calls for items that were judged but not kept
  expire at the same age; other model calls are removed once they are older
  than `retention.default_days`, unless something that remains refers to
  them.
- A linked source kept as an observation of its own (when an item is looked
  at before judging, or by a deep dive before deep dives left Kranto) belongs to the source its parent came
  from, so it expires at that source's age; the link between the two is
  removed with either one. A screen's model call expires with its item.
- Every removal is recorded in the `purges` table. Nothing is removed any
  other way, and no library row is edited in place.
- What stays after compaction: rollups, the map's counts and trends, idea
  cards with a snapshot of the evidence they cite, and one `items_seen` row
  per item (its deduplication key and URL, no text), so an expired item is not
  fetched again.

Details are in [docs/OPERATING.md](docs/OPERATING.md) ("What is deleted, and
when").

## What you are responsible for

- **Your use.** Which sources you watch, what you do with what the server
  writes, and whether that is allowed where you are.
- **Your keys and spend.** Model calls go to the provider you configure
  (OpenRouter by default), under your key and within the monthly budget you
  set (`budget.monthly_usd`). The text of each item that reaches the judge is
  sent to that provider after scrubbing.
- **Your jurisdiction.** Data protection and copyright law differ by country.
  the server does not decide what is lawful for you.
- **Not republishing third-party text.** Observations, excerpts, exports
  (`afk export`) and bundles hold text derived from other people's writing.
  Keep them for your own use; do not publish a library, an export or a bundle
  without checking the terms of every source in it.
