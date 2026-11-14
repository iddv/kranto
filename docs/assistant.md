# Use Kranto from your own Claude Code or Codex

Everything you can do on Kranto's pages is also a tool your own assistant can use: add a
topic, approve sources, brief a topic, write a post about an idea. The assistant reaches Kranto
through `kranto mcp` on this machine, and Kranto decides on its side what an assistant may do by
itself ([verbs.md](verbs.md): the ladder on Settings › Assistant).

## Claude Code: the plugin

    claude plugin marketplace add iddv/kranto && claude plugin install kranto@kranto

or let Kranto run those two lines for you, after showing them: `kranto assistant global claude`
(it changes nothing until you add `--yes`). The plugin carries:

- **Kranto's tools** (`kranto mcp`): one tool per verb you may run, the reads, and `kranto_verbs`
  and `kranto_act`. Claude Code loads their names only and a definition when it is used.
- **the `kranto` skill**: what Kranto is and how its tools work, loaded when Kranto is the
  subject (its one-line description, about 150 tokens, is always there), and short ones:
  `/kranto:add-topic`, `/kranto:status`, `/kranto:telemetry` (what Kranto's usage reports would
  send and how to choose) and `/kranto:report-issue`: when your assistant
  finds a bug in Kranto, or Kranto does something it shouldn't, it proposes filing it and asks
  you; it gathers the evidence (the version, what was done, `kranto_outcomes`' refusal, a
  repro) and prepares the issue with `kranto_factory_issue`, which your approval in Needs you
  files. Kranto makes the issue's fingerprint itself.
- **`kranto-digger`**, a read-only helper for a deep dive into a topic's sources and evidence,
  or a run's trace, so the main conversation stays short.
- **three hooks**: your assistant cannot read or edit Kranto's secrets (`data/secrets/`, `.env`,
  `~/.config/kranto/tokens/`); Kranto's own tools are not asked about twice: Kranto's ladder
  already decides them, so Claude Code does not prompt for them as well; and the usage hook
  (`hooks/telemetry.py`), which hands Kranto what only the session sees (its start, end and
  length, the model, Kranto's slash commands by name, a Kranto tool call that failed) and which
  Kranto keeps only as your usage-report choice allows ([what Kranto
  sends](privacy/what-kranto-sends.md#the-assistants-usage-detailed-only)). It never touches
  the network, holds no credential, never slows the session, and says nothing but one line,
  once, to an install that never answered the usage-report question. It also refuses to let
  the assistant raise that choice (`kranto telemetry basic|detailed`, or a sending mode written
  into `kranto.yaml`): consent is yours, on the page.

At start the plugin adds about 300 tokens (`claude plugin details kranto`), plus the tools'
names. Try it for one session without installing it:
`claude --plugin-dir "$(kranto paths plugin)"`.

## The console in Kranto's page

The console is your own Claude Code (or Codex) docked at the right of every page, with the same
plugin. An empty console (no conversation yet, or a new one) offers three questions above its
prompt: "What is new in Robotics?" (the topic of the page you are on, else the one with the
newest brief), "Which idea should I look at?", and "Write a post about this" on a card or a brief
(elsewhere "Write a post about this week's news"). A click starts the session if none runs, types
the question and sends it; the question names the card or the brief, since the assistant is not
told which page you are on. A post it writes is a draft that waits on Post; sending is yours.

On a phone you can read and approve. Start a conversation on a wider screen. There ✦ in the bar
of doors opens a sheet, not a terminal: what waits for your yes (each item an assistant
prepared, with Review) and what the console last said, with the page it linked; one link opens
the terminal full screen anyway.

The plugin's copy is written when the console starts, so a change to its skills (a feature you
turn on or off brings or takes away its skill) reaches the console at its next start: Settings ›
Assistant › Restart now, or the next time Kranto starts.

## Codex

Codex is the client to use if you do not use Claude Code. One line adds Kranto:

    codex mcp add kranto -- kranto mcp --compact

Codex keeps its MCP servers in `~/.codex/config.toml` (or `$CODEX_HOME/config.toml`), and the
line adds this entry there. You can write it by hand instead:

```toml
[mcp_servers.kranto]
command = "kranto"
args = ["mcp", "--compact"]
```

Kranto must be running (`kranto up`); `kranto mcp` never starts it, and each tool says so when it
is down. Codex loads every tool's definition on every turn, so `--compact` gives it the few
generic tools (`kranto_read`, `kranto_verbs`, `kranto_act`, `kranto_search`, …): the same verbs,
through `kranto_act`. `kranto assistant global codex` runs that line and copies the skills into
`~/.agents/skills`, after showing both. In Kranto's own folder, `kranto assistant setup` writes
`AGENTS.md`, the skills (`.agents/skills/`), the agent (`.codex/agents/`) and the hooks
(`.codex/hooks.json`: the secrets hook and the usage hook, on Codex's SessionStart,
SessionEnd, UserPromptSubmit, PostToolUse and Stop; Codex asks you once to trust them, and
again after `kranto update` changes the file). It writes nothing outside Kranto's home and never
replaces a file of yours. Without the hooks, Kranto still counts every verb Codex calls, at its
own door.

## Any other MCP client

Any client that starts a local MCP server over stdio can use Kranto. Its configuration names the
command `kranto` with the argument `mcp` (add `--compact` for a client that loads every tool's
definition on every turn). In the common JSON form:

    {"mcpServers": {"kranto": {"command": "kranto", "args": ["mcp"]}}}

The tools only: no skill, no hooks. [mcp.md](mcp.md) has how the server works and every tool.

## What every client gets, and what it does not

- The same verbs and the same ladder as the console in Kranto's page: done at once, prepared for
  your approval on the page (and in Needs you), or off. "Prepared" means nothing happened yet.
- The page shows what it did: Activity has the run marked "by Claude Code (outside)" or "by
  Codex (outside)".
- Never an assistant's, whatever the ladder says: keys, tokens and logins; approving
  what a cub asks (sending an issue, posting). They are not tools.
- `kranto assistant` shows what is set up; `kranto doctor` has an Assistant line.
