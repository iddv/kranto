# The web UI: how it is built and served

Kranto's page is one HTML page (`src/kranto/page/ui/app.html`) with hash routes (`#/home`,
`#/ideas/…`), served by `api.handle` under the server: the document at `/`, its own files, calls and terminal socket under `/brb/` (`/brb/` itself answers 308 to `/`, and a browser keeps the `#/…` part, so an old bookmark lands on the same page). The page has no
snapshot of its own: every page reads what it shows from the server's API (`/api/ideas`,
`/api/today`, `/api/home`, `/api/status`…) and the page server's own few routes (the header,
Activity, the console, traces, feedback). It is one Svelte 5 app in TypeScript, built by Vite. The shell (the
frame, the header, the navigator, the status bar, the splitters, the palette, the keys, the
routes and the live feed) is Svelte since every page inside it is components since when the last of the old hand-written module went.

| Part | Where | Notes |
|---|---|---|
| The shell | `src/kranto/page/ui/web/src/App.svelte`, `src/shell/`, `src/lib/` | the frame and its chrome; the routes (`lib/nodes.json`) and the key map (`lib/keys.json`) as data |
| The pages | `src/kranto/page/ui/web/src/pages/`, `src/ui/` | each page's list and pane, registered by its route's node (`pages/index.ts`); the parts they share |
| The app | `src/kranto/page/ui/web/src/lib/app/` | the data and the action, where a route draws, the rows and the keys, the chrome's facts, the palette's items; reached through `app()` |
| The UI's sources | `src/kranto/page/ui/web/` | Svelte 5 (runes), TypeScript, Vite; never in the wheel |
| The build | `src/kranto/page/ui/static/app/` | hashed files and Vite's manifest; git-ignored; in the wheel |
| Styles and themes | `src/kranto/page/ui/static/kranto.css`, `looks.css`, `theme.js` | tokens only; `theme.js` first in `<head>` |
| The DOM contract | `src/kranto/page/ui/web/CONTRACT.md` | the ids and classes the browser tests and the click stories use |

**Serving.** `routes/static.py` reads `static/app/.vite/manifest.json` and links the entry's
module and CSS into the page at `static/v<version>/app/<hashed name>`, after `theme.js` and the
stylesheets at the same versioned address. Every file there is cached for good (`immutable`); a
new release is a new address. the server's mount gzips them once. A Kranto with no build (installed
from git, or a checkout nobody built) answers `/` with 503 and one line: install a release (the
setup guide's step 2), or build it with `scripts/dev/build_ui.py`.

**The seam.** After every draw the old module works out what the chrome shows
(`chromeFacts()`: the lanes, the navigator's tree and counts, the service line, the list's head)
and the shell redraws from that (`ui.facts` in `lib/shell.svelte.ts`). The shell carries out
the keys (`lib/keyboard.ts`): its own verbs itself, the rows' and the panes' through the old
module (`rowKey`, `closeKey`, the page's own keys). Each later step moves a page into
components and deletes the old code behind it.

**A moved page** registers by its route's node in `ui/web/src/pages/index.ts`
(`register("settings/access", { list: lazy(() => import(...)), pane: lazy(...) })`). The old
module's `renderList` and `renderDetail` ask `pageFor(node)` (`lib/pages.svelte.ts`) and, when
a page answers, mount its list into `#rows` and its pane into `#dscroll` with props
`{ view: { w, back, tick } }` (`w` is the route as `where()` reads it; `back` is "‹ Back to
the list"'s address; `tick` counts the draws). A later draw only updates the props, so the
component keeps its state; another route unmounts it. Each page is its own file, loaded the
first time its route opens (the first load stays within its budget; a page's own file within
60 KB). Its reads go through `lib/reads.svelte.ts` (`read(path, maxAge)`: cached, reactive,
read again when stale on the next draw); a read's arrival draws the page again, as the old
page's reads did. Shared parts are in `src/ui/` (`List`, `Group`, `Row`, `SetRow`, `Pane`,
`Detail`, `Glyph`, `Tip`), each the old page's DOM, so a moved page looks the same.

**The page's head** is the shell's, never a page's: `shell/PageHead.svelte`,
mounted once and kept the first child of `#rows` (`#page-head`, once a page), drawn from two
declarations. The door's comes from `chromeFacts()` (`place`: the crumb's word, the subnav's
words and counts, Watch's topic scope, `classic` in the navigator's frame) and
`lib/app/heads.ts`'s `DOOR_HEADS` (the glyph, its wash, the gear's page, the door's
`RunLine`). The page's comes from `ui/PageTitle.svelte` (or `List`'s props, which use it):
`title`, `facts` (one muted line), `lede`, at most one `primary`, `stop`, `more` (⋯), `gear`,
`line`, `flash`, and for a page outside the doors its own `crumb` and `sub`. A page titled
with one of its door's words is shown under the door's name, the subnav saying which. Without
the doors (brb alone, or a component drawn by itself in a test) `PageTitle` draws the old
list head instead. A thing you read is `pages/Page.svelte` (the head, the outline, the body,
the sections, the evidence); the states are `ui/Loading.svelte`, `ui/Empty.svelte` (one
sentence and at most one link) and `ui/Failed.svelte` (the words, Try again, Tell us; an
answer that carries an error's id says Kranto's version and the id, and offers Send this error).

