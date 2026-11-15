# Memory

Kranto runs beside everything else on your machine, so it is capped: whatever it does, the
machine keeps working.

## What it uses

Measured on 2026-10-20 (a 12-core machine):

| | Resident memory |
|---|---|
| The server between reads (the embedding model is let go after 10 minutes unused) | about 0.25 GB |
| The server with the embedding model loaded | about 0.8 GB |
| A first read of a new topic (8 sources, 40 items each) | peaks at about 1.2 GB |
| A read of 130 sources, or the map of 10,000 observations | peaks at about 1.4 GB |
| A build | the build's own processes (Claude Code, the project's tests) on top |

The embedding model (nomic-embed-text-v1.5, 0.5 GB on disk) is most of the server's memory.
Before 0.4.11 a first read could take several GB (it embedded 40 texts in one model run and
kept that memory): see [the decision log](design/DECISIONS.md) and `src/kranto/embed.py`.

## The caps

`kranto up` writes these into `kranto.service`:

| Setting | Default | What it does |
|---|---|---|
| `MemoryHigh` | three quarters of `MemoryMax` | above it the kernel reclaims Kranto's memory and slows kranto down; nothing is killed |
| `MemoryMax` | the smaller of 4 GiB and half the machine's memory | the kernel's OOM killer ends the biggest process in Kranto's group (the server, or a build), never another program |
| `OOMPolicy=continue` | | a build ended for memory does not stop the server; a server ended for it is started again 15 s later |

The caps cover the server and everything it starts, builds included.

Where Kranto runs without the service (`kranto up --foreground`, a machine whose systemd user
manager is not running for the service) and for `afk run`, the command puts itself in a
`systemd-run --user --scope` with the same caps when the machine has a user systemd. It says
so on its first line. `KRANTO_NO_SCOPE=1` runs it without. Without systemd (macOS, a
container), there is no cap; the warning below still works.

## When it is high

Past 80% of the lowest cap, the server writes one line to its log
(`kranto logs`: `memory: kranto uses 2.7 GB of its 3.0 GB MemoryHigh ...`) and Settings ›
System shows a warning; one more line says when it is back under. `/api/health` carries the
figures under `memory`.

## Changing the caps

**Settings › System › Service › Memory** (`service.memory`) is the setting: the most Kranto may
use, in GB (1 to 64, in half GBs; `MemoryHigh` is 1 GB under it, a fifth under it below 5 GB),
or **Auto** (the defaults above). Save writes Kranto's own drop-in,
`~/.config/systemd/user/kranto.service.d/30-memory.conf` (updates keep it), runs `systemctl
--user daemon-reload` and applies the caps to the running service at once (`set-property
--runtime`): no restart. The row shows what Kranto uses now beside the caps. Your assistant
changes it with the verb `settings.service_memory` (`{"memory": 5}` or `{"memory": "auto"}`),
never by editing the file. It is refused by a Kranto that is not its service (a server started in
a terminal, a scratch copy): only the service's caps are Kranto's to change.

By hand, the same drop-in works as before (`systemctl --user edit kranto`, then `[Service]`
`MemoryHigh=5G` and `MemoryMax=6G`, then `systemctl --user restart kranto`); the setting reads
it and says it was written by hand. `MemoryMax=infinity` removes the cap (not recommended on a
machine you share). `systemctl --user show kranto -p MemoryCurrent -p MemoryPeak` shows what it
uses now and its peak since it started.
