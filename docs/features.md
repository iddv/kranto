# Features: how Kranto is extended

Kranto is one loop (watch, notice, propose, act, measure) applied to more and more things. A
**feature** is one unit of that: News, and later Media and the existing parts of Kranto.
Each declares one **manifest**; the core reads it and does the rest: the scheduler's jobs, the
settings, the routes, the bus, the grades, Spend's lines, `GET /api/features`. Cubs, which
other people write, are in [cubs.md](cubs.md).

## Words

- **Feature**: a package under `src/kranto/features/<id>/` with `FEATURE` in its
  `__init__.py`. In this release every feature is first-party (Kranto's own code).
- **Cub**: the same unit when someone other than Kranto writes it: a folder with `cub.yaml`
  and a Python file, run as its own sandboxed process. The manifest's data form
  (`Feature.to_manifest()`, schema 1, protocol `cub/1`) is what a cub ships as `cub.yaml`;
  the same validator checks both (`core/manifest.py`, which interprets the JSON Schema
  `bears_cub/cub.schema.json`, shipped with the SDK). An installed cub becomes a `Feature` again
  (`Feature.from_manifest`). Its tables are the `cub_*` ones (migration 31: the `mod_*`
  rows copied with their ids; the old tables stay, frozen).
- **Trust**: who a feature is: `first-party` here; later `owner`, `reviewed`, `listed`,
  `unreviewed`, `generated`. Every event carries its publisher's trust.

## The manifest

`kranto.core.Feature` (see `core/manifest.py`): `id`, `title`, `says`, `version`, then:

| Block | What it declares | What the core does with it |
|---|---|---|
| `jobs` | `Job(kind, run, every_hours, when=…)` | a scheduler job; off (shown as off) while the feature or its `when` setting is; one `runs` row and a `job.finished` event per run |
| `owns` | its tables, `<id>_*`, created by its numbered migration in `store.py` | append-only by trigger; `ctx.db` reaches these only |
| `api` | read functions `(ctx, params) -> dict` | `GET /api/f/<id>/<name>` for its page; a name in the v1 surface (`briefs.list`) is offered to other features |
| `actions` | `Action(kind, title, run, doors, click)` | `POST /api/f/<id>/act/<verb>`; the door and the confirm class are checked before `run`; `when` (a feature's own, like `placement="head"`) names one of its true-or-false settings, and the page offers the action only while it is on |
| `settings` | keys with rules, `sensitive`, `per_topic` | its own `kranto.yaml` section, checked at load; `POST /api/f/<id>/settings`; sensitive keys need the page and the confirm; `by_hand` keys are never written by Kranto |
| `permissions` | the closed list below | what its context can do |
| `events` | `publishes`, `subscribes` (with `min_trust` and an optional handler) | the bus's kind registry (one publisher per kind); delivery with cursors |
| `ui` | `nav`, `pages`, `today_rows`, `cards` (declarative), and the seven generic surfaces below | the page draws it (the page's `src/features/`, or the core's generic cub page) |
| `spend`, `telemetry`, `prompts`, `grades`, `docs`, `cli` | its purposes and caps, counters, prompts (editable in Settings › Prompts), grade targets and their chips, words, `afk <id> …` | Spend, the allow-list, the prompt registry and lock, the one grades table, the glossary, the command line |

## The seven generic surfaces

A cub ships no UI code: it gives data and the core draws it, tagged with its trust and mode.

| Surface | The manifest says | The core draws |
|---|---|---|
| Home tile | `ui.kind` (post, send, money, book, watch, make, other), `ui.glyph` (a closed set: mail, pen, up, plane, play, target, swap, grid, dot), `ui.tile: Tile(line, count, words, tone)` | the tile; `GET /api/features` returns it resolved (`tile: {line, count, words, tone}`), so the home is one read |
| Needs-you or New row | `TodayRow(kind, read, group, primary, card)`; the read answers `{"rows": [{id, title, meta, at, open, ticket}]}` | a row under the home's caps; `primary` is `open`, an action or a request kind (the ticket's confirm) |
| List with a sheet | `UIList(id, word, read, card, groups=(Group(key, word),…), count)`; each group is a key of the read's answer | the page's subnav, groups, rows; enter opens the card in a sheet |
| Form | `Form(id, word, submit, fields=(FormField(key, label, kind, choices, read, hint),…), cost)`; `Action.fields` the same, so an action with input is a form | a sheet with the fields by kind (text, enum, choice, bool, int, usd) and one primary |
| Card | `ui.cards.<kind>: {title, lines, fields, actions, origin, image_ref}`; keys may be dotted paths (`item.title`) | `ui/Card.svelte`, with the origin fence |
| Settings page | `settings.keys` | a sheet generated from the types (a key of type `topics`: the core's one topic picker), the core's per-cub keys beside it |
| The high-trust confirm | `permissions.requests` | the one dialog: the read-back from the kind's typed fields (`GET /api/features`' `request_schemas`), the mode, who asked and on what |

`Action.placement` (`place` in the data) is `card` or `head` (always in the page's head, first-party
only in schema 1). `Feature.mode(ctx)` gives the mode tag's word.
The request kinds `newsletter.send`, `post.mastodon` and `booking.propose` are declared with
their read-back fields; their performers come with the cub runtime, so a ticket of one is
refused at Confirm until then.

The home's arrangement is the core's `shell:` section in `kranto.yaml` (`core/shell.py`):
`shell.layout` (one layout, `new`: the home and its doors, each door one column with a subnav and
every object in the one sheet; `classic`, the navigator on the left, was cut in open-source wave 1:
a file that says it is kept and drawn as `new`, and `POST /api/shell` refuses to write it),
`shell.pins`,
`shell.hidden`, `shell.needs_cap`, `shell.new_cap`, `shell.needs_you.<id>`, `shell.new.<id>`;
`GET /api/shell` reads it and `POST /api/shell` (`{key, value}` or `{reset: true}`) is its one
writer. The layout's two keys until 0.5.8, `shell.home` and `shell.doors`, are still read (`false`
in either meant `classic`); Kranto writes `shell.layout` in their place once, as it starts.

