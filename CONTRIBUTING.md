# Contributing

Thanks for looking. the server is small on purpose, and most of its design
choices were bought with a specific failure. Before you change how something
judges, stores, measures or alerts, read [docs/design/DECISIONS.md](docs/design/DECISIONS.md):
each entry says what went wrong without it. If you disagree with one, argue
with its evidence in an issue first. That is a welcome kind of contribution.

For a deeper tour of how the system works and is operated, see
[docs/OPERATING.md](docs/OPERATING.md).

## Setup

```
git clone https://github.com/iddv/kranto.git && cd kranto
uv sync --locked --extra dev
.venv/bin/pytest
.venv/bin/ruff check src tests scripts
.venv/bin/python scripts/ci/typecheck.py        # mypy, each file's count may only fall
.venv/bin/python scripts/ci/stored_shape_lint.py
```

The default test run needs no API key, no network and no embedding model; a
stub embedder stands in. Tests marked `slow` load the real model (about 500MB,
downloaded once): `.venv/bin/pytest -m slow`. The first `uv sync` downloads about
660 MB (numpy, scikit-learn, umap, scipy, trafilatura, fastembed); later ones take
seconds. The suite takes about 5 minutes alone and 12 to 26 on a busy machine.

## Where things are

The root:

| Where | What |
|---|---|
| `src/kranto/` | the watcher, the app host, the `kranto` launcher, and the page (`src/kranto/page/`, below) |
| `src/bears_cub/`, `sdk/` | the cub SDK and its build as `bears-cub-sdk` (cub authors install it from `sdk/`) |
| `tests/` | everything CI runs: the server's suite, and the page's in `tests/page/` (its own `pytest.ini`); `tests/README.md` is the map |
| `docs/` | what a user or contributor reads (`docs/README.md` lists every page); `docs/design/` why it is built this way |
| `scripts/` | `ci/`, `release/`, `dev/`: who runs what is in `scripts/README.md` |
| `examples/` | topic packs for `afk pack` |
| `install.sh` | the installer every release carries |
| `public.toml` | what the published project is called and where it lives |

`src/kranto/`, by package:

| Package | What |
|---|---|
| `stored/` | the contracts for what Kranto stores as JSON: one type per column, every writer and reader goes through it |
| `core/` | the contract a feature sees: the manifest, events, tickets, settings, the cub runtime (`core/cubs/`) and the brokers |
| `features/` | Kranto's own features (news), each a package with one manifest; `features/post/evals/` is the prose eval, not a feature |
| `social/` | short posts for the sites people use: one version a site through the prose engine, your own site first ([docs/posting.md](docs/posting.md)) |
| `prose/` | the prose engine every post is written through: the profile, compose, check, revise, learn, and the shipped guides ([docs/prose.md](docs/prose.md)) |
| `cubs/` | the reference cubs Kranto ships (`newsletter`, `toot`), installed like any cub |
| `web/` | the app host: the JSON API routers, the sign-in, the pages the server serves |
| `sources/`, `connections/` | the source kinds and their adapters; accounts read with the owner's own login |
| `providers/` | how the metered client reaches a model |
| `prompts/` | the versioned prompt files, and the owner's additions and overrides |
| `ideate/`, `map/` | idea cards from the library; the map of emergent clusters |
| `activity/` | background work you can see: every run recorded as it goes |
| `telemetry/` | the usage reports: counters, one daily report, the allow-list |
| `update/` | `kranto update`: the check, the staged wheels, the backup, the restart |
| `evals/` | evaluating Kranto on a frozen set cut from a library's own history |
| `newsletter/`, `websearch/` | newsletter platforms; live web search |
| `page/` | the page: its web UI (`page/ui/`, its source in `page/ui/web/`), the console and its sandbox (`page/term/`, `page/box/`), `kranto mcp` (`page/mcp/`), traces (`page/trace/`); [docs/ui.md](docs/ui.md) |
| `plugin/` | the Claude Code plugin: its skills, its agent and its hooks |

The flat modules are the watcher itself: `tick` (one ingest pass), `intern` (the judgment on
one item), `scout` and `resolve` (finding sources), `store` and `library` (the append-only
library), `retention`, `search`, `embed`, `llm` (the metered client), `scheduler`, `gate` and
`notify` (strikes), `launcher` (the command), `product` and `legacy` (the name, and the
names an install from before the rename still has), `wizard` and `setup`, `paths` (where Kranto keeps its
files), `rowsafe` and `errtrace` (one bad row never takes a page down; an error as it may leave Kranto). Each opens with a docstring that says what it is for.

