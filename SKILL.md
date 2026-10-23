---
name: science-me
description: Contribute to science.me, a repository where agents and humans keep a machine-checked account of which theories the evidence supports. Use when proposing a theory as a frozen forecasting program, repairing one, requesting an observation, writing a read-back, shortening the library, or reading standings. Keywords - forecasting, frozen programs, prospective scoring, matched pairs, claims, wanted observations, read-back.
metadata:
  version: "0.1.0"
  category: science
---

# science.me: theories scored on data that did not exist when they were frozen

science.me is a repository in which humans and AI agents jointly maintain an honest, machine-checked, self-correcting account of what the evidence currently supports, what each supported claim rests on, and what would overturn it. A theory is a program that predicts data not yet collected. You freeze it, and it is scored when the data arrives. The one thing in science that cannot be gamed is time: a program frozen before the information it is scored on became available. Because agents can write programs cheaply, programs are abundant, and the scarce resource is observations that tell programs apart. The platform's most valuable output is therefore the ranked list of what to observe next.

Agents do everything that needs judgment (writing theories, repairs, read-backs, requests). The kernel does the checking. It is deliberately dumb: it freezes, runs frozen programs in a sandbox, scores them, and writes `standings.json`. It does not read your README or believe your comments.

## Setup (once per checkout)

Work from the repository root, or pass `--root PATH` before the command name.

```bash
uv sync
docker build -f scorer/Dockerfile -t scienceme-worker:latest .
uv run scienceme check          # prints "ok" when every program, mission and freeze is sound
```

**Prospective missions require container isolation, so build the image first.** Programs are untrusted code. In the container a program sees only its own frozen closure and the as-of archive view: no network, a read-only filesystem apart from a 256 MB `/tmp`, 2 GB of memory, one CPU, 256 processes, and a wall-clock limit of the mission's `run_timeout_s` (default 300 s) for all of one program's targets on one stream at one origin (a published issue). A mission's `required_isolation` is a floor, and `predict` and `rank-wanted` default to `--isolation container` and refuse anything weaker than the floor. `none` and `process` run program code with your full file and network access; they exist for simulation studies and trusted code, and are never how the prospective record is made. If docker or the image is missing, the command stops with an error and records nothing as a program's failure (what was already written stays); build the image and run it again. The worker never pulls an image; set `SCIENCEME_WORKER_IMAGE` to use another tag.

`uv run pytest -q` runs the tests. Tests that need a docker daemon are skipped unless you pass `--docker`; CI does not run them.

## Where things are

| Path | What it is | Who writes it |
|---|---|---|
| `programs/<name>/` | One program: `program.json`, entry module, `README.md`, later `readback.json` | contributors |
| `missions/<m>/mission.json` | The captain's standing orders: streams, horizons, claims, scoring parameters | the captain |
| `missions/<m>/wanted.jsonl` | Requested observations, one `WantedItem` per line, append-only | contributors |
| `archive/<stream id>/` | `stream.json` and one write-once capture per published issue | the kernel and fulfillers |
| `registry/freezes.jsonl` | Append-only record of every freeze and withdrawal, with times | `scienceme freeze` and `withdraw` |
| `scores/<m>/` | The prospective record (forecasts, rankings), write-once | `scienceme predict` and `rank-wanted` |
| `standings.json`, `STANDINGS.md` | Generated account of where each mission stands | `scienceme standings` |
| `scorer/` | The worker image's Dockerfile and pinned requirements | maintainers |

Never edit `registry/`, `archive/`, `scores/`, `standings.json` or `STANDINGS.md` by hand. The synthetic worlds that produce the data live in a private companion repository, `../science.me-worlds`. Never read it, list it or search it (see Rules).

## The loop

1. **Read** `standings.json` (see the last section) and the files in `missions/`.
2. **Pick a task** from the next section, by your own estimate of its value. The platform computes expected information gain for wanted items; everything else is your judgment.
3. **Produce the output**: a program, a repair, a wanted item, a read-back.
4. **It is checked.** Predictions are checked by the scorer, which no program can argue with. Text (read-backs, READMEs, tags) is checked by an agent of a different model lineage. Agenda is checked by the human.
5. **The scorer runs as vintages arrive**, standings regenerate, and you read them again.

The commands:

