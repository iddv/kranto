# Setting up Kranto for the first time

Kranto reads the sources you choose for your topics, keeps what is worth remembering, writes a
short brief each day and idea cards from what it kept, and drafts posts for you to approve. It
is one app: one install, one command to start it, one page in your browser at
http://127.0.0.1:8765/. It runs on Linux.

This guide is for you and, if you use one, the assistant that helps you. Every step has the
exact commands and what you should see when it worked. Kranto is pre-release: expect rough
edges, and please report them (see the end).

**For an assistant following this guide:** run the commands, compare the output with "You
should see", and stop to ask your person at the steps marked **(person)**. Those need a browser,
a login or a key that only they can give. Never print or paste the contents of token files,
`~/.kranto/.env` or anything under `~/.config/kranto/`.

## The short way: install.sh

Every release carries `install.sh`. Download it from the
[latest release](https://github.com/iddv/kranto/releases/latest) in your browser (you are
signed in on github.com and have accepted the invitations) and run:

```sh
sh install.sh
```

It installs uv when you have none, downloads the release with your `gh` login (it says how to
get gh when you have none), checks every file against `SHA256SUMS` before anything installs,
runs `uv tool install` exactly as step 2 below does, then runs `kranto setup`. Nothing it does
needs sudo.

**`kranto setup`** asks only what it cannot find, and every question has a default in
`[brackets]` that Enter keeps:

| Section (the Settings page it sets up) | What it does |
|---|---|
| System › This machine | checks Linux, uv, bubblewrap (the sandbox of the posting cubs and of Open in Claude Code), Claude Code and its login (a warn without it: Kranto works without it, the console needs it), systemd and the port; for each missing piece it prints your distribution's command (`sudo apt install bubblewrap`, ...) and waits: check again, skip for now, or stop |
| System › Where Kranto lives | the home (`~/.kranto`), the port (127.0.0.1 only), and whether Kranto runs as a systemd user service that starts at boot |
| Spend › Caps | **no cap is set unless you type one**; it says what Kranto costs (about $5 to $8 a month for one topic with ten sources, on your own model key) and suggests $10 a month for watching |
| Watching › Provider and key | the watcher's model, offered in this order: the Claude API (an Anthropic key), OpenRouter, another OpenAI-compatible endpoint, Claude Code's login (never the default: it says what that means for your plan and Anthropic's terms, and you agree to it), or later. A key is read hidden, tested once (no model runs) and kept in `~/.kranto/.env` (0600). Without a terminal: `--watch anthropic\|openrouter\|endpoint\|claude_code\|later`, `--watch-key-file F`, `--watch-url U`, `--watch-accept-terms`; in an answers file `watch: {provider, key_file, base_url, terms}`. A provider chosen since in the browser stays the default |
| Privacy › Usage reports | asked once; Enter sends nothing |
| System › Starting | writes what the sections decided and starts Kranto |
| Sources › Topics | a name and one sentence each; their sources are ticked in the browser |
| Ready | Welcome's last step in the terminal: Claude Code for the console ("installed and signed in", or "not installed; Kranto works without it" and `curl -fsSL https://claude.ai/install.sh | bash`, then run `claude` once), what it costs and the usage-reports answer; with Kranto running and a source watched it starts the first read (`--no-read` leaves it to Kranto's next read) |

Then it runs the doctor's checks, prints the sign-in link and where things live. Re-run it any
time: Enter everywhere changes nothing (each line says `kept` or `wrote`). `kranto setup
<page>` revisits one Settings page's part: `watching` (the model and live search), `sources`
(X's app), `assistant` (Claude Code's login token for the console), `spend` (the caps),
`privacy` (usage reports) or `system` (this machine, where Kranto lives, starting); a part's own
name (`caps`, `search`, `usage`, `topics`, `ready`, `service`, `machine`, `home`, `claude`,
`start`) works too. The three things it asks are the ones Welcome asks: the model key, the
first topic, and Ready.
Without a terminal, or with `--yes`, nothing is asked; `--answers FILE` (JSON or YAML, never
a secret: a key is a file path, `--watch-key-file`) and `--json` are for scripts.

