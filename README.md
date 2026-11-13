# Kranto

New here? Start with [docs/setup.md](docs/setup.md).

**Kranto watches the topics you choose, keeps what is worth remembering, writes idea cards from
it, and builds the ones you pick.** It runs on your own Linux machine, as one app with one page
in your browser at http://127.0.0.1:8765/.

- **Topics.** You describe a topic in a sentence. A scout proposes places to read (feeds, Hacker
  News searches, YouTube channels, blogs), test-fetches each one, and nothing is read until you
  tick it.
- **Gathering.** Every three hours a cheap model reads what is new and keep the few items
  that matter, each with its source link, in an append-only library on your machine. Your
  ratings steer what is gathered next.
- **Ideas.** Once there are about 30 observations, the library is mapped into themes, and idea
  cards propose a known pattern whose preconditions now appear to hold somewhere new, every
  claim linked to the observation it cites. Expect the first ones after a week or two of reading.
- **News.** Each topic gets a short brief a day, every line cited, and the item with the most
  behind it a full article. Any item can become an idea.
- **The console.** Your own Claude Code in a panel beside every page, sandboxed, doing what the
  pages do under the same rules (it needs Claude Code; Kranto works without it).
- **Posting.** Write a post about an idea (a blog draft, or a short toot), read it on Post, and
  send it to the platform you connected. Nothing is sent without your click.
- **Builds.** Pick an idea (or type your own) and Kranto builds it into a small, tested program
  with Claude Code, in a bubblewrap sandbox, and pushes it to a new **private** repository in
  your GitHub account. Nothing becomes public without your click.

It is one Python package, `kranto`, with the page's built files inside it: one install, one
command, one app.

## What it needs, and what it costs

- **Linux**, with [uv](https://docs.astral.sh/uv/) (the installer fetches it) and bubblewrap
  (`sudo apt install bubblewrap`) for builds. On macOS only the watching works.
- **For watching, one model:** an Anthropic API key (the Claude API, from the
  [Claude Console](https://console.anthropic.com)), an [OpenRouter](https://openrouter.ai) key,
  a key for another OpenAI-compatible endpoint, or, as an explicit choice, your Claude Code
  login (it uses your Claude plan's usage windows, shared with your own Claude Code and with
  builds; Anthropic's terms describe subscription login as meant for ordinary, individual use).
  Watching costs cents a day on a cheap model.
- **For building:** the [Claude Code](https://claude.com/claude-code) CLI signed in, and GitHub
  (Kranto's own sign-in, or the `gh` CLI logged in). A build has cost $10 to $14 on the Claude
  account it runs on.
- **No spend cap is set unless you set one** (`kranto setup`, or Settings › Spend). Every model
  call is metered, and each build shows the tokens it used.

## Install

Every release carries `install.sh`. While the repositories are private, download it from the
[latest release](https://github.com/iddv/kranto/releases/latest) (signed in on github.com, with
the invitations accepted) and run:

```
sh install.sh
```

It installs uv when you have none, downloads the release (with your `gh` login, or GitHub's
device sign-in when gh is not logged in), checks every file against `SHA256SUMS`, installs Kranto
and runs **`kranto setup`**. Setup checks the machine and prints this distribution's command for
anything missing (it never runs sudo). Then it asks where Kranto lives, the port, whether it runs
as a service, spend caps, the model for watching, GitHub, usage reports and your first topics.
Enter keeps every default, and nothing is asked without a terminal. It starts Kranto; `kranto open`
prints a one-time link that signs your browser in.

The same by hand, from the latest release:

```
tag=$(gh release view -R iddv/kranto --json tagName --jq .tagName)
gh release download "$tag" -R iddv/kranto -p '*.whl' -p SHA256SUMS -D "kranto-$tag"
(cd "kranto-$tag" && sha256sum -c SHA256SUMS)
uv tool install --python 3.12 "kranto-$tag"/kranto-*.whl
kranto up
```

`kranto up` makes the home (`~/.kranto`), starts `kranto.service` (a systemd user unit; without
systemd it serves in the foreground) and serves http://127.0.0.1:8765/. Every step, with what you
should see, is in [docs/setup.md](docs/setup.md).

## The first ten minutes

Measured on a fresh install (a new user, the 0.4.10 release, 2026-10-20):

1. **Install** (`sh install.sh`): about a minute, most of it downloading.
2. **Sign in**: `kranto open` prints a one-time link; open it on the same machine. The start page
   has one button, **Set up Kranto**.
3. **Welcome, step 1, Which model reads for you?**: paste a model key (it is tested before it
   is kept; the test is free), or use your Claude Code login (one click; your Claude plan).
4. **Step 2, First topic**: one sentence, then **Find places to read** (about two minutes; the
   page says what it is doing). The five places that fit best are ticked. **Watch these**.
5. **Step 3, Ready**: when the first brief comes, what it costs, whether Claude Code is there
   for the console, and usage reports (off until you turn them on). **Start reading** starts
   the first read and asks how you write (skippable); the home then shows the first hour.

Then leave it. The first brief is written as soon as the first read has kept 8 items (aimed at
under 8 minutes from the first page), and once more when the read ends; ideas come after the
first night's map once 30 items are kept. Grade what you see (▲ ▼): your grades steer the
gathering.

**From your own Claude Code or Codex.** Everything the pages do is a tool there too, under the
same rules ([docs/assistant.md](docs/assistant.md)):

    /plugin install kranto --marketplace iddv/kranto      # Claude Code
    codex mcp add kranto -- kranto mcp --compact          # Codex

## Usage reports

Kranto counts how it is used on your machine and sends nothing unless you
choose to: `kranto setup` and the app's first page ask once, and Enter sends nothing. With
basic or detailed chosen, one report a day goes to the maintainer's relay on AWS in the EU
(`KRANTO_TELEMETRY_ENDPOINT` names another). `kranto telemetry` says what is chosen,
`kranto telemetry show` prints the report as it stands, and `kranto telemetry docs` lists every
field and the notice. To decide before the first run, set `DO_NOT_TRACK=1` or
`KRANTO_TELEMETRY=off` in Kranto's environment (or `kranto setup --telemetry off`); either wins
over every setting.

## Where things live

A kranto install keeps everything in one home, `~/.kranto` (or `$KRANTO_HOME`): `kranto.yaml` and
`.env`, `data/` (the library), `loop/` (the build loop's `loop.yaml` and ledger) and `tasks/`
(one folder per build). Its tokens are in `~/.config/kranto/`. `kranto status` shows the homes,
the service, the jobs and the spend on one screen; `kranto doctor` checks everything and names
the fix for each failure.

## The watcher alone

The watcher also runs on its own, from a checkout (`python -m kranto.cli`): see
[docs/watcher.md](docs/watcher.md), which also covers what the library holds, the source kinds,
the costs measured per item, every command of the watcher alone and how data is kept and expires.

## Documentation

[docs/README.md](docs/README.md) lists every page. The ones to start with:

- [docs/setup.md](docs/setup.md): installing, step by step, with what you should see.
- [docs/GLOSSARY.md](docs/GLOSSARY.md): the words Kranto uses.
- [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md): source terms, personal data, retention, and what the person running Kranto is responsible for.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) (reporting a vulnerability privately, and the threat model), [SUPPORT.md](SUPPORT.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
