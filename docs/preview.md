# The preview

A second Kranto on the same machine as yours, built from a branch of this repository (`main` by default), serving **a copy of
your data** on `127.0.0.1:8766`, that **cannot send**. You try a branch on it before anything
reaches Kranto you use. It never touches your Kranto's folders, and it is never updated by
`kranto update`: `kranto-preview refresh` builds it again from the branch.

| | Your Kranto | The preview |
|---|---|---|
| Address | `127.0.0.1:8765` | `127.0.0.1:8766` (loopback only; its own sign-in) |
| Unit | `kranto.service` | `kranto-preview.service`, a transient user unit with a 3 GB memory cap (nothing is written under `~/.config/systemd`; after a reboot, `kranto-preview up` starts it again) |
| Code | a release | the wheel built from the branch, in `~/kranto-preview/venv` |
| Data | `~/kranto-kb`, `~/kranto-loop`, `~/tasks` | `~/kranto-preview/home` and `~/kranto-preview/loop`: a copy (below); `~/tasks` is not copied |
| Secrets | yours | none: no model key, no account |
| Jobs | on | off (a still copy: every page works, nothing new is read) until `kranto-preview jobs on` |
| Sending | as you choose | never |

## Try it

1. On your own PC, run this one line:

   ```
   ssh -t -L 8766:127.0.0.1:8766 the server '~/kranto-preview/bin/kranto-preview open; exec $SHELL -l'
   ```

   It opens the tunnel, prints a one-time sign-in link and keeps the tunnel open while that
   window stays open. Close the window to close the tunnel.
2. Open the link in your PC's browser. The status bar (on a phone, the strip above the doors)
   says **"Preview: a copy of your data from 11 November. Nothing is posted; no update or usage
   report goes out."** (Welcome's Test and save still asks the model's provider whether a key
   works: that is how a key is checked.)
3. Use it. Whatever you do there changes only the copy.

To see **"While you were away"** on the copy, run `kranto-preview away` (in that same window) and
reload the home: the copy is then last opened 9 days ago (`away 3` for three). It ends as it
does in your Kranto: when you open one of the five, or choose Show today.

## The commands

| Command | Does |
|---|---|
| `kranto-preview up` | makes `~/kranto-preview` if it is not there (the build, the copy, the switch), starts the unit and waits until it answers; then checks every page answers (`kranto doctor --routes`) |
| `kranto-preview refresh` | the code only: fetches the branch, builds, installs, restarts, checks the new commits answer and every page answers. Your copy's data is kept |
| `kranto-preview refresh-data` | the data only: a fresh copy of your Kranto (it asks first: the preview's own changes are lost) |
| `kranto-preview open` | a one-time sign-in link; its first line is the one command to run on your PC |
| `kranto-preview away [days]` | marks the copy last opened `days` ago (9), so its home says "While you were away"; it refuses on any home that is not a preview's |
| `kranto-preview status` | the commit it runs, when the data was copied, the bar's sentence, the jobs, the unit |
| `kranto-preview fresh` | an empty home on `127.0.0.1:8767`, for walking Welcome; `fresh link` signs in again, `fresh down` removes it |
| `kranto-preview jobs on` / `off` | the scheduler. Reading needs a model key, which you put in `~/kranto-preview/home/.env` yourself; with it, reading costs what your Kranto's does, a second time |
| `kranto-preview down` | stops it (the copy stays) |
| `kranto-preview logs` | the unit's last lines |
| `kranto-preview remove` | stops it and deletes `~/kranto-preview`, and nothing else |

The command lives at `scripts/preview/kranto-preview`; `up` links
`~/kranto-preview/bin/kranto-preview` to the copy of it on the branch. Run through a link of that
kind in another folder (`<folder>/bin/<name>`, with the copy in `<folder>/home`), it keeps that
folder and names its unit after the link: an older preview keeps its folder, unit, port and
bookmarks. It puts `~/.local/bin` (where
`uv` is) on its own PATH, so it works over a plain `ssh <this machine> '…'` with no login shell.

`scripts/preview/acceptance.py` checks a running preview read-only against the owner's Gate A
lines, the word test and the page counts; it exits non-zero on a failure (its `--help` says how).

## The copy

`scripts/preview/copy_live.py` reads your Kranto and never writes to it: `rsync` without `.env`,
`data/secrets`, `backups`, `update`, `telemetry`, the lock files, the console's sessions
(`term`, `chat`, `inbox`) and `trace.db`; each database through SQLite's online backup opened
read-only. Then the copy's settings point at the copy: every setting naming one of your folders is
rewritten to the copy's, the port is 8766, notifications and the heartbeat are off, usage reports
are off, the update check is off, and `preview: {enabled: true, copied_at}` is written. If a
setting still names one of your folders after that, the copy stops.

## What "cannot send" means

One switch, `preview.enabled: true` in the copy's `kranto.yaml`, and `kranto serve` passes it to
everything it starts (`KRANTO_PREVIEW=1`, `DO_NOT_TRACK=1`). The code is `src/kranto/preview.py`;
each line has a test in `tests/test_preview.py`.

1. Every posting cub is in practice. A kind cannot be turned live. An approval answers **"This is
   the preview: nothing is sent."** before anything is recorded, so the ask still waits. A cub's
   broker sends nothing but reads (a GET).
2. Usage reports are never sent, whatever the copied setting says.
3. `kranto update`, the update check and the cubs' own updates are off.
4. `/api/status` carries `preview`: the bar's sentence, when the copy was taken, the commits.
5. `kranto serve` refuses to start as the preview when its home or loop home is one of your
   Kranto's folders (`~/kranto-kb`, `~/kranto-loop`, `~/tasks`, or the home `kranto.service` names),
   or when its port is your Kranto's port.

`kranto-preview` itself refuses to start a build that has no switch (one from before the switch
existed).

The console in the preview is your own Claude Code, as in your Kranto, working in the preview's
folder; its Kranto tools reach only the preview.

## After a merge

Run `kranto-preview refresh` and say "preview at `<sha>`, routes ok" where your team talks. A
refresh takes a lock, so two never interleave; the second one wins. A refresh that fails is the
merging change's next fix. To try a branch before merging, set `KRANTO_PREVIEW_BRANCH` (and
`KRANTO_PREVIEW_URL` for a local clone) for one `refresh`, then refresh again from `main`.