**A row that can't be read**. Both APIs may hold, in any list, a row
`{id, …, unreadable: {what, words, error_id, exception}}` in place of one they could not build
(the server's and the page's `rowsafe.py`). The page never draws such a row with its list's own
code: every read (`lib/reads.svelte.ts`, `lib/app/data.ts`'s `api`, `api/client.ts`'s `get`)
takes them out of its lists as it arrives (`lib/unreadable.svelte.ts`'s `contain`), kept by the
read's path, and the shell lists those of the page's reads (the reads the last draw asked for)
in `#unreadable-box`, under the
page's head: `ui/Unreadables.svelte`, one line each with **Send this error**. Send this error
(`sendError` in `ui/sendFeedback.ts`) opens Feedback with the error's report (the server's `GET
/api/errors/<id>`) shown in full, and adds it to the issue; `?send_error=<id>` on any address
does the same (the server's error page links there).

**Settings › \<Feature\>** is one generated page for every feature and cub:
`pages/settings/FeaturePage.svelte` at `#/settings/:fid` (nodes.json's last settings route, after
Settings' own pages; the server refuses a cub id that is one of them), its sheet
`FeaturePane.svelte`, its data `feature.ts`. It reads `GET /api/features` (each key's `group`
and `advanced` from the server 0.5.19) and, for a cub, `GET /api/cubs/<id>`; it writes through the
same routes the cub's sheet did (`/api/f/<id>/settings`, `/api/cubs/<id>/{enable,disable,live,
dry,stop,resume}`, `/api/cubs/settings`, `/api/shell`). The cub page's old `?sel=settings` and
`?sel=about` land on it.

**News's pages**: Today (`features/news/NewsToday.svelte`: one line a
story, one open in place, `?s=<brief>.<n>`, `j`/`k`, each story's idea from the read's `stories`),
a brief's day `#/news/b/:id` (`BriefPage.svelte`: Today's layout for that brief, About under
Details), one page a story `#/news/i/:brief/:n` (`StoryPage.svelte`: the item and its article,
`articles.get`, as one page; `#/news/a/:id` replaces its address with its story's) and Earlier
(`NewsEarlier.svelte`: one row a day) are drawn in `pages/Page.svelte`; a draft's editor is
`features/post/DraftEditor.svelte` with PROSE's flags (`ProseFlags.svelte`, `prose.ts`: `POST
/api/prose/check`, `/api/prose/revise`, `/api/prose/learn`) and Save as `POST /api/post/d/<id>/edit`;
Settings › Posting › How you write is `pages/settings/VoicePage.svelte` (`#/settings/posting/voice`,
`GET /api/prose`, `POST /api/prose/voice`; its OpenAI key, `POST /api/prose/writer-key`); the top bar's Needs you count is
`pages/front/needstotal.ts`, and what a button in an open sheet did is said in it by `shell/PressLine.svelte`; their lines are `NewsSources.svelte` (title, where from and when, the
observation a quiet link). The figures are `features/news/diagrams/` (`Timeline` across the page
and down it on the phone, `Bars`, `Series`, `RelMap`, `Thumb` beside an item on News › Today): plain SVG in the tokens,
drawn from the article's data, `diagram` choosing the lead one (`evidence`, the cited lines' own
dates, when nothing else has three points). A brief from `briefs.get`/`latest` carries
`articles` (each item's newest), so Today and the brief's page link the article and the item page
offers Deep dive now (`news.article_now`, a confirm). The page's policy allows `img-src https:`
for the source's picture only (the owner's D3). Earlier's old `?sel=f<id>` lands on the brief's page. News › Topics'
rows are `Row` with News's switch; a row's sheet is `NewsTopicPane.svelte`.