| Command | Does | Usually run by |
|---|---|---|
| `scienceme check` | Loads every program, mission and wanted list; verifies every freeze. Exit 1 lists the problems. | everyone, before every commit |
| `scienceme freeze NAME` | Freezes `programs/NAME` and records the time. | the author, once |
| `scienceme withdraw NAME --reason TEXT` | Ends a frozen program's eligibility for new targets. Old scores stand. | the author or the captain |
| `scienceme readback-packet NAME --mission M` | Prints the blind packet for a reader. | whoever commissions a read-back |
| `scienceme predict --mission M (--issue N or --all)` | Runs every eligible program on the published origins and records the forecasts. | the operator's loop |
| `scienceme rank-wanted --mission M` | Ranks the wanted list by expected information gain and saves it. | the operator's loop |
| `scienceme standings [--check]` | Writes the two standings files, or exits 1 if they are stale. | everyone, after a change that affects them |

Exit codes: 0 success; 1 a domain error (one line on stderr, never a traceback), a failed `check`, or stale standings; 2 a usage error. CI runs `pytest`, `check` and `standings --check` on every push and pull request, so a change that leaves the generated files stale fails CI. Run `uv run scienceme standings` and commit the two files with your change.

## Tier 1 tasks (what the repository supports now)

### Propose a theory

Trigger: a claim in `standings.json` with no matched pair, or a mechanism from the literature that is absent from the mixture.

1. Read `missions/<m>/mission.json` for the claim ids, their scopes and the streams, and `programs/seir-core/README.md` and a seed theory such as `programs/seir-x1-s1` for the conventions.
2. Create `programs/<new-name>/` with `program.json`, `program.py` and a `README.md` (see the contract below). Import the seed libraries rather than copying them, so that a pair shares its lens and core exactly.
3. Declare a non-empty scope and at least one tag. Declare pairs if the theory completes one (see "Pairs and claims").
4. Test the draft **before** you freeze it. There is no dry-run command, and a frozen program can never be fixed. Copy the pattern in `tests/test_seed_library.py` (a temporary workspace, a synthetic archive built with `tests/helpers.py`, `run_origin` with `Isolation.NONE`), and freeze in that temporary copy, not in the real registry.
5. `uv run scienceme check`, then `uv run scienceme freeze <new-name>`, then commit the new directory and `registry/freezes.jsonl` together.

To get the closure hash of a frozen program (for `imports`, `pairs` and `supersedes`):

```bash
uv run python -c "from pathlib import Path; from scienceme.registry import Registry; from scienceme.workspace import Workspace; [print(f.name, h) for h, f in Registry(Workspace(Path('.'))).freezes().items()]"
```

A theory earns evidence only from its freeze onward, on origins whose data was published after it. Freeze as soon as the program is tested: every origin published before the freeze is evidence it can never earn.

### Propose a repair

Trigger: a program's coverage dropped, its `calibration.coverage_90` is far from 0.9, a wanted item lists it under `failed`, or its README names a known weakness you can fix.

A repair is a **new program**: a new directory name, a new closure, a new freeze time. Set `supersedes` to the closure hash of the program you replace, and say in the new README what changed and why. The predecessor stays active for new targets until someone withdraws it, and its old scores are never recomputed: replacing a lens in December does not re-score October's forecasts with December's lens. The repair earns evidence from its own freeze onward. If the old program was in a matched pair, declare the pair again from the new program.

### Request an observation

Trigger: top programs disagree about an arm, regime or measurement nobody has observed. Append a `WantedItem` line to `missions/<m>/wanted.jsonl`. Do not write the JSON by hand; build the item from the models, which validates it and refuses a duplicate id:

```python
from pathlib import Path
from scienceme.archive import Archive
from scienceme.mission import Candidate, WantedItem, append_wanted, load_mission
from scienceme.model import Intervention, StreamSpec
from scienceme.workspace import Workspace

ws = Workspace(Path("."))
mission = load_mission(ws, "<m>")
parent = Archive(ws).spec("<base stream id>")      # copies world, role, jurisdictions, support_max
arm = StreamSpec(**{
    **parent.model_dump(),
    "id": "<base stream id>/close-w30",
    "parent": parent.id,
    "intervention": Intervention(variable="schools_closed", value=1.0, start_week=30),
})
targets = tuple(mission.targets(arm, 29) + mission.targets(arm, 30))   # reference weeks you want forecast
item = WantedItem(id="close-schools-w30", proposed_by="<your agent name>", cost=1.0,
                  candidate=Candidate(stream=arm, targets=targets))
append_wanted(ws, mission.name, item)
```

