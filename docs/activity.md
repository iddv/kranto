# What Kranto is doing: runs, recorded as they go

Everything Kranto does in the background is a **run**: a scheduled job (reading your sources,
the map, a cub's weekly post), an action that does work (Brief now, the scout, an
explanation, Card it now) or the update check. A run has a kind, a title in words, a trigger
(the schedule, your approval), a subject (a topic, a cub), a state and a trace.

| State | Says |
|---|---|
| running | it is working now; its stage in words ("source 2 of 8, Lobsters · 3 kept so far") |
| waiting | it stopped for you: a cub's ask to approve; the verb and the action |
| ok | done |
| degraded | done with problems (a source failing, a model error on one item) |
| failed | it failed, with the reason |
| skipped | it had nothing to do, with why ("the map has not changed") |
| stopped | you stopped it, or Kranto restarted while it ran ("cut off") |

## How it is recorded

`runs` is the end record (the scheduler's due-ness reads it, as before). A run's life is a
second, append-only table, `run_marks`: `started` when it begins, `progress` as it goes,
`waiting` when it stopped for you, `stopping` when you clicked Stop, `ended` when it is over,
`dismissed` when you put a failure away. A run's uuid is its `runs` row's, its model calls' and
its marks', so its trace is one id from the first mark to the last call.

Writes never slow the work: every mark is a queue put that **one writer thread** commits in
batches, at most every second or 50 marks, a run's progress marks coalesced (the newest wins)
and dropped first when the queue is long; `started`, `waiting`, `stopping` and `ended` are never
dropped and are committed at once. Measured on a copy of live, a mark costs the job about 0.07
ms; the read and the server's stop commit what is queued first. After each batch the writer rewrites `data/activity.json` (the runs in progress; mode 0600), which the live
feed watches.

Every word a mark carries (title, words, error, the subject's name, the needs) is scrubbed
before it is written; a mark's `detail` is a small JSON of counts and ids, never a payload
(2,000 bytes at most).

## Stop

Stop is cooperative: a run checks between its steps. Reading your sources stops after the
source in hand (what was kept stays; the rest at the next read); the topics' briefs after the brief in hand; a cub's job
at its next call to Kranto (the cub's own deadline still bounds it). A stopped run's `runs` row is
`skipped`, so the job is due again at its hourly re-check, never lost.

## Failures, once

A failed run shows in Recent at once. A kind that failed **twice in a row**, or has been failing
for **two days**, is one Fix row in Needs you ("The update check · GitHub answered 401 · 3
tries"), with its verb (Try again, Run again), until its next good run; Dismiss puts it away
until it fails again. The update check's failed check, recorded as `skipped` with its error,
counts as a failure here.

## The read

`GET /api/activity` (the server's half; the page's `GET /brb/api/activity` merges it with the
build loop's runs, the builds and the sessions):

```
{"seq", "running": [Run], "waiting": [Run], "next": [Scheduled], "recent": [Run],
 "folded": [Fold], "failing": [Fail], "counts": {"running", "waiting", "failed_recent",
 "failing"}, "quiet": "Nothing is running. Next: reading your sources at 20:23."}
```

- `subject=topic:12` narrows to a topic (its own runs and the reading of the sources),
  `kind=ingest` to a kind; `all=1` unfolds the hourly skipped re-checks and the usage reports,
  which are otherwise one line a kind ("Writing idea cards · skipped 22 times today: the map has
  not changed"); `hours=` widens Recent (up to `activity.keep_days`); `limit=` (500 at most).
- `run=<uuid>`: one run with its marks, for the live trace.
- `POST /api/activity/<uuid>/stop`: your Stop. `POST /api/activity/dismiss` `{kind}`: put a
  failing kind away.

`kranto status` prints the same read in one line (`activity`).

## Settings

Settings › System › Activity, or `kranto.yaml`:

```yaml
activity:
  keep_days: 30      # marks older than this go at compaction, with a purge record
  max_rows: 20000    # at most this many marks; the oldest go first
```

`GET /api/settings/activity` and `POST /api/settings/activity` `{keep_days, max_rows}` read and
write them. `runs` rows are kept as before.
