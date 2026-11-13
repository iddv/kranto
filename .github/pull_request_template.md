Closes #

## What changed

## Reach
- [ ] This changes what a person sees or must do, for everyone (`big`): say what, and whether
      stable keeps the old behaviour behind a setting (`Setting(default_stable=...)`) until the
      owner turns it on. If `merge_when_green.sh` names a hint and it is not big, label it
      `not-big` and say why here.

## Verification
What you ran and what it showed. Say plainly what you did not verify.
For a move (files or folders to another place or repo), answer the four: history kept
(`git log --follow`), the UI build byte-identical, the guards named, the grep for the old
paths clean (pasted).

## Checklist
- [ ] A person read and ran this change, and every commit is signed off (`git commit -s`)
- [ ] `pytest` and `ruff check src tests` pass
- [ ] Tests make no model or network calls
- [ ] No secret-shaped literals, even fake ones (`tests/test_no_secrets.py`)
- [ ] Library tables stay append-only; any new migration uses a new explicit number
- [ ] Every model call goes through `LLMClient`
- [ ] docs/design/DECISIONS.md or docs/design/DESIGN.md updated if a principle or plan changed

## Stored data
- [ ] No stored field (a JSON column, a `settings` blob, a file kranto reads back) gains a new
      value or shape here. If one does: the field, the new shape, what
      `python3 scripts/dev/readers_of.py <table.column>` lists as its readers, how each
      handles it (the contract type's change in `kranto.stored` and green CI, or the line),
      and the odd case added for it. A new writer never stores `null` to mean something:
      "not measured" is a word or a field of its own.
