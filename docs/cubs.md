# Cubs: writing one

A **cub** is a folder with `cub.yaml` and a Python file. Kranto runs it as its own process in a
sandbox (no network, no home, no key of yours), speaks `cub/1` to it over its pipes, and checks
every call it makes against what you approved when you installed it. A cub can read what Kranto
knows (topics, the library, briefs, ideas), keep its own small store, call the model under its
own purpose and cap, and **ask you** for anything that leaves Kranto (send a newsletter, post):
each such action waits for your approval on the page, and in practice (the default) it sends nothing.

The protocol in full is [cub-protocol.md](cub-protocol.md); the manifest's schema is
`src/bears_cub/cub.schema.json`.

## Start from the template

`template/` in [octo-owner/bearcubs](https://github.com/octo-owner/bearcubs) is a working cub: one weekly
job, one action, two reads, its tests against `FakeHost` and its own CI. Copy it, rename
`my_cub` everywhere (the id is the prefix of its jobs, actions, events, settings and model
purposes), and change what it does.

```
cub.yaml          what it is and everything it may ask for
main.py           its handlers
README.md         what it does and what it asks for, in words
requirements.txt  its own packages (most cubs need none)
tests/test_cub.py its tests, against bears_cub.testing.FakeHost
```

Test it without Kranto, against the SDK at the tag of Kranto you run (`kranto --version`; the
newest is on the releases page): `pip install "bears-cub-sdk @
git+https://github.com/iddv/kranto.git@v0.5.27#subdirectory=sdk" pytest`, then `pytest`.
Check that Kranto will accept it: `python -m bears_cub.check path/to/cub`.

## `cub.yaml`

Every key Kranto does not know is refused, and every key has a default, so a cub writes only
what it needs. The ones that matter:

| Key | What it says |
|---|---|
| `schema: 1`, `api: cub/1` | the manifest's schema and the protocol it speaks |
| `id`, `version`, `title`, `says` | who it is (`says` is shown to you, never to a model) |
| `kranto: ">=0.5,<0.7"` | Kranto versions it was tested with; outside them it runs dry only |
| `entry`, `requirements` | its Python file (`main.py`) and its pinned packages (`null`: none) |
| `reads` | which reads it may use: `topics`, `library`, `themes`, `ideas`, `briefs`, `events`, `objects`, `spend` |
| `events` | kinds it `publish`es (each starting with its id) and kinds it `subscribe`s to, with a trust floor and, for a push handler, its `method` |
| `jobs` | `kind`, `method`, `every_hours`, or `at: "08:00"` with `days: [mon]`; `when` (a setting that turns it off); `deadline_s` |
| `actions` | what you can run from its page (and with `kranto cub act`): `kind`, `title`, `method`, `fields` (each `text`, `markdown` for several lines, `enum`, `choice`, `bool`, `int` or `usd`) |
| `provides` | the reads its page's lists, tiles and rows call |
| `requests` | what it may ask you to do: `send.newsletter`, `post.mastodon`, `draft.sanity`, `book.propose` |
| `broker` | typed operations Kranto performs with your credential, which the cub never sees (`newsletter: [emails.create_draft]`) |
| `http.hosts` | public names it may GET through Kranto, with no credential (a cub names its hosts; `fetch: [cited]`, the pages behind what a read returned, is Kranto's own features' only and refused in a `cub.yaml`) |
| `model` | its `tiers`, its `purposes` (its id or `<id>_…`) and the `monthly_usd` it asks for |
| `search` | live search kinds |
| `storage` | `own`: a key-value store Kranto holds for it |
| `settings.keys` | its own settings, with types and defaults (never a key or a token); type `topics` is "which of your topics" (topic ids, none: every topic), drawn by the core's topic picker, never typed |
| `settings.keys.<k>.group`, `.advanced` | where the key sits on its page, Settings › \<Cub\> (`#/settings/<id>`): under the heading `group` names (24 characters at most; none: "\<Cub\>'s settings"), or under the page's Advanced fold. Kranto draws the rest of that page itself: On and off, its live switches, the caps, the accounts it uses, About with Update and Remove |
| `ui` | its tile, lists, cards and forms: data the page draws (a cub ships no page code) |
| `ui.primary` | its page's one blue button: one of its `forms` by id (none: its first form); every other verb is under ⋯ |
| `ui.lists[].empty`, `ui.lists[].groups[].tone` | what a list says with nothing in it, as what will appear and when (160 characters; none: "Nothing here yet."), and each group's tone: `wait` (amber, waits on you), `good`, `bad`, `new` or `quiet` (the default) |
| `ui.cards.<card>.open`, `.body` | `open: page` makes an object you read (an issue, a post) open as a page of its own, `#/cub/<id>/o/<object>`, with the field `body` names drawn as its text (markdown drawn as text: no HTML, no image); `sheet` (the default) opens it in the one sheet |
| `ui.widgets` | at most four widgets for the home, each drawn by Kranto from one of its reads (see [Widgets](#widgets)); none is on anyone's home until they add it |

What a cub cannot ask for: tables of its own, a page, a keyboard key, the house confirm, the
`mcp` or agent doors, a perform operation of a broker, a core event kind. Its
trust is set by Kranto when it is installed (`owner` for your own folder), whatever the file says.
Its id may not be a section of `kranto.yaml`, one of Kranto's own features, or a page of Settings
(`spend`, `system`, `appearance`…): its settings page is `#/settings/<id>`. `ui.settings_group`
is retired: it is still accepted, so an older `cub.yaml` installs, and nothing reads it.

## The SDK

```python
from bears_cub import Cub, NotGranted, fence

cub = Cub()

@cub.job("compose")                 # jobs[].method: (ctx) -> {status?, summary?, line?}
def compose(ctx): ...

@cub.event("ticket.resolved")       # a push handler: (ctx, events) -> how many it handled
def on_resolved(ctx, events): ...

@cub.action("compose_now")          # actions[].method: (ctx, fields) -> {say?, refresh?}
def compose_now(ctx, fields): ...

@cub.read("issues")                 # provides[]: (ctx, params) -> dict
def issues(ctx, params): ...
```

`ctx` is everything a handler may do; each method is one call to Kranto, checked against your
grants first:

| `ctx.` | Does |
|---|---|
| `read.topics()`, `.observations(…)`, `.search(q)`, `.themes()`, `.ideas(editor_class=…)`, `.idea(id)`, `.briefs(…)`, `.brief(id)`, `.object(kind, id)` (an observation, idea, theme, brief, or a build, product or project by the loop's id), `.get(name, **params)` | the read surface; text comes back fenced |
| `events.read(kind)`, `.ack(kind, last_id)`, `.publish(kind, payload, subject=, dedupe=)` | the bus, at least once |
| `model.complete(purpose=, tier=, messages=, max_tokens=, schema=)` | the metered model: no tools, no model of its own |
| `search(q, kind=)`, `http.get(url)` | live search; a GET to a declared host |
| `broker(service).call(op, **args)` | a typed operation with your credential |
| `ticket(kind, fields, because=, subject=)` | ask you: a ticket you confirm; a duplicate returns `duplicate=True`. `because` names what it rests on, each a list of at most 50: `events`, `observations`, `briefs`, `ideas` (card ids) as ids, `labels` (short text); the confirm links each |
| `tickets.list(…)`, `.get(id)`, `withdraw(subject, note)` | its own tickets |
| `kv.get(key, default)`, `.put`, `.delete`, `.list(prefix)`, `.items(prefix)` | its own store (64 KiB a value, 8 MiB in all) |
| `once(key)` | True the first time only: makes a retried run harmless |
| `settings`, `mode`, `live(kind)`, `now()`, `today()`, `cancelled`, `log.info(…)` | the run |

Errors: `NotGranted` (not in your grants), `CapReached`, `RateLimited` (`retry_after_s`),
`NotConnected` (the service is not connected: a draft op still works), `HostTooOld`.

## Brokers: what Kranto does with your credential

A cub never holds a key or a token. It may be granted a service's read and draft operations;
the send itself is the owner's approval on a ticket, which Kranto performs with the connection on
Settings › Accounts (the newsletter: whichever newsletter platform you connected under
Newsletter, Connect a provider; Mastodon (posting): one account per Kranto, with
`read:accounts write:statuses` only; Sanity: one project and dataset per Kranto, with a robot
token).

**The newsletter is neutral.** A cub asks for the service `newsletter` and the kind
`send.newsletter`, and never names a platform: Kranto sends through the one you connected
(the platforms offered and their steps are in [the newsletter guide](newsletter.md)). A
draft made before any platform is connected is held by Kranto and goes out through whichever
one is connected at your approval.

| Service | Operation | Needs a connection | Window | Result |
|---|---|---|---|---|
| `newsletter` | `emails.create_draft` (`subject` ≤ 200, `body` ≤ 200,000 markdown, not starting with `---`) | no: held by Kranto until a platform is connected (and ready), then also a draft there | 20 a day | `{draft_ref, where, subject, url, created_at}` |
| `newsletter` | `emails.get` (`draft_ref`), `drafts.list` (`limit?`) | no | 60 an hour | the draft and its status (`kranto`, `draft`, `scheduled`, `sent`, …); the cub's drafts |
| `newsletter` | `newsletter.get` | yes | 60 an hour | `{name, subscriber_count}` |
| `mastodon` | `statuses.draft` (`text` within the instance's limit, 500 when not connected; `visibility?`, `language?`, `spoiler_text?`) | no: Mastodon has no server-side drafts | 20 a day | `{draft_ref, chars, limit, where}` |
| `mastodon` | `drafts.list` (`limit?`) | no | 60 an hour | the cub's drafts |
| `mastodon` | `account.get`, `instance.limits` | yes (`NotConnected` otherwise) | 60 an hour | `{acct, url, display_name}`; `{instance, max_characters}` |
| `sanity` | `documents.draft` (`doc` the id's own part, `[a-z0-9-]` ≤ 80; `title` ≤ 200, `slug` ≤ 96, `body` ≤ 200,000 markdown, not starting with `---`, `category` `dispatch` or `build`; optional `excerpt` ≤ 280, `tags` comma-separated, `email_teaser` ≤ 1,200, `x_post` ≤ 280, `linkedin_post` ≤ 1,300, `origin`, `cites` ≤ 400) | no: held by Kranto; nothing reaches Sanity before your approval | 20 a day | `{draft_ref, sanity_id, where, slug, created_at}` |
| `sanity` | `drafts.list` (`limit?`) | no | 60 an hour | the cub's drafts |
| `sanity` | `documents.get` (`draft_ref`) | yes | 60 an hour | `{sanity_id, in_sanity, edited, published, studio_url}` |

The action of `send.newsletter` sends the draft to the audience, or schedules it when the
ticket's `when` is a time (`now` or `YYYY-MM-DDTHH:MM:SSZ`; a platform that cannot schedule
refuses it). The ticket's fields are `draft_ref`, `subject`, `audience` (`all`) and `when`.
The action of `post.mastodon` posts it with the idempotency key `kranto-ticket-<id>`. The action of
`draft.sanity` (fields `draft_ref`, `title`, `slug`, `category`; 3 a day) files the
draft as `drafts.kranto-<doc>`, `_type: post`, without a publish date: it never publishes, never
writes over a published `kranto-<doc>`, refuses a slug another post has, and never overwrites a
draft edited in Studio (Kranto keeps the hash of what it wrote in the post's `krantoMeta`); a
draft it filed and nobody touched is updated with Sanity's revision check. Each resolves `refused` with the service's words when
the service says no, and `unknown` when its answer did not come (Kranto never sends again by
itself: look at the service). Dry, the default, sends nothing and says what live would do.

**A draft waits until it is seen.** The ask of `send.newsletter`, `post.mastodon` and
`draft.sanity` has no time limit (its `expires_at` is `9999-12-31T00:00:00Z`). It leaves the
waiting asks only when it is sent, declined, withdrawn by its cub (`ticket.withdraw`), or
replaced: a newer ticket of `send.newsletter` from the same cub replaces the open older one (an
issue is one series), and a newer `post.mastodon` or `draft.sanity` ticket about the same
`subject` replaces the older one about it. The replaced ticket's state is `expired` with the note
`replaced by #<id>`, and `ticket.resolved` tells the cub. A draft whose ask ran out of time
under an earlier release, and which is still the cub's newest and was never approved or declined,
waits again: Kranto files a fresh ask with the same fields when the cubs start and in the daily
`cubs.gc`. Every draft, waiting, sent or earlier, is on Post (`GET /api/post`), where it can be
copied or downloaded as markdown without an account (`GET /api/post/d/<id>.md`).

## Widgets

A cub may offer up to four widgets for the home. A widget is data Kranto draws, never code: a
title, one of six kinds, one of the cub's `provides` reads, the sizes it supports and how often
the home reads it again. **Installing or updating a cub never changes anyone's home**: its
widgets wait in the library (the home's Arrange › Add a widget) until the owner adds one.

```yaml
ui:
  widgets:
    - id: waiting                   # on the home as <cub>.<id>
      title: Posts waiting          # at most 40 characters
      says: Drafted posts that wait for your approval.   # the library's line, at most 120
      kind: stat                    # stat | rows | series | table | stages | note
      read: widget_waiting          # one of provides; called with {size: S | M | L}
      sizes: [S, M]                 # the first is the size it is added at
      every_s: 300                  # read again this often while the home is open; at least 60
      open: posts                   # one of ui.lists (the widget's head opens it), or left out
      empty: Nothing waits for you. # its words when there is nothing to show, at most 160
```

The read answers the kind's shape; Kranto checks every answer before the page draws it, draws
every string as text, cuts what is over a cap with an ellipsis and drops a link that leaves the
cub's own page. A wrong shape is that widget's error state; every other widget draws as usual.

| Kind | The read answers | Caps |
|---|---|---|
| `stat` | `{value, words, delta?: {value, words, tone: up\|down\|flat}, facts?: [{label, value}], line?}` | `value` 16 characters, `words` 40, three facts, `line` 120 |
| `rows` | `{rows: [{id, title, meta?, at?, tone?: new\|wait\|quiet\|good\|bad, tag?, open?}], note?}` | 20 answered; S draws 3, M 5, L 8; `title` 120, `meta` 160, `tag` 24 |
| `series` | `{series: [{label, points: [[x, y], …], unit?}], value?, words?}` | 3 series of 52 points, `label` 40 |
| `table` | `{columns: [{key, label, kind: text\|number\|money\|date\|delta}], rows: [{<key>: value, open?}], note?}` | 5 columns; S 3, M 6, L 10 rows; `label` 24, a cell 80, `note` 200 |
| `stages` | `{steps: [{key, word}], items: [{id, title, step, since?, change?: {from, to, at}, meta?, open?}], note?}` | 2 to 8 steps; S 3, M 4, L 8 items |
| `note` | `{markdown}` | 1,000 characters; no HTML and no images (drawn as text), headings at most h3, a link only to a Kranto route or `https://` on one of its `http.hosts` |

Every answer may carry `as_of` (an ISO time), and is at most 64 KiB. An `open` is a route under
the cub's own page (`cub/<id>?sel=o12`, `cub/<id>?list=posts`); any other link is dropped. The
home asks each widget with a two-second budget: a slow read shows its last answer, or a
skeleton, and goes on in the cub's queue under its usual ten-second deadline; a read that fails
says so inside its own frame. Reads made for widgets are page reads: they do not count against
`calls_per_day`.

kranto reads `ui.widgets` from 0.5.13. An older Kranto refuses the key as unknown, as it refuses
any key it does not know, so a cub that declares widgets says so: `kranto: ">=0.5.13"` (the
template does).

`host.widget(id, size)` draws a widget as Kranto does and raises `WidgetAnswerError` naming
anything Kranto would refuse or change; `kranto cub eval` reads every widget at every size with
the planted instruction in the library; `kranto cub check` says each widget in words.

## Rules a good cub keeps

- **Strangers' text is data.** Put anything from the library, a brief or a card into a prompt
  inside `fence(label, text)`, and tell the model it is data, not instructions.
- **Never let a model's text choose an action.** The kind, the `draft_ref` and `because` come
  from your code; the model writes only the words you show the owner.
- **At least once.** A job or a delivery may run twice: key its effects with `ctx.once(key)`
  or a `dedupe` key.
- **Draft, then ask.** Make the draft with the broker, then file the ticket with the draft's
  ref and the same text: Kranto refuses an action whose ticket differs from its draft.
- **Dry first.** A new cub's kinds are dry: the action resolves `dry` and nothing leaves Kranto
  until you turn the kind live on its page.

## Testing with `FakeHost`

```python
from bears_cub.testing import FakeHost

host = FakeHost.from_folder("path/to/cub")
host.library.add_topic(id=1, name="Robotics")
host.library.add_brief(id=41, topic_id=1, items=[{"headline": "…", "body": "…"}])
host.model.reply("newsletter_intro", text="Two sentences.")
result = host.run_job("compose")
assert host.tickets[0]["kind"] == "send.newsletter"
host.resolve(host.tickets[0]["id"], "dry")       # the owner's approval, simulated
host.assert_no_secret_asked()
host.fixtures.planted_instruction()             # an observation that tells a model to obey
host.widget("waiting", "S")                     # a widget as the home draws it
```

`FakeHost` answers every call the way Kranto does (the same grant check, ticket fields and caps,
broker operations and windows, the store's quota) and records `host.calls`, `host.refused`,
`host.tickets`, `host.drafts`, `host.kv` and `host.events.published`.

## The reference cubs

Kranto ships three cubs to read and to start from, in `kranto paths examples`:

- **newsletter**: every Monday at 08:00 the week's News briefs become one newsletter issue:
  each item verbatim from the brief, an intro from one model call over the headlines (fenced),
  a draft (in Kranto until a newsletter platform is connected), and one `send.newsletter`
  ticket.
- **toot**: a short post about an idea card when you ask (Write a post as a short post, or the
  console's `post.write`): a caption from one model call over the card's title and one-liner,
  cut to the instance's limit by the cub's own code, a draft in Kranto, and one `post.mastodon`
  ticket. (Its daily job still looks for the weekly editor's pick, which finds none while builds
  are off.)
- **blog**: a blog post about an idea card (`cards.get`: the card with its sources), a news item,
  a week of briefs, or your own markdown, written for your site (`blog.site`) in your voice:
  one model call, the card's or the item's own sources linked under it by the cub's code, a
  draft in Kranto, and one `draft.sanity` ticket. Kranto adds it from this folder the first time
  a post is asked for (Write a post, or `post.write`); with no Sanity account the post is
  copied or downloaded from Post.

All three write through Kranto's prose engine (`ctx.prose`, [prose.md](prose.md)): your voice
card and closest samples, Kranto's floor and the site's template go into the prompt, your take
(`take`, optional) leads, and the draft is checked and only its flagged lines rewritten (at
most two short calls). Their old tone settings (`blog.tone`, `toot.tone`, `newsletter.intro`)
became the voice card's first line once and are read by nothing else; the forms' one-off tone
(plain, playful, warm) is a hint for that post.
Each says its page's one primary (Compose, Draft a post), what its list says when empty and
its groups' tones, and its settings' groups; an issue and a post open as a page of their text
(`body_markdown` on the row; an issue drafted before newsletter 1.3.0 kept no text, and its
page says the text is in the draft).

All three keep the rules above: the model's words go into the text you read, never into the kind,
the draft or `because`; a run marks its day (or card) done only once its ticket is filed, so a
second delivery is harmless and a run the model failed is tried again; a redraft withdraws the
open ticket first. Their tests (`tests/test_cub.py`, against `FakeHost`) are the place to see what each
promises. Install them dry with

```
kranto cub add $(kranto paths examples)/newsletter
kranto cub add $(kranto paths examples)/toot
kranto cub add $(kranto paths examples)/blog
kranto cub eval newsletter        # its own tests and the standard fixtures
```

`kranto cub eval ID` runs a cub's `tests/` and the standard fixtures (`python -m
bears_cub.standard`: every job with the planted instruction in the library and a model that
echoes it; no secret asked, no ticket of a kind it did not declare, the planted text in no
ticket's kind, draft or `because`). It runs the cub's code outside its sandbox, so it is for
your own cubs only.

## Installing one

The cub shop is a developer's and is off unless you set `cubs.developer: true` under `cubs:` in
Kranto's config. Off, the Cubs page shows your installed cubs and what they ask you, and the
page's Available, Made by Kranto, Add a cub, Check a manifest and a hand-applied update are not
there (their routes answer 404, and the console offers none of their verbs). Your installed
cubs keep running and keep updating themselves daily when an update adds no permission and no
send. On, everything below is on the page as well as the command line.

From a folder on this machine (the cub is yours: trust `owner`) or a git URL at a tag, branch
or commit (trust `unreviewed`: nobody at Kranto has read it):

```
kranto cub check ./my-cub              # the validator and the findings; nothing installed
kranto cub add ./my-cub                # the words of the confirm, then y/N
kranto cub add https://github.com/you/my-cub --ref v1.0.0
kranto cub add "https://github.com/you/cubs#subdirectory=cubs/my-cub" --ref main
```

A repository that holds several cubs names the one to install with `#subdirectory=` (a
relative path inside it, as pip writes it); `kranto cub update` fetches the same folder again.
More cubs, such as **examplecom** (drafts posts for a Sanity-backed blog), live in
[octo-owner/bearcubs](https://github.com/octo-owner/bearcubs), each with its own guide.

Kranto copies the tree (never a `.git`, a `.venv` or caches), refuses a link out of the folder,
a native library or program and a script marked executable, validates `cub.yaml` against what
this Kranto can grant, and shows what the cub may do in words, with its findings (an `import
socket` is shown: a cub has no network, so it does nothing, or hides a try). After your yes the
cub's packages (`requirements.txt`: every line `name==version --hash=sha256:…`, wheels only)
are installed apart from the tree, the folder is placed in `<home>/cubs/<id>/` read-only, and
its tree hash and manifest hash are pinned. A cub whose files change after that is paused
("its files changed since you approved them").

Every kind it may ask for starts in **practice** (in the code, `dry`): an approval sends
nothing, the page says "Nothing was sent (practice)", and nothing leaves Kranto. **Send for real**
is turned on on the page only: in the ask's own dialog, or on the cub's page.

| Command | Does |
|---|---|
| `kranto cub list` | the installed cubs: version, trust, state, mode, last run, what waits for you, spend |
| `kranto cub inspect ID` | its source and pin, grants in words, limits, findings, last runs, and an update staged for it with what it may now do (`--manifest`, `--grants`, `--kv`) |
| `kranto cub update ID` | fetch its source again: the files' diff and the permission delta; `--apply JOB` applies it (an update that adds a permission, or of a cub that sends, is applied on the page). One update waits per cub: looking again answers the one staged, and newer files replace it. A staged update shows on the cub's page ("Update to 1.2.0" in its head) and under Cubs › Staged |
| `kranto cub source ID SOURCE` | where its updates are read from now: a folder, or a git URL (`URL#subdirectory=cubs/ID`; `--ref`). Only the recorded source changes; the installed copy, its pin and its grants stay. When its folder is gone, `inspect`, its page and Needs you (once) say so and name this command: Kranto's own example cubs left the package for octo-owner/bearcubs (`kranto cub source examplecom https://github.com/octo-owner/bearcubs#subdirectory=cubs/examplecom`) |
| `kranto cub enable ID` / `disable ID` | the owner's switch (`cubs.<id>.enabled`); what it asks you stays open |
| `kranto cub dry ID KIND` | a kind back to practice (Send for real is the page's) |
| `kranto cub stop ID` / `resume ID` | stop: its process killed, the cub paused, what it asks you closed |
| `kranto cub remove ID` | removed; its folder kept 30 days under `cubs/.removed`; `--purge` deletes its stored data too |
| `kranto cub log ID` | its log (`--run`, `--since 2h`, `-n`, `--calls`) |
| `kranto cub run ID JOB` | one of its jobs now, through the running Kranto |
| `kranto cub act ID ACTION --field KEY=VALUE` | one of its actions, as its page's form runs it (the action must list the `cli` door); `KEY=@path` reads the value from a file on this machine |
| `kranto cub stopfile --set` / `--clear` | `~/.config/kranto/cubs.STOP`: while it exists no cub runs and every approval is practice |

An update that grows its permissions puts every kind back to practice. A removed cub's asks,
calls, runs and pins stay in the library; its settings stay in `kranto.yaml`, so adding it again
finds them.

### Updates that apply by themselves

Once a day kranto reads every cub's source again (the `cubs.updates` job, as Look for an update
does). An update that **adds no permission and no send**, and whose `kranto:` range holds this
Kranto, is applied by itself: Activity says "Newsletter updated to 1.2.1 by itself" and the cub's
page says "Updated to 1.2.1 by itself". Its trust, its sandbox, its kinds sent for real and
what waits for you stay as they were. Any other update waits for one click, and Needs you
says why: "Newsletter 1.2.0 asks for one more permission · Review", "… asks to send something
new", "… needs a newer Kranto (>=0.6)". `cubs.auto_update: false` makes every update wait for
the action; `cubs.check_updates: false` as well stops the daily look. Clicking Update applies the
staged update; any other job staged for the same cub at that version or older is cancelled with
it, so the button never comes back for a version you have.

## Sending for real (the reference cubs)

A newsletter cub installed before the neutral names (`newsletter` 1.0.0) keeps working: its
platform-named kind and service are aliases of `send.newsletter` and `newsletter` for one
release, what it asks you is approved as before, and a kind it sends for real stays so.
`kranto cub update newsletter` moves it to 1.1.0.

Nothing is sent until you do all of this, in this order:

1. **Connect the service.** For the newsletter: Settings › Accounts › Newsletter, **Connect
   a provider…**, choose the platform and follow [the newsletter guide](newsletter.md)'s steps
   for it; Save and test only reads, and says what is missing. For the toot cub, Settings ›
   Accounts › Mastodon (posting): on your instance,
   Preferences › Development › New application named "Kranto (posting)" with only
   `read:accounts` and `write:statuses`; paste your instance and the access token, then Save
   and test (it names the connection `@you@instance`).
2. **Turn on Send for real** in the ask's dialog (the issue's Send, the post's Post toot), or on
   the cub's page. It applies to the ones after it too; the daily cap stays (3 issues, 5 posts).
   This is on the page only; `kranto cub dry ID KIND` turns it back from a terminal.
3. **Your next Send now sends** (or Schedule schedules, where the platform can). What can be
   undone is the platform's: the newsletter guide says what for each; delete a post on your
   instance.
4. **To stop everything at once:** Stop on the cub's page, `kranto cub stop ID`, or
   `touch ~/.config/kranto/cubs.STOP` (every cub stops within ten seconds and every approval is
   practice until you remove the file).
