# Questions people ask first

Short answers to "isn't this just...?" and the other questions a stranger asks in the first
minute. Other projects are named only by kind or where they are well known, and no comparison
here was measured: each answer says what Kranto does differently, not that it does it better.
Written on 2026-11-13; other projects change faster than this page.

## Isn't this just a feed reader with a model?

No. A reader shows you everything you subscribe to, and a model can summarise it. Kranto reads
for you and keeps the few items a day that matter, each linked to where it came from. If you
want to read every item yourself, a reader such as Miniflux or FreshRSS is the better tool.

## Isn't this just a daily AI briefing?

For the brief alone, close. There are open pipelines that read more places than Kranto does and
deliver to more. Kranto differs after the brief: it keeps a library on your machine, writes idea
cards from it, each linked to the items it came from, and drafts a post for you to approve.

## Can't a scheduled task in my chat assistant do this?

For a short brief each morning, yes, and it may cost nothing beyond the plan you already pay
for. It keeps no library, does not read a list of sources you chose, links no idea to its
evidence, and runs on the vendor's machines.

## Is it a web front end for Claude Code?

No. The console, your own Claude Code beside every page, is one part, and Kranto works without
it. If what you want is to drive coding sessions from another screen, tools made for that do it
better. Kranto's tools reach any Claude Code session that has `kranto mcp` added, and any other
MCP client ([assistant.md](assistant.md)).

## Is it a social media scheduler, or a newsletter tool?

Neither. Kranto writes a draft and hands it to one place you connected; you click Send. There
is no calendar and no posting to ten networks at once. If you schedule posts across many
networks, use a scheduler. A newsletter platform sends what you wrote; Kranto writes the draft
it sends.

## Isn't it an idea database?

Hosted idea databases sell everyone the same ideas. Kranto's idea cards come from the topics and
sources you chose, each linked to the items behind it, and your ratings reorder them. Whether the
ideas are good has not been measured.

## Does anything leave my machine without me?

What a model reads goes to the model provider you chose, under your key. Nothing is posted or
sent until you click Send. Usage reports are off until you turn them on
([privacy/what-kranto-sends.md](privacy/what-kranto-sends.md)).

## What does it cost?

Kranto is free software (Apache-2.0). The model calls are billed by your provider to your key.
Every call is metered and shown on Settings › Spend. No spending cap is set unless you set one;
`kranto setup` and Settings › Spend offer one.

## Does it run on macOS or Windows?

Linux only. On macOS only the watching works today; the console and posting need Linux. Windows
is out of scope ([scope.md](scope.md)).

## Can it use a local model?

Setup accepts another OpenAI-compatible endpoint, which is how most local model servers speak.
Nobody has tested Kranto that way yet.

## Is it safe to let it read the open web?

Feed items and pages can carry instructions meant for a model. [threat-model.md](threat-model.md)
says what holds, what does not, and why the console deserves care.
