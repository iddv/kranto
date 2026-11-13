# Kranto's documentation

Every page in this repository, by what you are trying to do.

## Before you install

| Page | What it covers |
|---|---|
| [faq.md](faq.md) | The questions people ask first, "isn't this just...?" among them |
| [scope.md](scope.md) | What Kranto will not become, and what comes next |
| [threat-model.md](threat-model.md) | Who can reach what, what holds when a text tries to steer a model, and the console |

## Using Kranto

| Page | What it covers |
|---|---|
| [setup.md](setup.md) | Installing, step by step, with what you should see after each step; troubleshooting |
| [ui.md](ui.md) | The page: how it is built, its routes, the console, and where each part lives |
| [mcp.md](mcp.md) | `kranto mcp`: Kranto as an MCP server for your own assistant, and every tool |
| [traces.md](traces.md) | Traces: what a session did, span by span, and how to export one |
| [watcher.md](watcher.md) | The watcher in detail: the library, the map, ideas, sources, costs per item, every command of the watcher, how data is kept and expires; the watcher on its own |
| [archive.md](archive.md) | `kranto archive`: the record of the features that left Kranto, and what happens to their settings |
| [memory.md](memory.md) | How much memory Kranto uses, its caps, and how to change them |
| [activity.md](activity.md) | What Kranto is doing: every background run recorded as it goes, Stop, failures said once, the activity read and its settings |
| [prose.md](prose.md) | How Kranto writes your posts: your voice card and samples, the floor against AI tells, the checker, the fix, learning from your edits, and the API |
| [assistant.md](assistant.md) | Use Kranto from your own Claude Code (the plugin), Codex (its config) or another MCP client: what each gets |
| [verbs.md](verbs.md) | Everything you can do, as one table for every caller: the console, your own Claude Code or Codex, a script with its own token; what an assistant may do by itself (the ladder) and the locks |
| [GLOSSARY.md](GLOSSARY.md) | The words Kranto uses, in the app and in this repository |
| [accounts.md](accounts.md) | Each provider and site Kranto can use: what it needs, and what to check in its terms (dated) |
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
| [../SECURITY.md](../SECURITY.md) | Reporting a vulnerability privately, and each security check in detail |
| [../SUPPORT.md](../SUPPORT.md) | Where questions go |
| [brand/README.md](brand/README.md) | The mark, the colour and the name |

## Why it is built this way

| Page | What it covers |
|---|---|
| [design/VISION.md](design/VISION.md) | The idea Kranto comes from |
| [design/TENETS.md](design/TENETS.md) | How Kranto is asked to think (sent to the model with every judging call) |
| [design/DECISIONS.md](design/DECISIONS.md) | Why each mechanism exists, with the evidence |
| [design/DESIGN.md](design/DESIGN.md) | The original plan, kept as written |
