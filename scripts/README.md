# scripts

Sorted by who runs them: `ci/` what CI and every merge run, `release/` what cutting and
checking a release runs, `dev/` what a maintainer runs by hand.

| Script | Who runs it | What it does |
|---|---|---|
| `ci/merge_when_green.sh` | everyone who merges, for both repos | waits for a PR's checks, refuses red or skipped required ones and a moved head, then squash-merges |
| `ci/merge_base.sh` | `merge_when_green.sh --merge-base`, anyone merging the base into a PR | merges the base in (never a rebase); when only generated files conflict (the usage reports' field page) it makes them again and finishes the merge |
| `ci/checks.py` | `merge_when_green.sh`, `release/decide.py` | is one commit green: the rule every merge and release follows |
| `ci/audit_merges.py` | the weekly `audit.yml` | files an issue listing every merge whose merged commit was not green |
| `ci/no_attribution.py` | CI (`gitleaks`), and by hand in | refuses tool or agent attribution lines in a range of commits |
| `release/decide.py` | whoever cuts | which heads a release takes, and whether it must be an rc first |
| `release/cut_local.sh` | whoever cuts | builds, tags and publishes a release from green heads (`--prerelease rcN`, `--from-tag`) |
| `release/build.sh`, `release/publish.py`, `release/notes.py` | `cut_local.sh` | the wheel (or, with `--shape compat`, the three wheels of the release that crosses an install made before the rename); the GitHub release; its notes |
| `release/compat_wheels.py` | `build.sh --shape compat` | the three old-shape wheels, from temporary copies of the tree |
| `release/names.py` | the release scripts | the product's names, the repository and the old names, read from `product.py`, `public.toml` and `legacy.py` |
| `release/rc_check.sh` | whoever cuts an rc | the rc on a scratch copy: a fresh install, `kranto update` from the last release, a rollback |
| `release/fresh_install.sh`, `release/smoke.sh`, `release/e2e_update.sh` | `rc_check.sh` (and by hand, step by step) | install as a newcomer does; install and start the wheels; the update's end-to-end steps |
| `preview/kranto-preview`, `preview/copy_live.py` | the owner, and every track after a merge into `oss` (`refresh`) | the preview: a second Kranto built from a branch on `127.0.0.1:8766`, with a read-only copy of live's data, that cannot send (`docs/preview.md`) |
| `dev/eval_fixtures.py` | a maintainer, when the eval sets change | writes `tests/fixtures/evals` (synthetic items, no third-party text) |
| `dev/resolve_check.py` | a maintainer, before a release that touches the source resolver | a real check of the resolver against a fixed list; calls a model and the network, never in CI |
| `dev/check_cub_schema.py` | a maintainer, after editing the cub schema | checks `cub.yaml` files with `jsonschema` and with Kranto's own validator, and says where they disagree |
| `ci/browser.sh` | CI (`browser`) | the page in a real browser: Playwright's headless Chromium in the runner's cache, then every browser test file |
| `ci/scrub.py` | CI (`lint`, `gitleaks`), and by hand | the public tree's check: old names, private words, home paths, hosts, plan citations, attribution, big files, the workflows' rules; `--commits` checks a range's messages, addresses and sign-off |
| `dev/build_ui.py` | CI (`browser`, `frontend`), the release build, and a maintainer | builds the page (`npm ci`, `vite build`) into `src/kranto/page/ui/static/app/` |
| `dev/gen_page_ts.py` | a maintainer, after changing `src/kranto/page/ui/types.py`; a test runs `--check` | writes the page's `types.gen.ts` |
| `dev/fake_gh.py` | the page's tests | a stand-in `gh` that answers from fixtures |
| `dev/make_icons.py` | a maintainer, after changing the mark | the favicons and icons, drawn from `mark.svg`'s shapes |
| `ci/typecheck.py`, `ci/typecheck_baseline.json` | CI (`lint`) | mypy with a per-file ratchet: a file's error count may only fall |
| `ci/stored_shape_lint.py`, `ci/stored_shape_baseline.txt` | CI (`lint`) | a stored value used as if it could not be missing, which no type checker sees |
| `dev/odd_install.py`, `dev/odd_old.py`, `dev/odd_walk.sh` | a maintainer, before a release that touches update or install | homes in odd shapes (an older release's, a half-made one) and a walk over them |
| `dev/readers_of.py` | a maintainer, when a stored value gains a shape | lists every reader of a stored field |
| `dev/telemetry_lists.py` | a maintainer, after adding a verb or a route | writes the usage reports' allow-lists |
| `preview/acceptance.py` | whoever changes what the preview shows | the acceptance walk on the preview, read-only, in both layouts and on the phone |
| `release/gate.py`, `release/guards.py`, `release/hotfix.sh`, `release/storm_walk.py` | `cut_local.sh`, and by hand | the release gate's checks; the refusals before a build; a fix on the stable line; the storm walk on a scratch copy |
| `gen_ts.py` | a maintainer, after changing `src/kranto/web/types.py`; a test runs `--check` | writes the page's `afk.gen.ts`. It stays here: the page's tests and the generated header name this path |
