<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/brand/wordmark-dark.svg">
  <img src="docs/brand/wordmark.svg" alt="kranto" height="48">
</picture>

**Kranto reads the sources you pick, tells you each day what happened and what it suggests, and
drafts the post about it for you to approve.**

It runs on your own Linux machine as one page in your browser. It needs one model (a key, or
your Claude Code login) and costs cents a day. Nothing is posted until you say yes.

```
curl -fsSL https://github.com/iddv/kranto/releases/latest/download/install.sh | sh
```

That installs uv if you have none, downloads the latest release, checks it against the release's
`SHA256SUMS`, installs Kranto and runs `kranto setup`: a few questions, each with a default that
Enter keeps; then it starts Kranto at http://127.0.0.1:8765/ and signs your browser in (`kranto
open` prints a new sign-in link). No GitHub account is needed. Linux only, for now. To
read the script first, or to install without it: [Install](#install). Step by step, with what you
should see: [docs/setup.md](docs/setup.md).

## Who it is for

One person who follows a field for their work or their writing, has a Linux machine that stays
on (a home server, a small VPS, a desktop), and wants the reading done rather than a better
reader. It is not for teams, not a hosted service or a phone app, and not for anyone who wants to
read every item (use a feed reader) or schedule posts across many networks (use a scheduler).

## What it does

- **Watch.** Describe a topic in a sentence. Kranto proposes places to read (feeds, Hacker News
  searches, YouTube channels, blogs) and test-reads each one; nothing is read until you tick it.
- **News.** Every few hours a cheap model reads what is new and keeps the few items that matter,
  each with its link, in a library on your machine. Each topic gets a short brief a day, every
  line linked to the item behind it.
- **Ideas.** Once about 30 items are kept, Kranto writes idea cards: what the news suggests,
  linked to the items it came from.
- **Post.** On any card or brief, ask for a draft: a blog post, a newsletter, or short posts for
  Bluesky, Mastodon, X, Threads and LinkedIn, in your voice, checked for what reads like AI. You
  read it and edit it; then Open hands it to the site, or, with an account connected, Kranto
  posts it once you approve. With nothing connected, copy the text.
- **The console.** Your own Claude Code in a panel beside every page, working on the same
  library through the same tools. It runs as you, not in a sandbox
  ([docs/threat-model.md](docs/threat-model.md)), and opens by itself once setup is done
  (Settings › Assistant turns that off). What it changes that costs money or shapes your posts
  waits for your yes. Optional: Kranto works without it.

## What it costs, and how long it takes

Measured, each with what limits it:

| Claim | The caveat that goes with it |
|---|---|
| **About 70 cents a day for five topics**, on your own model key. | Measured on one install over 14 days, with News on for one topic of the five. The first read of a new library costs about a dollar once. The console runs on your Claude plan and is not in this figure. No spend cap is set unless you set one (`kranto setup`, or Settings › Spend). |
| **A first brief, every item linked, within about ten minutes** of opening the welcome page. | One timed run on a fresh install: 9 minutes 43 seconds from the first page, 4 minutes 54 seconds after Start reading; the model ran on a Claude Code login, not an API key. Installing is not included. A quiet topic may keep nothing for days. |
| **About ten idea cards a week from five topics**, each linked to its items. | One install. Nobody but its owner has read the cards yet; whether they are good is not measured. |

## What it needs

- **Linux**, with [uv](https://docs.astral.sh/uv/). macOS and Windows are not supported yet.
- **One model for reading:** an Anthropic API key (from the
  [Claude Console](https://console.anthropic.com)), an [OpenRouter](https://openrouter.ai) key,
  a key for another OpenAI-compatible endpoint (a local model server speaks this; untested), or,
  as an explicit choice, your Claude Code login (it uses your Claude plan's usage, shared with
  your own Claude Code; Anthropic's terms describe subscription login as meant for ordinary,
  individual use).
- **For the console:** the [Claude Code](https://claude.com/claude-code) CLI, signed in.
- Kranto is not published on PyPI. Install it from a
  [release](https://github.com/iddv/kranto/releases); a package of the same name elsewhere is not
  this project.

## Install

**With the script, read first.** Every release carries `install.sh`; this is the line above in
three steps:

```
curl -fsSLO https://github.com/iddv/kranto/releases/latest/download/install.sh
less install.sh
sh install.sh
```

`sh install.sh --version vX.Y.Z` installs that release instead of the latest, and `sh install.sh
--help` lists the rest. It never runs sudo and writes nothing outside `~/.local` and a temporary
folder.

**By hand, without the script.** The release's wheel, checked against its `SHA256SUMS`, installed
with uv (the same files are on the [release page](https://github.com/iddv/kranto/releases/latest)
for a browser):

```
base=https://github.com/iddv/kranto/releases/latest/download
curl -fsSLO "$base/SHA256SUMS"
wheel=$(grep -o 'kranto-[^ ]*\.whl' SHA256SUMS)
curl -fsSLO "$base/$wheel"
sha256sum -c --ignore-missing SHA256SUMS
uv tool install --python 3.12 "kranto[connections,notify,mcp] @ file://$PWD/$wheel"
kranto up
```

The extras are posting accounts (`connections`), messages to your phone or chat (`notify`) and
`kranto mcp` (`mcp`); `install.sh` and `kranto update` install the same.

`kranto setup` checks the machine and prints this distribution's command for anything missing (it
never runs sudo), then asks where Kranto lives, the port, whether it runs as a service, spend
caps, the model for reading and your first topics. Enter keeps every default.

`kranto up` makes the home (`~/.kranto`), starts `kranto.service` (a systemd user unit; without
systemd it serves in the foreground) and serves http://127.0.0.1:8765/. `kranto open` prints a
new one-time link that signs a browser in.

**From your own Claude Code or another assistant.** Everything the pages do is a tool there too,
under the same rules ([docs/assistant.md](docs/assistant.md)):

    claude mcp add kranto -- kranto mcp                     # Claude Code
    codex mcp add kranto -- kranto mcp --compact            # Codex

## Usage reports

Kranto counts how it is used on your machine and sends nothing unless you choose to: `kranto
setup` and the app's first page ask once, and Enter sends nothing. With basic or detailed chosen,
one report a day goes to the maintainer's relay on AWS in the EU (`KRANTO_TELEMETRY_ENDPOINT`
names another). `kranto telemetry` says what is chosen, `kranto telemetry show` prints the report
as it stands, and `kranto telemetry docs` lists every field. To decide before the first run, set
`DO_NOT_TRACK=1` or `KRANTO_TELEMETRY=off` in Kranto's environment (or `kranto setup --telemetry
off`); either wins over every setting.

## Where things live

Everything is in one home, `~/.kranto` (or `$KRANTO_HOME`): `kranto.yaml` and `.env`, `data/`
(the library) and `loop/` (the page's settings file, `loop.yaml`). Its tokens are in `~/.config/kranto/`. `kranto status` shows the home,
the service, the jobs and the spend on one screen; `kranto doctor` checks everything and names the
fix for each failure.

## How Kranto is made

Most of Kranto's code is written by AI coding agents working from written briefs, and it is
reviewed, tested and run every day by its one maintainer. Every change passes the test suite and
a walk through the pages in a real browser before it ships. The checks run on GitHub Actions
([.github/workflows/ci.yml](.github/workflows/ci.yml)); a pull request from a fork runs them on
GitHub's hosted runners, once the maintainer has approved the run. If you would rather not run software
made this way, Kranto is not for you, and that is fine.

## Documentation

[docs/README.md](docs/README.md) lists every page. To start with:

- [docs/setup.md](docs/setup.md): installing, step by step, with what you should see.
- [CHANGELOG.md](CHANGELOG.md): what each release changed, and what is still unproven.
- [docs/faq.md](docs/faq.md): "isn't this just…", answered.
- [docs/scope.md](docs/scope.md): what Kranto will not do.
- [docs/GLOSSARY.md](docs/GLOSSARY.md): the words Kranto uses.
- [RESPONSIBLE_USE.md](RESPONSIBLE_USE.md): source terms, personal data, retention, and what the
  person running Kranto is responsible for.
- [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md) (reporting a vulnerability
  privately, and the threat model), [SUPPORT.md](SUPPORT.md).

## License

Apache-2.0. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