**The home** (open-source wave 2) is one fixed order and one read, `GET /api/home` (`core/home.py`
`today`): `date`, `sentence`, `waiting` (drafts and prepared items, for the sentence), `briefs`
(each topic's brief of the local day, three topics and three items each), `ideas` (the five newest
cards in Ideas' order, `new` since the last visit), `quiet` (topics, sources, the last read, the
next result) and `away`: after `home.away_days` days (3 by default, the `home:` section of
`kranto.yaml`, 1 to 60) without a visit, While you were away (the three best cards written in the
absence and the lead item of the two newest briefs, five rows at most), else null. The visit is
one `settings` row, `home.visit` (`{at, previous}`), moved only by `POST /api/home/visit`: the
ordinary home moves it as it draws, While you were away only when one of its rows is opened or
Show today is chosen; absent, the home is never "away". Tiles and widgets are no longer drawn, and
a cub's Needs-you rows only feed the one thing (a draft that waits); `GET /api/home` still answers
`slots`, `widgets`, `library` and `rows` for one wave (a cub's widget, `kranto cub check`, the
SDK's FakeHost), and `shell.pins`, `shell.hidden` and `shell.widgets` are read and ignored by the
home.

The cubs' switches and limits are the `cubs:` section of `kranto.yaml` (`core/cubs/settings.py`,
one writer, every key with a default): `cubs.enabled` (the global switch), `cubs.max_running`,
`cubs.idle_s`, `cubs.auto_update` (on: an update that adds no permission and no send applies by
itself; [cubs.md](cubs.md)), `cubs.check_updates`, `cubs.default_monthly_usd` and
`cubs.default_calls_per_day` (what a stranger's cub gets: $5 a month and 200 calls a day; your
own cubs are uncapped), `cubs.min_sdk`, and per cub `cubs.<id>.enabled`, `.live` (the request
kinds that are live; added on the page only), `.monthly_usd`, `.calls_per_day`,
`.tickets_per_day`, `.memory_mb`, `.pids`, `.cpu_pct`, `.tmp_mb`, `.kv_mb`.

## Permissions: a closed list, enforced by what the core hands the feature

A feature's code receives a `FeatureContext` and nothing else:

