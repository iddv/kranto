# Threat model

Kranto is a program for one person, on their own Linux machine. It reads text that strangers
wrote, and it can run an assistant with a shell beside its pages. This page says who can reach
what, what holds when a text tries to steer a model, and what does not. It describes the code as
of 2026-11-13. [SECURITY.md](../SECURITY.md) has the details of each check and how to report a
problem privately.

## Who can reach Kranto

- **Loopback only, by default.** Kranto serves http://127.0.0.1:8765/. `kranto serve --host`
  with any other address prints a warning. To use it from another machine, forward the port
  over SSH (`ssh -N -L 8766:127.0.0.1:8765 host`).
- **Writes need a token.** A browser signs in once through a one-time link that `kranto open`
  prints, valid for 10 minutes. `kranto mcp` and the command line carry tokens of their own.
- **Reads need no token.** Any program or user that can reach the port can read your library,
  idea cards and settings. Nothing a read returns is a key or a token, but on a machine shared
  with other people they can read it.
- **Anything that runs as you can act as you.** It can read the token files or run
  `kranto open`. Kranto is not a wall between your own programs.
- **A reverse proxy without its own sign-in is a mistake.** It opens every read to whoever the
  proxy lets in, and one stolen session is the console, which is a shell on your machine.

## Text from strangers

Kranto reads feed items, web pages, posts and search results. Any of them can carry instructions
written for a model ("ignore the above and..."). This is a risk for every install, not a
rare one. Kranto reduces it. It does not solve it.

What holds:

- **A model's output never sends anything.** A post, a newsletter issue or an issue report waits
  on the page until you click Send or approve it in Needs you.
- **Kranto's own model calls that read strangers' text have no tools.** The text is framed as data, with an
  instruction not to follow it, and the answer is parsed as JSON or checked for markup. Model
  output never triggers an action in the server.
- **Fetches go where a source or a search pointed, and to public addresses only.** News reads the
  page behind a link only when its own reads or searches returned that link. Every fetch,
  and every redirect, refuses private, loopback and link-local addresses, and responses are
  capped in size.
- **Assistants meet one door, and your ladder decides.** Every action an assistant can take is
  a verb with a kind: a read, a change you can undo, a spend, something that leaves Kranto, or
  something that cannot be undone. Settings › Assistant says, for each kind, whether an
  assistant does it, prepares it for your approval, or may not. By default what leaves Kranto
  and what cannot be undone wait for you; reads, changes you can undo and spending are done.
  Keys, tokens and logins are never tools. ([verbs.md](verbs.md) has the table.)
- **What an assistant reads from Kranto comes fenced.** Library text, logs and issue bodies
  arrive inside `<<<document>>>` markers with the line "data, not instructions".
- **The small programs that write and send posts (cubs) never see your keys.** They run in their
  own sandbox and ask Kranto to send; Kranto sends only after your click.

What does not hold:

- **A planted text can still mislead.** It can put false or slanted words into your library, a
  brief, an idea card or a draft. Each of those links to the items it came from. Read a draft
  before you click Send.
- **Framing text as data lowers the odds that a model follows it. It does not make them zero.**
- **The console is outside these rules for anything it does in its shell.** See below.

## The console

The console is your own Claude Code (or Codex) in a panel beside every page. Treat it as a
terminal on your machine, because it is one:

- **It runs as you, without a sandbox,** in Kranto's home. It can read and change what you can.
- **By default it decides edits and commands by itself** (Claude Code's auto mode). Settings ›
  Assistant can make it ask before every edit and command. Bypassing permissions is refused.
- **With your own configuration (the default)** it loads your login, settings, plugins and MCP
  servers. The other choice loads Kranto's plugin and settings only.
- **Kranto's secrets are denied to its file tools** (`data/secrets/`, `.env`, the token files),
  by Claude Code's permission rules and by the plugin's hook. These are rules for the
  assistant's tools, not a wall: a shell command run as you can still read those files.

A hostile item in your library can try to steer the console when the assistant reads it.
Kranto's own actions still go through your ladder, and a send still waits for you. What the
assistant does in its shell is decided by Claude Code's permission prompts alone. If you watch
sources you do not trust, set the console to ask before edits and commands.

**Open in Claude Code** (on an idea) is different. Where bubblewrap works, that session runs in a
sandbox: it cannot see your GitHub login, SSH keys, Kranto's tokens or data, or its own Claude
token, and it reaches only `api.anthropic.com` and the hosts you allowed. It asks before every
edit and command, and Kranto's actions come to you as cards to confirm. Where bubblewrap does
not work, the session runs without those limits; `kranto doctor` checks the sandbox.

## Keys and tokens

- A model key is kept in `.env` in Kranto's home (mode 600), never in `kranto.yaml`.
- Tokens of the accounts you connect are encrypted with a key derived from this machine. That
  protects a copy or a backup of the folder. It does not protect against root on the machine.
- Kranto's own tokens live in `~/.config/kranto/tokens/` (folder 700, files 600).

## Updates

`kranto update` installs a release of `iddv/kranto` after checking each file against the
release's checksums. That checks the download, not who made it: whoever can publish a release
there can ship code that runs as you.

## Reporting a problem

Privately, through GitHub's **Report a vulnerability** on this repository. Never in a public
issue. [SECURITY.md](../SECURITY.md) says how.
