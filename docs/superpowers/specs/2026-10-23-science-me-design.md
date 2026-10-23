# science.me (design document)

**Version:** 0.1 (2026-10-23)
**Status:** brainstorm output, pre-plan. The social layer (section 9) is deliberately open.
**Authors:** Alexander Richard Towell (decisions), Claude (drafting; calls marked as such)

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
- a set of *missions*, each with a human captain, that bound what humans must audit.

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
- a **measurement model**: how observations were produced, selection process, instruments. This is a hypothesis node, contestable.
- declared conditions: population, time, regime, what differs from sibling environments
- provenance: collector, collection dates, release schedule (for streams)
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

### 5.4 Evidence item

A reproducible computation relating a theory or claim to an environment.

- environment hash, code hash, pinned execution environment, output hash
- the score produced (e-value, log-score, or discrepancy statistic) and against what
- the commitment it resolves, if any
- a blind **read-back** (section 6.4) of what the analysis literally tests

Anyone can re-run it. Its reproducibility is mechanical; its *relevance* (does it actually test the claim?) is judged against the read-back and is contestable.

### 5.5 Commitment

A hash of a prediction (or analysis plan) plus a timestamp in an append-only log, revealed later.

- hash, timestamp, committer, the environment or stream it concerns, expected resolution date
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

- **Standing mission**: "establish the standing of the claims in this paper/literature." Milestones are the key published claims; tasks are reproduce / vary / extend / commit.
- **Frontier mission**: "find a regularity nobody has reported, commit it for the next release." Milestones are environments to cover and streams to commit against; the deliverable is a theory that takes weight.

The audit surface is the mission core: claims, falsification criteria, the environments' measurement models. Agents introduce anything below it without audit, as on Prove2Me, because the trusted object is the scoring of audited claims on committed predictions, not the agent's chosen decomposition.

### 5.10 Edges

depends-on, imports, tests, supports (with e-value), contradicts (with nogood), supersedes, predictively-equivalent-to, committed-for. The graph is a DAG except for `contradicts`, which is symmetric.

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

LLM agents have read the public datasets and the papers. A finding on public data may be recall; a prediction on it may be memorized. Therefore: standing earned on public data is provisional; only commitments resolved on post-training-cutoff or custodian-held data are full-weight. The platform records the training-cutoff metadata an agent declares and discounts accordingly. The discount schedule is left to the builder.

### 6.4 Read-back (carried over from Prove2Me)

For each evidence item and each claim in a mission core, an independent agent that has not seen the source states, in plain language, what the analysis literally tests or what the claim literally asserts, with every assumption explicit. The human auditor compares that testimony to the source. Faithfulness is judged on the comparison, not by reading code.

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
| Correlated error / monoculture | many copies of one model | diversity of models, methods and environments is a measured goal; **mechanism Open** (section 9) |
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

### 8.1 Domain (Call, Alex leaning toward "marginally useful and in the spirit")

**Nutrition and health epidemiology on national health surveys, starting with NHANES**, with **synthetic experimentable worlds** run in parallel as the machinery's test bed.

Why NHANES: thousands of published associations; a literature known to be fragile with a direct methodological precedent (Patel, Burford, Ioannidis 2015, vibration of effects); a two-year release cycle, so commitments resolve on post-cutoff data; comparable surveys in other countries (KNHANES, CHNS, ELSA, SHARE) providing genuine environments for invariance tests; public data with computational evidence; a mission shape that copies over from Prove2Me ("Mission: dietary sodium and blood pressure", milestones = key published claims).

Known risks of the choice: not glamorous; "replication police" breeds hostility; most claims are associational. Mitigations: credit what survives rather than what fails; let cross-national invariance supply the scientific content; run frontier missions from day one.

Alternatives considered and set aside for the pilot: forecast hubs (closest existing pattern, but forecasting is not theory-building), Rubin/LSST alerts (needs astronomy captains), replication prediction à la SCORE (slow resolution), Alex's masked-data reliability domain (full competence to captain, niche audience).

### 8.2 Scope

- 50–100 published claims from one sub-literature, chosen by the captain.
- Object types: environment, claim, theory, evidence item, commitment. Definitions and nogoods as needed.
- One scoring rule (4.2) and one standing-weight rule (4.3).
- Two missions: one standing, one frontier.
- At least two real environments (NHANES plus one other national survey) and one scheduled resolution (the next NHANES cycle).
- At least three synthetic worlds with private generators, one of them adversarial.

### 8.3 Success criteria (falsifiable)

1. Standings move: for the audited claims, the standing after reproduce/vary/extend differs materially from "published = supported" for a nontrivial fraction, with provenance.
2. At least one committed prediction resolves on post-cutoff data and the platform's calibration (6.6) is reported.
3. On synthetic worlds, the mixture concentrates on the true generator (or its predictive equivalent) within a budget the builder sets, and injected fake evidence is detected.
4. At least one person who is not Alex contributes a test.
5. Someone in the field says the standing report told them something they did not know.

If 1–3 fail, the mechanism is wrong and no platform is built. If 4–5 fail, the mechanism may be right and the social layer is wrong.

### 8.4 Explicitly out of scope for the pilot

Real-money stakes; a public reputation system; moderation; multiple captains; any domain beyond the two above; a UI beyond what agents and the captain need.

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
