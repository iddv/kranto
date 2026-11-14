# Evaluating Kranto

`kranto eval` measures whether a change made Kranto better, at two prices:

- **Free, on every CI run.** Recorded model replies (cassettes) replayed through the current code
  (`kranto eval replay`; `tests/test_evals.py` on the synthetic cassettes in
  `tests/fixtures/evals/`), and `prompts.lock.json`: a change to a prompt Kranto ships, or to
  TENETS, fails `tests/test_prompt_lock.py` until the lock names the scorecard that evaluated the
  new version, or says why it was skipped.
- **Cents to a few dollars, by hand.** A stage asked again on a frozen set through the product's
  own provider seam, under `--budget`, writing a dated scorecard.

A model is never asked under CI: `kranto eval` refuses when `CI` or `GITHUB_ACTIONS` is set.

## The frozen set

```
kranto backup                                    # a copy of kranto.db
kranto eval set build --from <backup>/kranto.db
kranto eval set show
kranto eval replay                               # free: do this kranto' readers agree?
kranto eval set grow --from <newer backup>       # the next version
```

A set is cut from a library's own history: the newest recorded screens and judges, every judge
whose observation the owner graded, every idea card with its inputs. Every message and reply goes
through `kranto.scrub` and a bearer-token mask, only the request's turns are kept, and a scan for
secret-shaped strings fails the build. One item in three is held out by a hash of its id, and
every owner-graded item is held. A set is never rewritten: `grow` writes the next version with
every old item, every new grade's item (held), the newest calls up to the size, and held items
older than 90 days rotated to dev. Sets live in `<home>/evals/sets/v<N>`; the owner's copy is the
private `the design notes` repository. Sets hold third-party text: never publish one.

## Scorecards

`<home>/evals/scorecards/<date>-<stage>-<set>-<model>[-<tag>].{json,md}`, one line each in
`<home>/evals/SCOREBOARD.md`. Each metric is shown with the last run, the baseline (the first
scorecard on the same stage, set and model; `kranto eval baseline <scorecard>` pins another) and the
noise floor (the baseline's self-agreement, measured by asking the same model twice). A move
smaller than the noise floor is "within noise"; a larger drop is `REGRESSION`, a larger rise
`better`. Agreement with the owner's grades, where n is small, is only ever "changed", with the
ids. A flag blocks nothing. `kranto eval scorecards` lists them.

## The prompt lock

```
kranto eval lock                                  # in a checkout: what changed since its scorecard
kranto eval lock set screen --scorecard the design notes:scorecards/<file>.md
kranto eval lock set name --skipped "no eval stage measures cluster names yet"
```

The owner's own prompts (Settings › Prompts) are not in the lock: they are the owner's,
versioned by the prompt store. The lock covers what ships.
