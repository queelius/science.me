# science.me (design document)

**Version:** 0.5 (2026-10-23)
**Status:** brainstorm output, pre-plan. The social layer (section 8) is deliberately open. Drafted by one model lineage; a review by a different lineage is pending before approval (6.2, item 10).
**Authors:** Alexander Richard Towell (decisions), Claude (drafting; calls marked as such)

Labels:

- **Decided**: Alex said this in conversation. Treat as fixed.
- **Call**: Claude's choice where a builder needed one. Alex has not confirmed; overridable.
- **Open**: nobody has decided. Sections 8 and 9 collect these.

Version 0.3 was a simplification pass over 0.2; 0.4 inverts the economics: intelligence is abundant and observations are scarce (changelog, section 11). The machinery (section 4) is two kinds of thing people create, one scorer, one puller, and git.

---

## 0. In one paragraph

science.me is a collaborative platform, in the mold of [Prove2Me](https://prove2.me), on which humans and AI agents jointly maintain an honest, machine-checked, self-correcting account of what the evidence currently supports, what each supported claim rests on, and what would overturn it; and, on the same machinery, propose new theories as programs that predict data not yet collected, and are scored when it arrives. Prove2Me industrialized the *verification and composition* of mathematical proofs so that uncoordinated contributions accumulate instead of piling up. science.me does the same for empirical claims. The one thing science has that cannot be gamed is *time*: a program committed before the data existed. That is the platform's kernel, and in the pilot it is literally a git repository. Agentic intelligence is assumed as a first principle (Decided): agents do everything that requires judgment, and the design's job is to make each of their outputs checkable (section 5). Because intelligence can be bought with compute, programs are abundant and the scarce resource is observations that discriminate between them, which arrive at the speed of the calendar. The platform's most valuable output is therefore the ranked list of what to observe next (4.10).

---

## 1. Intent

### 1.1 Purpose (Decided)

> Keep an honest, machine-checked, self-correcting account of what the evidence currently supports, what it rests on, and what would change it, and use that account to direct a large population of agents and humans at the tests that would change it most.

The long-run deliverable to a person: ask "what do we actually know about X, how strongly, and what would overturn it?" and get an answer with provenance. The literature answers "what has been asserted"; Wikipedia answers "what is the consensus"; neither answers *why, how well, on what assumptions*.

The grand vision (Decided) is the discovery of novel theories of a data-generating process, expressed as programs, from samples of it. The ledger and the discovery engine are the same machine; a discovery is a program that takes weight from the others (4.4).

### 1.2 What it is, and is not

It **is**: a repository of programs that predict streams of data, scored only on data that arrived after each program was committed, with a standing derived from those scores; a ranked list of the observations that would most change those standings; and a set of captained missions that say which streams, which claims, and which observations matter.

It is **not**: a replacement for the scientific community (the community is the open-ended collaboration of intelligences; what it lacks is a composition rule, and this is the composition rule); a way to extract new truths from static public data by volume (a fixed dataset holds bounded evidence and re-analysis spends it; given up deliberately); or a laboratory (it cannot make observations; it says which observation is worth making, with a number attached, and that is its main product).

### 1.3 Relation to Prove2Me

Prove2Me (Chen, Marwaha, Lu, Yuen, Peng, arXiv 2608.28433) rests on four structural properties; the generalization is the tuple *(statement language, verifier, composition rule, audit surface)*.

| Property | Prove2Me | science.me |
|---|---|---|
| Cheap, final checker | Lean 4 kernel; binary, never reversed | **None.** Replaced by: git history for ordering, a pinned scorer for arithmetic, reproducibility for everything else. All revisable except the ordering. |
| Statement separate from proof | Immutable theorem, many proofs | Immutable program, many scores over time. |
| Composition preserves certainty | Parent proved iff children proved | **Does not hold.** Standings are recomputed from scratch whenever an input is superseded. Nothing propagates; everything is derived. |
| Small fixed audit surface | Mission core; blind read-back | Mission README plus each program's read-back. Same idea. |
| Where intelligence goes | agents write proofs; Lean checks | agents write programs, pick tests, assign blame; the scorer checks predictions, other lineages check text, humans check agenda (section 5) |

Carried over unchanged: statement/proof separation, immutability, atomization, missions with captains, the discussion channel, credit for reuse, "point your agent at one URL," a workspace repo that mirrors the server's layout. New: scoring on future data in place of a kernel, and git as the substrate.

---

## 2. Goals, non-goals, anti-goals

**Goals.** (1) Every standing is recomputable by anyone who clones the repo and runs the scorer. (2) A standing changes only because new data arrived or an input was superseded; never by fiat. (3) An agent with no context can write a program, commit it, and have it scored, without coordinating with anyone. (4) Human attention goes to mission READMEs, read-backs, and reading the standings. (5) The platform's own calibration is reported.

**Non-goals.** Settling realism (predictive adequacy on unobserved observables is the whole criterion). Replacing journals, registries, or the forecast hubs. Automating agenda-setting. A single scalar truth score per claim.

**Anti-goals**, each with the indicator the standings report so that drift is visible:

| Anti-goal | Indicator |
|---|---|
| A correlation mountain | share of mixture weight on programs with exposed structure; mixture entropy trend |
| An oracle nobody can trace | share of top-weight programs whose read-back matches their README |
| A monoculture | lineage entropy among top-weight programs and among read-back authors |
| Goodhart | weight held by predictive near-duplicates (4.4); rank divergence between log-score and WIS |
| A manufactured-doubt engine | deferred with the social layer (section 8) |

---

## 3. Philosophical commitments

Unchanged from 0.2 in substance; tightened.

1. **Predictive adequacy, out of distribution (Decided).** A theory is judged by how well it predicts observables, and must predict ones not yet observed: future data, new regimes, interventions. Realism is not settled and need not be.
2. **Falsifiability is the entry rule (Decided).** A program that declares no targets it could score badly on is not a theory.
3. **No claim is tested alone (Decided).** A bad score indicts a set: theory, lens, data, scorer. Blame is assigned by whoever proposes a supersession that improves the score, priced in bits.
4. **Theories are generative programs (Decided).** Prediction is running the program; evidence is how well real data scores under it; comparing theories is comparing scores on shared targets. The scorer and the lenses are programs under the same review.
5. **Theory quality is compression (Call).** Prior weight 2^(−|p|) in a shared reference language; posterior weight ∝ 2^(−[|p| + codelength of data under p]). The reference language is the paradigm: a change of primitives that makes a long theory short is what a paradigm shift is, and the shared library of importable programs is that language. Compression across environments, not within one, recovers invariant (causal) structure, which is why out-of-distribution adequacy forces causal content without any appeal to unobservables. In the pilot the length term is a tie-breaker; the data term dominates within weeks.
6. **Keep all consistent theories, weighted (Decided).** Consistency is comparative, never absolute. Falsification is weight decaying to negligible relative to the mixture, and is reversible. The mixture is the standing belief; a short program that collapses it is understanding.
7. **The only trusted kernel is time (Call).** What cannot be faked is the order of commits. Everything else, including the scoring rule, is a revisable program.
8. **Severity (Call).** A test counts in proportion to how probably it would have failed had the theory been wrong: committed before the data, on targets the program had not seen, differing from what the mixture already predicted. All three are facts in git history.
9. **Messiness is functional (Decided).** Standings are cumulative scores, so they move by bounded amounts per week and never toggle.
10. **Interventions are program surgery (Call).** For a program that exposes its assignments, `do(X = x)` is: replace the assignment of X, leave the rest. Derived, not authored, correct by construction relative to the declared structure. The structure *is* the causal claim, and two observationally equivalent programs that differ in one assignment's parents differ in what they predict on an intervention arm.
11. **Intelligence is abundant; observations are scarce (Decided).** Programs cost compute. Discriminating observations cost calendar time, instruments, and people. The binding constraint on real evidence is time, so the platform's throughput is bits of evidence per week, and its levers are breadth of streams, observing where programs disagree, and synthetic worlds that compress time. Data found in the wild is context for generating theories, not evidence, because current models have read it.

---

## 4. The design

### 4.1 Two kinds of thing people create

**Data vintages.** A stream is a directory `data/<stream>/`; each release is a commit of a CSV plus metadata (jurisdiction, period, `do` arm if any). The git history of the directory is the vintage sequence. Release time is push time, which the host records and the pusher does not control. Streams are revised (backfill), which is why vintages exist: a target is scored against a stated vintage, by default the first release at or after a fixed lag the mission names.

**Programs.** A directory `programs/<name>/` containing:

- `program.py`: takes a masked history (all data before the target) and returns samples of the target. May import other programs. May expose its assignments (4.6).
- `README.md`: a natural-language account of what it assumes and why, with **tags** naming the mechanisms it encodes (4.5). Required, as on Prove2Me; this is what search indexes.
- `readback.md`: written by a different model lineage than the author's, stating what the program literally assumes, with every assumption explicit (4.8).

Every theory, lens, definition, baseline, synthetic generator, and the scorer itself is a program. "Definition" and "lens" are roles (a program others import), not kinds.

### 4.2 Time is the commitment

A program's score on a vintage **counts iff the program's commit precedes the vintage's commit.** That is the whole commitment mechanism. There is no separate commit/reveal, no per-prediction commitment, and no preregistration object: the program is the analysis plan, and the scorer runs it on a history masked to end before the target, so "used only prior data" is enforced rather than promised. Methods are therefore public from the moment they are committed, which is the Prove2Me licensing stance and a deliberate choice.

### 4.3 The scorer

One pure function, one program, pinned in a container with no network:

```
score(program, vintage, target) =
    samples ← run program on history(vintage) masked before target, fixed seed, time limit
    pmf     ← negative binomial fitted to samples by moments
    log pmf(realized value at target)
```

Summed over a mission's targets. A failed or timed-out run scores as the mission's baseline program. Scores are a cache keyed by (program hash, vintage hash, scorer hash); nobody creates them. Quantiles and WIS are computed from the same samples for comparability with the forecast hubs, but standing uses the log-score.

Negative-binomial-by-moments is a Call: it has no free parameter, suits counts, keeps likelihood-ratio semantics between programs (so the evidence layer and the theory layer are one number), and admits any sampler, which mechanistic epidemic models are.

### 4.4 Weights and standings

```
weight(program) ∝ exp( Σ counted scores ) × 2^(−amortized length)
```

where length is gzipped canonical source bytes, and an imported program's length is divided among its importers. This is the Bayes/Hedge rule; its cumulative score is within the length prior of the best single program in hindsight. Stacking is deferred (4.12). A discovery is a program whose entry shifts weight; its size is the bits by which the mixture's total codelength fell. Amortized length is what prices the protective belt: a lens imported by one program is charged to it in full; one imported by twenty is nearly free.

**Near-duplicates (Call).** Programs whose predictive distributions coincide on all scored targets (negative-binomial fits within a tolerance) are one program for weighting: the cluster's weight is computed once and split among members, and the shortest member is canonical. Without this, N copies of one program carry N times the weight, which is a Sybil attack on the mixture and, with agent loops that generate variants, an accident waiting to happen. The tolerance is a free parameter.

Standings report mixture weights and never a single best program: with N committed programs the prior pays log N bits, which is the population-scale multiple-comparisons correction, and the top-ranked of a million is lucky, not right.

`STANDINGS.md` is generated by the scorer and committed; CI fails when it is stale, the pattern Alex already uses for `STATE.md`.

### 4.5 Claims are tags

A claim such as "absolute humidity reduces transmission" is a tag. Programs declare the mechanisms they encode; the read-back (4.8) checks that the tags match what the code assumes; a claim's standing in a mission is the weight of programs carrying the tag against the weight of those not carrying it. A published effect size is a pair of narrow programs differing in one term. Claims need no arithmetic of their own.

Where programs exist that differ *only* in the tagged mechanism (same lens, same structure otherwise), the claim's standing is computed over those matched pairs; otherwise it falls back to tagged-versus-untagged weight and is labeled as the weaker comparison. The reason is weakness 2 in 6.2: the score conflates mechanism with noise model, and matched pairs hold the noise model fixed.

### 4.6 Environments are masks; interventions are arms

An environment is a vintage plus a mask over its rows. The out-of-distribution test is a mask: the mission names held-out jurisdictions, the scorer fits the program on the rest and scores it on the held-out ones, and that score is reported separately as the program's **invariance score**.

An intervention is a stream with `do` metadata: a synthetic world publishes arms (baseline, `do(school = closed)`, `do(vaccination = 0.8)`), and agents request new arms in the mission discussion. Before scoring a program on an arm, the scorer applies surgery (3.10) to the program's exposed assignments. A program that does not expose assignments receives the baseline's score on intervention arms. There is no admission rule; the incentive does the work.

### 4.7 Supersession and recomputation

Objects are immutable. To change a program or a vintage, commit a new one; the old hash and its scores remain. When an imported program, a vintage, or the scorer is superseded, every standing downstream is recomputed from scratch. Nothing propagates, nothing is damped, and there is no blame-assignment machinery: the diff in `STANDINGS.md` is the blame report, and the supersession that improved the score, priced in bits, is the verdict. Prove2Me's "parent proved iff children proved" is the special case where recomputation always returns the same answer.

### 4.8 Read-back

For every program, an agent of a different model lineage than the author's, given the code and its imports but not the README, writes what the program literally assumes. The captain compares it to the README and the tags. Faithfulness is judged on that comparison, not by reading code. This is Prove2Me's mechanism verbatim, and it is also the design's first anti-monoculture measure.

**LLM captains (Decided for the pilot; safeguards Call).** The captain may be an agent. Safeguards: read-back by a different lineage; the human spot-checks a sample; every read-back records which agent wrote it, so trust can be discounted retroactively. A mis-audited program in the pilot is a mis-tagged ledger entry, so the cost is bounded.

### 4.9 Kernel and trust

Three components. **Git**, pushed to a host that records push time: content-addressed, append-only, ordering not under the committer's control. **The scorer**, a pinned container, tiny, tested against synthetic worlds with analytic answers, versioned; every score records its scorer hash, and upgrading the scorer is a recomputation like any other. **The puller**, which runs stream-ingest programs on schedule inside the kernel, so that a vintage is attested as what the source served at that time by the kernel and not by an agent. Anyone who clones the repository can recompute every standing.

Honesty about the pilot's kernel: the repository has one owner who can force-push, so ordering is trusted-by-owner, not ungameable, and the puller runs on the owner's machine, so its attestation is as strong as the owner. Before any contributor outside Alex's loops, anchor each push's commit hash externally (OpenTimestamps, or a mirror the owner cannot rewrite); this is cheap and should not be skipped.

Contamination policy is binary: a score counts iff committed before the vintage, or the vintage is from a private synthetic world. There are no discount classes; the weekly stream makes them unnecessary.

### 4.10 Wanted observations and expected information gain

A mission file carries a **wanted list**: candidate observations proposed by agents (an intervention arm on a synthetic world, a new stream with its puller program, a real experiment or data pull someone could perform). For each candidate the kernel computes its **expected information gain**: the mutual information between the candidate observation and program identity under the current mixture, which is the entropy of the mixture's predictive minus the weighted entropies of the programs' predictives, all from samples the programs already produce (with surgery applied for arms). Agents propose; the kernel ranks; the synthetic custodian fulfills automatically; humans fulfill real ones in order.

The standings also report the mixture's entropy and the expected information gain of the next scheduled vintage. Together they are an **allocation signal**: when programs agree, more data is useless and the hypothesis space needs new programs; when they disagree, data is the bottleneck and the wanted list is what to spend on.

A flexible, mechanism-free program (the baseline, or a well-tuned statistical model) is always in the mixture as the **none-of-the-above check**: if it dominates every mechanistic program, no mechanism in the mixture is adequate, and the right task is new programs, not new data. This recovers the model-check layer that 0.3 dropped, at no cost, and it is the guard against weakness 3 in 6.2.

This is "the mixture's disagreement is the map" made operational, and it is the design's answer to abundant intelligence: a million agents are for pointing at the next observation, not for mining the last one.

### 4.11 Repository layout

```
science-me/
  SKILL.md                 # agent entry point, Prove2Me style
  scorer/                  # the trusted program; container spec; tests
  data/<stream>/           # vintages as commits; metadata incl. do arms
  programs/<name>/         # program.py, README.md (tags), readback.md
  missions/<name>.md       # targets, lag, held-out masks, claims of interest, wanted list, captain
  pullers/<stream>/        # ingest programs the kernel runs
  scores/                  # derived cache
  STANDINGS.md             # generated; CI fails when stale
  standings.json           # the same, machine-readable (5.4)
```

A private companion repository holds synthetic generators and publishes their vintages into `data/synthetic-*/`.

### 4.12 What 0.2 had and 0.3 dropped

| Dropped | Replaced by | Comes back when |
|---|---|---|
| Truth maintenance, nogoods, blame distribution, damping | recompute from scratch (4.7) | never, unless recomputation becomes too slow |
| Claims as objects with e-values; test specifications | tags over programs (4.5) | never |
| Evidence items as submissions | the scorer's cache (4.3) | never |
| Lens as a node type | a program others import; amortized length (4.1, 4.4) | never |
| Commitment objects, commit/reveal | commit order of programs (4.2) | if methods ever need to be hidden |
| Interactive `do()` API | intervention arms as streams (4.6) | if arm requests become a bottleneck |
| Interventional-content classes; admission rule | baseline score on arms for opaque programs (4.6) | never |
| Four calculi; stacking; anytime-valid tests | one score, Bayes/Hedge weights (4.3, 4.4) | stacking if the mixture collapses badly; tests when a verdict with error control is wanted |
| Three contamination classes | binary rule (4.9) | if static data is ever scored |
| Reusable holdout, Thresholdout budgets | streams | if static holdouts are ever used |
| Density requirement | negative binomial fitted to samples (4.3) | never |
| Web service and API | repository, CLI, scorer | if contributors outside Alex's loops appear |

---

### 4.13 The library: seeding with established theories (Decided as an idea; discipline Call)

Alex's proposal: populate the platform with programs implementing established theories, and the datasets they predict and explain. On the trail, with one discipline.

What seeding is for:

1. **The reference language.** Established theories are the primitives new programs import; the shared library is the paradigm (3.5). Without it every new program is long and the length prior is meaningless.
2. **Baselines with teeth.** A discovery is a program that takes weight from the field's actual theories, not from a last-value model.
3. **Legibility.** Standings anchored to named theories read as science.
4. **Scorer calibration on real history.** A theory known to explain a historical dataset should score well on it; a cheap sanity check, like synthetic worlds but on real data.
5. **Claims need both sides.** Tags mean nothing until programs with and without the mechanism exist.

Prove2Me has the exact precedent: when handed an existing compiled project, upload it first and set the mission on top of it.

The discipline: **historical data is pre-commit, so it earns no standing.** A dataset enters either as a stream with a puller (future vintages count) or as mission context (no scores). Seeding builds the library and the baselines; standing comes only from predicting the streams from the commit onward. That is a feature, not a limitation: established theories get tested prospectively, which the community almost never does. Seeding is mission-driven, not encyclopedic: the pilot seeds the standard epidemic models (SIR and SEIR variants with seasonal forcing, Serfling-style seasonal regression, humidity-driven transmission, the hub baseline and, where reproducible, hub ensemble members as programs) and attaches past seasons as context. "Download everything the theories explain" is the sea-of-data fantasy returning, and is out of scope.

## 5. The engine: agents are the industrial loop (Decided: agentic intelligence is a first principle)

The kernel (4.9) is deliberately dumb. Everything that requires judgment is done by agents, and the design's job is to make every agent output checkable by something that is not an agent of the same lineage. That is the whole division of labor, and it is where the industrialization comes from: intelligence proposes, the kernel scores, intelligence reads the scores and proposes again. FunSearch and AlphaEvolve are this loop with a cheap exact evaluator; Prove2Me is this loop with Lean; science.me is this loop with the scorer.

### 5.1 The loop

Each agent session, as `SKILL.md` will describe it:

1. Read `standings.json` and the mission files.
2. Pick a task (5.2), prioritized by the agent's own estimate of expected information gain. The platform does not compute this; agents do, from the standings and the programs' READMEs.
3. Produce the output: a program, an arm request, a mission edit, a read-back, a flag.
4. The output is checked (5.3).
5. The scorer runs as vintages arrive; standings regenerate; repeat.

### 5.2 Tasks (what intelligence does)

| Task | Trigger in the standings | Output |
|---|---|---|
| Propose a theory | a claim of interest with no program on one side; a mechanism from the literature absent from the mixture | a program with README and tags |
| Request an observation | top programs disagree on a hypothetical arm, regime, or measurement | an entry in the mission's wanted list; the kernel attaches its expected information gain (4.10) |
| Propose a stream | a public, regularly updated source would discriminate programs or open a domain | a puller program the kernel runs (4.9) |
| Assign blame | a program's score dropped, or its invariance score is poor | a supersession of the theory, a lens, or a shared program, with a README saying why |
| Translate the literature | a mission's claim of interest cites a paper | a program encoding the paper's mechanism, tagged |
| Write a read-back | any new program | `readback.md`, by a different lineage |
| Shorten the library | several programs share code | a shared program others import (DreamCoder's sleep phase) |
| Draft or edit a mission | a captain's request, or a new stream | a mission file for the human to spot-check |

These replace mechanisms earlier versions tried to engineer: prioritization, identification analysis, natural-experiment search, blame distribution. All are judgment, so all are agent tasks.

### 5.3 Checks (what keeps intelligence honest)

Three checkers, and every output has exactly one:

- **The scorer** checks predictions. Programs cannot argue with it.
- **A different model lineage** checks text: read-backs against READMEs and tags, mission drafts, blame narratives.
- **The human** checks agenda and samples: which missions and streams exist, and a spot-check of read-backs.

Nothing an agent writes enters a standing without passing through one of these. The scorer is a proper scoring rule, so optimizing against it is honest prediction; its one known limitation is that the negative-binomial projection cannot represent multimodal predictives, which is a limitation rather than an exploit.

### 5.4 What this does to the design

- The standings must be machine-readable: `standings.json` beside `STANDINGS.md`, including per-target disagreement among the top programs and the ranked wanted list, so agents can find crucial tests without parsing prose.
- The allocation signal (4.10) tells agents which task is worth compute right now: new programs when the mixture agrees, observations when it disagrees.
- Throughput scales with compute: scoring and read-backs are parallel, git append is cheap, and there is no merge queue. The same scaling story as Prove2Me.
- The human role narrows to agenda, spot-check, and reading the output. The pilot's LLM captain is the first instance.
- The monoculture risk concentrates, because proposer, prioritizer and auditor are all agents. Lineage diversity in read-backs is the minimum; weighting by lineage diversity is the first thing to add from section 8.

---

## 6. Failure modes, known weaknesses, abandonment criteria

### 6.1 Failure modes and designed responses

| Failure | Response |
|---|---|
| Forking paths | only pre-commit programs score (4.2) |
| Training-data contamination | the stream is post-cutoff for every model by construction; synthetic worlds are private |
| Evidence exhaustion | the platform is organized around streams, not static re-analysis; throughput is measured in bits per week, and the wanted list directs collection to where it pays (4.10) |
| Look-elsewhere at population scale | mixture weights, never a headline program; the prior pays log N (4.4) |
| Monoculture | read-back by a different lineage (4.8); **further mechanism Open** |
| Cascades | **Open** (section 8) |
| Manufactured doubt | **Open**; in the pilot, one contributor |
| Goodhart | credit is weight shift on committed data, which rewards only what nothing else predicted; no volume metrics |
| Brittleness | cumulative scores move by one week's worth per week |
| Correlation mountain | invariance scores (4.6); the length prior; intervention arms |
| Illegibility | README and read-back on every program; `STANDINGS.md` is readable |
| Scorer bugs | the scorer is a versioned program tested against analytic cases; recompute on upgrade |
| Overengineering | section 4 fits on one screen |


### 6.2 Known weaknesses (self-criticism)

1. **The domain may be uninformative about mechanism.** Weekly admission counts may not discriminate mechanistic theories; the hubs have run for a decade without producing theory. If so, mixture entropy over mechanistic programs stays flat and the stream's expected information gain for mechanism is near zero. The allocation signal would show it, and the response is arms the real stream cannot supply, which is why tier 1 exists. This is the central risk, and it is a risk of the domain, not of the mechanism.
2. **The score conflates mechanism and noise model.** Log-score rewards calibration and sharpness, so a right mechanism with a wrong noise lens loses to a wrong mechanism with a good one. Mitigation: lenses are importable, and claims use matched pairs (4.5). Residual: real.
3. **Active learning with a misspecified hypothesis space can be worse than random.** If nothing in the mixture is near the truth, expected information gain directs collection toward distinguishing wrong theories. Mitigation: the none-of-the-above check (4.10) and lineage diversity. Residual: real.
4. **The read-back is an LLM judging an LLM.** Published audits of comparable setups find faithfulness far from perfect. It catches gross mismatches; tags can be subtly wrong; claim standings inherit that. Mitigation: human spot-checks and low stakes per tag.
5. **The pilot's kernel is trusted-by-owner** (4.9).
6. **Near-duplicates inflate weight**, and the clustering fix has a free parameter (4.4).
7. **The length prior is crude and minifiable.** Tie-breaker only.
8. **Thirty resolutions per season is coarse.** Year-one real standings will be noisy; tier 1 carries the statistical weight.
9. **No flagship.** Prove2Me grew on a famous theorem; this design has no equivalent, and the social layer will not bootstrap without one.
10. **Monoculture begins with this document**, drafted by one lineage. A different-lineage review of the design is the first thing to do before approval.

### 6.3 What would make us abandon this

- Tier 1: directed collection does not beat random, or weight fails to concentrate on the generator even with unlimited arms. The kernel is too weak for composition. Abandon the design.
- Tier 2: the none-of-the-above program dominates every mechanistic program all season, while tier 1 passed. The mechanism works and the domain is wrong. Change the domain, not the design.
- No program ever takes weight from the seeded library (4.13). Either the library is complete, which is unlikely, or agents cannot produce theories that beat the field, in which case the premise that intelligence is the cheap input fails for this domain.

---

## 7. Pilot

### 7.1 Domain (Decided)

Two tiers, run concurrently, in one domain.

**Tier 1, feedback on demand: private synthetic epidemic worlds.** A stochastic multi-jurisdiction SEIR-type generator with seasonal forcing and jurisdiction-specific parameters, observed through a reporting lens (delay, backfill, under-ascertainment), publishing a baseline arm and at least two intervention arms. Plus one adversarial generator not written as a compartmental model (an agent-based network model), so the true program is not short in the reference language by construction. Vintages are released on demand. This is where the scorer is built and debugged, and where a lens swap (a new observation channel on the same generator) tests whether the platform absorbs it in an imported program rather than a theory rewrite.

**Tier 2, the real stream: US respiratory disease surveillance.** Weekly hospital admissions for influenza, COVID-19 and RSV from NHSN, and outpatient ILINet, the data behind the CDC forecast hubs. The 2026–27 season is starting, so every week is post-cutoff for every model. Hub target definitions, formats and scoring exist to borrow. The field is theory-rich: mechanistic transmission programs compete with phenomenological ones, and jurisdictions are the invariance axis. Backfill exercises vintages from the first week. One natural experiment is on record: the near-absent 2020–21 influenza season.

Claims of interest for the mission README, as examples: absolute humidity and transmission (Shaman and Kohn 2009); school holidays (Cauchemez et al. 2008); vaccination coverage and admissions; the post-pandemic RSV seasonality shift; the 2020–21 interventions.

Alternatives set aside: NHANES (two-year cycle, latest release already in training data); CSEP earthquake forecasting (the strongest precedent for prospective committed testing, irregular events); Rubin/LSST (needs captains); masked-data reliability (niche).

### 7.2 Scope

- One mission, `missions/respiratory-2026-27.md`: targets (streams, jurisdictions, weeks), resolution lag, held-out jurisdictions, claims of interest, captain (an LLM, 4.8).
- Three synthetic worlds (two compartmental with different lenses, one adversarial), each with a baseline and at least two intervention arms, each with its own mission file.
- A baseline program (last-value negative binomial) in every mission.
- Every mission file has a wanted list; the synthetic custodian fulfills requests in EIG order.
- The library is seeded with the standard epidemic models as programs (4.13) before the first real vintage is scored.
- Contributions come from Alex's existing agent loops through `SKILL.md`; no orchestrator is built (Decided).
- Scores are summed across jurisdictions and weeks for weights; this is a score, not a test, and claims no error control.

### 7.3 Success criteria (falsifiable)

1. Tier 1: weight concentrates on the generator's predictive equivalent within a budget the builder sets; surgery-derived predictions on intervention arms match the generator; a lens swap is absorbed by an imported program; a deliberately wrong program injected with a false README is caught by read-back; and **directed collection beats undirected**: bits of mixture entropy removed per fulfilled request are higher for agent-proposed, EIG-ranked requests than for random arms. The last is the test of the whole premise.
2. Tier 2: (a) eight consecutive weekly vintages scored, with the platform's calibration reported; (b) at least one claim of interest has a standing that differs materially from "published = supported," with provenance; (c) at least one invariance score reported for a program fitted on some jurisdictions and scored on the held-out ones.
3. One person who is not Alex commits a program.
4. Someone in the field says `STANDINGS.md` told them something they did not know.

If 1 or 2 fails, the mechanism is wrong and nothing more is built. If 3 or 4 fails, the mechanism may be right and the social layer is wrong.

Time horizon (Decided: a year is too long). Tier 1 in days. Tier 2's first counted score one week after the first program commit; 2(a) about two months after.

### 7.4 Out of scope

Real-money stakes; reputation; moderation; multiple captains; other domains; a UI beyond the repository and `STANDINGS.md`; a web service; stacking; anytime-valid tests; static holdouts; beating the hub ensemble; NHANES.

---

## 8. Open: the social layer

Deliberately undecided. Alex's instruction: copy existing systems where possible, Prove2Me first. With git as the substrate, the pilot gets defaults for free: a submission is a commit or pull request, credit is authorship, conflict is review. Whether those survive contributors outside one person's agent loops is the open question. Specifically:

1. **Cost of submission**: compute, reputation, nothing. The sole defense against manufactured doubt.
2. **Credit**: weight shift and import count are the currencies; how they become a portable credential, and whether it flows to the human or the agent, is open. Prove2Me credits the human account.
3. **Conflict**: who adjudicates a contested read-back. Prove2Me: captains plus moderators.
4. **Diversity and cascades**: blind phases before discussion is visible; weighting by lineage diversity; rewarding dissent that later wins.
5. **Agenda**: how captains are recruited.
6. **Markets**: play-money markets over claim standings as the human-facing layer.

Sources: Prove2Me; the forecast hubs; Metaculus; Polymath; Stack Exchange; CASP.

### 8.1 Git as substrate (Call, raised by Alex)

Git's object store is right and git's workflow is wrong. The pilot uses the store (content-addressed, append-only, externally timestamped) and avoids the workflow: there is no trunk to merge into, because programs are self-contained and added once. The Prove2Me paper names the merge queue as the bottleneck of large swarms; this design has no merge queue. A million agents appending to a sharded append-only store is an ordinary systems problem; a million agents merging into one branch is not.

---

## 9. Left to the builder

1. **Program interface.** The `program.py` contract (inputs: masked history as a dataframe plus target spec; output: samples), the optional exposed-assignments convention that surgery acts on, and the import mechanism.
2. **Scorer.** Container spec, seeds, time and memory limits, the negative-binomial fit, WIS alongside, the cache format, `STANDINGS.md` generation, CI staleness check.
3. **Ingest.** The puller: weekly NHSN and ILINet pulls into `data/`, with vintage metadata; the resolution lag; the contract for agent-proposed puller programs.
7. **Expected information gain.** The computation from program samples (entropies of the negative-binomial fits), its cost, and how often the wanted list is re-ranked.
8. **Near-duplicate clustering.** The predictive-distance measure and tolerance (4.4).
9. **External anchoring.** The timestamping or mirroring used once contributors outside Alex's loops appear (4.9).
4. **Synthetic generators.** The three generators, their lenses and arms, in the private repository; the publishing step.
5. **Length measure.** Gzipped canonical source; the amortization over importers.
6. **SKILL.md.** Mirroring Prove2Me's: setup, roles, the loop and task table of section 5, the read-back protocol.

---

## 10. References

Platform and prior art: Chen et al., *Prove2Me*, arXiv 2608.28433 (2026). Romera-Paredes et al., *FunSearch* (2023); *AlphaEvolve* (2025). Ellis et al., *DreamCoder* (2021). Steegen et al., multiverse analysis (2016). Udrescu and Tegmark, *AI Feynman* (2020).

Epistemology and statistics: Popper; Lakatos; Kuhn; Mayo, *Statistical Inference as Severe Testing* (2018); van Fraassen, *The Scientific Image*; Worrall (1989); Peirce (1877); Merton (1942). Gelman and Shalizi (2013). Dawid, prequential principle (1984). Rissanen, MDL (1978). Solomonoff (1964). Cover, universal portfolios (1991). Yao, Vehtari, Simpson, Gelman, stacking (2018). Minka (2000). Grünwald, de Heide, Koolen, *Safe Testing* (2024). Shafer, *Testing by betting* (2021). Peters, Bühlmann, Meinshausen, invariant prediction (2016). Schölkopf et al. (2021). Woodward (2003). Pearl, *Causality* (2009). Tetlock et al., extremizing (2014).

Pilot domain: Mathis et al., FluSight evaluation, Nature Communications (2024). Bracher, Ray, Gneiting, Reich, WIS (2021). Cramer et al., COVID-19 Forecast Hub ensemble, PNAS (2022). Shaman and Kohn, PNAS (2009). Cauchemez et al., Nature (2008). Schorlemmer et al., CSEP (2018).

---

## 11. Changelog

- **0.1** (2026-10-23): initial draft from the brainstorm.
- **0.1.1** (2026-10-23): builder check applied.
- **0.2** (2026-10-23): Alex's decisions applied: respiratory surveillance stream, synthetic worlds for feedback on demand, LLM captain, contributions from Alex's agent loops; interventions as surgery; lenses; vintages.
- **0.5** (2026-10-23): self-criticism pass. Added: indicators per anti-goal (2); near-duplicate clustering (4.4); matched-pair claim standings (4.5); honesty about the pilot kernel and external anchoring (4.9); the none-of-the-above check (4.10); the library and the seeding discipline (4.13, Alex's proposal); known weaknesses and abandonment criteria (6.2, 6.3); different-lineage review pending (status).
- **0.4** (2026-10-23): economics inverted (Decided: intelligence is abundant, observations are scarce). Added: commitment 11; wanted lists with kernel-computed expected information gain and the allocation signal (4.10); the puller as a kernel component (4.9); mixture weights as the look-elsewhere correction (4.4); observation-request and stream-proposal tasks (5.2); directed-versus-undirected collection as a pilot criterion (7.3).
- **0.3** (2026-10-23): simplification pass (KISS). Two kinds of created object (data vintages, programs); programs are the commitments; scores are a cache; claims are tags; environments are masks; interventions are arms; recompute replaces truth maintenance; one scorer (negative binomial by moments) and one weight rule; binary contamination rule; git as the substrate; no web service. Section 4.12 lists what was dropped and when it returns. Added section 5, the engine: agentic intelligence as a first principle (Decided), the agent loop, the task table, and the three checkers.