Notes. The arm must carry an intervention and a `parent`. Intervene on a variable programs declare in their `interface` (the seed library responds to `schools_closed` and `vaccinate_fraction`); a program with no matching interface entry cannot forecast the arm and does not enter its gain. `mission.targets` applies the mission's horizons and resolution lag, and skips targets that fall before the intervention starts. `cost` is declared by whoever would pay it, is positive, and is never voted; `fulfiller` defaults to `custodian`. An item is open while no archive stream has `fulfills` set to its id and its intervention starts after the latest published issue. The kernel attaches the gain, the supporting programs, and a priority of `(gain + sum of claim weight times targeted gain) / cost`. Run `scienceme check`; it validates every wanted list.

### Write a read-back

Trigger: any new program, or any program whose `flags` in `standings.json` include `missing` or `same-lineage`. (`pending` is the captain's to clear.) The protocol is in its own section below. Do not write the read-back of your own program, or of any program written by your own lineage.

### Shorten the library

Trigger: several programs repeat code. Put the shared code in a library program (`"library": true`, no `predict` needed) and have the programs import it by closure hash. A library is never run by itself. Existing programs are never edited to import it: the shortened versions are new programs that `supersede` the old ones, and keep the same lens so that pairs stay matched. Length is reported in the standings (`length_bytes`), not weighed in the score.

Not in tier 1, so leave to the captain: proposing a new stream, committing a predictive pmf on a wanted item, and editing `mission.json`. A mission draft you write is a proposal for the human to spot-check.

## The program contract

A program is a directory `programs/<name>/`. Its identity is its **closure hash**: a sha256 over every file in the directory, by relative path and content, except a top-level `readback.json` and anything under `__pycache__`. Symlinks are refused. `program.json` records the closure hash of each import, so the hash commits to the whole dependency closure. **The README is part of the closure.** Fixing a typo in a frozen README changes the hash.

### `program.json`

A `ProgramManifest`; unknown keys are rejected. `name` and `author_lineage` are required.

| Field | Meaning |
|---|---|
| `name` | Must equal the directory name. |
| `author_lineage` | Your model family, as `vendor/family` (the seeds use `anthropic/claude`). A read-back is compared with this string for equality. |
| `entry` | The module that defines `predict`. Default `program.py`. Must lie inside the directory. |
| `library` | `true` for code others import. A library is never run and never forecasts. Default `false`. |
| `imports` | Alias to closure hash. Every import must already be frozen. |
| `lens` | The alias (it must be one of `imports`) of the program that models how counts are reported, or `null`. |
| `scope` | A filter on `streams`, `roles`, `jurisdictions`, `horizons`; `null` matches anything. A program forecasts only the targets in its scope. |
| `interface` | The intervention variables it can condition on: `variable`, `timing` (`start_of_week`), and `alters` (the mechanisms it changes). |
| `tags` | Claim id to `asserts`, `denies` or `unspecified`: what the program says about each claim. |
| `pairs` | Matched-pair declarations: `{"claim": ..., "partner": <closure hash>}`. |
| `supersedes` | The closure hash of the program this replaces, or `null`. |

```json
{
  "name": "my-theory",
  "author_lineage": "openai/gpt",
  "entry": "program.py",
  "library": false,
  "imports": {"core": "sha256:...", "lens": "sha256:..."},
  "lens": "lens",
  "scope": {"roles": ["admissions"]},
  "interface": [{"variable": "schools_closed", "timing": "start_of_week", "alters": ["transmission"]}],
  "tags": {"school": "asserts"},
  "pairs": [],
  "supersedes": null
}
```

A theory (a program that is not a library) must declare a scope that restricts something and at least one tag. The kernel does not check this, but an unrestricted theory with no tags can take part in no claim and forecasts everything it is handed. A program with no `interface` forecasts base streams only: on an arm it gets no score, and it never inherits its baseline score there. `README.md` is prose for humans: what the program assumes and why, and its known weaknesses. Nothing is parsed from it, and the read-back reader never sees it.

### `program.py`

```python
from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)      # alias -> loaded module of each import; call at module level

def predict(ctx: Context, target: Target) -> Pmf:
    ...
```

`ctx.view` is the as-of archive: `view.as_of`, `view.spec(stream)`, `view.history(stream)` (every visible vintage, oldest first), `view.latest(stream)`, `view.series(stream, jurisdiction)` and `view.find(world, role)`. An origin is one published issue `t`: each eligible program is run on the archive as of `t`, which holds only vintages with `issue <= t` that were published at or before the origin's information cutoff. An arm's history is its parent's. A target names `stream`, `jurisdiction`, `reference_week`, `horizon` and `resolution_lag`; `target_week = reference_week + horizon`, and the target resolves against the vintage published in issue `target_week + resolution_lag`. **You forecast the value that vintage will report**, so reporting delay and backfill matter. Counts are revised upward in later issues, and `lens-admissions` exists to model that.

Return a `Pmf`: `Pmf.from_probs(lo, probs)`, `Pmf.point(v)`, `Pmf.uniform(lo, hi)` or `Pmf.from_samples(samples)`. It is the distribution you commit to, not a point estimate. It is scored as `(1 - eps) * pmf + eps * Uniform{0..support_max}`, in nats, so the loss on any one target is bounded. Its support must lie inside `[0, support_max]` (read `ctx.view.spec(target.stream).support_max`).

- **Determinism.** Draw every random number from `ctx.rng()`, a generator seeded by program and target. Never seed from the clock, and never use the global `random` or `numpy.random`.
- **No network, no files outside your closure.** Read your own files relative to `__file__` if you must. Only the standard library, `numpy`, `scipy`, `pydantic` and the `scienceme` package (import from `scienceme.sdk`) are installed in the worker image.
- **Failures are per target.** If `predict` raises, or returns something that is not a `Pmf`, or a pmf with NaN or negative mass or mass outside `[0, support_max]`, that target is recorded as unscored with the error as the reason, and the other targets proceed. There is no fallback score: an unscored target neither helps nor hurts your weight, but it lowers your coverage, and a pair whose member covers fewer than `coverage_min` of its targets is dropped from claim standings.
- **One process per run.** All the targets of one program at one origin on one stream run in one process under one time limit. Fit once and cache at module level, keyed by what the fit depends on (`seir-core` does).
- **Targets in the future.** While ranking wanted items, a candidate's targets lie beyond the data: `target.reference_week` can exceed `ctx.view.as_of`. Measure the lead from the last week in the view, not from `target.horizon`, and do not assume the reference week has been published.

## Pairs and claims

A claim is a statement the mission wants evidence on, with a scope. It is not a property of one program. Its standing comes only from **matched pairs**: two frozen programs that differ only in their stance on it. The result is model-relative predictive support, never causal evidence: it says the mechanism helped or did not help these forecasts, under the assumptions the pair shares.

How pairs work now:

- A program pairs with **one partner over a set of claims**. Every `{claim, partner}` entry naming the same partner joins that set.
- The set must be split the same way. This program asserts every claim in the set and the partner denies every one, or the reverse. It cannot assert one and deny another in the same pair.
- **Every other tag must be equal** (a missing tag counts as `unspecified`), the scopes must be equal, and the lenses must both be absent or the same import.
- `scienceme freeze` checks all of this against the partner's manifest, and refuses with a one-line reason. The partner must already be frozen, so the first program of a pair declares nothing and the second declares the first. One declaration is enough.
- Some claims come in a broad form and a narrower one that **refines** it (`refines` in the mission file; the same mechanism where it cannot act, say). Two programs that differ in that mechanism are tagged differently on both, and `freeze` requires every claim on which they differ to be in the declared set, so declare the pair over the broad claim and its refinement together.
- A pair **counts for a claim only within the claim's family**: the claim itself, the claims that refine it, and the claim it refines. A pair whose declared set reaches outside the family is confounded for that claim and left out of its standing. So never put unrelated mechanisms in one pair: pair them separately, as the seeds do.
- A pair is also left out when either member's coverage is below the mission's `coverage_min`.
- Each pair's `delta_nats` is the summed log-score difference, asserting side minus denying side, over the resolved targets in the claim's scope that both programs predicted. When `delta_nats / tau` (the mission's `tau`) is at least `claim_threshold_nats` the pair supports the claim, and when it is at most the negative of that it contradicts it. In between is `insufficient evidence`. Pairs that disagree give `mixed`. A claim with no pair is `insufficient evidence`.

The seed library is a worked example: the four `seir-x{0,1}-s{0,1}` programs assert or deny `covariate-x`, its refinement `covariate-x-flat`, and `school`. A program pairs with the one that differs in the covariate effect (declared over `covariate-x` and `covariate-x-flat` together) and with the one that differs in the school effect (declared over `school` alone), never with the one that differs in both. Read their `program.json` files.

The kernel checks the manifests, not the code. Whether two programs really differ only in the tagged mechanism is what the README and the read-back are for. Do not tag a program `asserts` or `denies` for a mechanism its code does not literally contain or lack.

## Rules

1. **Never edit a frozen directory.** Not the code, not a comment, not the README, not whitespace. A directory that no longer hashes to its freeze is `modified-after-freeze`: its runs are skipped, it is never scored under the old hash, and `scienceme check` reports it until it is restored (`git checkout -- programs/<name>`). A program edited after freezing is never scored.
2. **Every change is a new directory name, with `supersedes`.** Two edits to one idea are two names. Write the README before you freeze.
3. **Freeze, then commit.** Run `scienceme freeze`, and commit the program directory and `registry/freezes.jsonl` in the same commit, promptly. The freeze time decides which origins you are eligible for: only those whose data was published strictly after it.
4. **Theories declare a non-empty scope and at least one tag.**
5. **Never read `../science.me-worlds`.** It is the private companion repository that generates the synthetic worlds. Do not open, list, grep or import from it, and do not infer its contents. A program written from the generator is written from the answer, and the platform exists to prevent that. Write programs from general knowledge of the domain and from the data in the archive.
6. **Do not write the stores that belong to the kernel.** `registry/freezes.jsonl`, `archive/`, `scores/` and the generated standings files are never edited by hand. Append-only stores raise on a write that would overwrite.
7. **No weaker isolation to record anything.** If the container does not work, fix docker, do not lower `--isolation`.
8. **Do not mark your own homework.** Do not write the read-back of your own program or your lineage's, and set a `captain_verdict` only if you are the captain.
9. Before committing, run `uv run pytest -q`, `uv run scienceme check`, and `uv run scienceme standings --check` (run `scienceme standings` first if it reports stale).

## The read-back protocol

A read-back is a different lineage's account of what a program literally assumes, so that disagreement with the author's tags and README is found by comparison, not by reading code. It is implemented in `src/scienceme/readback.py`.

1. **Commission.** Run `uv run scienceme readback-packet NAME --mission M`. The packet is printed to stdout and is deterministic. It holds the source of the program and of every program in its closure (imports first), and the mission's claims (id and statement), then the `Readback` JSON schema. Programs are labelled by the first 12 hex digits of their closure hash, not by name. **Left out:** the name, `author_lineage`, `tags`, `pairs`, `interface`, `supersedes`, every README (any case, any extension, any depth) and `readback.json`. `program.json` is shown only through an allowlist: `entry`, `library`, `imports`, `lens`, `scope`.
2. **Read.** Hand the packet, and only the packet, to an agent of a **different model lineage** than the author's `author_lineage`: Codex for a Claude program, Claude for a Codex program. The reader judges what the code does and disregards comments, docstrings and names.
3. **Write.** The reader's answer is one JSON document that matches the `Readback` schema, saved as `programs/NAME/readback.json`:
   - `author_lineage` and `author_agent`: the *reader's* lineage and agent name, not the program's author's.
   - `assumptions`: each assumption about the world or the data, one sentence each.
   - `inferred_tags`: for every claim listed in the packet, keyed by claim id, `asserts`, `denies` or `unspecified`.
   - `inferred_interface`: the names of the intervention variables the code responds to.
   - `summary`: a short plain description of what the program does.
   - `captain_verdict`: `"pending"`. The reader leaves it.
4. **Captain's verdict.** The captain (the human, or an LLM captain) compares the read-back with the README and the tags, and sets `captain_verdict` in that file to `"matches"` or `"mismatch"`. Nobody else does.
5. **Commit and refresh.** Writing `readback.json` does **not** change the closure hash, so the program stays frozen and eligible. Check that the file loads (`uv run python -c "from pathlib import Path; from scienceme.readback import load_readback; print(load_readback(Path('programs/NAME')))"`; an invalid file stops `scienceme standings`), run `uv run scienceme standings`, and commit `readback.json` with the regenerated standings files.

The flags that comparison raises appear on the program in `standings.json`: `missing` (no read-back), `same-lineage` (reader's string equals the author's), `tag-mismatch` (inferred tags differ from the manifest's over any claim either names, absent meaning `unspecified`), `interface-mismatch` (the sets of variable names differ), `pending` (no verdict yet) and `captain-mismatch`. A flag shows on the program's row in every stream it appears in and lowers `readback_clean_share`, because a wrong tag on a heavy program redirects the wanted list. Read-back is an audit aid, not a proof.

## Reading `standings.json`

It is a JSON list with one object per mission that has published data (an empty list means nothing is scored yet). `STANDINGS.md` is the same account for humans. Everything in it is a pure function of the repository, and programs are identified by closure hash; `program_names` maps each hash to its name.

- **`mission`, `epoch`, `as_of`, `scorer`.** The mission, its scoring epoch, the latest published issue, and the hash of the scorer that produced the numbers.
- **`streams`**: one per count stream (arms included). Its `programs` are those with records on it that were never withdrawn, best cumulative weight first:
  - `w_cumulative` and `w_current` are weights over the programs awake on the stream, proportional to `exp(advantage / tau)`. `advantage_cumulative` is a program's summed log score over the mixture's, in nats. `current` discounts old targets by the mission's half-life, so recent evidence counts more. A newcomer starts at zero advantage.
  - `n_predicted`, and `coverage = predicted / (predicted + unscored)`. Low coverage means the program is failing on targets.
  - `calibration`: a PIT histogram `pit` and central-interval `coverage_50` and `coverage_90` over `n` resolved points (the coverages are `null` when `n` is 0). A calibrated program has a flat histogram and coverage equal to the level. Weight says relative advantage; calibration says whether a program is adequate on its own terms.
  - `length_bytes` (size of the closure) and `flags` (the read-back flags above).
  - Per stream: `mixture_log_score`, `mixture_calibration`, and `n_resolved` and `n_pending`. **Pending targets are waiting for their resolution vintage; they are never scored as zero.** `regime_flag` is true when `regime_tv`, the distance between cumulative and current weights, exceeds the mission's threshold: recent evidence disagrees with the long record.
- **`claims`**: one per mission claim, with `verdict` (`supports`, `contradicts`, `insufficient evidence`, `mixed`) and its `pairs`, each with `asserts`, `denies`, `delta_nats`, `n_targets` and its own verdict.
- **`ranking`**: the wanted list as last ranked, best first, or `null`. Each item has `gain` (nats of expected information about which program is right, over the `supporting` programs that forecast every target), `targeted` (the gain per claim that has a pair among them), `priority`, `cost`, and `failed` (programs that should have forecast it but did not).
- **`indicators`**: the field's health over the programs holding 90% of the cumulative weight on the first base stream. `lineage_entropy` near 0 means one lineage dominates; `readback_clean_share` is the share of top programs with no flags; `interface_weight_share` is the weight held by programs that can forecast arms.

How to turn that into a task:

| You see | Do |
|---|---|
| A claim with no pairs, or only `insufficient evidence` | Propose a theory that completes a matched pair. |
| Top programs disagree on a hypothetical arm | Request an observation, targeted at a claim. |
| A program with poor `coverage` or `coverage_90` far from 0.9 | Propose a repair. |
| A program under `failed` in the ranking | Find out why: a target failed, or its directory was modified after freezing (restore it from git). Then repair it as a new program. |
| `missing` or `same-lineage` flags | Commission a read-back from a different lineage. (`pending` waits for the captain.) |
| Low `lineage_entropy` | Contribute from a lineage the top set lacks. |
| A large `n_pending` | Wait. Nothing resolved is hidden, and nothing pending is counted. |
| Several programs repeating code | Shorten the library. |

Before you finish: `check` and `standings --check` both exit 0, a new program is frozen and committed together with its freeze record, and its README says plainly what it assumes and where it is known to be wrong.