**A cub's page** declares its head like any page (`features/cub/CubPage.svelte`:
the manifest's glyph, trust, mode, `ui.primary`, its head actions with Stop, ⋯, the gear) and
draws its lists as `Group` and `Row` (a group's `tone` its rows' glyph, a list's `empty` its
words). It is no longer a stage: its objects and forms open in the shell's
one sheet (`CubPane.svelte`, registered as the `cub` node's pane; `where()` keeps a cub's `sel`
its own, so `sel=o<id>` is its object, not the library's observation). A card that says
`open: page` opens `#/cub/<id>/o/<oid>` (`CubObjectPage.svelte`, a stage: its `body` field drawn
by `ui/Md` as text). Cubs' Add a cub and Check a
manifest are its pane (`CubsPane.svelte`).

**Security.** Both servers send the same Content-Security-Policy: scripts only from the page's
own origin and never inline, no CDN, no framing. The components never write HTML (a test
fails on `{@html}` and the DOM's HTML sinks), and the build ships no source maps.

**Types.** `src/kranto/page/ui/types.py` says, as TypedDicts, what each read the page makes answers
(`RETURNS`: `api/kranto`, `api/header`, `api/info`, `api/actions`, `/api/whoami`). From it and
the registry's action schemas, `scripts/dev/gen_page_ts.py` writes `ui/web/src/api/types.gen.ts` and
`actions.gen.ts`, which the typed client (`src/api/client.ts`) uses: `get("api/kranto")` is a
`Snapshot`, and `act({kind, subject, fields})` is typed per action, with `confirm: true`
required for the confirm class. Three checks keep the two sides together:
`tests/page/test_api_types.py` fails when the generated files are stale and when a real answer on
the fake app does not have its declared shape, and `npm run check` fails a component that
reads a field that is gone. Change a read's shape: change `types.py`, run
`python3 scripts/dev/gen_page_ts.py` (in the page's venv), commit both.

**The live feed.** `GET /api/stream` (`ui/live.py`) is a server-sent-events stream that says
what changed, never the data: `event: host` with the server's version first, then `event:
change` with `{"kinds": [...], "keys": [...], "seq": N}` (kinds: term, activity, verb,
trace), and a `: ping` every 15 s. One watcher thread per process stats the files every state
change already touches (the console's and Open in Claude Code's session records, the server's
`activity.json`), once a second, only while a stream is open. It reads no network and no
model.

**What Kranto is doing.** `GET /brb/api/activity` (`ui/api.py`'s `activity`) is the one read
of every run as it goes: the server's (its `/api/activity`, through `afk`: the scheduled jobs,
the actions, the cubs' jobs) and the open sessions, from their records. Running, waiting on
you, next, recent (the hourly skips folded), failing; `subject=topic:12`, `kind=`, `limit=`,
`all=1`, `run=<id>`; cached 2 s, so the header, the sheet and every line on a page share one
read. A the server without the read says so in `afk_error`. `POST /brb/api/activity/stop {id}`
stops a run where it can stop: the server's at its next step, a session by End.
the server's own read and its words are in [the server's docs/activity.md](https://github.com/iddv/kranto/blob/main/docs/activity.md).
A the server run's trace (`afk:<uuid>`) is live while it runs: a page that follows it watches
`activity.json` and reads its calls and marks again; its steps are stage spans, and its head
says the run in one line ("Reading your sources · source 2 of 8 · 3 model calls · $0.02") with
its Stop. The trace page (`#/sessions/<tid>/trace`, `#/research/<id>/trace`,
`#/afk/<id>/trace`) reads `api/trace?trace=<source>:<id>`; an old build's or loop step's trace
row is read-only and has no page. At most 8 streams per process; one more gets 503
and the page polls. Both servers serve it (`api.stream`; the server's mount streams it through
its guard), a loopback GET like every read. A reconnecting page sends `Last-Event-ID` and gets
what it missed. The page (`lib/live.ts`) reads again on a change, at most every 2 s; while
the feed is down (two errors in 30 s, or refused) it reads every 5 s, as before, and tries the
feed again after 30 s; a read every 60 s runs whatever happens. A new version on the feed's
`host` event reloads the page.

**Building.** CI (`frontend` and `browser` jobs) and the release (`build.sh` in the server) run
`scripts/dev/build_ui.py`: `npm ci --ignore-scripts` from the lockfile, then `vite build`, then a
check that the page's JavaScript and CSS stay under 200 KB gzipped. Users never need Node.
CONTRIBUTING's "The web UI" has the commands and the dev loop.

**The layout (shell.layout).** One set of pages, the doors' (their addresses, rows and sheet
contents), in one frame: the home and the doors, `body.doors`, the sheet. The Classic frame was
cut in open-source wave 1: `layoutOf` answers `new` whatever the file says,
`frameClassic` is always false, the server keeps a stored `shell.layout: classic` and refuses a
new write of it. `chrome.ts` `classicTree` stays as the ☰ drawer's tree; the frame's leftover CSS
and code go in wave 3. A page that branches asks `shellDoors`/`doorsNow`. `coverage.test.ts`
walks the matrix with both stored values. Without the server there is no shell to read: the
pages say what they need the server for.

**The doors and the home (open-source wave 2).** `shell/doors.ts` lists
the four doors (News, Ideas, Watch, Post): `Header.svelte` draws them after the brand on a wide
screen, `TabBar.svelte` at the foot of a phone with ✦ (the console) as the fifth item; the lit one
is `chrome.ts`'s `doorId` (`cubs` and `cub` are Post's). `#/post` draws today's Cubs page until
S2's Post page; `#/cubs`, `#/cubs/approvals` and `#/cubs/tickets` redirect to it. The home
(`pages/front/Home.svelte`) is one fixed order from the server's one read, `GET /api/home` (the
sentence, today's brief, the five newest cards, the quiet line, `away`), plus the one thing, which
it still works out from the reads it shares with Needs you (`home.ts` `coreNeeds`, the prepared
items, a cub's asks, `pages/front/needs.ts` `nextOf`). Needs you (`#/needs`; `#/today` lands
there) is `pages/front/NeedsPage.svelte` and `Needs.svelte`, its pane `NeedsPane.svelte`. It posts `POST /api/home/visit` once a load when it draws
the ordinary home, and from While you were away only on Show today or a row's click. The widgets,
tiles and Arrange are gone from the page; `features/home.ts` keeps the widgets' writers (unused
by the pages since S2) until wave 3 removes them with `home.arrange`.

