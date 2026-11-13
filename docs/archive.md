# The archive: what the features that left Kranto kept

Kranto was cut down to three things: news into ideas, the console, and posting about an idea.
The features that left (builds and their projects, Invest, the trend radar, deep dives and the
browser extension) kept data on your machine. **None of it is deleted:** every table stays in
its database, every folder where it was. `kranto archive` writes it out in a form you can read
without those features.

```
kranto archive              # writes <home>/archive/
kranto archive --out DIR    # writes somewhere else
kranto archive --json       # says what it wrote, as JSON
```

It writes one page and one JSON file per group, and only reads: each database is opened
read-only, and nothing in it changes. Run it again whenever you like; the files are written
anew from what the databases hold then.

| File | What it holds | From |
|---|---|---|
| `index.html` | One page, no scripts, no outside requests: every build with its repository's link, every project with its repositories, Invest's cards, the radar's trends and proposals, and each table's row count | all of the below |
| `builds.json` | Each build: its idea, state, repository, task folder, every history row and spend row | the loop's `loop.db` (`ideas`, `history`, `spend`) |
| `projects.json` | Each project: its repositories, every charter version and every change | `loop.db` (`projects`, `charter_versions`, `changes`) |
| `invest.json` | Every row of Invest's tables (cards, their events and resolutions, the calendar, fills, marks) | Kranto's database (`invest_*`) |
| `radar.json` | Every row of the trend radar's tables (trends, proposals, the price series, stages, chains, scores) | Kranto's database (`radar_*`) |
| `deepdives.json` | Every deep dive and its events | Kranto's database (`deep_dive*`) |
| `extension.json` | Every paired browser, capture and capture event | Kranto's database (`browser_*`) |

Each JSON file starts with `counts`: the rows of each table, as the database counts them. A
file with no rows says so; a fresh install writes the same files, empty.

## Settings of a feature that left

A `kranto.yaml` that still holds such a feature's section (`invest:`, `radar:`, `browser:`, and
later `builds:`) loads as before. The section stays in the file as you wrote it and is never
read, and `kranto doctor` says one line about it:

```
ok    invest         Invest is not part of kranto any more: its settings are ignored, and its
                     data is kept (kranto archive writes it to ~/.kranto/archive)
```

You can delete the section, or leave it.
