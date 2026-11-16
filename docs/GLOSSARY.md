# Glossary

The words Kranto uses, in the app, its commands and this repository.

## The app

- **Kranto**: the app. One install (`uv tool install … kranto`), one start (`kranto up`), one
  service (`kranto.service`), one page at http://127.0.0.1:8765/. It is one Python package,
  `kranto`, in two parts:
- **the server**: the part that watches. It reads the sources of your topics, keeps what is
  worth keeping in the library and writes idea cards. It also serves the page and holds the
  `kranto` command and `kranto update`.
- **the page**: the web UI in your browser (drawn at `/`; its own files and calls under
  `/brb/`), with the console and `kranto mcp` (`src/kranto/page/`).
- **`kranto`**: the command. The watcher's own commands also run from a checkout as
  `python -m kranto.cli` ([watcher.md](watcher.md)).
- **Home**: where an install keeps its data. A Kranto home (default `~/.kranto`) holds
  `kranto.yaml`, `.env`, `data/` (the library) and `loop/` (the page's `loop.yaml`).
  `~/.config/kranto/home` records which home `kranto` uses.
- **Token**: who may act. Every write needs one (the page's session cookie, `kranto mcp`'s,
  the console's, the command line's, or a named agent's); reads do not. They live in
  `~/.config/kranto/tokens/`. A door is one of those callers.
- **Verb**: one click a page offers (Add topic, Approve, Write a post), said once in Kranto's registry
  so the page, `kranto mcp` and the console run the same thing (`docs/verbs.md`).
- **Ladder**: what an assistant may do by itself, per kind of verb: Do it, Ask me in the UI or
  Never (Settings › Assistant). Keys and approving what a cub asks are locks: yours.
- **Prepared action**: a verb an assistant asked for that waits for your approval on its page and
  in Needs you, because the ladder says Ask me in the UI. Nothing has happened until you approve it.

## Settings' words

One name for each thing, in the pages, Welcome, `kranto setup` and the commands' help.

- **Watching**: reading your sources, never "monitoring". `kranto status` says
  "watching $10.39 of $40.00 this month".
- **Provider**: where model calls go: Claude API, OpenRouter, Another endpoint, Claude Code.
  The command line's choices stay `anthropic`, `openrouter`, `endpoint`, `claude_code`.
- **Key**: a secret you paste (never "model key", "api key" or "token" for a key). **Login**:
  a program's own sign-in on this machine (Claude Code's, the GitHub CLI's), Ready or Missing.
- **Account**: one you read sources with or post through (Mastodon, Bluesky, X, GitHub…);
  Connect and Disconnect… are its verbs. Kranto also uses a connected GitHub account, or your
  gh login, to check for updates while the repository is private.
- **Door** and **agent**: who may act; the file each uses is a token.
- **Cap**: a spend ceiling, always "X a month" or "a day"; "no cap" when there
  is none. Never "budget" or "limit" (a provider's own spend limit keeps its name).
- **Source states**: watched, proposed, retired, failing, paced, needs an account. A source is
  **watched** (read every run), never "active" (a topic's state) nor "watching".
- **Needs you**: something waits on you, as a group, a state or a count.
- **Your settings**: the settings files. A page names the file only in its kind line and its
  `?`, never in a sentence.
- **Usage reports**: Nothing, Local only, Basic, Detailed (`off`, `local`, `basic`,
  `detailed` on the command line, which calls them telemetry), on Settings › Privacy & access.
- **When a change takes effect**: every Save ends with one of "Applies at once.", "From the
  next check.", "From the next run." or "After a restart (kranto down, kranto up)."
- **Formats**: money as `$1.00`; tokens as 84k or 5.2M; a time as "now", "7 min", "3 h" (in a
  sentence "7 min ago"), else "17 Oct 08:44".

## Watching (the server)

- **Topic**: something you want watched, in your words. Topics are yours: Kranto proposes
  sources for them, never the topics themselves. A **project topic** followed a product
  Kranto built; since builds left, project topics are kept but not read.
- **Source**: a feed, a Hacker News query, a subreddit and so on, attached to a topic once you
  approve it. The **scout** proposes sources for a topic with one model call; a **wildcard**
  is a proposed source unrelated to the topic that may carry the same patterns. Sources with
  no topic form the **broad lane** (on the page: **No topic**, "every item is judged"). One
  source can feed several topics; **Remove from <topic>** stops it for that topic only, while
  Mute, Read less and Retire act **everywhere** and say so. **Could not be fetched**: a proposal
  that was empty or unreachable when checked. **Imported labels**: names on observations
  imported from Parallax, never read.
- **Judging**: one cheap model call that reads a new item and decides whether it is worth
  remembering (in the code, the *intern*).
- **Watching model** and **provider**: where Kranto's model calls go. The provider is the
  Claude API (an Anthropic key), OpenRouter, another OpenAI-compatible endpoint, or your Claude
  Code login (an explicit choice; its calls are billed to your Claude plan, shown as their
  **list-price equivalent**), chosen in Settings › Watching; the two tiers are the **Judge** (every
  item: Haiku 5.5 by default; `judge` in your settings) and the **Reasoner** (scouts, idea
  cards: Sonnet 5.5; `reason`). A provider can
  **pause** watching until a time (a spend limit reached, a Claude plan's usage window closed):
  nothing is lost, items wait and are read when it ends.
- **Observation**: what the judging kept: a summary, three ratings, a verbatim excerpt and the link.
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

## Acting and spending

- **Sandbox**: bubblewrap around every cub and every Open in Claude Code session: the system
  read-only, your home hidden, the network only through a proxy that reaches public addresses.
  The console is not in it: it runs as you ([threat-model.md](threat-model.md)).
- **Action**: one thing Kranto can do (add a topic, approve a source, write a post…), the same
  from the page, the command line, `kranto mcp` or a Claude Code proposal you confirm. Some
  always wait for your click.
- **Spend**: what was spent, in dollars on Settings › Spend and in tokens everywhere else.
  There is no cap by default; every cap is configurable.

Builds, projects, pitches, maintenance and the weekly editor (which chose one idea a week to
build) left Kranto. What builds and projects kept is in [archive.md](archive.md); cards the
weekly editor judged keep its notes.