| Grant | The context gives | Refused |
|---|---|---|
| `reads: [topics, library, themes, ideas, briefs, events, objects, spend]` | `ctx.read("library.observations", topic_id=…)`: the v1 read surface, text fenced and labelled (`[obs 8231]`) | a family not granted |
| `model: Model(tiers, purposes, monthly_usd)` | `ctx.llm.complete(purpose=…, tier=…)`: the metered client | another purpose or tier, **any tool**, a provider or model of its own, a call past the cap |
| `search: [web, discussion]` | `ctx.search.search(q, kind=…)` as caller `<id>` (`search.callers.<id>: off` turns it off) | page fetching; other kinds |
| `fetch: [cited]` | `ctx.fetch(url, max_chars=6000)`: the page behind a URL this context's own `library`/`objects` reads or searches returned (News reads the page behind a brief item's observation), fetched as a cub's `http.fetch` is (https, public addresses only, 3 redirects, 20 s, 2 MiB, no credential) with no host list, its main text extracted, scrubbed, fenced and cut; `{url, final_url, fetched_at, chars, text, image}` (`image`: the page's own `og:image`, an address only) or `{url, fetched_at, error}` | any URL the context was not handed (one a model wrote); a cub (it names its `http.hosts`) |
| `http_hosts` | (none of today's features asks) | everything else: there is no network client on the context |
| `requests: [<kind>]` | `ctx.ticket(kind, fields, because=…)`: a **ticket** the owner confirms (`ctx.request`, its old name, works through 0.5.x) | performing the action |
| `storage: own` | `ctx.db`: SELECT and INSERT on its own tables | any other table, any other statement |

Two tests hold the rest: **the import contract** (a feature imports `kranto.core` and itself,
never `kranto.store`, `kranto.llm` or the web; it never touches `ctx.store`) and the
manifest validator.

## Events

`ctx.publish("brief.published", {"brief_id": 12, "topic_id": 3}, subject=("brief", 12))`. A
payload is ids and small facts (2,000 bytes, strings of 200 characters at most): the reader
fetches the object through a read. An event is a fact, never an instruction: nothing acts
because of one by itself. A subscriber reads with `ctx.take(kind)` and moves its cursor with
`ctx.ack(kind, last_id)`, or names a handler the scheduler calls after every round of jobs
(at least once: key on the event id). `GET /api/events?since=` reads the bus.

The core's own kinds: `job.finished`, `settings.changed`, `grade.given`, `spend.capped`,
`ticket.filed`, `ticket.resolved`.

## High-trust actions: tickets

Posting and sending (and, later, booking) belong to the core. A feature files a
ticket with typed fields and its provenance; the ticket waits for the owner; the owner's approval
on the page (the session cookie: never the command line's token, `kranto mcp`, an agent token
or a chat) with the confirm dialog runs the core's performer, once. A ticket expires (a
draft's ask, the posting kinds', waits until it is answered or replaced by the next draft of its
series: [cubs.md](cubs.md)), is never duplicated, and every state is a row (`GET /api/tickets/<id>` shows the read-back, the
provenance and the history; `/api/requests…` answers the same through 0.5.x). A cub's
ticket is confirmed in the mode of the moment: its kind is live only while it is listed in
`cubs.<id>.live` (turned on on the page only), the cub's `kranto` range holds and
`~/.config/kranto/cubs.STOP` does not exist; otherwise the action resolves `dry` and nothing
leaves Kranto. The kinds: `send.newsletter`,
`post.mastodon` (no account field: Kranto names the account from the connection),
`draft.sanity` (a post filed in the owner's Sanity dataset as a draft, never published) and
`book.propose` (filed and declined, never performed in 0.5).

Post's one read is `GET /api/post`: the drafts waiting, sent and earlier, newest first, each with
its kind in a word, its title, one fact, its ask's row (Send, or Send again) and, once sent, the
platform's words and link; and the newsletter, Mastodon and blog accounts. `GET /api/post/d/<id>`
is one draft's sheet with its words as markdown, and `GET /api/post/d/<id>.md` downloads them as
`<title>.md`. Both are reads: they need no account, no model and no network. A source written
into a draft as the writer's label ("obs 12825", "exa 3") reads there as its outlet's name.

Edit is `POST /api/post/d/<id>/edit` (the verb `post.edit`, a change you can undo) with
`{title, body}` (a long post), `{parts: [{text}]}` (a short post) or `{drop: <key>}` (an
extra). Only a draft that waits can be edited. The owner's words are filed as the next draft of
the same series (`content.edited`, `content.edited_from`): the old ask closes as "replaced by
#<ask>", a new ask waits with the new words, and the original draft stays under Earlier drafts,
to open, copy or start again from (the sheet's `original_draft`). A short post past its limit is
refused with the count. A send that waited for the owner's yes is withdrawn first, and the answer
says so. The sheet carries what the editor needs: `edit`, `can_edit` and `cannot_edit`, `limit`,
`edited`, `edited_from`, `original_draft`.

Write a post is `POST /api/post/write` with `{about, as, angle?}` (the verb `post.write`): `about`
is `card:<n>`, `brief:<id>:<item>` (the item from 1) or `week`, `as` is `blog` (the default) or
`toot` (a short post, about a card only), and `angle` is the owner's angle, one sentence of their
own or one of the three `POST /api/post/angles` proposes (optional, at most 600 characters; the
post opens on its angle (where it leads, a bet or a scene) and argues past the item, and with none it is a plain summary that says
so: [prose.md](prose.md)); `take`, its old name, still works. It answers at once (202, "Writing the draft. It will be
on Post in about a minute.") and the writing cub's action runs in the background
(`GET /api/post/write?about=&as=` reads its job; asking again while it runs gets the same job,
never a second model call). The draft waits on Post like any other; nothing is sent until you
choose Send. Kranto adds its own blog writer from `kranto paths examples` the first time it is
asked; the toot cub is yours to add.

## The read surface, v1

`topics.list` (each with `first_read_at`: when its first read ended, null before),
`library.observations`, `library.search`, `themes.list`, `themes.get`,
`ideas.list` (with the weekly editor's verdict, `editor_class` to filter; each card's latest
`outcome` and `built`: what the loop made of it, `{state, repo, url}` or null), `ideas.get`, `briefs.list`, `briefs.get` (News), `objects.get` (observation, idea, theme, brief, and from the loop build, product and project: public records, no path or log; none for a cub narrowed to some topics), `events.read`,
`spend.mine`. `GET /api/read/<name>` serves them to the page and the command line.

## Adding a feature

1. `src/kranto/features/<id>/__init__.py` with `FEATURE = Feature(...)`, add it to
   `kranto.features.FEATURES`.
2. Its tables in a numbered migration in `store.py` (pre-assigned numbers, add-only).
3. Its prompt files in `src/kranto/prompts/` and a line in `prompts.lock.json`.
4. Its page in the page's `ui/web/src/features/<id>/`.
5. `afk features <id>` prints the manifest as the core sees it.
