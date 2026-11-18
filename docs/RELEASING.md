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

## Where the numbers start

The first number is **0.7.0**. Installs made before the product took its name were on 0.6.x,
and their updater can only install a release in their old shape (three wheels). So
`v0.7.0-dev1` was cut once in that shape (`--shape compat`), only to carry those installs
across; `install.sh` refuses it for a new install. Every release after it, from `v0.7.0-dev2`
on, is the one wheel. `decide.py`'s `FLOOR` keeps the numbering above it, and the features
Kranto ships declare `>=0.5.19,<0.8`, so 0.7.x runs them for real.

`scripts/release/rehearse_way_back.py` rehearses that crossing and its way back on a scratch
HOME in a sandbox (it fails if a real unit file changes). It is kept for the record; a later
release does not need it.

### Stable 0.7.0

From the nightly that was run and checked:

    scripts/release/cut_local.sh --from-tag v0.7.0-devN

with `RELEASE_INTRO=docs/releases/0.7.0.md` set (the notes open with it). It is published held
and makes `release/0.7`. Run the `rc_check.sh` line it prints, then
`scripts/release/gate.py promote --now --tag v0.7.0 --reason "the first release"`. Then check
the release page (the wheel `kranto-0.7.0-py3-none-any.whl`, `SHA256SUMS`, `manifest.json`,
`install.sh`, the notes) and, as a new user, that README's install lines and `kranto up` reach
the page.

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

## Repository settings

None of these is needed by a cut, but the repository relies on them: a ruleset on `main` (pull
requests only, the required checks, squash only), a tag ruleset for `v*`, private
vulnerability reporting.
