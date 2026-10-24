# Tier 1 results

Tier 1 asks whether the mechanism works on synthetic worlds whose generator the programs cannot see. Its criteria were fixed before any run, in the plan (Task 24) and in the pre-registration published in [science.me-lab](https://github.com/queelius/science.me-lab) (`preregistrations/tier1.json`, commit `40398bf`). This file records the outcomes. It names no world parameters.

| Criterion | Where | Judged | Result |
|---|---|---|---|
| A blind read-back catches a program whose description does not match its code | `w-alpha`, `seir-liar` | yes | **pass** |
| A lens swap is absorbed by an imported program | `w-alpha`, ED-visits channel | yes | **fail** |
| The pre-registered evaluation (80 replicate runs) | private worlds | yes | not yet run |

The spec's rule (7.3) is that if any judged criterion fails, the mechanism is wrong as built and tier 2 is not planned on it. The lens swap failed, so that rule already applies, whatever the evaluation shows. The evaluation still runs, because it says which parts of the mechanism do work.

## Read-back (pass)

A Claude-lineage agent wrote `seir-liar`. Its README and tags assert the school effect and the flat-covariate claim, and its interface declares `schools_closed`, but the code ignores both. It was frozen, and a Codex-lineage agent (`codex-cli-0.163.0`) received only `scienceme readback-packet seir-liar --mission w-alpha`. The packet holds the source with every README, name, tag and interface hidden.

The pass condition was that the flags include `tag-mismatch` or `interface-mismatch`. The reader inferred `school: denies` and `covariate-x-flat: denies` against the declared `asserts`, and an interface of `vaccinate_fraction` alone. The read-back raised `tag-mismatch`, `interface-mismatch` and `captain-mismatch`. The program was then withdrawn with the reason "read-back experiment: declarations deliberately false". The read-back is `programs/seir-liar/readback.json`.

## Lens swap (fail)

At issue 10 the world began publishing the same epidemic through a second channel, ED visits. A fresh agent working only from `SKILL.md` wrote a lens library `lens-ed` and four wrappers `seir-x?-s?-ed`. Each wrapper imports the unchanged `seir-core` and swaps only the lens. All of them were frozen, then the world was ticked and the programs predicted for 8 issues, through issue 18.

There were two pass conditions, both fixed before the run:

1. Each ED wrapper's `coverage_90` on the ED stream is within 0.10 of its admissions counterpart's on the admissions stream. Both are taken over the same reference weeks (11 to 14), 40 targets each.
2. The wrappers' cumulative-weight order on ED matches their counterparts' order on admissions for at least 5 of the 6 pairs.

| Theory | Admissions `coverage_90` | ED `coverage_90` | Gap |
|---|---|---|---|
| `seir-x1-s1` | 0.466 | 0.475 | 0.009 |
| `seir-x1-s0` | 0.375 | 0.335 | 0.041 |
| `seir-x0-s1` | 0.525 | 0.425 | 0.100 |
| `seir-x0-s0` | 0.421 | 0.325 | 0.096 |

Coverage passes. The `seir-x0-s1` gap is exactly 21/40 minus 17/40, which is 1/10. It counts as within, because floating point puts it a hair above.

Order fails. On admissions the cumulative weights rank the four `x1-s0 > x1-s1 > x0-s0 > x0-s1` (0.94, 0.055, 1.8e-12, 6.2e-14). On ED they rank `x0-s1 > x0-s0 > x1-s1 > x1-s0`, the exact reverse, so 0 of 6 pairs agree. As a check outside the pre-registration, the same comparison using log scores over the shared weeks 11 to 14 agrees on 2 of 6.

What this does and does not show:

- The lens was absorbed in the calibration sense. Swapping it left each theory about as well calibrated on the new channel as on the old.
- The ranking was not preserved. Over 40 targets, the four theories' admissions log scores span about 10 nats. A ranking with that little separation can flip between channels on noise alone.
- So the failure may say more about the criterion than about the mechanism: an order test needs enough data to separate the theories first. That reading is a hypothesis for the next plan, though, not a reason to re-judge this one. The criterion was fixed in advance and it failed.

## The evaluation (not yet run)

It is deferred to a machine with more room. A run needs about 10 GB of memory and 25 GB of disk per worker. The command and resume rules are in the science.me-lab README under "Running tier 1". Its report, a pass or fail for each criterion per generator, will be added here with the commit it ran from.