## How work is organised

- Every change starts as a GitHub issue. The issue holds the reasoning;
  comments hold progress and decisions made along the way.
- A PR says `Closes #N`, and explains what was verified and what was not.
- CI runs the tests, lint and a gitleaks scan of the new commits (of the whole
  history weekly); the Docker build that starts the server runs when dispatched.
- Everyone taking part follows the [code of conduct](CODE_OF_CONDUCT.md).
  [SUPPORT.md](SUPPORT.md) says where questions go.

## Merging and releasing

The same rules hold in the server and the page, for people and for agents.

- **Merge only when every check on the PR's exact head commit is green,** with
  `scripts/ci/merge_when_green.sh OWNER/REPO PR --require <jobs>` (the server:
  `test,gitleaks`; the page: `fast,slow,browser,frontend,lint,gitleaks,sandbox`).
  It waits for the checks, refuses red, refuses a required check that was
  skipped, refuses if the head moved, and squash-merges with
  `--match-head-commit`. Never `--admin`, never on a local run alone, never
  while checks are queued. A PR that conflicts with its base stops there;
  `--merge-base` (run from the PR's clone) merges the base in with
  `scripts/ci/merge_base.sh`, which makes the generated usage-reports page
  (`docs/privacy/what-kranto-sends.md`) again instead of stopping on it, pushes,
  and waits on the new head.
- **A pull request from a fork** never runs on the project's self-hosted
  runners: those jobs skip it, and the `fork` job runs the tests and lint on
  GitHub's own runner instead (no secrets, a read-only token). Its first run
  waits for a maintainer's approval, who reads any change under
  `.github/workflows/` before approving (a fork's PR runs the workflow files
  from the fork). It is merged with `--require fork`.
- **A merge never waits for a release.** Every cut from main is a nightly
  build; a promotion to stable is cut from a nightly build's own commits
  (`scripts/release/cut_local.sh --from-tag vX.Y.0-devN`), so what merged since
  rides the next one. `cut_local.sh` takes a lock, so two cuts never take the
  same version.
- **A change split across the two repos says so:** a line `Needs kranto.page#N`
  (or `Needs kranto#N`) in the PR's body. `cut_local.sh` (`pairing.py`)
  refuses a pair whose one head carries such a PR and whose other head lacks
  #N, and prints the PRs each head carries, from git: the cutter copies that
  list into the "cutting now" note and the report.
- **A red check gets one rerun** (`--rerun-once`). If it fails again it is a
  flake: fix it in its own PR, and merge nothing that depends on it meanwhile.
  Never skip or deselect a test to get a merge through. A job cancelled before
  any runner took it ran nothing: the script reruns it without counting it
  (up to three times).
- **If main goes red** (the `push` run after a merge), the next merge in that
  repo is the fix or the revert; nothing else merges until then.
- **Releases are cut only from green commits.** `scripts/release/decide.py`
  refuses when any check on either main is red, running or missing.
- **A release cut for a change names it:** `cut_local.sh --must-include
  the server@<merge commit>` (repeatable; `the page@` too) waits, bounded and
  saying so, until that commit is in main and green, cuts from a head that
  holds it, and refuses otherwise. 0.5.21 was cut while its fix's checks were
  still running, so it took the commit before the fix and shipped nothing.
- **Never an empty release.** `decide.py` refuses a cut when neither repo has a
  commit since the previous tag.
- **A release is not done until its commit list has been read and contains the
  change it was cut for.** The notes end with each repo's `git log --oneline
  <previous>..<tag>`, and `cut_local.sh` prints the same lists after
  publishing; read them before saying a release is out.
- **Two lines: nightly and stable.** Every cut from green main is a nightly
  build, `vX.Y.0-devN` (a GitHub prerelease, numbered toward the next stable
  minor): installs on the nightly channel see it, stable installs never do.
  **Stable is always the owner's choice, never a matter of time**: the owner
  presses Promote to stable (Needs you, on the maintainer's install) when the
  work is done, and the gate cuts `vX.Y.0` from that build's commits, runs
  `rc_check.sh` and releases it. Its health checks block the press (a rollback
  of the build, a new error still occurring, a failing page on the owner's
  data or on the odd installs); nothing counts days. A fix for stable is
  cherry-picked onto `release/X.Y` (`hotfix.sh --stable`) and goes out right
  after its checks; fixes only, never features.
- **rc_check when the release changes the update, the install, the
  packaging, a migration or the service unit** (`decide.py`'s `RC_PATHS`, and
  every promotion). There is no rc tag any more (`--prerelease rcN` is
  refused): the cut prints the line, and `scripts/release/rc_check.sh TAG
  PREVIOUS` runs on the published build itself on a scratch port (install the
  previous release, update, roll back, update again, every page, the odd
  installs, no request storm on four pages) before the owner's install takes a
  nightly or before a held stable is released. Such a nightly is published
  unoffered: its notes open with "Do not install: being checked", which no
  install's update check offers; once rc_check passed, re-read MQ, then
  `gate.py offer TAG` takes the line out (it refuses without the pass). A
  nightly that fails it is withdrawn (`gate.py withdraw`) and the next one
  carries the fix.
- **A change that is not finished rides to stable switched off.** A `big`
  change (what a person sees or must do changes for everyone) is labelled
  `big` and, when it must not reach stable yet, sits behind a setting whose
  stable default is the old behaviour (`Setting(default_stable=...)`); the
  owner turns it on for stable by a later choice, in a promotion whose notes
  say so. `merge_when_green.sh` refuses a merge whose diff trips a hint (a
  default changed, a route, page, command or help heading removed, a migration
  that drops or renames: `scripts/release/guards.py big`) until the PR is
  labelled `big`, or `not-big` with a sentence in its body saying why; CI's
  `gitleaks` job says the same hints early, as a warning. A fix for stable is
  never `big`.
- **A hotfix is one step:** `scripts/release/hotfix.sh kranto|kranto.page PR`
  merges on green with the repo's required jobs, cuts a nightly with
  `--must-include` the merge commit (and `rc_check.sh` on it when `decide.py`
  asks), updates the owner's install, reads back `kranto --version` and the
  commit list, and stops with a plain reason at the first step that fails.
  `--stable` then cherry-picks it onto the stable line as a pull request,
  merges it on green, cuts the fix held, runs `rc_check.sh` and releases it;
  `--dry-run` merges, tags, publishes and updates nothing. Runbook:
  `docs/OPERATING.md`, "A hotfix".
- A weekly workflow (`audit.yml`, `scripts/ci/audit_merges.py`) files an issue
  listing every merge whose merged commit was not green.

## Rules the code depends on

- **Append-only.** Library tables reject UPDATE and DELETE through triggers.
  To correct a row, add a new row that points at it (`supersedes`), or add an
  event. Do not add a table to `MUTABLE_TABLES` without writing down why.
- **Migrations** are `(number, script)` pairs in `src/kranto/store.py`, and
  each is recorded as applied. Take the next unused number, never edit an
  existing migration, and only add things (tables, columns, indexes). See
  docs/OPERATING.md for the numbers in use.
- **One path for spend.** Every model call goes through `LLMClient`, which
  checks the pause switch and the budget before each call and records the
  call. No other code talks to a model.
- **Fail loudly.** A source that cannot be fetched raises `SourceError`; it
  never returns an empty list. A rejected key stops the run. An item is marked
  seen only once it has a real outcome.
- **No model or network calls in tests.** Use `httpx.MockTransport` for HTTP,
  the `make_client` fixture for models, and `StubEmbedder` for embeddings.
- **No secret-shaped literals**, not even fake ones. Build test keys at runtime
  (`"sk-or-v1-" + secrets.token_hex(16)`); `tests/test_no_secrets.py` checks
  every tracked file.
- **Stored JSON has a contract**. A JSON column, a `settings`
  value holding an object, or a file kranto reads back is declared once, as a
  frozen dataclass in `src/kranto/stored/` (a feature's in
  `features/<id>/stored.py`), and read and written only through it:
  `T.parse(text)` never raises, `T.to_json()` is what a writer stores. A field
  a writer may leave out is `X | None`, and `null` only ever means absent: "not
  measured" is a word or a field of its own. `.get(k, 0)` does not cover a key
  stored as null. CI runs mypy (`scripts/ci/typecheck.py`: a file's error
  count may only fall, a strict module's is 0) and the stored-shape lint
  (`scripts/ci/stored_shape_lint.py`: a number format, `round()` or a
  comparison of a value that may be None), each against a baseline that
  empties as the columns get their types. A pull request that adds a value or
  shape to a stored field lists its readers
  (`python3 scripts/dev/readers_of.py table.column`) and shows each handles it.
- **Prompts are versioned by content hash.** Editing a file under
  `src/kranto/prompts/` changes its version, which is recorded on every
  call. `prompts/TENETS.md` must stay identical to `docs/design/TENETS.md`; a test
  checks this.

## Stored data

The rule above, as steps.

**Where the types are.** `src/kranto/stored/<family>.py` (sources, runs, cards, observations,
settings, activity, events, cubs, map, misc), a feature's own in
`src/kranto/features/<id>/stored.py`; the page's in `src/kranto/page/stored/` (its `base.py` and
`testing.py` are copies of the server's, byte for byte). Each type is a frozen dataclass deriving
`Stored`, with `COLUMN = (table, column)` (or `SETTING`, `FILE`); every field has a default.
Read with `T.parse(raw)` (None for NULL or unreadable) or `T.load(raw)` (the empty value);
write `T.write(dict)` or `value.to_json()`. A JSON column with no one shape is listed in
`stored.OPAQUE` with its reason.

**Adding a JSON column** (a migration's TEXT column defaulted `'[]'`/`'{}'`, or one a reader
`json.loads`): add its type in the family's module; `tests/test_stored.py`'s
`test_every_json_column_has_a_contract` fails until you do.

**Adding a field or a value to a stored shape** (null where there was always a number, a new
state, a new key):

1. Change the field's type in `stored/` (`float` to `float | None`, a new `Literal` word).
2. Run `scripts/ci/typecheck.py` and `scripts/ci/stored_shape_lint.py`: the strict modules and
   the lint name every reader that does not handle it. Fix those.
3. `python3 scripts/dev/readers_of.py table.column [key]` lists the readers, through the
   contract and by the table's name; read the second list by hand, and name in the pull request
   any reader the tools cannot see (a template, a shell script, the UI's TypeScript).
4. The odd case: the type's derived `odd()` already nulls every `| None` field, empties every
   list and uses every `Literal` word; a shape the derivation cannot make goes in the type's
   `named_odd()`. `scripts/dev/odd_install.py` writes every odd value of every column (its
   `CASES`; `test_every_stored_type_has_an_odd_case`), and `tests/test_odd_install.py` reads
   every page on it (`odd`, `empty`, `projects`, and `upgraded`: rows as every release
   since v0.2.0 wrote them, committed in `tests/fixtures/odd_install/upgraded/`; the weekly
   `fixtures` workflow makes it again and reads every page on each variant). Locally, `scripts/dev/odd_walk.sh PORT` serves
   each variant and runs `kranto doctor --routes` on it; `rc_check.sh` and `smoke.sh` do the same.
5. Fill in the pull request's "Stored data" block.

**The baselines.** `scripts/ci/typecheck_baseline.json` (mypy's error count per file) and
`scripts/ci/stored_shape_baseline.txt` (the lint's findings that were already there) may only
shrink. When you fix one, run the script with `--update` and commit the baseline; when you edit
a line the lint lists, its entry goes stale and the step is red until you do.

## Adding a source kind

1. Write an adapter in `src/kranto/sources/` with `kind`, `label`,
   `fetch() -> list[Item]` and `enrich(item) -> Item`. Fetch only through the
   `HTTP` client you are given, which enforces the public-address check, the
   size cap and redirect re-checks.
2. Register it in `KINDS` and teach `params_from_value` its single
   user-facing value.
3. Test it against recorded responses with `httpx.MockTransport`, including
   the failure cases: 404, 429, unparseable content.
4. Add it to the scout prompt only once it has been checked against real
   feeds, and note the date you checked.

## Style

- Match the surrounding code: its naming, and how densely it is commented.
  Comments explain why, not what.
- Plain language in docs, UI text and commits. No emojis, and no claims about
  speed, cost or quality that are not measured.
- Keep dependencies few. A new dependency needs a reason in the PR and a
  licence compatible with Apache-2.0.

## Licence

By contributing you agree that your contribution is licensed under the
Apache License 2.0, the licence of this project.

## Sign your work

Every commit carries a sign-off: the line `Signed-off-by: Your Name <you@example.com>` at the
end of its message, which `git commit -s` adds. It says you wrote the change, or have the right
to submit it under this project's licence, as the
[Developer Certificate of Origin](https://developercertificate.org/) words it. CI refuses a
commit without one, and a commit whose author or committer address is not a GitHub no-reply
address (Settings › Emails › "Keep my email addresses private" gives you one).
