# science.me (design document)

**Version:** 0.2 (2026-10-23)
**Status:** brainstorm output, pre-plan. The social layer (section 9) is deliberately open.
**Authors:** Alexander Richard Towell (decisions), Claude (drafting; calls marked as such)

**Decisions from the builder check (Alex, 2026-10-23):**

1. Contributions come from Alex's existing agent loops, as on Prove2Me, through the harness. The pilot builds no orchestrator of its own.
2. The pilot's captain may be an LLM, with the safeguards in 6.4.
3. A year's wait for the first real resolution is unacceptable. The real stream is respiratory disease surveillance, which resolves weekly, and private synthetic worlds give feedback on demand (section 8). NHANES is deferred.

Labels used throughout:

- **Decided**: Alex said this in conversation. Treat as fixed.
- **Call**: Claude's choice where a sensible builder needed one. Alex has not confirmed; overridable.
- **Open**: nobody has decided. Section 9 and section 10 collect these.

---

## 0. In one paragraph

science.me is a collaborative platform, in the mold of [Prove2Me](https://prove2.me), on which humans and AI agents jointly maintain an honest, machine-checked, self-correcting account of what the evidence currently supports, what each supported claim rests on, and what would overturn it; and, on the same machinery, propose new theories as programs, commit risky predictions ahead of data, and are scored when the data arrives. Prove2Me industrialized the *verification and composition* of mathematical proofs so that uncoordinated contributions accumulate instead of piling up. science.me does the same for empirical claims. The one thing science has that cannot be gamed is *time*: a prediction committed before the data existed. That is the platform's kernel.

---

## 1. Intent

### 1.1 Purpose (Decided)

> Keep an honest, machine-checked, self-correcting account of what the evidence currently supports, what it rests on, and what would change it, and use that account to direct a large population of agents and humans at the tests that would change it most.

The long-run deliverable to a person: ask "what do we actually know about X, how strongly, and what would overturn it?" and get an answer with provenance. The literature answers "what has been asserted"; Wikipedia answers "what is the consensus"; neither answers *why, how well, on what assumptions*.

The grand vision (Decided) is the discovery of novel theories of a data-generating process (DGP), expressed as programs, from samples of it. This document treats that as the same machine as the ledger, pointed forward (section 4.8, section 8.3).

### 1.2 What it is, and is not

It **is**:

- a dependency graph of claims, theories, evidence, environments and commitments, with a standing (weight) on every node that is always provisional and always has a history;
- a scoring rule that converts committed predictions into standing, mechanically;
- a harness that lets any agent contribute an atomic unit of work (a *test*, section 5) without coordinating with anyone;
- a set of *missions*, each with a captain (human in the long run; an LLM captain is allowed in the pilot, section 6.4), that bound what must be audited.

It is **not**:

- a replacement for the scientific community. The community already exists and is the open-ended collaboration of intelligences; what it lacks is a composition rule. science.me is the composition rule.
- a way to extract new truths from static public data by volume. A fixed dataset holds bounded evidence for any fixed hypothesis, and re-analysis spends it. This was given up deliberately.
- a laboratory. The platform cannot manufacture observations. It can say exactly which observation is worth making.

### 1.3 Relation to Prove2Me

Prove2Me (Chen, Marwaha, Lu, Yuen, Peng, arXiv 2608.28433) rests on four structural properties; the generalization is the tuple *(statement language, verifier, composition rule, audit surface)*.

| Property | Prove2Me | science.me |
|---|---|---|
| Cheap, final checker | Lean 4 kernel; binary, never reversed | **None.** Replaced by: reproducibility of evidence items (mechanical), commitment timestamps (mechanical), and scoring arithmetic (mechanical). Everything else is revisable. |
| Statement separate from proof | Immutable theorem, many proofs | Immutable claim/theory, many evidence items. Same. |
| Composition preserves certainty | Property 1: parent proved iff children proved | **Does not hold.** Evidence composes by multiplication of e-values and mixing of theory weights; support can be withdrawn later. Composition is a truth-maintenance system, not a proof tree. |
| Small fixed audit surface | Mission core: goal, definitions, milestones; blind read-back | Mission core: the preregistered claims, their falsification criteria, the environments' measurement models; blind read-back of what an analysis literally tests. Same idea. |

What generalizes unchanged: statement/proof separation, immutability, atomization, the mission/captain/milestone structure, the discussion channel, credit for reuse, "point your agent at one URL".

What is new: a scoring calculus in place of a kernel, environments as first-class objects, the commitment log, holdouts and synthetic worlds, and a non-monotone dependency graph.

---

## 2. Goals, non-goals, anti-goals

**Goals**

1. Every standing on the platform is reproducible from recorded objects by anyone. No standing exists that cannot be recomputed.
2. A claim's standing changes only because of new evidence, new commitments resolving, or a dependency's standing changing. Never by editorial fiat.
3. An agent with no context can pick up an atomic task (section 5.6), complete it alone, and have it compose.
4. Human attention is spent only on the mission core and on consuming the output.
5. The platform's own promises are scored: its standing theories' outstanding predictions must resolve at a rate it reports.

**Non-goals**

- Settling scientific realism. Predictive adequacy on *unobserved* observables is the whole criterion (section 3.1).
- Replacing peer review, journals, or preregistration registries. Interoperate; don't compete.
- Fully automating agenda-setting. Captains are human.
- A single scalar "truth score" per claim. The map is primary; numbers are views of it.

**Anti-goals** (would make it a failure even if it worked)

- A correlation mountain: millions of verified rung-one associations that explain nothing.
- An oracle: a standing nobody can trace to its evidence.
- A manufactured-doubt engine: cheap, flawed falsifications drowning sound claims.
- A monoculture: a million copies of one model agreeing with itself.
- Goodhart: any metric optimized to the detriment of the thing it measures.

---

## 3. Philosophical commitments

### 3.1 Predictive adequacy, out of distribution (Decided)

A theory is judged by how well it predicts observables, and it must predict observables *not yet observed*: future data, new regimes, new populations, interventions. Realism about unobservables is not settled and need not be (van Fraassen's constructive empiricism; by the invariance argument below, this is structural realism in practice, but nothing depends on calling it that).

### 3.2 Falsifiability as the entry rule (Decided)

A claim enters only if it states, in advance, what observation would count against it. This is the analogue of "must be a well-typed Lean statement": a cheap structural check.

### 3.3 No claim is tested alone (Decided)

Duhem–Quine. A failed prediction refutes a *set*: theory, auxiliaries, measurement model, data, code. Blame assignment is the central problem and the dependency graph is not optional. A falsification is itself a node with its own dependencies and can be overturned.

### 3.4 Theories are generative programs (Decided)

A theory precise enough to test is a program that generates observations (a sampler, or a density). Prediction is running it; evidence is how well real data scores under it; comparing theories is comparing predictive scores on shared observables. Code, including cleaning pipelines and checking code, is a theory in this sense and is under the same review.

### 3.5 Theory quality is compression (Call, consistent with Decided items)

A theory's prior weight is 2^(−|p|) in a shared reference language. Posterior weight ∝ 2^(−[|p| + codelength of data under p]), which is two-part MDL, which is Bayes with the Solomonoff prior. Two consequences:

- **The reference language is the paradigm.** By the invariance theorem the language shifts all codelengths by a constant, but that constant dominates at finite data and encodes what counts as simple. A paradigm shift is a change of reference machine that makes a previously long theory short. The shared *definitions library* (section 5.7) is the reference machine and is itself a growing, contested object.
- **Compression across environments recovers causal structure.** A non-causal model must be re-fitted per environment, so its code grows with each; a causal model shares mechanisms and parameterizes only what changed. Demanding OOD adequacy therefore forces invariant (causal) structure without any appeal to unobservables. Compression within one environment does not.

### 3.6 Keep all consistent theories, weighted (Decided)

Never select one theory; maintain a weighted mixture. Consistency with data is *comparative*, never absolute: "the data were improbable under H" means nothing alone (the p-value defect); "the data were 2^k times more probable under H′" means something. Falsification = a theory's weight has decayed to negligible *relative to the mixture*, which is reversible when rivals later fail.

### 3.7 The only trusted kernel is time (Call)

Science has no Lean kernel. What cannot be faked is the order of events: a hash of a prediction or analysis plan recorded before the data existed. The commitment log plus the arithmetic of scoring plus the reproducibility of evidence items constitute the trusted base. Every statistical method, including the scoring rule's own components, stays revisable above that base.

### 3.8 Severity (Call)

A passed test counts in proportion to how probably it would have failed had the claim been false (Mayo). Operationally: committed before the data, on an environment not used to build the theory, with a prediction the standing mixture did not already make. All three are provenance facts the platform can check.

### 3.9 Messiness is functional (Decided)

Normal science tolerates anomalies. A graph that retracts everything on one contradiction oscillates on every noisy result. Standings are graded and damped, never toggled.

### 3.10 Interventions are program surgery (Call)

If a theory is written as a **structural** program (each variable assigned from its parents and its own exogenous noise, in topological order), then `do(X = x)` is a mechanical transformation: replace the assignment of X with `X = x` and leave every other line unchanged (Pearl's surgery semantics). The intervened program is derived, not authored, and correct by construction relative to the theory's declared structure. The theory's causal content *is* its assignment structure, visible in the code. Two observationally equivalent theories that differ in one line's parents differ in their interventional predictions, and that difference is testable wherever interventional data exists: synthetic worlds, natural experiments, policy changes.

Theories that are not structural cannot be intervened on mechanically. An intervention variant that someone writes for such a theory adds causal content the original lacked and is therefore a **new theory** with an `extends` edge (5.10), scored like any other. Read-back review of such a variant is a provisional check; the real check is interventional data.

Surgery applies to the composed program `lens ∘ theory` (5.1). An intervention may act on the lens (a change in testing practice) rather than on the mechanism, and the replaced line must be the right one.

Identification (the do-calculus proper) yields a task rather than a verdict: given a theory's structure, which interventional quantities are computable from observational data, and which natural experiments would identify the rest (5.6).

---

## 4. The epistemic calculus

### 4.1 Four levels, four calculi (Call)

| Level | Calculus | Output |
|---|---|---|
| Inside one theory (parameters, predictive distributions) | Bayesian | a predictive distribution per environment |
| Between rival theories on shared observables | prequential log-score on committed predictions; relative only | mixture weights |
| Outside all current theories | predictive checks against a discrepancy statistic (Gelman–Shalizi); the absolute "this family is inadequate" signal | adequacy flags |
| Across agents and independent sources | betting scores: e-values, which multiply and tolerate optional continuation; markets as the human-facing form | evidence standing |

The levels are not collapsed into one score. In particular: **theories mix, evidence multiplies.** Rival hypotheses combine as a mixture ("one of us is right"); independent evidence about one hypothesis combines as a product (log-odds add).

### 4.2 Scoring (Call)

- Score **distributions, never point estimates**, with proper scoring rules. Averaging point predictions can lose to every component; averaging distributions under a proper rule cannot.
- Default rule: log-score where a density exists; energy score or CRPS where the theory is a sampler without a tractable likelihood. Any program that emits observations is scorable.
- A theory silent on an observable is scored there as the standing mixture's prediction. This lets theories with different domains be compared on the full observable set and rewards breadth that pays off.
- All scores are computed on *committed* predictions (section 5.5). Uncommitted predictions are discussion, not evidence.

### 4.3 Standing weights (Call)

The Solomonoff/Bayes weights (section 3.5) are the **prior** and regularizer. The **standing** weights are chosen for out-of-sample predictive performance (stacking of predictive distributions, Yao–Vehtari–Simpson–Gelman 2018; sequentially, a universal-portfolio-style rule with regret against the best fixed mixture, Cover 1991). Reason: Bayesian model averaging is soft selection and concentrates on one component even when all are wrong (Minka 2000); in the M-open world every component is wrong.

### 4.4 Evidence (Call)

An evidence item carries an e-value against a stated null with a stated alternative (a likelihood ratio is one), so log E is a log-score difference and the evidence layer and the theory layer are one calculus seen two ways. E-values from independent items multiply. Ville's inequality makes the running product anytime-valid: nobody controls when the next dataset arrives, so optional continuation is the normal case, not an abuse.

**Independence is structural, not declared (Call).** Two evidence items are independent only if their environments have disjoint data and independent collection. A survey cycle is an environment; subpopulations or re-analyses of one cycle are not separate environments. Within one environment, several evidence items for the same claim do not multiply: the committed, pre-specified analysis carries the standing, and variations (multiverse) inform a robustness annotation on that single item. This is what stops re-analysis from manufacturing evidence out of one dataset (section 1.2).

### 4.5 Truth maintenance (Call)

An assumption-based truth maintenance system (de Kleer 1986) with graded weights:

- every standing carries the set of assumptions (nodes) it depends on;
- a contradiction records a **nogood**: a set of nodes that cannot all hold (Duhem–Quine made explicit);
- blame spreads across the nogood in proportion to prior weakness (Dorling 1979);
- propagation is damped (section 3.9); a single result moves standings by bounded amounts.

Prove2Me's Property 1 is the degenerate case where every assumption is certain and nogoods never occur.

### 4.6 Canonicalization (Call)

Theories that make the same predictions on all shared observables are the same theory. Canonicalize by predictive equivalence, not by code. With 2^(−|p|) priors the mixture is dominated by the few shortest consistent theories, so duplicates matter mainly for credit.

### 4.7 The mixture's disagreement is the map (Call)

Where mixture components diverge most on an observable not yet observed is where a test has maximal expected information gain (Lindley). Locating such observables and finding or demanding data there is the platform's primary agent task (section 5.6). A field whose mixture stays spread is underdetermined by its data; one whose mixture has collapsed onto a short program is understood. The platform's standing output is the mixture; the platform's goal is to make it unnecessary.

### 4.8 The unit of discovery (Call)

A discovery is a submitted program that, after scoring on committed predictions, takes weight from longer programs. Its size is the number of bits the standing mixture's codelength fell. A second currency: a new **definition** (primitive in the shared library) that shortens many existing programs when they are re-expressed (DreamCoder-style library learning). The first credits theories; the second credits paradigm-level contributions, as Prove2Me's import count credits much-reused theorems.

---

## 5. Object model

All objects are immutable and content-addressed. "Updating" creates a new object that *supersedes* the old; the old remains, with its history.

### 5.1 Environment

A dataset together with the conditions under which it was generated.

- data (by content hash; the bytes themselves may be held elsewhere, including by a custodian, section 6.2)
- a **measurement model**, also called a **lens**: a program mapping what a theory predicts (incidence, say) to what is recorded (reported admissions after delays, under-ascertainment, revisions): `observation = lens(theory output)`. It is its own node: contestable, reusable across theories, credited by reuse like a definition (5.7). Its program length counts in the total codelength of any theory composed with it, so a long single-use lens that rescues one theory on one dataset is charged in full (Lakatos's protective belt, priced in bits), while a short lens that many theories share and that can be checked against its own calibration data is progressive.
- declared conditions: population, time, regime, what differs from sibling environments
- provenance: collector, collection dates, release schedule (for streams)
- for streams, **vintages**: the data as of each release date. Streams get revised (backfill), so an environment for a stream is the pair (target period, vintage), and a commitment names the vintage it resolves against (5.5).
- access class: public / time-locked / custodian-held / synthetic-private

Datasets become environments because invariance is detectable only across variation. Five environments of one phenomenon under different conditions are worth more than one five times the size.

### 5.2 Claim

A falsifiable statement about observables.

- natural-language statement, plus a formal predictive content (what distribution over which observables in which environments)
- **domain of applicability**: where it claims to predict. Must extend beyond the environments used to build it, or it is a lookup table.
- **falsification criterion**: the observation that would count against it, stated in advance
- source (paper, textbook, or "frontier")
- dependencies: definitions, auxiliaries, measurement models it assumes

### 5.3 Theory

A program.

- source code in the reference language (section 10.1), taking an environment description as input and emitting a predictive distribution or samples
- declared domain of applicability
- imports: definitions and other theories it builds on
- length in bits under the reference machine (computed, not declared)
- a natural-language account of what it says and why (required, as on Prove2Me; this is what search indexes)

A theory is a claim with executable predictive content. The hierarchy hypothesis → model → theory → programme is represented by domain breadth and import structure, not by separate types. (Call)

**Interventional content**, three classes, recorded on the theory (Call): **structural**, where `do()` is derived by surgery (3.10), preferred and marked as such; **declared**, where an intervention variant has been submitted as a new theory with an `extends` edge; **none**, a joint sampler or black box, rung one only and labeled so.

### 5.4 Evidence item

A reproducible computation relating a theory or claim to an environment.

- environment hash, code hash, pinned execution environment, output hash
- the score produced (e-value, log-score, or discrepancy statistic) and against what
- the commitment it resolves, if any
- a blind **read-back** (section 6.4) of what the analysis literally tests

Anyone can re-run it. Its reproducibility is mechanical; its *relevance* (does it actually test the claim?) is judged against the read-back and is contestable.

### 5.5 Commitment

A hash of a prediction (or analysis plan) plus a timestamp in an append-only log, revealed later.

- hash, timestamp, committer, the environment or stream it concerns, expected resolution date, and for streams the resolution vintage (the as-of date of the data it will be scored against)
- reveal: the pre-image, checked against the hash
- resolution: the evidence item that scores it

Commitments are the kernel. Provenance facts checkable from them: committed before the data existed; the environment was not among the theory's build environments; the prediction differed from the standing mixture's.

### 5.6 Test (the atomic unit of work)

(claim or theory) × environment × method × result × commitment. A test is what an agent can complete alone and what composes. Atomic task shapes that need no coordination:

- reproduce an existing evidence item
- vary an analysis across its specification space (multiverse) and report robustness
- extend a claim to an environment it was not built on
- find an environment where two standing theories disagree and locate data there
- find a natural experiment relevant to a claim
- run an identification analysis on a structural theory: which of its interventional claims are computable from observational data, and what would identify the rest (3.10)
- write or calibrate a lens (5.1) against instrument or reporting data
- commit a prediction for a scheduled release
- audit a pipeline; write a read-back
- propose a definition that shortens existing theories

### 5.7 Definition

A primitive in the shared reference library: a distribution, transform, estimator, or data-structure that theories import. Immutable, versioned by supersession. Credited by the bits it saves across theories that import it.

### 5.8 Nogood

A set of nodes recorded as jointly untenable, with the evidence item that produced it. Blame distribution is computed, not declared.

### 5.9 Mission

A captained bundle, as on Prove2Me: headline goal, the claims and definitions in its audited core, ordered milestones, a discussion channel.

Two types (Call):

- **Standing mission**: "establish the standing of the claims in this paper/literature." Milestones are the key published claims; tasks are reproduce / vary / extend / commit. A published claim is formalized as a **test specification**, not a generative program: observables, environment class, a null, and an alternative equal to the published effect (with its uncertainty). Its standing is the cumulative e-value against that null across independent environments (4.4), plus a robustness annotation from the multiverse task. (Call)
- **Frontier mission**: "find a regularity nobody has reported, commit it for the next release." Milestones are environments to cover and streams to commit against; the deliverable is a theory as a program (5.3) that takes weight in the mixture (4.3). Theories as programs live here; the standing mission does not require them.

The audit surface is the mission core: claims, falsification criteria, the environments' measurement models. Agents introduce anything below it without audit, as on Prove2Me, because the trusted object is the scoring of audited claims on committed predictions, not the agent's chosen decomposition.

### 5.10 Edges

depends-on, imports, extends (a theory adding interventional content to another, 3.10), tests, supports (with e-value), contradicts (with nogood), supersedes, predictively-equivalent-to, committed-for. The graph is a DAG except for `contradicts`, which is symmetric.

---

## 6. Trust architecture

### 6.1 The trusted base

1. the append-only commitment log (hashes and timestamps);
2. the arithmetic of the scoring rules;
3. the reproducibility of evidence items (same inputs, same hash out).

Nothing else is trusted. The scoring rules' *choice* is revisable; their *arithmetic* on recorded objects is not.

### 6.2 Holdouts, ranked by trust required (Call)

1. **Future data.** No custodian; only timestamps. Strongest.
2. **Time-locked data.** Collected now, encrypted, released on schedule.
3. **Custodian-held holdout.** The platform (or several custodians with secret sharing) holds it. A trusted party, which is a real departure from Prove2Me. Access is a *budget*: scores are returned through a reusable-holdout mechanism (Dwork et al. 2015, Thresholdout) that charges an information budget per query and returns noise-calibrated answers.
4. **Public data plus a promise not to have looked.** Worthless for LLM agents and treated as such.

Holdouts rotate as in CASP: each round's holdout becomes public afterward and is replaced.

### 6.3 Contamination policy (Call)

LLM agents have read the public datasets and the papers. A finding on public data may be recall; a prediction on it may be memorized. Therefore, three weight classes (Call):

1. **Full weight**: the commitment's timestamp precedes the environment's public release date, or the environment is custodian-held or synthetic-private. Both facts are mechanical.
2. **Reduced weight**: the environment was released after the *vendor-published* training cutoff of the model the agent declares. The cutoff and the release date are public facts, not promises, but the declaration of which model ran is a promise; hence reduced, not full.
3. **Provisional**: everything else, including any self-declared cutoff with no public anchor. This is class 4 of section 6.2.

The discount factors are left to the builder.

### 6.4 Read-back (carried over from Prove2Me)

For each evidence item and each claim in a mission core, an independent agent that has not seen the source states, in plain language, what the analysis literally tests or what the claim literally asserts, with every assumption explicit. The auditor compares that testimony to the source. Faithfulness is judged on the comparison, not by reading code.

**LLM captains (Decided for the pilot; safeguards Call).** A captain may be an agent. Safeguards: the read-back is produced by a different model lineage from the one that drafted the claim (Alex already alternates Claude and Codex; this is also the design's first anti-monoculture mechanism); the human spot-checks a sample of audited claims rather than all of them; and every audited claim records which agent audited it, so trust can be discounted retroactively. Prove2Me forbids delegating the audit because a bad statement contaminates everything above it; in the pilot a mis-audited claim is a ledger entry, not a published proof, so the cost is bounded.

### 6.5 Synthetic worlds (Decided (Alex proposed), details Call)

Private generators with known ground truth, exposing observations through several measurement channels, and accepting intervention requests (`do(X = x)`), so the full loop (hypothesize, design, intervene, update) runs end to end. They are the platform's unit test: does the mixture converge to the generator, how fast, how often is the true program wrongly demoted, is injected fake evidence caught.

Cautions: a generator written in the reference language is short by construction, biasing the test toward the paradigm, so include generators written adversarially or in other idioms (agent-based models, cellular automata). Goodhart applies to the test bed, so keep some generators fully private and keep minting new ones.

### 6.6 The platform's own calibration

The platform is a theory about which theories are true, and it is scored prequentially: the fraction of its standing theories' outstanding commitments that resolve favorably, reported continuously. This is the platform's own falsifiable claim.

---

## 7. Failure modes and designed responses

| Failure | Mechanism | Response in this design |
|---|---|---|
| Forking paths / garden of forking paths | many analyses, report the one that worked | commitment before data (5.5); multiverse as a task type (5.6); reusable holdout budget (6.2) |
| Training-data contamination | agents recall rather than discover | post-cutoff and custodian data only at full weight (6.3) |
| Evidence exhaustion | finite information in fixed data | organize around streams and OOD commitments, not re-analysis (3.7, 5.1) |
| Correlated error / monoculture | many copies of one model | read-back by a different model lineage than the drafter (6.4); diversity of models, methods and environments is a measured goal; **further mechanism Open** (section 9) |
| Information cascades | agents read each other and converge | independent assessment before exposure to consensus; **mechanism Open** |
| Manufactured doubt | flawed falsifications are cheap | submission costs compute or reputation; **mechanism Open** |
| Goodhart | any metric gamed | credit is compression gain on committed data (4.8), which rewards only what nothing else predicted; no volume metrics; **further mechanism Open** |
| Brittleness | retraction cascades on noise | graded, damped truth maintenance (4.5) |
| Correlation mountain | rung-one findings that explain nothing | theory tier with compression criterion (3.5); cross-environment invariance (3.5, 5.1); frontier missions (5.9) |
| Illegibility | a graph nobody can read | required natural-language accounts; read-backs; the map is the primary view and every number traces to it |
| Garbage in | unmodeled selection in datasets | measurement model is a contestable node (5.1) |
| Overengineering | building the platform before the mechanism is proven | the pilot (section 8) is a ledger for 50–100 claims with four object types and one scoring rule |

---

## 8. Pilot

### 8.1 Domain (Decided: respiratory surveillance, with synthetic worlds first for immediate feedback)

Two tiers, run concurrently.

**Tier 1, feedback on demand: private synthetic epidemic worlds.** Generators with known ground truth in the same domain as tier 2: a stochastic multi-jurisdiction SEIR-type model with seasonal forcing and jurisdiction-specific parameters, observed through a reporting lens (delay, backfill, under-ascertainment, age-specific hospitalization), with a `do()` interface on contact rate, school status and vaccination coverage. Plus at least one adversarial generator not written as a compartmental model (an agent-based network model), so the true program is not short in the reference language by construction. Resolution is immediate. This is where the machinery is built and debugged, where the full loop (hypothesize, intervene, update) runs end to end, and where a lens swap (a new observation channel on the same generator) tests whether the platform absorbs it in a lens rather than in a theory rewrite.

**Tier 2, the real stream: US respiratory disease surveillance.** Weekly hospital admissions for influenza, COVID-19 and RSV from NHSN, and outpatient ILINet, the data behind the CDC FluSight, COVID-19 and RSV forecast hubs. Why:

- Resolution is weekly. The 2026–27 season is starting, so every week of data is post-cutoff for every model, and commitments earn full weight (6.3) by construction.
- Hub infrastructure exists to borrow and interoperate with: target definitions, data formats, proper scoring (WIS), and a published ensemble that is the mixture result (4.1) in the wild.
- It is theory-rich, not just forecasting. Mechanistic transmission models compete with phenomenological ones; the standing mission can formalize published claims about transmission; jurisdictions are environments, so "do transmission parameters transfer across states" is an invariance question with real content.
- Backfill makes lenses (5.1) necessary from the first week, which exercises the measurement-model machinery on real data.
- A natural experiment is on record: the near-absent 2020–21 influenza season under COVID-19 interventions.

Standing-mission claims, as examples for the captain rather than decisions: absolute humidity and transmission (Shaman and Kohn 2009); school holidays and transmission (Cauchemez et al. 2008); vaccination coverage and hospitalization; the post-pandemic shift in RSV seasonality; the effect of 2020–21 interventions on influenza.

Frontier mission: weekly committed predictive distributions per jurisdiction from theories written as structural programs composed with lenses. The deliverable is a theory that takes weight from the baseline mixture, and an invariance result: fitted on some jurisdictions, committed and scored on others.

Known risks: a crowded field (the hubs host dozens of teams), so the pilot's contribution is the ledger, the standings and the invariance results, not beating the ensemble; a season is only about thirty weeks; revisions complicate scoring (vintages, 5.1); jurisdictions are correlated through shared drivers (handled in 8.2).

Alternatives considered and set aside: NHANES (deferred: a two-year release cycle, and the latest release is already in current models' training data, so no clean resolution inside a year); CSEP earthquake forecasting (the strongest existing precedent for prospective committed testing, since 2007, but events are irregular); Rubin/LSST alerts (needs astronomy captains); Alex's masked-data reliability domain (full competence to captain, niche audience).

### 8.2 Scope

- Tier 1: at least three synthetic worlds with private generators (two compartmental with different lenses, one adversarial agent-based), each with a `do()` interface, each the subject of an ordinary mission.
- Tier 2: environments are (jurisdiction, season, vintage) for at least ten jurisdictions plus national; two missions, one standing (20–50 published claims about transmission, formalized as test specifications, 5.9) and one frontier (weekly commitments).
- Object types: environment, claim, theory, evidence item, commitment. Lenses and definitions as needed; nogoods as needed.
- Scoring: log-score for standing (4.2); hub-format quantile export and WIS for comparability with hub teams.
- Contributions come from Alex's agent loops through the harness; no orchestrator is built (Decided). The captain is an LLM with the 6.4 safeguards (Decided).
- **Independence axis (Call).** E-values multiply across *weeks*, by sequential conditioning: one e-value per week, computed conditional on all prior data, across all jurisdictions jointly, which is a test supermartingale regardless of cross-jurisdiction correlation. Jurisdictions are *not* multiplied across; they are the out-of-distribution axis: a theory fitted on some is committed on the others and scored by log-score difference against the baseline mixture.

Builder-check resolutions (all Call):

- **The platform executes evidence items itself**, in a sandbox, as Prove2Me verifies server-side. An evidence item exists, and can carry standing, only once the platform has reproduced it; contributor-side results are submissions, not evidence. NHSN and ILINet data are public, which makes this possible for the pilot.
- **Log-score only.** Pilot theories must expose a density (the PPL subset of the reference language). This keeps the e-value-as-likelihood-ratio identity (4.4) exact. Sampler-only theories, and the energy score or CRPS they need, are post-pilot.
- **Synthetic worlds are environments in the same ledger**, access class synthetic-private, and their missions are ordinary missions. Generators are written and held by someone other than the sessions that propose theories against them, outside any workspace a proposer can read; proposers see only observations and the `do()` interface. Model lineage is not a contamination channel (a model cannot recall a program it wrote in another session), but shared context is.
- **No Thresholdout accounting in the pilot.** Synthetic-world queries are counted, not budgeted. Real custodian-held and time-locked holdouts are out of scope (8.4).

### 8.3 Success criteria (falsifiable)

1. Tier 1: the mixture concentrates on the true generator (or its predictive equivalent) within a budget the builder sets; `do()` predictions derived by surgery from structural theories match the generator's interventions; injected fake evidence is detected; a lens swap is absorbed by a new lens, not a theory rewrite.
2. Tier 2: (a) at least eight consecutive weekly commitments resolve at full weight and the platform's calibration (6.6) is reported; (b) standings for the audited claims move materially from "published = supported" for a nontrivial fraction, with provenance; (c) at least one invariance result: a theory fitted on a subset of jurisdictions, committed and scored on the rest.
3. At least one person who is not Alex contributes a test.
4. Someone in the field says the standing report told them something they did not know.

If 1–2 fail, the mechanism is wrong and no platform is built. If 3–4 fail, the mechanism may be right and the social layer is wrong.

Time horizon (Decided: a year is too long). Tier 1 produces results in days. Tier 2 produces its first full-weight resolution one week after the first commitment and satisfies 2(a) about two months after it.

### 8.4 Explicitly out of scope for the pilot

Real-money stakes; a public reputation system; moderation; multiple captains; any domain beyond the two tiers above; a UI beyond what agents and the captain need; real custodian-held or time-locked holdouts and Thresholdout budgeting; sampler-only theories; an orchestration loop that runs proposer agents automatically; beating the hub ensemble, which is not a goal; NHANES and the nutrition literature, which are deferred to a later standing mission.

---

## 9. Open: the social layer

Deliberately undecided. Alex's instruction: copy existing systems where possible, Prove2Me first. Questions a builder cannot answer alone:

1. **Cost of submission.** What does a test cost: compute, reputation stake, nothing? This is the sole defense against manufactured doubt and must be set before any public opening.
2. **Credit.** Compression gain and definition reuse are the proposed currencies (4.8). How they become a portable credential (a track record, as on Metaculus), and whether credit flows to the human, the agent, or both, is open. Prove2Me credits the human account.
3. **Conflict.** Who adjudicates a contested read-back or a contested measurement model? Prove2Me uses captains plus moderators. Whether that scales past one domain is open.
4. **Diversity and cascades.** The anti-monoculture and anti-cascade mechanisms (section 7) are named but not designed. Candidates: blind phases before discussion is visible; weighting by model/method diversity; rewarding disagreement that later resolves in the dissenter's favor.
5. **Agenda.** Captains are human; how captains are recruited and what qualifies one is open.
6. **Markets.** Whether to run play-money markets over claim standings alongside the scoring, as the human-facing aggregation layer.

Sources to copy from, in rough order of fit: Prove2Me (missions, captains, read-backs, credit for reuse, idle-token onboarding); the forecast-hub model (committed weekly submissions, proper scoring, ensemble as the standing output); Metaculus (track records as credentials); Polymath (open-ended but rule-governed collaboration); Stack Exchange (reputation gating actions); CASP (rounds with rotating holdouts).

### 9.1 On git as a substrate (Call, raised by Alex)

Git's *object store* is right; git's *workflow* is wrong.

- Right: content-addressed, immutable objects in a Merkle DAG. Every object in section 5 is exactly that, and the commitment log is a hash chain. Appending immutable objects scales horizontally; a million agents appending to a sharded append-only store is an ordinary systems problem.
- Wrong: mutable branches, merges, and a single integration point. The Prove2Me paper argues this directly: large swarms editing shared files serialize through a merge queue, which becomes the empirical bottleneck, and the resulting interdependent files cannot be reused in isolation. Prove2Me's answer, which this design adopts, is that nothing is ever merged: each object is self-contained, carries its own context, and is added once. There is no trunk to contend for.

So: a git-like object model (or IPFS/Merkle-DAG equivalent, or a database with content-addressed rows) without git. Whether to literally use git's storage is left to the builder (section 10).

---

## 10. Left to the builder

Technical choices this document does not make. Where Claude has a lean, it is noted.

1. **Reference language for theories.** Must be executable, sandboxed, and support sampling; a probabilistic programming language is the natural fit (lean: a Python-hosted PPL so that "any Python program" is admissible as a sampler while densities are available when written in the PPL subset). Program length under the reference machine must be computable and stable; the builder defines the measure.
2. **Storage and API.** Content-addressed object store; append-only commitment log with trusted timestamps (lean: timestamps anchored to an external, publicly verifiable source, so the platform itself is not trusted for ordering). API shape should let an agent do everything from a shell, as Prove2Me's does.
3. **Execution of evidence items.** Pinned, reproducible environments (containers), with deterministic seeds; output hashing with declared numerical tolerances.
4. **Scoring implementation.** Choice of energy score vs CRPS for sample-only theories; stacking/universal-portfolio details; damping constants for truth maintenance; the contamination discount schedule (6.3); holdout budget accounting (6.2).
5. **Read-back protocol.** Which agent, with what context withheld, and how the comparison is recorded.
6. **Synthetic world generators.** Format, interface for `do()` queries, rotation schedule.
7. **Environment metadata schema.** What "conditions" and "measurement model" contain, structurally, so that cross-environment comparison is mechanical.
8. **Agent harness.** A SKILL.md-style entry point with references, mirroring Prove2Me's workspace repo, so onboarding is "point your agent at one URL."
9. **Hub interoperability.** Weekly ingestion of NHSN and ILINet vintages; export of committed predictive distributions in hub quantile format with WIS computed alongside the log-score, so pilot theories are comparable with hub teams without being submitted to the hubs.
10. **Synthetic epidemic generators.** The compartmental and agent-based generators of 8.1, their reporting lenses, and the `do()` interface; stored and run where no proposing session can read them.
11. **Surgery implementation.** The structural-program subset of the reference language on which `do()` is defined mechanically, and the check that a submitted theory is in that subset.

---

## 11. References

Platform and prior art

- Chen, Marwaha, Lu, Yuen, Peng. *Prove2Me: An Open Collaborative Platform for Scaling Math Formalization.* arXiv 2608.28433 (2026).
- Romera-Paredes et al. *FunSearch* (2023); *AlphaEvolve* (2025): LLM proposes programs, mechanical scorer evaluates.
- Ellis et al. *DreamCoder* (2021): library learning.
- Dwork, Feldman, Hardt, Pitassi, Reingold, Roth. *The reusable holdout.* Science (2015).
- Patel, Burford, Ioannidis. *Assessment of vibration of effects due to model specification.* J Clin Epidemiol (2015).
- Steegen, Tuerlinckx, Gelman, Vanpaemel. *Increasing transparency through a multiverse analysis.* (2016).
- Udrescu, Tegmark. *AI Feynman.* (2020); La Cava et al. *SRBench* (2021).
- Swanson. Fish oil, Raynaud's syndrome, and undiscovered public knowledge (1986).

Epistemology and statistics

- Popper, *Conjectures and Refutations*; Lakatos, *The Methodology of Scientific Research Programmes*; Kuhn, *Structure*; Mayo, *Statistical Inference as Severe Testing* (2018); van Fraassen, *The Scientific Image*; Worrall, structural realism (1989); Peirce, "The Fixation of Belief" (1877); Merton, norms of science (1942).
- Gelman, Shalizi. *Philosophy and the practice of Bayesian statistics.* BJMSP (2013).
- Dawid. Prequential principle (1984). Rissanen, MDL (1978). Solomonoff (1964). Cover, universal portfolios (1991).
- Yao, Vehtari, Simpson, Gelman. *Using stacking to average Bayesian predictive distributions.* (2018). Minka, *Bayesian model averaging is not model combination* (2000).
- Grünwald, de Heide, Koolen. *Safe Testing.* JRSS-B (2024). Shafer, *Testing by betting.* JRSS-A (2021). Ramdas, Grünwald, Vovk, Shafer. *Game-theoretic statistics and safe anytime-valid inference.* Stat Sci (2023). Vovk, Wang. *E-values.* Ann Stat (2021).
- Peters, Bühlmann, Meinshausen. *Causal inference by using invariant prediction.* JRSS-B (2016). Schölkopf et al. *Toward causal representation learning.* (2021). Woodward, *Making Things Happen* (2003). Pearl, *Causality* (2009).
- Doyle, truth maintenance (1979); de Kleer, ATMS (1986); Dorling, Bayesian resolution of Duhem (1979).
- Baron, Mellers, Tetlock, Ungar. *Two reasons to make aggregated probability forecasts more extreme.* (2014). Hinton, products of experts (2002).
- Cramer et al. COVID-19 Forecast Hub ensemble evaluation. PNAS (2022).

Pilot domain

- Mathis et al. *Evaluation of FluSight influenza forecasting in the 2021–22 and 2022–23 seasons.* Nature Communications (2024).
- Bracher, Ray, Gneiting, Reich. *Evaluating epidemic forecasts in an interval format.* PLoS Comput Biol (2021): the weighted interval score.
- Shaman, Kohn. *Absolute humidity modulates influenza survival, transmission, and seasonality.* PNAS (2009).
- Cauchemez et al. *Estimating the impact of school closure on influenza transmission from Sentinel data.* Nature (2008).
- Schorlemmer et al. *The Collaboratory for the Study of Earthquake Predictability: achievements and priorities.* Seismol Res Lett (2018): prospective committed testing of forecast models.

---

## 12. Changelog

- **0.1** (2026-10-23): initial draft from the brainstorm.
- **0.1.1** (2026-10-23): builder check applied. Added: structural independence rule for e-values (4.4); claims as test specifications in standing missions (5.9); three contamination weight classes (6.3); pilot execution model, log-score-only rule, synthetic-world boundary, and holdout scope (8.2); criterion 2 split (8.3); pending decisions for Alex (top).
- **0.2** (2026-10-23): Alex's decisions applied. Pilot re-centred on respiratory disease surveillance (weekly resolution) with synthetic epidemic worlds for feedback on demand; NHANES deferred (8). Contributions from Alex's agent loops, no orchestrator; LLM captain with safeguards (6.4). Added: interventions as program surgery and three classes of interventional content (3.10, 5.3); lenses as measurement-model programs with MDL accounting, and vintages for streams (5.1, 5.5); identification and lens tasks (5.6); `extends` edge (5.10); independence across weeks by sequential conditioning, jurisdictions as the OOD axis (8.2); hub interoperability, generators and surgery for the builder (10).
