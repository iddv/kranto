# Glossary

The words Kranto uses, in the app and in both repositories.

## The app

- **Kranto**: the app. One install (`uv tool install … kranto`), one start (`kranto up`), one
  service (`kranto.service`), one page at http://127.0.0.1:8765/. It is two packages:
- **the server**: the half that watches. It reads the sources of your topics, keeps what is
  worth keeping in the library and writes idea cards. It also serves the page and holds the
  `kranto` command and `kranto update`.
- **the page**: the half that builds. It takes an idea through the build pipeline to a
  private GitHub repo, maintains what it published or adopted, and draws the builds part of
  the page (drawn at `/`; its own files and calls under `/brb/`).
- **`afk`, `brb`, `kranto`**: the commands. `kranto` runs the app; `afk` and `brb` are each half
  on its own.
- **Home**: where an install keeps its data. A kranto home (default `~/.kranto`) holds
  `kranto.yaml`, `.env`, `data/` (the library), `loop/` (the build loop's `loop.yaml` and
  ledger) and `tasks/` (one folder per build). `~/.config/kranto/home` records which home
  `kranto` uses.
- **Token**: who may act. Every write needs one (the page's session cookie, `kranto mcp`'s,
  the console's, the command line's, or a named agent's); reads do not. They live in
  `~/.config/kranto/tokens/`. A door is one of those callers.
- **Verb**: one click a page offers (Add topic, Approve, Publish), said once in Kranto's registry
  so the page, `kranto mcp` and the console run the same thing (`docs/verbs.md`).
- **Ladder**: what an assistant may do by itself, per kind of verb: Do it, Ask me in the UI or
  Never (Settings › Assistant). Keys and approving what a cub asks are locks: yours.
- **Prepared action**: a verb an assistant asked for that waits for your approval on its page and
  in Needs you, because the ladder says Ask me in the UI. Nothing has happened until you approve it.

## Settings' words

One name for each thing, in the pages, Welcome, `kranto setup` and the commands' help.

- **Watching** and **building**: the two halves, never "monitoring". `kranto status` says
  "watching $10.39 of $40.00 this month".
- **Provider**: where model calls go: Claude API, OpenRouter, Another endpoint, Claude Code.
  The command line's choices stay `anthropic`, `openrouter`, `endpoint`, `claude_code`.
- **Key**: a secret you paste (never "model key", "api key" or "token" for a key). **Login**:
  a program's own sign-in on this machine (Claude Code's, the GitHub CLI's), Ready or Missing.
- **Kranto's GitHub sign-in** (a code you type at github.com) and **Kranto's GitHub App** (the bot
  that comments and opens pull requests): two of the three GitHub things, with your gh login.
- **Account**: one you read sources with (Mastodon, Bluesky, X…); Connect and Disconnect…
  are its verbs.
- **Door** and **agent**: who may act; the file each uses is a token.
- **Cap**: a spend ceiling, always "X a month", "a day" or "one build"; "no cap" when there
  is none. Never "budget" or "limit" (a provider's own spend limit keeps its name).
- **Source states**: watched, proposed, retired, failing, paced, needs an account. A source is
  **watched** (read every run), never "active" (a topic's state) nor "watching".
- **Needs you**: something waits on you, as a group, a state or a count.
- **Your settings**: the settings files. A page names the file only in its kind line and its
  `?`, never in a sentence.
- **Usage reports**: Nothing, Local only, Basic, Detailed (`off`, `local`, `basic`,
  `detailed` on the command line, which calls them telemetry), on Settings › Privacy & access.
- **When a change takes effect**: every Save ends with one of "Applies at once.", "From the
  loop's next tick (under a minute).", "From the next build.", "From the next check.", "From
  the next run.", "From the next publish." or "After a restart (kranto down, kranto up)."
- **Formats**: money as `$1.00`; tokens as 84k or 5.2M; a time as "now", "7 min", "3 h" (in a
  sentence "7 min ago"), else "17 Oct 08:44".

## Watching (the server)

- **Topic**: something you want watched, in your words. Topics are yours: Kranto proposes
  sources for them, never the topics themselves. A **project topic** follows one of your
  published products.
- **Source**: a feed, a Hacker News query, a subreddit and so on, attached to a topic once you
  approve it. The **scout** proposes sources for a topic with one model call; a **wildcard**
  is a proposed source unrelated to the topic that may carry the same patterns. Sources with
  no topic form the **broad lane** (on the page: **No topic**, "every item is judged"). One
  source can feed several topics; **Remove from <topic>** stops it for that topic only, while
  Mute, Read less and Retire act **everywhere** and say so. **Could not be fetched**: a proposal
  that was empty or unreachable when checked. **Imported labels**: names on observations
  imported from Parallax, never read.
- **Bear**: one cheap model call that reads a new item and decides whether it is worth
  remembering. (Older documents call them interns.)
- **Watching model** and **provider**: where Kranto's model calls go. The provider is the
  Claude API (an Anthropic key), OpenRouter, another OpenAI-compatible endpoint, or your Claude
  Code login (an explicit choice; its calls are billed to your Claude plan, shown as their
  **list-price equivalent**), chosen in Settings › Watching; the two tiers are the **Judge** (every
  item: Haiku 5.5 by default; `judge` in your settings) and the **Reasoner** (scouts, idea
  cards: Sonnet 5.5; `reason`). A provider can
  **pause** watching until a time (a spend limit reached, a Claude plan's usage window closed):
  nothing is lost, items wait and are read when it ends.
- **Observation**: what a Kranto kept: a summary, three ratings, a verbatim excerpt and the link.
  Its **signal** combines the ratings.
- **Library**: every observation, append-only. After the retention window observations are
  compacted into **rollups** (a weekly summary that keeps the trend and drops the text).
- **Map** and **cluster**: the library grouped by meaning, redrawn daily; a cluster is one
  theme with its keywords and sources.
- **Idea card**: a known pattern whose preconditions now seem to hold somewhere new, citing
  the observations that suggest it. You grade cards.
- **Watch**: the door for your topics (Watch › Topics, and a topic's Sources, Evidence and Map).
  (Watches, saved searches flagged when a new observation matched, were retired.)
- **Strike**: a rare interruption worth your attention (a theme rising faster than its
  sources explain, a strong card), behind a gate with a threshold and a weekly
  cap. A **heartbeat** arrives weekly even when nothing struck.
- **Linked observation**: one kept with its parent (its discussion, a page or repository it
  links to), read when the parent was judged. (Deep dives, which read the same by hand, left
  Kranto; what they found stays in the library, see docs/archive.md.)

## Cubs

- **Cub**: a small program Kranto runs for you in a sandbox (no network, none of your files or
  keys), a folder with `cub.yaml` and a Python file (docs/cubs.md). News is one of Kranto's
  own features, drawn the same way; a cub is installed. Older documents call them mods.
- **Trust**: whose a cub is, on its every tile and row: **built-in** (Kranto's own), **yours**
  (installed from a folder on this machine), **unreviewed** (from a git URL: nobody at Kranto has
  read it), and later listed, reviewed and made by Kranto.
- **An ask** (in the code, a *ticket*): what a cub asks you to do that leaves
  Kranto (send an issue, post), with typed fields; only your click in its dialog on the page does
  it (**Send now**, **Post toot**). **Practice** (in the code, *dry*): the action does nothing and
  says so (every kind starts in practice); **Send for real**: the action does it. Turning it on is
  on the page only: in the ask's dialog, or on the cub's page.
- **Broker**: what Kranto does with your credential for a cub (a newsletter draft, a Mastodon
  post), which the cub never sees. **Draft**: what a cub prepares for you to approve, held by Kranto
  (or by your newsletter platform once one is connected).
- **Stop**, **paused**, **cubs.STOP**: Stop ends a cub's process and closes what it asks you;
  Kranto **pauses** a cub that failed three runs in a row, whose files changed, or that flooded;
  the file `~/.config/kranto/cubs.STOP` stops every cub and makes every approval practice
  while it exists.

## Building (the page)

- **The loop**: the page's scheduler, running as a lane of `kranto serve`: ideas in, published
  software out. Its settings are `loop.yaml`; its record is the **ledger** (`loop.db`).
- **Idea**: something to build, from an idea card, the inbox, `brb loop add` or the page.
  When builds start on their own is a setting (automatic builds wait until enough signals
  agree; you can always pick an idea by hand).
- **Pitch**: one model call that turns an idea into a product brief.
- **Build**: the v5 pipeline that turns a brief into a repo, in **rounds** made of **stages**
  (scope, build, verify, repair, readiness, deliver). Every session in it runs in the sandbox.
- **Sandbox**: bubblewrap around every session that writes or runs code: the workspace
  writable, the system read-only, your home hidden, the network only through a proxy that
  reaches public addresses. See the page's SECURITY.md.
- **Exam**: the checks a build is judged by (scenarios, the product's own tests, its README's
  commands, the readiness scorecard), kept outside the product. **Readiness** is the stage
  that reviews security, operations and the README.
- **Gate**: the release check after a round. A build that passes is **ready**; one that does
  not is **held**, with the reasons.
- **Ask for changes** (revise): another round on a held or ready build, with your instructions.
- **Publish**: a ready build becomes a **private** GitHub repo with a first release. It
  becomes public only when you approve it.
- **Project**: a published or adopted repo that Kranto keeps improving. Its **charter** says
  what it is, for whom, and what it promises; the weekly **evolve** run proposes changes, and
  the autonomy setting says which ones need you.
- **Maintenance**: Kranto looking after a repo: triage, fixes as pull requests, dependency
  updates. An **adopted** repo is one of yours that you asked Kranto to maintain.
- **Action**: one thing Kranto can do (start a build, publish, close, revise…), the same from
  the page, the command line, `kranto mcp` or a Claude Code proposal you confirm. Some always
  wait for your click.
- **Spend**: what was spent, in dollars on Settings › Spend and in tokens everywhere else.
  There is no cap by default; every cap is configurable.
- **Weekly editor**: once a week reads what was gathered and recommends at most one idea worth
  building (the **nominee**), or says why not. The **research desk** checks a nominee against
  what already exists before you see it.
- **Review**: the page where you grade the week's cards and builds (`g r`). A build's own page
  is opened with Open; a pull request with Open on GitHub ↗.
