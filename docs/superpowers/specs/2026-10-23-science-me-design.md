# science.me (design document)

**Version:** 0.7 (2026-10-23)
**Status:** brainstorm output, pre-plan. The social layer (section 8) is deliberately open. Reviewed by a different model lineage (Codex) at 0.6; the review is at `docs/superpowers/reviews/2026-10-23-codex-review-of-design-0.6.md` and 0.7 applies it (changelog, section 11). Two decisions pending from Alex (section 7.5).
**Authors:** Alexander Richard Towell (decisions), Claude (drafting; calls marked as such), Codex (review of 0.6)

Labels:

- **Decided**: Alex said this in conversation. Treat as fixed.
- **Call**: Claude's choice where a builder needed one. Alex has not confirmed; overridable.
- **Open**: nobody has decided. Sections 8 and 9 collect these.

The machinery is two kinds of thing people create, one scorer, one archive, and git. It is somewhat heavier than 0.3 claimed; the Codex review showed where 0.3's simplifications had thrown away load-bearing parts.

---

## 0. In one paragraph

science.me is a collaborative platform, in the mold of [Prove2Me](https://prove2.me), on which humans and AI agents jointly maintain an honest, machine-checked, self-correcting account of what the evidence currently supports, what each supported claim rests on, and what would overturn it; and, on the same machinery, propose new theories as programs that predict data not yet collected, and are scored when it arrives. Prove2Me industrialized the *verification and composition* of mathematical proofs so that uncoordinated contributions accumulate instead of piling up. science.me does the same for empirical claims. The one thing science has that cannot be gamed is *time*: a program frozen before the information it is scored on became available. That is the platform's kernel. Agentic intelligence is assumed as a first principle (Decided): agents do everything that requires judgment, and the design's job is to make each of their outputs checkable (section 5). Because intelligence can be bought with compute, programs are abundant and the scarce resource is observations that discriminate between them, which arrive at the speed of the calendar. The platform's most valuable output is therefore the ranked list of what to observe next (4.10).

---

## 1. Intent

### 1.1 Purpose (Decided)

> Keep an honest, machine-checked, self-correcting account of what the evidence currently supports, what it rests on, and what would change it, and use that account to direct a large population of agents and humans at the tests that would change it most.

The long-run deliverable to a person: ask "what do we actually know about X, how strongly, and what would overturn it?" and get an answer with provenance. The literature answers "what has been asserted"; Wikipedia answers "what is the consensus"; neither answers *why, how well, on what assumptions*.

The grand vision (Decided) is the discovery of novel theories of a data-generating process, expressed as programs, from samples of it. The ledger and the discovery engine are the same machine; a discovery is a program that takes weight from the others (4.4).

### 1.2 What it is, and is not

It **is**: a repository of programs that predict streams of data, scored only on data that became available after each program was frozen, with a standing derived from those scores; a ranked list of the observations that would most change those standings; and a set of captained missions that say which streams, which claims, and which observations matter.

It is **not**: a replacement for the scientific community (the community is the open-ended collaboration of intelligences; what it lacks is a composition rule, and this is the composition rule); a way to extract new truths from static public data by volume (a fixed dataset holds bounded evidence and adaptive re-analysis spends it; given up deliberately); or a laboratory (it cannot make observations; it says which observation is worth making, with a number attached, and that is its main product).

### 1.3 Relation to Prove2Me

Prove2Me (Chen, Marwaha, Lu, Yuen, Peng, arXiv 2608.28433) rests on four structural properties; the generalization is the tuple *(statement language, verifier, composition rule, audit surface)*.

| Property | Prove2Me | science.me |
|---|---|---|
| Cheap, final checker | Lean 4 kernel; binary, never reversed | **None.** Replaced by: an as-of archive and git history for ordering, a pinned scorer for arithmetic, reproducibility for everything else. All revisable except the ordering. |
| Statement separate from proof | Immutable theorem, many proofs | Immutable program (its whole dependency closure), many scores over time. |
| Composition preserves certainty | Parent proved iff children proved | **Does not hold.** The prospective record is immutable; standings are derived from it and a correction is a new, labeled analysis. |
| Small fixed audit surface | Mission core; blind read-back | Mission file plus each program's read-back. Same idea. |
| Where intelligence goes | agents write proofs; Lean checks | agents write programs, pick tests, propose repairs; the scorer checks predictions, other lineages check text, humans check agenda (section 5) |

Carried over unchanged: statement/proof separation, immutability, atomization, missions with captains, the discussion channel, credit for reuse, "point your agent at one URL," a workspace repo that mirrors the server's layout. New: scoring on future data in place of a kernel, and git as the substrate.

---

## 2. Goals, non-goals, anti-goals

**Goals.** (1) Every standing is recomputable by anyone who clones the repository and the archive and runs the scorer. (2) A standing changes only because new data arrived, or because a correction was made and labeled as such; never by fiat. (3) An agent with no context can write a program, commit it, and have it scored, without coordinating with anyone. (4) Human attention goes to mission files, read-backs, and reading the standings. (5) The platform's own calibration is reported.

**Non-goals.** Settling realism (predictive adequacy on unobserved observables is the whole criterion). Replacing journals, registries, or the forecast hubs. Automating agenda-setting. A single scalar truth score per claim: a claim's standing is a labeled comparison with provenance, and the map behind it is primary.

**Anti-goals**, each with the indicator the standings report so that drift is visible:

| Anti-goal | Indicator |
|---|---|
| A correlation mountain | share of mixture weight on programs with a declared structural interface (4.6); calibration of the mixture (4.10) |
| An oracle nobody can trace | share of top-weight programs whose read-back matches their README |
| A monoculture | lineage entropy among top-weight programs and among read-back authors |
| Goodhart | predictive near-duplicates among top-weight programs (4.4); rank divergence between log-score and WIS |
| A manufactured-doubt engine | deferred with the social layer (section 8) |

---

## 3. Philosophical commitments

1. **Predictive adequacy, out of distribution (Decided).** A theory is judged by how well it predicts observables, and must predict ones not yet observed: future data, new regimes, interventions. Realism is not settled and need not be.
2. **Falsifiability is the entry rule (Decided).** A program that declares no targets it could score badly on is not a theory.
3. **No claim is tested alone (Decided).** A bad score indicts a set: theory, lens, data, scorer. The platform does not assign blame; it records which repair, made afterward, predicted better from then on. That identifies a successful modification, not which component was originally wrong, and the design says so.
4. **Theories are generative programs (Decided).** Prediction is running the program; evidence is how well real data scores under it; comparing theories is comparing scores on shared targets. The scorer and the lenses are programs under the same review.
5. **Theory quality is compression (Call, as a principle; not implemented in the weights).** The Solomonoff/MDL picture, prior weight 2^(−|p|) in a reference language, is the right account of what a good theory is, and the shared library of importable programs is the reference language, which makes the library the paradigm. But a usable length measure for weighting does not exist at pilot scale (6.2, item 5), so length is reported and not used in standings. Compression across environments *rewards* invariant structure; it does not establish causation (4.6).
6. **Keep all consistent theories, weighted (Decided).** Consistency is comparative, never absolute. Falsification is weight decaying to negligible relative to the mixture, and is reversible in principle; in practice a single very confident wrong prediction can cost hundreds of nats, so the score floors the pmf (4.3). The mixture is the standing belief; a short program that collapses it is understanding.
7. **The only trusted kernel is time (Call).** What cannot be faked is which information was available when a program was frozen. Everything else, including the scoring rule, is a revisable program.
8. **Prospective-only is a conservative eligibility rule (Call; softened after review).** A score counts only if the program was frozen before the information it is scored on was available. This is not a severity calculation in Mayo's sense, which would need a specified error and a probe's power to expose it; it is the eligibility rule under which adaptively selected analyses cannot be presented as fresh confirmation.
9. **Messiness is functional (Decided).** Standings never toggle by editorial act. They can move a lot on one observation, because log loss is unbounded above; the floor in 4.3 bounds how much.
10. **Interventions are program surgery, where the program declares its semantics (Call).** Replacing an assignment is a valid intervention inside a declared structural causal model. A Python assignment is not one by default: timing, who is affected, and which downstream mechanisms change must be declared. Surgery is applied only through a declared structural interface (4.6).
11. **Intelligence is abundant; observations are scarce (Decided).** Programs cost compute. Discriminating observations cost calendar time, instruments, and people. The binding constraint on real evidence is time, so the platform's throughput is bits of evidence per week, and its levers are breadth of streams, observing where programs disagree, and synthetic worlds that compress time. Data found in the wild is not counted as prospective evidence, because exposure cannot be ruled out; it is context for generating theories. The long-run scaling path is fulfillers that take requests from agents, from the synthetic custodian to human collaborators to automated cloud laboratories; that integration is out of the pilot's scope, but the interface to it is not (4.10).

---

## 4. The design

### 4.1 Two kinds of thing people create

**Data, held in an as-of archive.** A stream is a source (NHSN admissions, a synthetic world's arm). The kernel captures the source's raw responses on schedule, with headers, timestamps and hashes, and stores them untouched (4.9). Versioned transformation programs turn raw captures into tables. The archive answers one question: *what was available at time t*. Every forecast origin is a time t, and a program run for origin t sees exactly the archive as of t, not the rows with event dates before t. Revisions (backfill) are therefore handled by construction: a later vintage of an earlier week is new information with its own availability time.

**Programs.** A directory `programs/<name>/` containing:

- `program.py`: given the archive as of an origin and a target specification (stream, jurisdiction, reference date, horizon), returns a **predictive pmf** over the target's integer values (or the hub's quantile set, 4.3). May import other programs. May declare a structural interface (4.6). May declare a narrower scope than the mission's full target set (4.4).
- `README.md`: a natural-language account of what it assumes and why, with three-valued **tags** per claim of interest (4.5).
- `readback.md`: written by a different model lineage than the author's, stating what the program literally assumes (4.8).

A program's identity is the hash of its **entire dependency closure**: its own source, every import at the exact hash imported, and any fitted artifacts it ships. Changing any of these creates a new program with a new freeze time (4.7).

Every theory, lens, definition, baseline, synthetic generator, transformation and the scorer itself is a program. "Definition" and "lens" are roles, not kinds.

### 4.2 Time is the commitment

A program is **eligible** for a forecast origin t iff its dependency-closure hash was committed and pushed before the **information cutoff** of t, which is the source's own publication time for the data that origin t may use, not the kernel's capture time. The agent who reads the CDC's Wednesday release and commits a program before the puller runs is not eligible for that week. For a synthetic world the rule is the same: the custodian releases a vintage only after the programs to be scored on it are frozen; a private generator does not make its already-published outputs unseen.

A counted **forecast opportunity** (Call, answering the reviewer's question 1) is a prediction of a future event week at a declared horizon from a reference date, resolved against the vintage of that week at a declared resolution lag. Nowcasts of already-occurred but unreported weeks, and forecasts of later revisions, are distinct categories and are out of the pilot.

There is no separate commit/reveal and no per-prediction commitment: the frozen program is the analysis plan, and the kernel runs it on the as-of archive, so "used only prior information" is enforced rather than promised. Methods are public from the moment they are committed, which is the Prove2Me licensing stance and a deliberate choice.

### 4.3 The scorer

One pure function, one program, pinned in a container, with a worker that sees only the archive as of the origin and the program's closure, nothing else in the repository, no network:

```
score(program, origin, target) =
    pmf ← run program on archive(as of origin) for target
    pmf ← (1 − ε) · pmf + ε · floor          (ε declared; floor = baseline's pmf)
    log pmf(realized value at resolution vintage)
```

The scorer scores **the submitted distribution**, which is what makes the log score proper; it does not project samples onto a parametric family, because that projection can be exploited by misreporting the variance (review, finding 2). Programs that simulate convert their own samples to a pmf; that conversion is theirs. The ε-floor bounds the loss of any single target at −log ε and is what makes 3.6's reversibility true in practice; ε is declared per mission and is a known compromise of strict propriety at the floor. Quantiles and WIS are computed from the same pmf for comparability with the forecast hubs, but standing uses the log score.

A failed or timed-out run produces **no score**: the target is marked unscored for that program, which affects its coverage (4.4). A fallback prediction is never attributed to the program (review, finding 10).

### 4.4 Weights and standings

Programs have different entry dates and may have different scopes, so cumulative scores are made comparable by **common opportunities**: for any target a program did not predict, whether because it was not yet frozen, outside its declared scope, or failed, it is assigned the standing mixture's score at that target. A newcomer therefore starts level with the mixture and must beat it from its entry onward; it cannot escape accumulated losses by re-entering (review, finding 3). A program's **coverage** (the share of the mission's targets it predicted itself) is reported beside its weight, and a program whose own predictions cover less than a mission-declared minimum does not enter claim comparisons (4.5).

```
weight(program) ∝ exp( Σ scores on common opportunities / τ )
```

These are **tempered exponential predictive weights**, declared as such, and not Bayesian posterior beliefs: scores summed across correlated jurisdictions overcount shared information, and the temperature τ (declared per mission, with the number of jurisdictions as the default scale) is the acknowledged correction. The Hedge bound, that the mixture's cumulative loss is within log(1/π_i) of any fixed program's, holds under fixed prior masses and common opportunities, both of which 4.4 now supplies; it says nothing about population-scale multiple comparisons, and the design no longer claims it does. Standings still report mixture weights and never a single best program.

Two quantities are reported, because they answer different questions (review, finding 14): **cumulative standing**, the undiscounted sum, which is the evidential record; and **current usefulness**, the same sum under exponential forgetting with a declared half-life, which is what the forecast hubs and the wanted list care about during a changing epidemic. Which of these counts as "the" standing in missions is pending Alex (7.5).

Length is **not** in the weights. It is reported per program as a diagnostic, and used to choose the canonical member when two programs are predictively identical. Predictive near-duplicates are reported, not clustered into the weights: agreement on past targets is not equivalence on future interventions, and splitting weight by cluster membership invited a claim-level Sybil attack (review, finding 6). Sybil resistance at the hypothesis level is a social-layer question (section 8).

Stacking is not exceptional in the M-open world; it is the standard remedy when every program is wrong and a persistent mixture predicts better than any one. It remains deferred for the pilot, with that acknowledged.

`STANDINGS.md` and `standings.json` are generated by the scorer and committed; CI fails when they are stale, the pattern Alex already uses for `STATE.md`.

### 4.5 Claims are labeled comparisons over matched programs

A claim of interest (a mission names them: "absolute humidity reduces influenza transmission in this population, at these horizons") is a **three-valued tag** on programs: *asserts*, *denies*, or *unspecified*. An untagged program need not deny the mechanism; it may fold it into seasonality or make no mechanistic claim at all, so tagged-versus-untagged weight is not evidence about the claim and is not computed (review, finding 8).

A claim's standing is computed only over **matched pairs**: programs that differ only in the tagged mechanism, each separately refitted, with the same lens and otherwise the same structure (Call, answering the reviewer's question 6). Where no matched pair exists, the claim's standing is "insufficient evidence." The result is reported as **model-relative predictive support** with the pair's provenance, never as causal evidence: ablating a term tests its predictive contribution under the remaining assumptions, and confounding, measurement error and collinearity remain. A claim's scope (population, outcome, horizon, regime) is declared in the mission file, and a published effect size is represented as a matched pair with that scope, not as a bare number.

### 4.6 Held-out jurisdictions; interventions through a declared interface

The mission names held-out jurisdictions; the scorer fits a program on the rest and scores it on the held-out ones, and that score is reported separately as the program's **held-out-jurisdiction predictive score**. It measures geographic transfer. It is not an invariance test and does not establish causal structure (review, finding 9); a seasonal proxy can transfer because the confounding persists, and a correct mechanism can transfer badly because susceptibility or reporting differ. A separately specified invariance analysis, with explicit environment assumptions, is out of the pilot.

An intervention is a stream with `do` metadata: a synthetic world publishes arms (baseline, `do(school = closed)`, `do(vaccination = 0.8)`), and agents request new arms in the mission discussion. Surgery (3.10) is applied only through a **declared structural interface**: the program names its intervenable variables, when in the time step each takes effect, which units it applies to, and which downstream mechanisms it alters, in a schema the builder defines (9.1). An arm is **supported** by a program only if its interface covers the arm's `do`. On arms it does not support, a program gets no score and is excluded from arm-based standings and from any claim comparison that needs that arm; it never inherits the baseline's performance there (review, finding 10).

### 4.7 Supersession and the prospective record

Objects are immutable. To change a program or an import, commit a new one; it is a new program with a new freeze time and its own eligibility. The predecessor stays active for new targets unless withdrawn, and withdrawal stops new scoring without touching old scores. Lineage (`supersedes`) is tracked for reporting, not for weight.

**The prospective record is never recomputed.** A program's scores on the targets it predicted, with the closure it had when frozen, stand. Replacing a lens in December does not re-score October's program with December's lens; that would turn a post-outcome repair into historical predictive success (review, finding 4). Two kinds of correction exist and are labeled: a **scorer arithmetic correction** (a bug in the scorer, fixed and recorded as a new scorer hash, re-run on the prospective record with both results kept), and a **source data correction** (the source itself corrects a release). Neither is a change of scoring convention after seeing outcomes; a change of convention is a new mission epoch. Current standing is computed from the prospective record under the current scorer hash, with the corrected analysis beside it.

### 4.8 Read-back

For every program, an agent of a different model lineage than the author's, given the code and its imports but not the README, writes what the program literally assumes. The captain compares it to the README and the tags. Faithfulness is judged on that comparison, not by reading code. This is Prove2Me's mechanism verbatim, and it is also the design's first anti-monoculture measure.

The read-back is an audit aid whose error is not bounded to one entry: a wrong tag on a high-weight program redirects the wanted list, and a wrong shared import affects many programs. Read-back disagreement is therefore reported as a flag on every standing that depends on the program.

**LLM captains (Decided for the pilot; safeguards Call).** The captain may be an agent. Safeguards: read-back by a different lineage; the human spot-checks a sample; every read-back records which agent wrote it, so trust can be discounted retroactively.

### 4.9 Kernel and trust

Four components. **The archive**: raw source captures stored untouched with provenance (URL, time, headers, hash), separate from the versioned transformations that produce tables; running a transformation on the owner's machine establishes who ran it, not that its output is what the source served, so the raw capture is what is trusted and transformations are programs like any other (review, finding 15). **Git**, pushed to a host that records push time: content-addressed, append-only. **The scorer**, a pinned container, tiny, tested against synthetic worlds with analytic answers, versioned; every score records its scorer hash. **The worker**, which isolates a program run to the archive as of its origin and the program's closure; the information boundary is enforced by what the worker can read, not by disabling the network alone.

Honesty about the pilot's kernel: the repository has one owner who can force-push, so ordering is trusted-by-owner, not ungameable. Before any contributor outside Alex's loops, anchor each push's commit hash externally (OpenTimestamps, or a mirror the owner cannot rewrite); this is cheap and should not be skipped.

Eligibility is binary (4.2). There are no contamination discount classes.

### 4.10 Wanted observations, expected information gain, and calibration

A mission file carries a **wanted list**: candidate observations proposed by agents (an intervention arm on a synthetic world, a new stream with its transformation program, a real experiment or data pull someone could perform). Each candidate names its observation model: what would be measured, on whom, when. For each candidate the kernel computes **expected information gain about program identity**:

```
I(M; Y) = H( Σ_m w_m p_m(Y) ) − Σ_m w_m H( p_m(Y) )
```

over the **subset of programs whose interfaces support the candidate** (4.6), using their actual predictive pmfs for that observation; the mixture inside the first entropy stays a mixture and is never projected. The subset is reported with the number, because a gain computed over three programs is a different claim from one computed over thirty (Call, answering the reviewer's question 7). For experiments producing several measurements the computation uses marginals, which can miss disagreement about dependence; that is a stated limitation.

This objective is about *which program*; it is blind to parameter uncertainty inside a program and to shared blind spots (review, finding 12). Two guards: a declared **exploration reserve**, a fraction of fulfilled requests chosen outside the current disagreement; and **calibration** as the absolute adequacy check, which program-identity gain cannot supply. The scorer reports probability-integral-transform histograms and interval coverage for the mixture and for each program, which is the standard forecast-evaluation check of whether a predictive distribution is adequate on its own terms, and it is the operational form of the model-check layer that Gelman and Shalizi distinguish from model comparison. A flexible mechanism-free program is kept in every mixture as a useful competitor, not as a check: its winning shows relative advantage, not that every mechanism is inadequate.

Agents propose; the kernel ranks; **fulfillers** act. A fulfiller is anything that turns a wanted item into a vintage: the synthetic custodian (automatic, zero latency, the pilot's cloud lab), a human collaborator, or eventually an automated laboratory with an API. Each fulfiller declares a **cost**; priority is gain per unit cost. Cost is declared by whoever would pay it, never voted.

Gain can be **targeted** at a claim of interest: how much the observation would move that claim's matched-pair standing. Missions weight their claims of interest, and priority uses targeted gain. That is how human values enter prioritization without anyone voting on experiments.

**Votes are predictions (Call, from Alex's proposal that the community vote on proposed experiments).** The scorable form of "this experiment is worth running" is a committed predictive distribution for its outcome, recorded against the wanted item and scored when it is fulfilled. Disagreement among committed predictions is information gain computed over judgments rather than programs, and it can carry what the mixture cannot see, such as a suspicion that every program is wrong. In the pilot these predictions are recorded and scored but not weighted into priority; weighting by track record is the reputation system (section 8).

The standings report mixture entropy, the gain of the next scheduled vintage, and calibration together as an **allocation signal**, which is a heuristic: low gain with good calibration suggests new programs are needed more than new data; low gain with bad calibration suggests every program shares a blind spot; high gain suggests data is the bottleneck.

### 4.11 Repository layout

```
science-me/
  SKILL.md                 # agent entry point, Prove2Me style
  scorer/                  # the trusted program; container spec; tests
  archive/                 # raw source captures with provenance (kernel-written)
  transforms/<stream>/     # versioned programs: raw capture -> table
  programs/<name>/         # program.py, README.md (tags), readback.md
  missions/<name>.md       # targets, horizons, lag, held-out masks, claims (scope), wanted list, epsilon, tau, captain
  scores/                  # the prospective record; append-only
  STANDINGS.md             # generated; CI fails when stale
  standings.json           # the same, machine-readable (5.4)
```

A private companion repository holds synthetic generators and releases their vintages into the archive after the programs to be scored are frozen.

### 4.12 What earlier versions had and 0.7 does not

| Dropped | Replaced by | Comes back when |
|---|---|---|
| Truth maintenance, nogoods, blame distribution | the immutable prospective record plus labeled corrections (4.7); repairs earn evidence going forward | never |
| Claims as objects with e-values; tagged-versus-untagged weight | three-valued tags and matched pairs (4.5) | never |
| Evidence items as submissions | the scorer's prospective record (4.3) | never |
| Lens as a node type | a program others import (4.1) | never |
| Commitment objects, commit/reveal | freeze time of the dependency closure against the source's cutoff (4.2) | if methods ever need to be hidden |
| Interactive `do()` API | intervention arms as streams through a declared interface (4.6) | if arm requests become a bottleneck |
| Negative-binomial projection of samples | programs submit pmfs; ε-floor (4.3) | never |
| Length in the weights; amortized import cost; near-duplicate clustering | length reported; duplicates reported (4.4) | a frozen reference library with a specified coding scheme per epoch |
| Bayesian interpretation of the weights; "the prior pays log N" | tempered exponential predictive weights, declared as such (4.4) | a joint model across jurisdictions |
| Baseline fallback scores for opaque or failed programs | unscored, excluded (4.3, 4.6) | never |
| Flexible baseline as the none-of-the-above check | calibration (PIT, coverage) as the adequacy check (4.10) | never |
| Invariance score | held-out-jurisdiction predictive score (4.6) | a specified invariance analysis |
| Recompute from scratch on supersession | never for the prospective record (4.7) | never |
| Four calculi; stacking; anytime-valid tests | one score, one weight rule | stacking is likely needed and is deferred, not dismissed |
| Three contamination classes; reusable holdout | binary eligibility against the source's cutoff | if static data is ever scored |
| Web service and API | repository, CLI, scorer | if contributors outside Alex's loops appear |

### 4.13 The library: seeding with established theories (Decided as an idea; discipline Call)

Alex's proposal: populate the platform with programs implementing established theories, and the datasets they predict and explain. On the trail, with one discipline.

What seeding is for: the reference language (established theories are the primitives new programs import, and the library is the paradigm); baselines with teeth (a discovery takes weight from the field's actual theories); legibility; scorer calibration on real history; and matched pairs (claims are computable only when programs with and without the mechanism exist). Prove2Me has the exact precedent: when handed an existing compiled project, upload it first and set the mission on top of it.

The discipline: **historical data is pre-freeze, so it earns no standing.** A dataset enters either as a stream in the archive (future vintages count) or as mission context (no scores). Seeding builds the library and the baselines; standing comes only from predicting the streams from the freeze onward. That is a feature: established theories get tested prospectively, which the community almost never does. Seeding is mission-driven, not encyclopedic: the pilot seeds the standard epidemic models (SIR and SEIR variants with seasonal forcing, Serfling-style seasonal regression, humidity-driven transmission, the hub baseline and, where reproducible, hub ensemble members) and attaches past seasons as context. "Download everything the theories explain" is the sea-of-data fantasy returning, and is out of scope.

---

## 5. The engine: agents are the industrial loop (Decided: agentic intelligence is a first principle)

The kernel (4.9) is deliberately dumb. Everything that requires judgment is done by agents, and the design's job is to make every agent output checkable by something that is not an agent of the same lineage. That is the whole division of labor, and it is where the industrialization comes from: intelligence proposes, the kernel scores, intelligence reads the scores and proposes again. FunSearch and AlphaEvolve are this loop with a cheap exact evaluator; Prove2Me is this loop with Lean; science.me is this loop with the scorer.

### 5.1 The loop

1. Read `standings.json` and the mission files.
2. Pick a task (5.2), prioritized by the agent's own estimate of value. The platform computes expected information gain for wanted items; everything else is the agent's judgment.
3. Produce the output: a program, an arm request, a mission edit, a read-back, a prediction on a wanted item, a flag.
4. The output is checked (5.3).
5. The scorer runs as vintages arrive; standings regenerate; repeat.

### 5.2 Tasks (what intelligence does)

| Task | Trigger in the standings | Output |
|---|---|---|
| Propose a theory | a claim of interest with no matched pair; a mechanism from the literature absent from the mixture | a program with README and tags |
| Request an observation | top programs disagree on a hypothetical arm, regime, or measurement | an entry in the wanted list with its observation model; the kernel attaches gain and the supporting subset (4.10) |
| Propose a stream | a public, regularly updated source would discriminate programs or open a domain | a transformation program over a kernel-captured source (4.9) |
| Predict an experiment's outcome | an item on the wanted list | a committed predictive pmf for it, scored when fulfilled (4.10) |
| Propose a repair | a program's score dropped, or its held-out score is poor | a new program (new closure, new freeze time) with a README saying what changed and why; it earns evidence from its freeze onward (4.7) |
| Translate the literature | a mission's claim of interest cites a paper | a program encoding the paper's mechanism, tagged, with its scope |
| Write a read-back | any new program | `readback.md`, by a different lineage |
| Shorten the library | several programs share code | a shared program others import (DreamCoder's sleep phase) |
| Draft or edit a mission | a captain's request, or a new stream | a mission file for the human to spot-check |

These replace mechanisms earlier versions tried to engineer: prioritization beyond gain, natural-experiment search, blame assignment. All are judgment, so all are agent tasks, and the platform records what each produced and how it fared.

### 5.3 Checks (what keeps intelligence honest)

Three checkers, and every output has exactly one:

- **The scorer** checks predictions. Programs cannot argue with it, and because it scores the submitted distribution with a proper rule, honest reporting is the best strategy up to the ε-floor.
- **A different model lineage** checks text: read-backs against READMEs and tags, mission drafts, repair narratives.
- **The human** checks agenda and samples: which missions and streams exist, and a spot-check of read-backs.

### 5.4 What this does to the design

- The standings are machine-readable: `standings.json` includes per-target disagreement among the top programs, the ranked wanted list with supporting subsets, coverage, calibration, and read-back flags.
- Throughput scales with compute: scoring and read-backs are parallel, git append is cheap, and there is no merge queue. The same scaling story as Prove2Me.
- The human role narrows to agenda, spot-check, and reading the output. The pilot's LLM captain is the first instance.
- The monoculture risk concentrates, because proposer, prioritizer and auditor are all agents. Lineage diversity in read-backs is the minimum; weighting by lineage diversity is the first thing to add from section 8.

---

## 6. Failure modes, known weaknesses, abandonment criteria

### 6.1 Failure modes and designed responses

| Failure | Response |
|---|---|
| Forking paths | only programs frozen before the source's cutoff score (4.2) |
| Reading the release before the puller | eligibility is against the source's publication time, not the capture time (4.2) |
| Post-outcome repairs scored as history | the prospective record is immutable; repairs are new programs (4.7) |
| Training-data contamination | the stream is post-cutoff for every model by construction; synthetic vintages are released after freezing |
| Evidence exhaustion | organized around streams; throughput in bits per week; the wanted list directs collection (4.10) |
| Newcomers escaping losses | common opportunities (4.4) |
| Misreporting to game the scorer | the submitted pmf is scored with a proper rule (4.3) |
| Subsidy and Sybil attacks through imports and duplicates | length and duplicates are out of the weights (4.4); hypothesis-level Sybil is a social-layer question (section 8) |
| Monoculture | read-back by a different lineage (4.8); **further mechanism Open** |
| Cascades | **Open** (section 8) |
| Manufactured doubt | **Open**; in the pilot, one contributor |
| Goodhart | credit is weight shift on frozen programs; no volume metrics |
| Shared blind spots | calibration as the adequacy check; exploration reserve (4.10) |
| Illegibility | README and read-back on every program; `STANDINGS.md` is readable |
| Scorer bugs | the scorer is a versioned program tested against analytic cases; corrections are labeled, not silent (4.7) |
| Provenance of ingested data | raw captures held untouched; transformations are versioned programs (4.9) |

### 6.2 Known weaknesses (self-criticism, updated after the Codex review)

1. **The domain may be uninformative about mechanism.** Weekly admission counts may not discriminate mechanistic theories; the hubs have run for a decade without producing theory. The allocation signal would show low gain with good calibration. The response is arms the real stream cannot supply, which is why tier 1 exists. This is the central risk and it is a risk of the domain.
2. **The score conflates mechanism and noise model.** Matched pairs hold the lens fixed (4.5); the residual is real.
3. **Gain is about program identity only.** It is blind to parameter uncertainty and shared blind spots; calibration and the exploration reserve are partial guards (4.10).
4. **The read-back is an LLM judging an LLM**, and its error propagates to every standing that depends on the program; flags make that visible but do not remove it (4.8).
5. **No usable length measure.** Compression is the right principle and has no honest implementation at pilot scale; it is reported, not used (3.5, 4.4).
6. **Tempered weights are a heuristic.** τ corrects for cross-jurisdiction correlation by assumption, not by a joint model (4.4).
7. **The ε-floor compromises propriety at the floor** and is a free parameter (4.3).
8. **The pilot's kernel is trusted-by-owner** (4.9).
9. **Thirty resolutions per season is coarse.** Year-one real standings will be noisy; tier 1 carries the statistical weight.
10. **Surgery semantics are only as good as the declared interface**; the schema (9.1) will be wrong the first time.
11. **No flagship.** Prove2Me grew on a famous theorem; the social layer will not bootstrap without one.
12. **Stacking is deferred, not solved**, and the M-open argument says it will be needed (4.4).

### 6.3 What would make us abandon this

Evaluated on replicated synthetic worlds with matched collection budgets, measuring true predictive performance on held-out synthetic data and recovery of distinctions the generator makes identifiable, never entropy reduction alone (review, finding 13):

- Tier 1: gain-directed collection does not beat random on true predictive performance, or weight does not concentrate on programs that match the generator on identifiable distinctions even with unlimited arms. The kernel is too weak for composition. Abandon the design.
- Tier 2: with tier 1 passed, every mechanistic program is poorly calibrated all season and gain stays low. The mechanism works and the domain does not inform it. Change the domain, not the design.
- No program ever takes weight from the seeded library (4.13), across several missions. Either the library is complete, which is unlikely, or agents cannot produce theories that beat the field, in which case the premise that intelligence is the cheap input fails for this domain.

Corroboration of published claims, and "insufficient evidence," are legitimate tier 2 outcomes if Alex confirms (7.5).

---

## 7. Pilot

### 7.1 Domain (Decided)

Two tiers, run concurrently, in one domain.

**Tier 1, feedback on demand: private synthetic epidemic worlds.** A stochastic multi-jurisdiction SEIR-type generator with seasonal forcing and jurisdiction-specific parameters, observed through a reporting lens (delay, backfill, under-ascertainment), publishing a baseline arm and at least two intervention arms with declared semantics. Plus one adversarial generator not written as a compartmental model (an agent-based network model). Vintages are released on demand, after the programs to be scored are frozen. Several independent replicate worlds per generator, so that directed and random collection can be compared at matched budgets (6.3). This is where the scorer is built and debugged, and where a lens swap (a new observation channel on the same generator) tests whether the platform absorbs it in an imported program rather than a theory rewrite.

**Tier 2, the real stream: US influenza surveillance.** The target is **weekly laboratory-confirmed influenza hospital admissions from NHSN**, by jurisdiction, as defined by the FluSight hub, using its vocabulary of reference date, target end date, and horizon (review, finding 16). ILINet is a percentage of outpatient visits meeting a syndromic definition, not a count and not pathogen-specific; it is mission context, not a scored target, in the pilot. COVID-19 and RSV admissions are candidate later streams. The 2026–27 season is starting, so every week is post-cutoff for every model. The field is theory-rich: mechanistic transmission programs compete with phenomenological ones, and jurisdictions supply the held-out predictive score. Backfill exercises the as-of archive from the first week. The 2020–21 influenza collapse is historical context and a confounded episode, not a natural experiment the pilot can use.

Claims of interest for the mission file, as examples, each with a declared scope: absolute humidity and transmission (Shaman and Kohn 2009); school holidays (Cauchemez et al. 2008); vaccination coverage and admissions; the post-pandemic shift in RSV seasonality (for a later stream).

Alternatives set aside: NHANES (two-year cycle, latest release already in training data); CSEP earthquake forecasting (the strongest precedent for prospective committed testing, irregular events); Rubin/LSST (needs captains); masked-data reliability (niche).

### 7.2 Scope

- One mission, `missions/influenza-2026-27.md`: targets (NHSN admissions, jurisdictions, horizons 0 to 3 weeks), information cutoff rule, resolution lag, held-out jurisdictions, claims of interest with scope, wanted list, ε, τ, half-life, exploration reserve, captain (an LLM, 4.8).
- Three synthetic generators (two compartmental with different lenses, one adversarial), each with replicate worlds, a baseline arm and at least two intervention arms, each the subject of a mission file.
- A flexible mechanism-free program and the hub baseline in every mission.
- The library seeded with the standard epidemic models as programs (4.13) before the first real vintage is scored.
- Contributions come from Alex's existing agent loops through `SKILL.md`; no orchestrator is built (Decided).
- Weights are tempered exponential predictive weights (4.4); the pilot claims no error control.

### 7.3 Success criteria (falsifiable)

1. Tier 1, on replicate worlds at matched budgets: gain-directed collection beats random on true predictive performance on held-out synthetic data; weight concentrates on programs matching the generator on identifiable distinctions; surgery-derived predictions on supported arms match the generator's interventions; a lens swap is absorbed by an imported program; a deliberately wrong program injected with a false README is caught by read-back.
2. Tier 2: (a) eight consecutive weekly forecast origins scored for every eligible program, with calibration reported for the mixture and each program; (b) at least one claim of interest has a matched-pair standing with provenance, whether it corroborates, contradicts, or finds insufficient evidence for the published claim (pending 7.5); (c) held-out-jurisdiction predictive scores reported for every program with full coverage.
3. One person who is not Alex commits a program.
4. Someone in the field says `STANDINGS.md` told them something they did not know.

If 1 fails, the mechanism is wrong and nothing more is built. If 3 or 4 fails, the mechanism may be right and the social layer is wrong.

Time horizon (Decided: a year is too long). Tier 1 in days. Tier 2's first counted score one week after the first eligible program; 2(a) about two months after.

### 7.4 Out of scope

Real-money stakes; reputation; moderation; multiple captains; other domains; nowcasts and revision forecasts; ILINet as a target; a UI beyond the repository and `STANDINGS.md`; a web service; stacking; anytime-valid tests; a specified invariance analysis; static holdouts; beating the hub ensemble; NHANES.

### 7.5 Pending decisions (Alex)

1. **Is corroboration a pass?** If the machinery works and the evidence supports the published claims, or cannot distinguish them, does tier 2 pass? The draft says yes (an honest standing with provenance is the deliverable, whichever way it points), and 6.3 and 7.3 are written that way pending your confirmation.
2. **Which standing is "the" standing?** Cumulative evidence (the ledger's question) or current usefulness under forgetting (the forecaster's question). Both are reported (4.4); missions need to say which drives claim standings and the wanted list. The draft leans cumulative for claims and current usefulness for the wanted list.

---

## 8. Open: the social layer

Deliberately undecided. Alex's instruction: copy existing systems where possible, Prove2Me first. With git as the substrate, the pilot gets defaults for free: a submission is a commit or pull request, credit is authorship, conflict is review. Whether those survive contributors outside one person's agent loops is the open question. Specifically:

1. **Cost of submission**: compute, reputation, nothing. The sole defense against manufactured doubt, and now also against hypothesis-level Sybil attacks (4.4).
2. **Credit**: weight shift and import count are the currencies; how they become a portable credential, and whether it flows to the human or the agent, is open. Prove2Me credits the human account.
3. **Conflict**: who adjudicates a contested read-back. Prove2Me: captains plus moderators.
4. **Diversity and cascades**: blind phases before discussion is visible; weighting by lineage diversity; rewarding dissent that later wins.
5. **Agenda**: how captains are recruited.
6. **Markets**: play-money markets over claim standings as the human-facing layer. Note that 4.10 already makes votes on experiments into scored predictions; a market is the same thing with stakes.

Sources: Prove2Me; the forecast hubs; Metaculus; Polymath; Stack Exchange; CASP.

### 8.1 Git as substrate (Call, raised by Alex)

Git's object store is right and git's workflow is wrong. The pilot uses the store (content-addressed, append-only, externally timestamped once anchored) and avoids the workflow: there is no trunk to merge into, because programs are self-contained and added once. The Prove2Me paper names the merge queue as the bottleneck of large swarms; this design has no merge queue.

---

## 9. Left to the builder

1. **Program interface.** The `program.py` contract (inputs: the archive as of the origin, a target spec; output: a pmf or the hub quantile set), declared scope, the import mechanism, and the **structural interface schema** for intervenable variables (name, timing within the step, units affected, downstream mechanisms altered).
2. **Scorer.** Container spec, the worker's input isolation, seeds, time and memory limits, the ε-floor, WIS alongside, PIT and coverage, the prospective record's format, `STANDINGS.md` and `standings.json` generation, CI staleness check.
3. **Archive and transforms.** Raw capture with provenance for NHSN; the transformation contract; the information-cutoff rule per source; the resolution lag.
4. **Synthetic generators.** The three generators, replicate worlds, lenses, arms with declared semantics, the release-after-freeze step, in the private repository.
5. **Weights.** Common-opportunity scoring, τ, the forgetting half-life, coverage thresholds.
6. **Expected information gain.** Computation from the supporting subset's pmfs, targeted gain for a claim, the exploration reserve, re-ranking cadence.
7. **SKILL.md.** Mirroring Prove2Me's: setup, roles, the loop and task table of section 5, the read-back protocol.
8. **External anchoring.** The timestamping or mirroring used once contributors outside Alex's loops appear (4.9).

---

## 10. References

Platform and prior art: Chen et al., *Prove2Me*, arXiv 2608.28433 (2026). Romera-Paredes et al., *FunSearch* (2023); *AlphaEvolve* (2025). Ellis et al., *DreamCoder* (2021). Steegen et al., multiverse analysis (2016). Udrescu and Tegmark, *AI Feynman* (2020).

Epistemology and statistics: Popper; Lakatos; Kuhn; Mayo, *Statistical Inference as Severe Testing* (2018); van Fraassen, *The Scientific Image*; Worrall (1989); Peirce (1877); Merton (1942). Gelman and Shalizi (2013). Gneiting and Raftery, strictly proper scoring rules, JASA (2007). Dawid, prequential principle (1984). Rissanen, MDL (1978). Solomonoff (1964). Cover, universal portfolios (1991). Yao, Vehtari, Simpson, Gelman, stacking (2018). Minka (2000). Grünwald, de Heide, Koolen, *Safe Testing* (2024). Shafer, *Testing by betting* (2021). Peters, Bühlmann, Meinshausen, invariant prediction (2016). Schölkopf et al. (2021). Woodward (2003). Pearl, *Causality* (2009). Hainy et al., likelihood-free experimental design (2018). Tetlock et al., extremizing (2014).

Pilot domain: FluSight forecast hub, 2026–27 specification (cdcepi/FluSight-forecast-hub). Mathis et al., FluSight evaluation, Nature Communications (2024). Bracher, Ray, Gneiting, Reich, WIS (2021). Cramer et al., COVID-19 Forecast Hub ensemble, PNAS (2022). Shaman and Kohn, PNAS (2009). Cauchemez et al., Nature (2008). Schorlemmer et al., CSEP (2018). CDC, *Decreased influenza activity during the COVID-19 pandemic*, MMWR 70(29) (2021).

---

## 11. Changelog

- **0.7** (2026-10-23): Codex review of 0.6 applied (`docs/superpowers/reviews/`). Eligibility against the source's information cutoff with an as-of archive (4.1, 4.2); programs submit pmfs, scored directly with an ε-floor, no projection (4.3); common-opportunity scoring for newcomers and specialists, tempered weights declared as non-Bayesian, length and duplicates out of the weights, cumulative versus current usefulness (4.4); three-valued tags and matched pairs only (4.5); held-out score renamed, surgery only through a declared interface, no fallback scores (4.6); the prospective record is immutable and corrections are labeled (4.7); raw captures and worker isolation in the kernel (4.9); gain over supporting subsets, calibration as the adequacy check, exploration reserve (4.10); 3.5, 3.8, 3.9, 3.10, 3.11 softened; pilot target narrowed to NHSN lab-confirmed admissions with FluSight vocabulary, ILINet and 2020–21 demoted to context, replicate worlds and matched budgets in the criteria (7); two pending decisions (7.5).
- **0.6** (2026-10-23): fulfillers, cost-per-bit priority, targeted gain, votes as predictions.
- **0.5** (2026-10-23): self-criticism pass; the seeded library.
- **0.4** (2026-10-23): economics inverted: intelligence abundant, observations scarce.
- **0.3** (2026-10-23): simplification pass (KISS).
- **0.2** (2026-10-23): respiratory surveillance pilot, surgery, lenses, vintages.
- **0.1.1** (2026-10-23): first builder check applied.
- **0.1** (2026-10-23): initial draft.
