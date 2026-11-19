# Changelog

What changed in each release of Kranto, for the person who runs it. Versions follow
[semantic versioning](https://semver.org/); until 1.0 anything may change. Nightly builds
(`vX.Y.0-devN`, GitHub prereleases) are not listed one by one: their notes name the pull
requests they carry.

## 0.7.0 — 2026-11-19

The first release of Kranto.

### What it is

Kranto runs on your own Linux machine as one page in your browser, on 127.0.0.1. You describe
the topics you follow; it proposes places to read and reads only the ones you tick. Every few
hours a cheap model keeps the few items that matter, each with its link, in a library on your
machine. From that it writes a short brief a day per topic and idea cards: what the news
suggests, each line linked to the items behind it. On a card or a brief you can ask for a draft
(a blog post, a newsletter, or short posts for the sites people use); Kranto checks the draft
against your voice and against the usual tells of machine writing, and nothing is posted until
you say yes. Your own Claude Code can sit beside every page as the console, working on the same
library with the same tools.

It needs Linux, Python 3.12 and [uv](https://docs.astral.sh/uv/), and one model for reading: an
Anthropic or OpenRouter key, another OpenAI-compatible endpoint, or your Claude Code login. The
console needs the Claude Code CLI, signed in. It is installed from this repository's release
wheel, with `install.sh` or by hand, no GitHub account needed (it is not on PyPI);
`docs/setup.md` has every step.

### What is in it

- **Watch.** Topics in a sentence; proposed sources (feeds, Hacker News searches, YouTube
  channels, blogs, GitHub, arXiv and more), each test-read before you tick it; a library of
  kept items with their links, a map of themes, and how much each source costs.
- **News.** A cited brief per topic at the hour you choose, and fuller articles for the items
  with the most behind them.
- **Ideas.** Idea cards from the library, each linked to its items; a review queue with keys;
  your ratings steer what is kept next.
- **Post.** Drafts from a card or a brief: your blog, a newsletter, and short posts for
  Bluesky, Mastodon, X, Threads and LinkedIn. A voice card and samples of your own writing;
  a checker that underlines what reads like AI and what breaks a site's limits; the fix; a
  time to send at. **Nothing is posted without your yes:** Open hands the draft to the site, or,
  with an account connected, Kranto posts it once you approve.
- **The console.** Claude Code beside every page (✦, or Ctrl+J; ⌘J on a Mac). It runs as you, not in a
  sandbox (`docs/threat-model.md`). What an assistant changes that costs money or shapes your
  posts waits for your yes on Needs you; the spend caps and the update settings are yours only.
- **Your own assistant.** `kranto mcp` gives Claude Code, Codex or any MCP client the same
  tools under the same rules (`docs/assistant.md`).
- **Spend.** Every model call is metered; every cap is a setting, none is set unless you set
  one (Settings › Spend).
- **Updates and the way back.** `kranto update` installs a newer release, checks every page and
  rolls back by itself on a failure; `kranto update --rollback` goes back by hand; an update cut
  off while it installs leaves `update/RECOVER.txt`, which puts the previous version back.
- **An install made before the rename** crosses over
  with its data, settings, connections and service unit kept; both commands and both sets of
  variable names keep working.
- **Usage reports are off** until you choose otherwise; `DO_NOT_TRACK=1` wins over every
  setting (`docs/privacy/what-kranto-sends.md`).

### What it is not

- Not a hosted service, not for teams, not a phone app: one person, one machine, loopback only.
- Not for macOS or Windows yet.
- Not a scheduler for many networks and not a feed reader for reading everything.

### What is unproven

- **One install's record.** The costs in the README (about 70 cents a day for five topics) and
  the idea cards' rate were measured on the maintainer's own install. Whether the cards are good
  for anyone else is not measured.
- **Posting for real** has been rehearsed with stand-ins and the preview's switch; each site's
  direct posting needs your own app or token, and the sites' terms change (`docs/accounts.md`).
- The console starts Claude Code with your own login and plan, as you and not in a sandbox;
  whether it opens by itself and what it may do without asking are settings (Settings ›
  Assistant), and `docs/threat-model.md` says what the defaults allow.

### Before you upgrade from an install made before the rename

Read `docs/setup.md` › "Updating" first: its settings must name this repository
(`update.repo: iddv/kranto`), or it never sees a Kranto release. The crossing is two releases: a nightly build in the
old shape (three wheels, for the old update helper), then the one-wheel release. `kranto update
--rollback` goes back at each step.

### If you ran a pre-release: fixed since v0.7.0-dev2

- An install that crossed over from before the rename keeps its connected accounts: Kranto
  reads the secrets file the old version wrote (0.7.0.dev1 and dev2 said "cannot be decrypted
  here") and rewrites it in its own form at the next change; `kranto doctor` says so.
- The console's "Kranto's own Claude config" choice, saved before the rename, is read as that
  again (it fell back to your own config).
- The daily job that reads back the numbers of sent posts now records its run, so it runs once a
  day instead of once a minute.
- A ? tip's **More in the docs** opens the help page; it opened an address that does not exist.
- The short posts' daily job and the newsletter's weekly job no longer run every minute
  after a run that found nothing to do: that run now counts for its day.

### If you ran a pre-release: changed since v0.7.0-dev2

- **A new install has one command, `kranto`.** The command's name from before the rename is no
  longer in the package; an install made before the rename keeps it: `kranto up`, which every
  update runs, links it to `kranto` because the service that install kept starts that name.
- **An unfinished setup shows on the home**, on a phone too: "Kranto is not set up yet", what is
  still missing (a model, a topic, a place to read) and **Set up**, which opens Welcome there.
- **Keys are shown as your computer names them:** Ctrl+K and Ctrl+J on Linux and Windows, ⌘K
  and ⌘J on a Mac, on the page, in the help and in `kranto doctor`.
- Plainer words: `kranto doctor`'s page line, `kranto down` without systemd, `kranto watch
  import`'s help; `kranto uninstall` names GitHub's pages only when GitHub was connected, and
  looking for Claude Code no longer runs npm (which left `~/.npm/_logs` behind).
- **Installing needs no GitHub account:** `install.sh` and the guide's by-hand steps download
  the release's wheel and `SHA256SUMS` from its public addresses and check every hash.
- **The watcher's commands are under `kranto watch`** (`kranto watch topics`, `kranto watch
  websearch "…"`, `kranto watch provider show`, …). Every command Kranto or its docs print now
  runs on an installed Kranto; `python -m kranto.cli` still works from a checkout.
- **A live web search and a page fetch need a sign-in** (`/api/websearch` and
  `/api/websearch/fetch`), as every change does; other reads still need none. A script that
  called them without a token now gets 401; `kranto mcp` and the page send theirs. Switching
  usage reports to basic or detailed, the console's last words and a raw model answer are the
  signed-in page's only.
- **A new home's console asks first and does not open by itself** (`ask: {open: false,
  permission: ask}` in its `loop.yaml`); a home made before keeps what it had. `kranto doctor`
  says how the console behaves.
- **A feature from an unreviewed source waits for your approval at every update**
  (`cubs.auto_update_unreviewed`, off); one from your own folder still updates by itself.
- **The embedding model is kept in `~/.cache/kranto/fastembed`**, not in `/tmp` (gone at a
  reboot on many machines); a copy an older Kranto left in `/tmp` is copied over once.
- When GitHub's rate limit stops the update check, it says so, when it lifts, and that a GitHub
  login avoids it. Without systemd, `kranto uninstall` says when a foreground Kranto still runs,
  and `kranto setup` no longer takes another program on its port for Kranto.
- The page says "feature" where it said "cub", and drops the rename's other leftovers; finding
  places for a new topic says "a few minutes" and ticks first the places that publish.
- Removed what nothing used: the build loop's settings, the `brb` command line, the evals and
  setup-key routes, the browser extension's pairing path.
- NOTICE names the copyright holder, and the package's and the SDK's metadata name the same
  author.