**The console.** `term/Console.svelte` is mounted once by `App.svelte`, after
`#app` and outside the routed panes, so a hash change never touches it: its xterm keeps its
buffer and its socket stays open. It is a fixed column on the right (`body.con-open #app` gives
up `--conw`), a 36 px rail when collapsed (`body.con-rail`), one top-bar item when minimized, a
sheet from the bottom under 760 px, and the whole window with Open full screen
(`body.con-full`). Its place is kept per browser (`kranto.console`); a first visit follows
`ask.open`. It reads `GET api/term/console` and opens with `POST api/term/console/open` (attach,
or start resumed; a reload replays the screen from the server's ring). Where the server serves no
terminal (`brb ui` alone, the browser tests) it draws nothing. ⌘J is `keys.json`'s, handled
before a terminal's own keys; `ctrl+]` leaves it. Each hash change tells the server the page's
title (`api/term/console/here`) for the status line.

The starters: while the conversation is empty (none yet, or
a new one nobody typed in) three questions stand above the prompt; a click starts the session if
none runs and sends the sentence once its screen goes quiet (1.2 s without output). On a phone
(`PHONE_MAX`, 760 px) the first visit is minimized and ✦ in the tab bar opens `term/PhoneSheet.svelte`
instead of the terminal: the prepared items with Review (`/api/prepared`, the same dialog) and
`GET api/term/console/last` (the page `term/console.py` `last_reply`: the newest assistant turn
with words in Claude Code's transcript, its first six lines and the first `#/…` it links; Codex
keeps none, so it says why). No terminal starts on a phone until Open the terminal full screen.

**Settings (before it).** `#/settings` is the Overview (one row a
page, its state in a line; the pane finds a setting by its name or its key), then seven pages in
the order you set kranto up (`pages/settings/doorpages.ts`' `DOORS_PAGES`): Watching, Posting,
Assistant (the console's settings in `loop.yaml`'s `ask:` and the server's ladder,
`pages/settings/assistant.ts`), Spend, Privacy & access, System and Appearance. **Advanced**, folded,
holds Prompts (the server's `/api/prompts`, read and written directly) and what a settings file
switches on by hand (the cub shop); on a phone the
Overview is the seven pages and the version line. A page made of several of the older lists
(Watching: Keys' provider and Models' tiers; Privacy & access; System: the service, Updates,
Activity, Health) draws them with `ui/Parts.svelte`, inside which `List` draws a list's groups
only, and its pane opens the older list's pane by the selection. Every row kept its selection
key, so every old route redirects (`nodes.json`: `redirect`, `sel`, and `by_sel` where a page
split, as `settings/accounts?sel=eacct:3` going to Watching); the address of a page that left
(Building, Publishing, Build tools and their aliases) lands on the Overview. A page's state words come from `ui/settings.ts`
(`SET_ST`), its kind line from `kindLine(page, group)`; a field is `ui/SettingField.svelte`, a
Save row `ui/SaveBar.svelte`, and every Save goes through `ui/save.ts` (`saveUndo`: the toast
"Saved: <what>. <when it takes effect>" with Undo for 9 s); a confirm is the house dialog
(`confirmThen` in `ui/dialog.svelte.ts`, never the browser's own). The words are `lib/words.ts`'s
`SETTING_WORDS` and `EFFECT`, pinned by `words.test.ts`.

**Settings with the server (open-source wave 2).** Seven pages (`doorpages.ts`
`DOORS_PAGES`): Watching (with `ConnectionsList` part `reading`: the logins sources are read
with), Posting (`PostingList.svelte`: the newsletter platform, `ConnectionsList` part `posting`
(Mastodon, Sanity), each posting cub's own page), Assistant, Spend, Privacy, System (the home's
arrangement left it), Appearance. Advanced (`ADVANCED_PAGES`: Prompts) and, while a settings file
turns it on, the cub shop. A Settings page whose switch is off lands on the Overview (`route.ts`
`landOf`), and the pages of what left the product (Invest, the radar, the browser's) land on the
home, Settings or Watch › Sources without their old selection (`nodes.json`'s `gone`); `settings/accounts` lands on Posting
(a site's account, `?sel=eacct:…`, on Watching; its old GitHub rows on the Overview); every
Settings address of `nodes.json` has a row in `settingsRedirects.test.ts`, which walks them all.
Spend reads the server's `/api/spend/topics` and `/api/settings/spend` only; Watching's Models
offer the catalog in `pages/settings/models.svelte.ts`.

**Pages that left.** Builds, Projects, Repos, Today (its editor and its
queue), Ideas' New idea and Editor, Settings' Building, Publishing and Build tools, Welcome's
Building and Publishing steps and the trace comparison are gone. Each of their addresses is a
redirect in `nodes.json` (to the home, Ideas, Needs you, Welcome or the Settings Overview; a
build's or a project's says so in a toast, its `said`), and `src/cut.test.ts` fails on an import
of a page that left or a name of the factory's routes.

## What is in the page's package

| Where | What |
|---|---|
| `src/kranto/page/ui/` | the web UI (served at `/`) and the page's own small server (`api.py`, `routes/`) |
| `src/kranto/page/term/` | the console: the real Claude Code in the page, in its own copy of the folder |
| `src/kranto/page/box/` | the console's sandbox: bubblewrap, the network proxy, the sign-in handoff, the one `claude -p` that only answers |
| `src/kranto/page/mcp/` | `kranto mcp`, the local MCP server ([mcp.md](mcp.md)) |
| `src/kranto/page/trace/` | agent traces: Kranto's own runs and the console's sessions as a tree of spans, live ([traces.md](traces.md)) |
| `src/kranto/page/settings/` | the page's settings file (`loop.yaml` over the defaults) and its one writer |
| `src/kranto/page/host_api.py` | exactly what the server may use of the page |
| `src/kranto/page/feedback.py`, `report.py` | "File an issue" through your own `gh`, and the scrub it goes through |
| `src/kranto/page/gitcmd.py`, `gh.py`, `tokens.py` | the hardened git; the one `gh` wrapper; who may act |
| `scripts/dev/` | the UI build, the generated TypeScript ([../scripts/README.md](../scripts/README.md)) |
