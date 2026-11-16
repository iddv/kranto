# Releasing

Kranto is released from the maintainer's own machine with `scripts/release/cut_local.sh` (the
maintainer's `gh` login and git remotes; CONTRIBUTING's "Merging and releasing" has the rules it
keeps). A cut clones the repository into a fresh work folder, takes main's newest commit whose
checks are all green, numbers it (`decide.py`), makes the wheels with the page inside
(`build.sh`), installs and starts them on a scratch home (`smoke.sh`), writes the notes
(`notes.py`) and publishes a GitHub release with `SHA256SUMS` and `manifest.json`. Nothing is
uploaded to a package index. `--plan` stops after the numbering; `--dry-run` stops before
anything is pushed or published.

The release tag is annotated. Name its tagger with `RELEASE_TAGGER_NAME` and
`RELEASE_TAGGER_EMAIL` (your public identity, such as your GitHub no-reply address); without
them the tagger is `kranto release <release@kranto.invalid>`, never the machine's own git
identity.

## The two lines

- **Nightly:** every cut from main without a flag, `vX.Y.0-devN`, a GitHub prerelease. Installs
  on the nightly channel see it; stable installs never do.
- **Stable:** `vX.Y.0`, cut from a nightly build's own commit (`--from-tag vX.Y.0-devN`),
  published held and released by `gate.py promote` after `rc_check.sh` passed on it. `README`'s
  install lines take the newest stable release.

## The first release: 0.7.0

The first number is **0.7.0**: above the last release of the earlier install (0.6.0.dev18), so
its updater takes it; the first nightly `decide.py` allows (`FLOOR`, `v0.7.0-dev1`); and inside
the range the shipped cubs declare (`>=0.5.19,<0.8`), so they run for real, not dry.

It takes three cuts, because an install made before the rename can only install the old shape
(three wheels) with its own updater:

1. **The crossing, `v0.7.0-dev1`, the old shape.** On green main:

       scripts/release/cut_local.sh --shape compat --plan     # says v0.7.0-dev1 and the commit
       scripts/release/cut_local.sh --shape compat

   Read the commit list it prints. A new install cannot take this release (`install.sh`
   refuses it); it exists for the crossing only.
2. **One merge on main** after it (an empty release is refused): the pull request that moves
   `## 0.7.0` in `CHANGELOG.md` from "the first release" to its date is enough.
3. **The one-wheel nightly, `v0.7.0-dev2`.** On green main: `scripts/release/cut_local.sh`
   (no flag; the shape guard refuses it until the crossing exists). If it prints an
   `rc_check.sh` line, run it on a free port, then `scripts/release/gate.py offer v0.7.0-dev2`.
4. **Rehearse the crossing on the published sets** (a scratch HOME in a sandbox; no real unit
   is touched, it fails if one changes): download each release's wheels and `SHA256SUMS` into a
   folder named by its tag, then

       systemd-run --user --scope -p MemoryMax=3G -- python3 scripts/release/rehearse_way_back.py \
         --work ~/kranto-rehearsal-$(date +%s) --old <dir>/v0.6.0-dev18 \
         --k0 <dir>/v0.7.0-dev1 --k1 <dir>/v0.7.0-dev2 --port <a free port>

   Every step must say `"ok": true` and `"real_units_same": true`.
5. **Your own install crosses** (docs/setup.md › Updating): `update.repo: iddv/kranto` in its
   settings, a backup, `update.auto: off`; then the old command's
   `update --to v0.7.0-dev1 --yes`, the walk; then `kranto update --to v0.7.0-dev2 --yes`, the
   walk. Each step goes back with `update --rollback --yes`; a rollback or a stop warning stops
   the release.
6. **Stable `v0.7.0`** from the nightly you ran:

       scripts/release/cut_local.sh --from-tag v0.7.0-dev2

   with `RELEASE_INTRO=docs/releases/0.7.0.md` set (the notes open with it). It is published
   held and makes `release/0.7`. Run the `rc_check.sh` line it prints, then
   `scripts/release/gate.py promote --now --tag v0.7.0 --reason "the first release"`.
7. **Check the release page:** the wheel `kranto-0.7.0-py3-none-any.whl`, `SHA256SUMS`,
   `manifest.json`, `install.sh`, and the notes. On a clean user, README's install lines and
   `kranto up` reach the page.

## Each later release

- A nightly: `scripts/release/cut_local.sh` (add `--must-include kranto@<merge commit>` when it is
  cut for one change). Read the commit list it prints.
- A stable: add `## X.Y.0` to `CHANGELOG.md` in a pull request (and `docs/releases/X.Y.0.md` for
  the notes' opening, if you want one), then `cut_local.sh --from-tag vX.Y.0-devN`, the
  `rc_check.sh` line, `gate.py promote`.
- A fix for stable: `scripts/release/hotfix.sh --stable` (CONTRIBUTING).

## When something fails

- The cut stops before publishing (red checks, an empty release, the shape guard, the smoke):
  nothing was pushed; fix it in a pull request and cut again.
- `rc_check.sh` fails on a nightly: `gate.py withdraw vX.Y.0-devN --reason …`; the next nightly
  carries the fix.
- Never move, reuse or delete a published tag; release the next number instead.

## Once, before the repository is public

The maintainer's settings, none of which a cut needs: a ruleset on `main` (pull requests only,
the required checks, squash only), a tag ruleset for `v*`, private vulnerability reporting.
