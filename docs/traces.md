# Traces

What Kranto does is Claude Code sessions, tool calls and model calls. A trace shows
them the way an observability tool shows a request, not as a log file: a tree of sessions,
turns and tool calls with their inputs, outputs, timings and tokens, the conversation as a
chat, each edit as a diff, and the step that failed marked. A trace grows live while its run
runs.

Kranto keeps nothing new to make a trace: it reads the files a session already writes, where
they are (each session's transcript, the server's record of a run's model calls). The only thing
it writes is a cache, `trace.db` in the home's `loop/` folder (`~/.kranto/loop/` by default): the trace list and the text the search reads,
beside your other Kranto files, made again whenever it is missing.

## What has a trace

- **An Open in Claude Code session**, and the console's: its conversation, `session:<id>`. A
  session that ended before Kranto 0.5.0 kept no transcript, and its trace says so. One you
  continued in your own terminal stops at the hand-over.
- **A Watching run**: an ingest, an analyst run, a brief, a cub's run, `afk:<run>`. Each model
  call's request and answer as the server kept them; a cub's host calls show their operation and
  never their payload. A run that made no model calls says so, and its summary is in the run's
  Overview.

Traces of builds and maintenance fixes left Kranto with those features; their files stay on
disk, unread ([archive.md](archive.md)).

## Where to open one

- The **Trace** list: the sessions and the server's runs, newest first.
- **Open in Claude Code** and the console: **Trace** in the panel's head, for the session
  running or the one before it.
- **Activity**: a run's row opens its trace.
- The command palette (Ctrl+K; ⌘K on a Mac): "Trace of …".

## The page

The head says the state, the sessions, tool calls, tokens and time, and where it failed (a link
to that span). A trace that is short or stops says why.

- **Tree**, **Timeline** (bars over the run's time) or **Log** (one line a span; the phone's
  form).
- The selected span opens on the right (on the phone, as a sheet): **Overview**, **Input**,
  **Output**, **Chat** (the session as messages, thinking folded), **Diff** (an Edit or a Write),
  **Raw**.
- **Errors only**, a **Tool**, a **Stage** and a **Kind** filter, and the search box (`/`). The
  search looks in what the trace holds at hand: names, previews, each call's input and the start
  of its output. **Search every payload…** then reads the trace's files: every tool's whole input
  and output, every turn's words and thinking, at most 500 matches.
- **Download (redacted)**: the trace as JSON, every payload included and redacted.
- Keys: `j` `k` move, `←` `→` fold, `e` the next error, `t` the next tool call, `1`–`6` the
  inspector's tabs, `f` follow the end while it runs, `esc` closes the span, then goes back.

Tokens are shown where a step used some; money is on Settings › Spend, not here. The command
line and the API carry each span's cost for anyone who wants it.

### Live

While a session runs, its trace page asks Kranto to watch its files; each new line shows as new
rows within a second or two, the running span pulses, and the head says what runs now. If the
page loses its connection, it reads on from where it was as soon as the connection is back.

## Redaction and who may read

A trace holds file contents, prompts and command output, so it is yours only: the page signed
in, or the command line on this machine. Any other caller is refused, including an agent's
token or `kranto mcp`.

Everything is redacted as it is shown or sent: tokens and keys of the known shapes, credentials
in URLs, private keys, e-mail addresses and phone numbers. A
tool that read or wrote a credentials file (`.env`, a token file) shows that it did, never the
contents. The page never draws a raw line: **Raw** gives the command to read it at your own
terminal.

## The command line

`kranto trace`:

```
kranto trace list [--since 7d] [--state error]
kranto trace show session:<id> [--errors] [--all]
kranto trace show session:<id> --span <id> [--raw]
kranto trace follow session:<id>
kranto trace export session:<id> --otlp http://127.0.0.1:4318 [--content]
```

- `show` prints the tree with the failure marked; `--errors` keeps the error spans and their
  ancestors; `--span` prints one span and its payload; `--raw` that span's lines from the file,
  unredacted, with the path: your terminal only. `--json` prints the records; `--share` also
  hides the host, your login and your home.
- `follow` prints each span as it lands, a running one again when it ends, until the session
  ends or Ctrl-C.
- `export` sends the trace to an OpenTelemetry collector (OTLP over HTTP) with the GenAI
  attribute names; the turns' messages and the tools' arguments and results only with
  `--content`, redacted. `--out <file>` writes the JSON instead of sending it.

## Settings

In `loop.yaml`, the page's settings file (`~/.kranto/loop/loop.yaml` by default):

| Key | Default | What it decides |
|---|---|---|
| `trace.page_kb` | 64 | A long output or message is shown this many KB at a time |
| `trace.payload_max_mb` | 2 | A single line bigger than this is not drawn or searched; the page names the file and the byte to open it at |
| `trace.export.otlp_url` | none | Where `kranto trace export --otlp` sends a trace when no address is given (this machine only) |
| `trace.export.content` | false | An exported trace carries the messages and the tools' arguments and results, redacted |
