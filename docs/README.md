# Kranto's documentation

Every page in this repository, by what you are trying to do.

## Using Kranto

| Page | What it covers |
|---|---|
| [setup.md](setup.md) | Installing, step by step, with what you should see after each step; troubleshooting |
| [ui.md](ui.md) | The page: how it is built, its routes, the console, and where each part lives |
| [mcp.md](mcp.md) | `kranto mcp`: Kranto as an MCP server for your own assistant, and every tool |
| [traces.md](traces.md) | Traces: what a session did, span by span, and how to export one |
| [watcher.md](watcher.md) | The watcher in detail: the library, the map, ideas, sources, costs per item, every `afk` command, how data is kept and expires; `afk` on its own and in Docker |
| [archive.md](archive.md) | `kranto archive`: the record of the features that left Kranto, and what happens to their settings |
| [memory.md](memory.md) | How much memory Kranto uses, its caps, and how to change them |
| [activity.md](activity.md) | What Kranto is doing: every background run recorded as it goes, Stop, failures said once, the activity read and its settings |
| [prose.md](prose.md) | How Kranto writes your posts: your voice card and samples, the floor against AI tells, the checker, the fix, learning from your edits, and the API |
| [posting.md](posting.md) | Posting: your own site first, then the sites people use; Open or Post directly, which sites and why, how a short post is written, what to connect |
| [assistant.md](assistant.md) | Use Kranto from your own Claude Code (the plugin) or Codex: one install line each, what each gets |
| [verbs.md](verbs.md) | Everything you can do, as one table for every caller: the console, your own Claude Code or Codex, an agent; what an assistant may do by itself (the ladder) and the locks |
| [GLOSSARY.md](GLOSSARY.md) | The words Kranto uses, in the app and in both repositories |
| [news.md](news.md) | News: a short, cited brief per topic |
| [privacy/what-kranto-sends.md](privacy/what-kranto-sends.md) | Usage reports: every field, made from the allow-list |
| [../RESPONSIBLE_USE.md](../RESPONSIBLE_USE.md) | Source terms, personal data, retention, and what the person running Kranto is responsible for |

## Extending Kranto

| Page | What it covers |
|---|---|
| [features.md](features.md) | How Kranto is extended: features, their manifest, the bus and the seven generic surfaces |
| [cubs.md](cubs.md), [../sdk/README.md](../sdk/README.md) | Writing a cub (a sandboxed extension) and its SDK |
| [cub-protocol.md](cub-protocol.md) | `cub/1`, the protocol between Kranto and a cub's process: every method, its shapes, errors, grant and limits |
| [newsletter.md](newsletter.md) | Sending a newsletter cub's issues through the platform you connect: each platform's steps, what each action does, undo |

## How Kranto is measured

| Page | What it covers |
|---|---|
| [evals.md](evals.md) | `kranto eval`: whether a change made Kranto better |

## Working on Kranto

| Page | What it covers |
|---|---|
| [../CONTRIBUTING.md](../CONTRIBUTING.md) | Setup, the rules the code depends on, merging and releasing, pull requests from forks |
| [OPERATING.md](OPERATING.md) | The operator manual: the data model, jobs, money, runbooks, invariants |
| [preview.md](preview.md) | The preview: a second Kranto built from a branch, on a copy of your data, that cannot send (`kranto-preview`) |
| [../SECURITY.md](../SECURITY.md) | Reporting a vulnerability privately, and the threat model |
| [../SUPPORT.md](../SUPPORT.md) | Where questions go |
| [../ops/telemetry/README.md](../ops/telemetry/README.md) | The maintainer's side of usage reports: the relay and its dashboard |
| [brand/README.md](brand/README.md) | The logo and its variants |

## Why it is built this way

| Page | What it covers |
|---|---|
| [design/VISION.md](design/VISION.md) | The idea Kranto comes from |
| [design/TENETS.md](design/TENETS.md) | How Kranto is asked to think (sent to the model with every judging call) |
| [design/DECISIONS.md](design/DECISIONS.md) | Why each mechanism exists, with the evidence |
| [design/DESIGN.md](design/DESIGN.md) | The original plan, kept as written |