Then continue at step 4 (check it) and step 5 (sign your browser in). The steps below are the
same install by hand.

## 0. What you need

| You need | Why | Check it |
|---|---|---|
| Linux | The posting cubs and Open in Claude Code run in a bubblewrap sandbox, which needs Linux. Without it (macOS, for one) only the watching works. | `uname -s` prints `Linux` |
| [uv](https://docs.astral.sh/uv/) | Installs Kranto and its Python (3.12; uv downloads it if you have none). | `uv --version` |
| bubblewrap (`bwrap`) | The sandbox every cub and every Open in Claude Code session run in. The console is not sandboxed: it runs as you ([threat-model.md](threat-model.md)). Debian and Ubuntu: `sudo apt install bubblewrap`; Fedora: `sudo dnf install bubblewrap`; Arch: `sudo pacman -S bubblewrap`. | `bwrap --version` |
| The Claude Code CLI, signed in (optional) | The console runs it, on **your** Claude account and usage. Kranto works without it. | `claude auth status` |
| The GitHub CLI (`gh`), logged in | Downloading the release while the repository is private. | `gh auth status` |
| Access to `iddv/kranto` | It is private before launch: accept the invitation first. | `gh repo view iddv/kranto --json name` prints `{"name":"kranto"}` |
| One model for watching: an Anthropic API key (the Claude API, from the [Claude Console](https://console.anthropic.com)), an [OpenRouter](https://openrouter.ai) key, a key for another OpenAI-compatible endpoint, or (an explicit choice, on your Claude plan's usage) your Claude Code login | Watching: a cheap model reads and judges what your sources publish. | You choose it in step 6. |

## 1. Check your GitHub login

```sh
gh auth status
```

**You should see:** `Logged in to github.com account <you>`. If not, run `gh auth login` and
follow it. The next step downloads Kranto with this login, so it works for the private
repository once you have accepted the invitation.

## 2. Install

Kranto is installed from the latest release: one wheel, `kranto`, on a GitHub Release of
`iddv/kranto`, the same file `kranto update` installs later.
Run these in a folder where you keep downloads (they make a `kranto-v0.x.y` folder there):

```sh
tag=$(gh release view -R iddv/kranto --json tagName --jq .tagName)
gh release download "$tag" -R iddv/kranto -p '*.whl' -p SHA256SUMS -D "kranto-$tag"
(cd "kranto-$tag" && sha256sum -c SHA256SUMS)
uv tool install --python 3.12 "kranto[connections,notify,mcp] @ file://$(ls "$PWD/kranto-$tag"/kranto-*.whl)"
kranto --version
```

**You should see:** one `OK` line from `sha256sum`, a list of packages, then the
executables uv installed: `kranto`, and the command's name from before the rename (kept for
installs made then; it runs the same program), and then `kranto 0.x.y`. It takes under a minute.
If your shell then says `kranto: command not found`, run `uv tool update-shell` and open a new
terminal. The downloaded folder can be deleted afterwards.

The three extras are what `install.sh` installs too: `connections` (posting accounts, their
tokens encrypted), `notify` (messages to your phone or chat) and `mcp` (step 9). `kranto update`
keeps them.

**Later:** once the repository is public, the same commands work without an invitation
(and the wheels can also be downloaded from the release page in a browser). Once Kranto is on
PyPI, this step becomes one `uv tool install` line and this guide will say so. Until then,
always install the wheel by path as above.

## 3. Start Kranto

```sh
kranto up
```

**You should see:**

```
kranto home: /home/you/.kranto (new)
  wrote /home/you/.kranto/kranto.yaml
  wrote /home/you/.kranto/data/
  wrote /home/you/.kranto/loop/
  wrote /home/you/.kranto/loop/loop.yaml
  made the ui, mcp, console, cli token(s) in /home/you/.config/kranto/tokens
```

and then one of two endings:

- **With systemd** (most Linux desktops and servers): `Kranto is running: http://127.0.0.1:8765/`
  and a sign-in link. Kranto now runs as the user service `kranto.service`, starts again at
  every boot, and keeps running after you log out (`kranto up` turns on "linger" for your user).
  The terminal is free again.
- **Without a systemd user manager** (a container, WSL without systemd, or a shell whose `HOME`
  is not your login home): `not using systemd: <the reason>; serving in the foreground (Ctrl-C
  stops it)`, then `kranto on http://127.0.0.1:8765` and its log, ending with `Sign a browser in
  with 'kranto open'`. Kranto runs only as long as that terminal does: leave it open, and use a
  second terminal for the next steps (step 5 prints the sign-in link).

Useful options: `kranto up --port 8790` for another port, `kranto up --no-browser` to print the
sign-in link instead of opening a browser. Kranto only ever listens on 127.0.0.1. The home keeps
the port: a later `kranto up --port N` moves it to N (it says `wrote … kranto.yaml (port N)`), and
`kranto open` and `kranto doctor` follow.

`kranto up` rewrites and restarts the unit only when the unit runs this same `kranto` (or the
old command beside it). Run from a checkout or a second tool while another install's command
runs the unit, it stops with `<unit> runs <command>, not this kranto` and changes nothing;
`kranto up --adopt` makes the one you ran the unit's command.

## 4. Check it

```sh
kranto doctor
```

**You should see:** one line per check, each `ok`, `warn` or `FAIL`, and every `FAIL` names its
fix. On a fresh install, before Welcome, lines like these are expected until you finish the
next steps (the model is chosen in step 6):

```
warn  model          none chosen yet: Welcome's first step (Which model reads for you?) chooses one; ...
warn  sources        none approved; add a topic or a pack                               -> step 7
warn  claude         Claude Code is not installed; kranto works without it. For the console: ...
```

Kranto needs neither Claude Code nor `gh` to run: without them `kranto doctor` warns and exits
0. Claude Code is the console's (the panel beside every page). `kranto doctor` exits with 1
while any check fails.

## 5. Sign your browser in (person)

`kranto up` with systemd opens (or prints) a one-time sign-in link; in the foreground it tells
you to run `kranto open`. For a new one at any time:

```sh
kranto open --no-browser
```

**You should see:**

```
This link signs one browser in to kranto (once, within 10 minutes):
open http://127.0.0.1:8765/auth/open?code=…
```

Open that link in a browser on the same machine. **You should see** the kranto start page with a
**Set up Kranto** button. Reading needs no sign-in; anything that changes something does, so a
browser that was never signed in sees the page but cannot act.

On another machine, tunnel the port first, then open the link there:

```sh
ssh -N -L 8765:127.0.0.1:8765 you@the-machine-running-kranto
```

## 6. Set a spend cap if you want one, then the model key (person)

**Spend is uncapped by default.** To cap it, open http://127.0.0.1:8765/#/settings/spend
(**Settings › Spend**, from ⚙ in the top bar): the monthly budget for watching stops the
watching model calls when it is reached. An empty field means no cap. `kranto status` shows the
caps too.

Then click **Set up Kranto** on the start page (or open http://127.0.0.1:8765/#/welcome).
Welcome has three steps, **Model**, **First topic** and **Ready**, and then **How you write**.
Step 1, **Which model reads for you?**, offers the ways in as boxes: **A model key** (**Paste a
key** opens the form below) and **Your Claude Code login** (one click, with Anthropic's terms
sentence beside it; never preselected). Clicking **Test and save** with nothing typed says
"Paste a key first."

1. **A model key**: choose **Claude API** (an Anthropic API key), **OpenRouter**, or
   **Another endpoint** (any OpenAI-compatible one, with its base URL), paste the key and click
   **Test and save**. It is tested with one request that runs no model (the Claude API's model
   list, OpenRouter's key check) and kept in `~/.kranto/.env`, as `ANTHROPIC_API_KEY` or
   `OPENROUTER_API_KEY`. A key already in `.env` or the environment can be chosen without
   pasting it (**Test and use**). On the Claude API Kranto caches the stage prompts and prices
   each call from Anthropic's list prices.

   **Claude Code** (last, never preselected) uses your Claude Code login instead of a key. It
   says, where you choose it: Claude Code as the watching model uses your Claude plan's usage,
   shared with your own Claude Code; when a usage window closes, watching
   pauses until it reopens. Anthropic's terms describe subscription login as meant for
   ordinary, individual use and ask developers building products to use API keys. Its calls
   cost nothing in dollars here: Settings › Spend shows how many there were, and `kranto doctor`
   what they would have cost at API list prices. Each call is `claude -p` with no tools, no MCP server and no
   settings, in an empty folder of the kranto home; `llm.claude_code.sandbox: true` also runs it
   in bubblewrap.

**You should see:** **Works** beside the provider, and **Continue**. Watching needs only this.

### Live search (nothing to do by default)

The scout, idea cards, the weekly editor and the research desk search the live web, so what
they say exists, is new or is prior art comes from dated results rather than a model's memory.
Out of the box they use **Exa's free mode**: it works with no account and no key, and is
rate-limited. Hacker News, GitHub (through your connection) and arXiv are searched too, free.

- **Your own limits:** make a free Exa account (it has $10 of credit a month, about 1,400
  searches) and give Kranto the key: `kranto setup search --search exa --search-key-file FILE`
  (a 0600 file), or Settings (Watching, Live search).
- **Another backend:** `--search brave` or `--search tavily` with that service's key, or
  `--search anthropic` to search with the watcher's Claude API key ($10 per 1,000 searches).
- **Off:** `--search none`. Every caller then says "no live search: results are from model
  memory and may be stale" wherever its output is shown. One caller at a time:
  `search.callers.<name>: off` in `kranto.yaml` (scout, cards, editor, research, resolve,
  pitch, evolve, sources).
- **Check it:** `python -m kranto.cli websearch "local-first sync engines"` (the watcher's own
  command, [watcher.md](watcher.md#the-watcher-alone)) prints the dated results; `kranto
  doctor` has a `search` line. Every search is counted on Settings › Spend (the free ones at
  $0); `search.monthly_usd` caps the paid ones (no cap by default).

## 7. Add your topics (person)

Step 2, **First topic** (later: **Watch › Topics**). A topic is a name and one
sentence in your own words, such as *Home server tooling: small tools that make running a home
server easier and safer.* Click **Find places to read**: one model call proposes places to read,
and every proposal is test-read. It takes about two minutes; while it runs the page says what it
is doing ("Searching the web, Hacker News, GitHub and arXiv, then test-reading each place it
finds"); stay on the page.

**You should see:** `Proposed for "<your topic>"` and a list of places, each with how well it
fits. A topic that watches nothing yet has at most the five that fit best ticked (its first read,
and so its first brief, stays short); the rest stay proposed. Tick the ones to watch and click
**Watch these and continue** (on the topic's Sources page later: **Watch these**); nothing is
watched until you tick it.
The page estimates how many items a day that brings. If you left the page while it scouted,
open the topic (**Watch › Topics**, then its name, then **Sources**): the proposals wait there.

Then Kranto reads every 3 hours and keeps what fits your sentence. The first brief is written as
soon as the first read has kept 8 items, and once more over the whole read when it ends; idea cards come after the first night's map once 30 items
are kept (with only the five best places ticked, that can take a day or two: tick more to go
faster). Ideas show under **Ideas** and under each topic. Grade them (**▲ Useful**, **▼ Not useful**, or the
weekly queue under **Ideas › Review**): your grades reorder the cards.

### Read X (optional, paid, person)

X is off until you connect it. It is read only through X's official API with **your own**
developer account and app, so X bills **your** developer account: $0.005 for each post a reply
returns ($0.001 for your own bookmarks and likes). A typical install (10 topics, one list of
about 200 accounts) is estimated at about $46 a month at the defaults: a list or your home
timeline 20 posts a run, an account 10, searches 10 posts once a day, bookmarks and likes once a
day. Kranto counts every read on **Settings › Spend**; your Developer Console is the bill.

1. Sign in at console.x.com with your X account and accept the Developer Agreement.
2. Buy credits and set a **spending limit** for the billing cycle. X stops answering at a zero
   balance; Kranto then marks the source "X credits exhausted" and tries again six hours later.
3. Create an app named Kranto. For its description, the connection page offers the use-case
   text (also in RESPONSIBLE_USE.md, section X).
4. In the app's **User authentication settings**: type **Native App**, permissions **Read**,
   the callback URL exactly as Settings › Accounts › X prints it
   (`http://127.0.0.1:8765/connections/x/callback` on the default port), website
   `https://github.com/iddv/kranto`. Save.
5. Under **Keys and tokens** copy the **OAuth 2.0 Client ID** (a Native App has no secret: do not
   make one). Paste it on **Settings › Accounts › X** and click **Save**, or run
   `kranto setup sources --x-client-id <id>`.
6. Open Kranto as **http://127.0.0.1:8765** (not localhost: X sends your browser back to exactly
   the callback), click **Connect**, and allow read access. **You should see:** `Connected X /
   Twitter @yourname`.
7. Add X sources from **Add source** (a list of yours is the cheapest signal per post). Each
   source page says what one run reads and costs. To cap X: **Settings › Spend › X a month**
   (empty, the default, is no cap); reached, X sources wait until the first of next month.

Disconnect revokes the tokens at X. X's posts are kept 30 days by default; a post deleted on X
leaves within a week (a weekly check of up to 100 kept posts), and `python -m kranto.cli sources
forget <post URL>` removes one at once. Without an X developer account, an xAI key can search X through Grok
instead (`python -m kranto.cli provider xai --key-stdin`, then **X / Twitter › Search through Grok** in Add
source; xAI bills $5 per 1,000 posts Grok reads, plus the model's tokens).

A post writer can run on its own model, apart from the models that watch your sources
(`docs/prose.md`, "The writer's model"). On **Settings › Posting › How you write**, under **Who
writes**, choose a writer's provider and type the model's name, then Save. For a GPT model,
paste an OpenAI key there and choose **Save and test** (or `kranto provider openai --key-stdin`
from the command line): it goes to Kranto once, is tested, spending nothing, and is kept as
`OPENAI_API_KEY` in the home's `.env` (0600) only when it works; the page never shows it again
and no log holds it. The page's choice is `POST /api/prose/voice` with `{"writer_model": {"blog":
{"provider": "openai", "model": "<a model id>"}}}`; the verb `prose.voice` does not take it, so an
assistant cannot choose a writer's model. The key is used for a writer only, never for watching;
no writer model is chosen for you.

## 8. Ready (person)

Step 3, **Ready**: four lines and a button.

- **The first brief**: "In about 5 minutes."
- **What it costs**: on a key, "About $5 to $8 a month for one topic with ten sources, on your
  own model key. No cap is set; set one in Spend."; on the Claude Code login, "Your Claude plan's
  usage, no bill. The first read is about 200 short model calls, shared with your own Claude
  Code."
- **The console**: "Claude Code is ready. It asks once whether to trust Kranto's folder; that is
  expected.", or "Not installed; Kranto works without it" with the line to fix it (`curl -fsSL
  https://claude.ai/install.sh | bash`, then run `claude` once) and **Check again**.
- **Usage reports**: "Off. Nothing leaves this machine unless you turn them on." **What they
  hold** shows Basic, Detailed and Nothing; nothing is sent unless you choose one that sends.

**Start reading** finishes setup, starts the first read and opens **How you write**: paste a few
things you wrote (put `---` on a line between them), set how long, how formal, opinions and emoji,
and **Save how I write**, or **Skip for now** (posts then follow the shipped rules and plain
words; Settings › Posting changes it later). Either way the home shows **The first hour**: the
read as it goes and the topic's four rows, Sources, First read, First brief (as soon as 8 items
are kept), First ideas (after the map, once 30 items are kept). The status bar says "Reading for
the first time" until the first read ends. The console stays on its rail, starting nothing,
until setup is done; then, with Claude Code installed and signed in, it **starts by itself**
beside the page (untick Settings › Assistant › **Open the console when Kranto opens** to stop
that): Claude Code, as you,
not in a sandbox, asking once whether to trust Kranto's folder.

**You should see:** the home, with **Needs you** at its top, `Kranto is reading <your topic> for
the first time.` and **The first hour**.

## 9. Let an assistant or a script use Kranto

Reads need nothing. Every change needs a token, and each caller gets its own, so the record says
who did what:

```sh
kranto token add agent:helper
```

**You should see:**
`added agent:helper; its token is in /home/you/.config/kranto/tokens/agent-helper.token (mode 600)`.
The caller sends that token with every change, through the same door the page uses
([verbs.md](verbs.md)). Without the token the answer is `not signed in`.
`kranto token list` shows every token (never their values); `kranto token revoke agent:helper`
removes one.

**Over MCP** (Claude Code and other MCP clients), with `kranto[mcp]` installed (step 2):

```sh
claude mcp add --scope user kranto -- kranto mcp
```

`kranto mcp` talks to the running Kranto on 127.0.0.1; it opens no port and never starts Kranto.
`kranto doctor` says `ok    mcp            the MCP extra is installed` when it is ready. Tools whose
description says they need `confirm: true` should be confirmed with you first.

### Open in Claude Code (person)

`c` on an idea opens the real Claude Code about it, in a panel in the page. It works in its own
empty folder, starts with what Kranto knows about it, and asks you before every edit and
command, as Claude Code does in a terminal. Kranto's own actions are never run by it: each one is
a card above the terminal that you **Confirm** or **Dismiss**. While its panel is closed, cards
that wait are a row in Needs you. Where `bwrap` works, the session cannot see your GitHub login,
SSH keys, Kranto's tokens or data, or its own Claude token, and reaches only
`api.anthropic.com` unless you allow another host on its card.

It turns on by itself once Kranto has `bwrap` and a Claude token; `kranto doctor` says which is
missing, and `c` says so in the page. It needs:

1. Your Claude plan: `kranto setup claude` (or `kranto setup assistant`) runs `claude
   setup-token` and keeps the token it prints at `~/.config/kranto/claude/login.env` (0600);
   every session gets it by pipe, with no restart. A token you already give Kranto's unit
   (`CLAUDE_CODE_OAUTH_TOKEN=` in a file a `kranto.service.d` drop-in loads with
   `EnvironmentFile=`) keeps working, and so does a Console API key there
   (`ANTHROPIC_API_KEY=`). The watcher's Claude API key, which Settings › Watching saves in
   Kranto's `.env`, is not used by a session until you choose **Use the API key** in the panel
   (`term.allow_api_key`): without a login token, the page says the session would bill that
   key.
2. `bwrap` (bubblewrap) working. `term: {enabled: false}` in `~/.kranto/loop/loop.yaml` turns it
   off; `true` turns it on without `bwrap`, with a one-line warning that the session runs
   without Kranto's sandbox. Each `c` reads it, so no restart is needed.

**You should see:** `kranto doctor` says `ok    term           Open in Claude Code: sandboxed, its
Claude login token by pipe` (or `its Claude API key by pipe`).

**Continue outside:** the panel's **Continue outside** ends it in the page and shows two
commands for your own terminal: `cd <its folder> && claude --resume <id> …` (your own Claude
Code and permissions, with Kranto's tools while Kranto runs) and `kranto term open <id>` (the same
limits as in the page). `kranto term list` lists the sessions; `kranto term end <id>` ends one for
good and removes its copy, unless a card still uses it.

### Features that left

Builds, projects and repository maintenance, Invest, the trend radar, the browser extension
and deep dives left Kranto; their data is kept,
see [archive.md](archive.md).

## 10. Where Kranto keeps things

| Path | What |
|---|---|
| `~/.kranto/` (or `$KRANTO_HOME`) | The home: `kranto.yaml` (settings), `.env` (the model key), `data/` (the library), `loop/` (the page's `loop.yaml`) |
| `~/.config/kranto/` | `home` (which home `kranto` uses), `tokens/` (mode 600) |
| `~/.config/systemd/user/kranto.service` | The service, when systemd runs Kranto |
| `~/.local/share/uv/tools/kranto/`, `~/.local/bin/kranto` | The installed program |
| `/tmp/fastembed_cache/`, `~/.cache/Microsoft/` | The embedding model's download and its runtime's cache |

An install that was switched over from an older setup with `kranto adopt` keeps its data where it
was; `kranto status` and `kranto doctor`
print the homes in use.

## 11. Every day

| Command | Does |
|---|---|
| `kranto status` | One screen: the service, jobs, spend and caps |
| `kranto doctor` | Every check, each failure with its fix |
| `kranto report [ID]` | Write an error's report (what Send this error sends) to one file and print its path |
| `kranto logs` | The service's log (with systemd) |
| `kranto down` | Stop the service; it starts again at the next boot |
| `kranto update` | Install a newer version; rolls itself back if it does not come up, or if any page it serves fails on your data |
| `kranto doctor --routes` | Read every page the running Kranto serves, once, on your data (what `kranto update` checks before it keeps a new version) |
| `kranto open` | Sign another browser in |

The page has help too: `?` on any page lists its keys, and the `?` tips explain each setting.

### Updating

`kranto update` installs the newest release on your channel (stable unless you chose nightly in
Settings › System), checks every page on your data, and goes back by itself if anything fails.
`kranto update --rollback` goes back to the version before by hand. If an update is cut off while
it installs, `kranto status` names `update/RECOVER.txt`: `sh` it (Troubleshooting).

**An install made before the rename** keeps its old command, its folders and its service. It
crosses in two steps, each with the way back:

1. the nightly build in the old shape (three wheels, the only shape its own update helper
   installs): its old command's `update --to vX.Y.0-devN --yes`; back: `update --rollback --yes`;
2. the next release, one wheel: `kranto update --yes`; back: `kranto update --rollback --yes`.

Its settings must name this repository first (`update.repo: iddv/kranto` in its settings file),
or it never sees a Kranto release. Both commands, and both the old and the new names of the
environment variables, keep working after the crossing.

## 12. Remove Kranto

```sh
# 1. stop the service, keep it from starting at boot and remove its unit (your data stays).
#    --linger-off also turns lingering off, which kranto up turned on; leave it out if anything
#    else of yours needs it. Without systemd: click Ctrl-C in the terminal running kranto
kranto uninstall --linger-off

# 2. the program, and the MCP entry if you added one
uv tool uninstall kranto
claude mcp remove --scope user kranto

# 3. the data, tokens and caches, if you want them gone (this cannot be undone)
rm -rf ~/.kranto ~/.config/kranto
```

**You should see:** `Kranto is stopped and will not start again.` and a line naming where your
data is kept, then uv's `Uninstalled` line, and `kranto` is no longer found.

On a version without `kranto uninstall` (`kranto uninstall --help` fails), step 1 by hand is:

```sh
systemctl --user disable --now kranto.service
rm -f ~/.config/systemd/user/kranto.service
systemctl --user daemon-reload
loginctl disable-linger    # only if nothing else of yours needs it
```

## Known rough edges

- **Spend is uncapped by default**, for watching and for Open in Claude Code. Set a cap in
  step 6, or in `kranto setup`'s Spend section.
- **`kranto down` stops Kranto until the next boot.** `kranto down --disable` keeps it stopped;
  `kranto uninstall` removes the service (step 12).
- **Several places.** Data is in one home (`~/.kranto`), but tokens, the service, the program and
  the caches live elsewhere: see step 10.

## Troubleshooting

| You see | Do |
|---|---|
| `release not found`, `HTTP 404` or `could not find any release` while downloading (step 2) | `gh auth status` (step 1), and check you accepted the repository invitation. |
| `sha256sum` says `FAILED` | The download is incomplete or altered: delete the `kranto-v…` folder and run step 2 again. |
| The page says `this kranto was installed without its web page` | It was installed from git, which carries no built page: install from a release (step 2). |
| `kranto: command not found` after installing | `uv tool update-shell`, then open a new terminal. |
| `not using systemd: …; serving in the foreground` | Expected without a systemd user manager: keep that terminal open. With a `HOME` that is not your login home, systemd is skipped on purpose. |
| `port 8765 is already in use` | Another program (or another Kranto) holds it: `kranto up --port 8790` (the home then keeps 8790). |
| `kranto.service runs …, not this kranto` from `kranto up` | Another install's command runs the unit (you ran a checkout or a second tool): run that one's `kranto up`, or `kranto up --adopt` to make the one you ran the unit's command. |
| `an update was cut off while it installed`, or `kranto status` names `RECOVER.txt` | `sh ~/.kranto/update/RECOVER.txt` (the path it names): it puts the previous version back and removes the file. |
| `FAIL  api key` in `kranto doctor`, or `Scouting failed: no API key: set $OPENROUTER_API_KEY` (or `$ANTHROPIC_API_KEY`) | Paste the key in Welcome › Watching, or Settings › Watching › Watching model (step 6). |
| `Watching paused until … (Claude Code usage limit)` in the top bar or in Health | Your Claude plan's usage window closed. Watching resumes by itself at the time shown, when the window reopens; nothing is lost. |
| `FAIL  claude login` in `kranto doctor` | Run the command it names (`claude auth login`, or `claude update` for an old version). |
| `Watching paused until … (spend limit set in the Claude Console reached)` in the top bar or in Health | The Claude API refused calls for a spend limit. Watching resumes by itself at that time. To go on sooner, raise the limit in the Claude Console, then click **Resume now** in Settings › System › Health (or run `python -m kranto.cli resume`). |
| `FAIL  claude … is not signed in` | `claude auth login`, then `kranto doctor` again. |
| The header says `Can't check for updates: GitHub answered 404 (a private repo needs a GitHub login)` | While the repository is private, Kranto needs a GitHub login that can see it: connect GitHub in Settings › Accounts › GitHub (Kranto uses that login for updates, with or without `gh`), or `gh auth login`. Then **Check for updates** (click the version, or ⌘K). |
| The sign-in link says it expired or was used | Each link works once, within 10 minutes: `kranto open --no-browser` for a new one. |
| A script's write answers `cross-origin request refused` | Your Kranto is older than 0.3.30: `kranto update`, or send `Origin: http://127.0.0.1:8765` (your port) with the `Authorization` header (step 9). |
| `kranto mcp: install the MCP extra` | Install `kranto[mcp]`: the command is in the message, and in step 2. |
| `kranto down` says Kranto is not managed by systemd | It runs in the foreground: click Ctrl-C in its terminal. |

## Reporting

**An error.** When Kranto cannot read one row of a list, the row stays, saying `Couldn't read
this source` (or idea, topic…) with a short error id, and the rest of the page works.
When a whole page fails, Kranto's error page says the version and the error id. Each has **Send
this error**: it opens Feedback with the error's report, which you read before anything is sent
(the error id, the kind of error, the lines of Kranto's own code it went through, the version,
your OS and `kranto doctor`'s summary; never your data, a path in your home or a token). From a
terminal, `kranto report` writes the same report for the newest error (or `kranto report <id>`)
to one file under `~/.kranto/reports/` and prints its path.

Anything else confusing or broken: **Feedback** in the header, or an issue on `iddv/kranto`.
Include the output of `kranto status` and `kranto doctor`. Never include token files,
`~/.kranto/.env` or anything under `~/.config/kranto/`.
