# Codex review of science.me design 0.6

Reviewer: OpenAI Codex (codex-cli 0.163.0), run read-only on 2026-10-23 at Alex's request as the different-lineage review required by design 0.6, section 6.2 item 10. Prompt: adversarial "where is this wrong" plus the builder-check questions. Unedited.

**PART A — Where this is wrong**

There are several design-breaking errors. The first four would invalidate the evidence accounting even if the implementation followed the specification perfectly. Findings are ranked by severity.

**1. Critical — The commitment rule permits already-known outcomes to count as prospective evidence. (§§4.1–4.3, 4.9)**

“Program commit precedes vintage commit” establishes ordering inside the platform. It does not establish that the outcome was unavailable when the program was written.

For example: CDC publishes Wednesday morning; an agent reads the result and commits a program; the puller commits Wednesday afternoon. The program qualifies. External timestamping faithfully proves the wrong thing.

There are two additional leaks:

- Masking rows by **event date** does not restrict information by **availability date**. Running against the resolving vintage can supply revisions to earlier weeks that were unavailable at the forecast origin.
- A program committed after an initial release can qualify against its later revision. That is potentially a forecast of backfill, but it cannot be presented as a previously unseen disease outcome.

The private-synthetic-world exception in §4.9 is worse: a private generator does not make its previously published outputs unseen.

**Instead:** define forecast origins, information cutoffs, horizons, and resolution rules. Freeze the complete executable and its input-selection policy before the cutoff; run it against an archived *as-of* information set. An algorithm commitment can suffice without individual forecast submissions, but the executable, dependencies, and information available to it must actually be fixed.

**2. Critical — The proposed scorer is not proper for the submitted predictive distribution. (§§4.3, 5.3)**

A logarithmic score is proper when it evaluates the distribution being reported. Applying it to an arbitrary moment-matched projection does not inherit that property. The honesty guarantee invoked in §5.3 therefore does not follow. [Gneiting and Raftery](https://sites.stat.washington.edu/people/raftery/Research/PDF/Gneiting2007jasa.pdf)

Here is a concrete counterexample, using population moments so Monte Carlo error is irrelevant. Suppose the truth is

\[
P(Y=0)=0.9,\qquad P(Y=10)=0.1.
\]

Its mean is 1 and its variance is 9. I computed the expected score under §4.3:

| Submitted predictive distribution | Mean | Variance | Expected log score |
|---|---:|---:|---:|
| The true distribution | 1 | 9 | −0.796408 |
| A negative binomial with deliberately inflated variance | 1 | 21 | **−0.716891** |

Higher is better. **Misreporting the distribution improves expected performance.** This is an exploit, not merely an inability to represent multimodality.

The moment fit also requires variance greater than mean, with special handling at boundaries. Underdispersed count distributions have no matching negative binomial. Deterministic forecasts and finite samples create further boundary cases. Thus “admits any sampler” is false.

The resulting likelihood ratios concern the **projected negative-binomial forecasts**, not the submitted generative programs.

**Instead:** require evaluable predictive probabilities, or score samples/quantiles using an appropriate proper score. WIS is an established option, but exponentiating WIS does not recover Bayesian likelihood semantics. The design must relinquish one of its incompatible requirements. [Bracher et al.](https://pmc.ncbi.nlm.nih.gov/articles/PMC7880475/)

**3. Critical — Programs with different entry dates have incomparable cumulative scores. (§§4.2, 4.4)**

For count PMFs, every log score is nonpositive. An established program with cumulative score −100 competes against a newcomer with cumulative score −2. With equal length penalties, the newcomer receives \(e^{98}\) times the weight—even if its forecasting ability is worse.

Nothing in the formula supplies a common evaluation history or an entry adjustment. New versions can repeatedly escape accumulated losses. Selective target coverage creates a related problem if programs can declare different targets.

This is not ordinary uncertainty about a new entrant. It is a structural reward for having faced fewer observations.

**Instead:** use fixed comparison cohorts, or a specified online protocol for introducing experts that allocates existing probability mass and defines their evaluation opportunities. Compare programs on common prospective tasks. Dividing by the number of observations would change the problem but would not restore the claimed Bayesian interpretation.

**4. Critical — Supersession can turn post-outcome repairs into historical predictive success. (§§3.3, 4.2, 4.7)**

Suppose a program committed in October imports a reporting lens. In December, after examining November’s errors, an agent replaces that lens.

Section 4.7 either:

- reruns the October program with December’s lens, violating its original commitment; or
- creates a new effective program, which requires a December eligibility date.

It cannot preserve the October commitment while using the December implementation. The same issue applies to changes in fitted assets and transitive dependencies.

Scorer corrections and data corrections require another distinction: correcting an arithmetic error is different from choosing a more favorable scoring convention after observing outcomes.

Also, “the supersession that improved the score … is the verdict” does not solve Duhem–Quine blame assignment. Several compensating changes can improve the same observations. Improvement identifies a successful modification, not which component was originally wrong.

**Instead:** preserve immutable prospective histories and separately labeled corrected analyses. Hash the complete executable dependency closure. New substantive repairs earn evidence on subsequent observations.

**5. High — The length rule is neither the claimed MDL accounting nor a stable prior. (§§3.5, 4.4)**

Dividing an import’s length among its importers makes a program’s prior depend on other submissions. Twenty additional importers can make an existing theory cheaper without producing evidence.

That is a direct subsidy attack: submit programs that import a favored expensive lens. Predictive clustering does not necessarily repair it, because the denominator counts importers.

Shared code can be paid for once in a specified joint coding scheme, or treated as part of a fixed reference language. Dividing its cost among alternative hypotheses does not automatically produce such a scheme.

There is also a units error: the formula treats compressed **bytes** as **bits**. A finite normalized version can still define a heuristic prior, but it does not establish the asserted coding interpretation.

Finally, this is not a tie-breaker. An extra 1,000 compressed bytes costs 1,000 bits under the written formula. Nothing guarantees that several weeks of predictive advantage will overcome that.

**Instead:** freeze a reference library and coding convention for an evaluation epoch. Charge dependencies consistently, or explicitly describe the length term as a heuristic regularizer and drop the MDL guarantees.

**6. High — Near-duplicate clustering can erase relevant distinctions and still permits claim-level Sybil attacks. (§§4.4–4.5, 4.10)**

Agreement on past scored targets is not equivalence on future interventions. Two programs can make identical observational predictions while disagreeing completely about school closure. Those are precisely the alternatives the wanted list should preserve.

“Within a tolerance” is also not an equivalence relation: A can resemble B, and B resemble C, while A differs materially from C. Choosing a clustering algorithm resolves computation, not the scientific meaning of the resulting hypothesis.

More seriously, splitting cluster weight among members leaves a claim-level attack. Suppose one cluster contains a humidity-tagged program and an untagged program. Add nine predictively equivalent tagged variants. Its total weight stays fixed, but its contribution to the humidity claim changes from one-half to ten-elevenths of that weight.

Choosing the shortest member can additionally change the entire cluster’s prior after submission.

**Instead:** retain fixed hypothesis masses and causal distinctions. Aggregate identical forecasts computationally without redefining their prior or claim membership. Use empirical similarity as a diagnostic; do not let membership counts determine scientific support.

**7. High — The Bayes/Hedge guarantee is being used outside its stated conditions. (§§4.4, 7.2)**

For fixed normalized prior masses \(\pi_i\), common prediction opportunities, and the actual sequential mixture forecast, the log-loss bound is

\[
L_{\mathrm{mix}}\leq L_i-\log \pi_i.
\]

That does not automatically apply to changing importer costs, retrospectively changing clusters, or programs with different scoring histories. The penalty is \(-\log\pi_i\); it becomes \(\log N\) for a uniform prior over a fixed population. “The prior pays log N” is not a universal population-scale multiple-comparisons correction.

Separately, summing marginal log scores across jurisdictions can be a legitimate forecast evaluation score without assuming independence. **Interpreting its exponential as evidence about mechanisms introduces additional assumptions.** Correlated jurisdictions, national totals, and overlapping forecasts can repeatedly count the same information. Duplicating an observation squares a likelihood ratio while adding no evidence.

Calling this “a score, not a test” does not remove the problem when the resulting weights are subsequently treated as beliefs and used in information-gain calculations.

**Instead:** specify a joint/sequential probability model, or explicitly use a generalized predictive weighting scheme with appropriately limited interpretations.

**8. High — Tag weight is not support for the corresponding scientific claim. (§§2, 4.5)**

An untagged program need not assert that humidity has no causal effect. It may omit humidity because its effects are captured by seasonality, because it forecasts only short horizons, or because it makes no mechanistic assertion.

Consequently, tagged-versus-untagged weight is not generally a comparison between a proposition and its negation.

Matched pairs improve control over implementation differences, but they do not establish causal identification. Removing a humidity term tests that term’s predictive contribution under the remaining assumptions. Confounding, measurement error, collinearity, and nuisance-parameter fitting remain.

Likewise, two programs differing in one term do not automatically constitute an **effect size**. An effect requires an estimand: intervention, population, outcome, horizon, and contrast, with uncertainty.

There is also a direct contradiction with §2’s rejection of a scalar truth score per claim: §4.5 supplies exactly such a scalar unless its interpretation is tightly restricted.

**Instead:** distinguish asserted absence, asserted presence, and unspecified mechanisms. Define claim scope and estimands explicitly. Report model-relative predictive support separately from causal evidence.

**9. High — The “invariance score” is a geographic transfer score, not an invariance test. (§§3.1, 3.5, 4.6)**

Training on some jurisdictions and scoring others measures transfer performance. It does not test whether a particular causal mechanism remains invariant.

A seasonal proxy can generalize across all selected states because the confounding relationship persists. A correct causal mechanism can transfer poorly because susceptibility, reporting, demographics, or parameters differ.

Invariant causal prediction requires specific assumptions about conditional distributions and environmental changes. Those assumptions do the identification work; a row mask does not supply them. [Peters, Bühlmann, and Meinshausen](https://arxiv.org/html/1501.01332)

Thus “out-of-distribution adequacy forces causal content” is overstated. Future observations are not necessarily out of distribution, and robustness across selected environments does not establish causality.

**Instead:** call the existing metric a held-out-jurisdiction predictive score. Add a separately specified invariance analysis if causal conclusions are required, with explicit environment assumptions and identification limits.

**10. High — Exposed assignments do not automatically support causal surgery, and baseline substitution fabricates intervention performance. (§§3.10, 4.3, 4.6)**

Replacing an equation is a valid intervention operation within a defined structural causal model. Ordinary Python assignments are not automatically structural equations. Their meaning depends on state, time indexing, exogenous randomness, update order, and the declared intervention semantics. [Pearl](https://ftp.cs.ucla.edu/pub/stat_ser/r240-reprint.pdf)

For example, setting “vaccination = 0.8” leaves unanswered when vaccination occurs, who receives it, and which susceptibility or severity mechanisms change. A standardized variable name cannot resolve those differences.

The fallback rule introduces a separate error: an opaque mechanistic program receives the baseline’s intervention score despite producing no intervention prediction. Successful baseline performance can then support the opaque program’s tags.

The same attribution problem arises when a failing program receives baseline scores. The effective predictor is a hybrid containing the fallback.

**Instead:** require explicit structural semantics for surgery. Attribute fallback predictions to the fallback mechanism, and mark unsupported interventions as unsupported. They must not become evidence that another program’s causal assumptions survived testing.

**11. High — The EIG formula is valid, but the proposed predictive representation can destroy the information being sought. (§§4.3, 4.10)**

For a coherent fixed mixture,

\[
I(M;Y)=H\!\left(\sum_m w_m p_m\right)-\sum_m w_m H(p_m)
\]

is the appropriate model-discrimination quantity. The mixture inside the first entropy must remain a mixture; it is generally not negative binomial.

The projection creates a concrete failure. Consider two equally weighted programs:

- A: \(P(0)=P(4)=0.5\).
- B: \(P(1)=0.8,\ P(6)=0.2\).

Both have mean 2 and variance 4. Their fitted negative binomials are identical, so projected EIG is zero. Their actual supports are disjoint, so **one observation identifies the program perfectly: one bit of information**.

For experiments producing several measurements, marginal predictive samples also do not determine the joint information gain. Models can agree on every marginal and disagree entirely about dependence.

Finally, samples for existing targets are not generally samples for a new measurement channel or intervention. Candidate-specific simulation is required, and some programs may not define that observation at all.

**Instead:** calculate EIG for the actual observation model and joint outcome of the proposed experiment. If likelihoods are unavailable, simulation-based discrimination methods exist, but they require additional estimation and validation. [Hainy et al.](https://arxiv.org/abs/1809.05301)

**12. High — Agreement does not make data useless, and a flexible competitor is not a “none-of-the-above” check. (§4.10; §§6.2–6.3)**

A mixture containing one Bayesian program has zero uncertainty about program identity. That program can nevertheless have substantial parameter uncertainty, and another observation can be extremely valuable. Program-identity EIG misses this entirely.

Agreement can also reflect a shared blind spot, insufficiently varied experiments, or equality of one-step predictions despite different predictions for sequences.

Likewise, a flexible baseline winning establishes relative predictive advantage. It does not establish that every mechanistic program is inadequate. Conversely, the baseline can lose while **every** program is badly wrong.

This does not recover model checking “at no cost.” Model comparison and checking absolute predictive adequacy are different operations—the distinction emphasized by a reference the document already cites. [Gelman and Shalizi](https://arxiv.org/abs/1006.3868)

**Instead:** retain independent calibration and discrepancy checks, include relevant parameter/effect uncertainty in acquisition objectives, and reserve some collection for exploration outside current disagreements.

**13. High — The pilot can reward overconfidence and reject a functioning system for the wrong reasons. (§§6.3, 7.3)**

Entropy reduction is not correctness. Rapid concentration on a wrong model scores well on that measure. Adding or splitting program identities also changes entropy without changing scientific knowledge.

An informative observation can increase realized posterior entropy: moving from weights \((0.99,0.01)\) to \((0.5,0.5)\) increases entropy from approximately 0.081 to 1 bit. That can be a useful correction of misplaced confidence. Expected entropy reduction remains a valid Bayesian objective; individual realized reductions are not an uncomplicated progress meter.

The separate truth-concentration criterion helps, but “predictive equivalent” must not mean equivalent only after the lossy projection in §4.3.

The abandonment rules also do not isolate causes. Failure to recover a generator can reflect nonidentifiability, missing hypotheses, bad likelihood approximation, or insufficient exploration. Baseline dominance on real data does not demonstrate that the domain is wrong. Agreement with published claims is compatible with a successful platform, yet §7.3 requires a material departure.

**Instead:** compare directed and random collection across independent replicated worlds and matched budgets, measuring true predictive performance and recovery of identifiable distinctions. Permit corroboration and “insufficient evidence” as legitimate real-stream outcomes.

**14. High — Cumulative log scores are neither smoothly bounded nor reliably reversible. (§§3.6, 3.9, 6.1)**

“One week’s worth” is not a bound on log loss. A single outcome assigned probability \(10^{-200}\) incurs about 461 nats of loss. One observation can reverse enormous odds. Probability zero creates permanent exclusion under ordinary Bayesian updating.

Thus “move by bounded amounts per week and never toggle” is false.

The best-single-program guarantee also does not guarantee the best combination. When all models are misspecified, Bayesian model averaging can concentrate on one model even though a persistent mixture predicts better. This is a central motivation for stacking, rather than an exceptional collapse scenario. [Yao et al.](https://arxiv.org/abs/1704.02030)

Changing epidemic regimes introduce another problem: cumulative historical success can overwhelm current performance.

**Instead:** specify whether the platform values cumulative evidence, current predictive usefulness, or stable reporting. Those require different mechanisms. Any robustness floor, switching model, discounting rule, or alternative ensemble must be explicit, including what interpretation it sacrifices.

**15. High — Running an ingest program inside the kernel does not attest that its output is what the source served. (§§4.9, 5.2–5.3)**

An agent-authored puller can transform, omit, fabricate, or selectively retrieve records. Running that code on the owner’s machine establishes who executed it; it does not independently establish the provenance of its output.

Similarly, disabling network access does not enforce the scorer’s information boundary if a program can read resolving data, other repository files, mutable artifacts, or privileged environment contents.

The read-back’s impact is also not bounded to a mislabeled entry. A wrong tag on a high-weight program can redirect the wanted list; an incorrect shared component can affect many programs.

**Instead:** separate trusted raw-response capture from versioned transformations, preserve raw source artifacts and provenance, and isolate prediction workers to explicitly permitted inputs. Treat read-back as an audit aid, with its downstream uncertainty visible.

**16. Moderate — The surveillance pilot conflates materially different observation processes. (§§4.3, 7.1–7.2)**

ILINet’s common target is a percentage of outpatient visits meeting an influenza-like-illness definition. It is not a laboratory-confirmed influenza count, and the syndrome includes other pathogens. Its case definition and reporting composition also matter. A negative-binomial count scorer cannot simply cover that target. [CDC surveillance methods](https://www.cdc.gov/fluview/overview/)

Current FluSight rules explicitly distinguish reference dates, target dates, horizons, and nowcasts; they also include a proportion-valued ED target. Borrowing its infrastructure requires those distinctions, not just CSV formats. [FluSight 2026–27 specification](https://github.com/cdcepi/FluSight-forecast-hub/blob/main/README.md)

The 2020–21 influenza collapse is not an isolated intervention identifying school closure, humidity, or vaccination. Multiple interventions and behavioral changes coincided, and surveillance itself was affected. CDC’s analysis explicitly discusses those limitations. Under this document’s own rules, it is also historical context rather than counted prospective evidence. [CDC’s 2020–21 analysis](https://www.cdc.gov/mmwr/volumes/70/wr/mm7029a1.htm)

**Instead:** define separate observable-specific models and evaluation strata, including denominators, reporting coverage, and pathogen attribution. Avoid presenting this historical episode as a ready-made causal discriminator.

**17. Moderate — The claimed severity criterion is neither established by git nor implemented by the weights. (§§3.8, 4.4)**

Commitment, non-exposure, and disagreement do not establish the probability that a procedure would detect a specified error. Severity requires a claim, a discrepancy from it, and an assessment of the procedure’s capacity to expose that discrepancy. [Mayo](https://errorstatistics.com/wp-content/uploads/2020/10/mayo2006_chapter_criticalrationalismanditsfailu.pdf)

The weight update contains no separate severity calculation. Likelihood evidence can be informative, but calling it Mayo-style severity without defining the relevant error probe adds an unsupported philosophical guarantee.

Likewise, “public data is not evidence because current models have read it” overstates a defensible operational policy. Exposure is not universally known, and data do not cease to be evidence when published. What becomes difficult is treating adaptively selected analyses as fresh independent confirmation.

**Instead:** describe the prospective-only policy as a conservative eligibility rule. Either implement specified severity analyses or remove the claim that severity is automatically recorded in git.

**PART B — Questions a builder still needs answered**

These concern scientific or evaluation policy, rather than the implementation choices delegated in §9 or the social mechanisms left open in §8.

1. **What constitutes a forecast opportunity?** Are counted tasks strictly future event weeks, nowcasts of unreported events, predictions of later revisions, or several explicitly separate categories? What information is legitimately available at each origin? (§§4.1–4.3, 7.2)

2. **What is the persistent unit of competition?** Is it a source snapshot, an adaptive forecasting procedure, or a research programme spanning supersessions? How does a new version enter the existing weight system, and does its predecessor remain active? (§§4.4, 4.7)

3. **Which historical results may be restated?** When a scorer, lens, or resolving dataset changes, should the official record preserve the original prospective evaluation alongside a corrected analysis, or replace it? Which record determines current standing? (§§2, 4.7, 4.9)

4. **Are specialists permitted?** Must each program forecast every mission target, pathogen, jurisdiction, and arm, or can it declare a narrower scope? If narrower scopes are allowed, which common comparisons determine its weight and which claim updates may use fallback predictions? (§§3.2–3.4, 4.3–4.6, 7.2)

5. **What does absence of a tag mean?** Does it assert absence of the mechanism, or merely leave the mechanism unspecified? What population, regime, outcome, and intervention scope belongs to each claim? (§4.5)

6. **What is a matched-pair comparison intended to estimate?** Is it an ablation holding fitted parameters fixed, a comparison of separately refitted models, or an integrated comparison over nuisance uncertainty? When matched pairs exist, does their conditional standing replace the global tagged weight, and which quantity feeds targeted EIG? (§§4.5, 4.10)

7. **What happens when a proposed observation is outside some programs’ predictive scope?** Can it enter the wanted list before those programs have observation models for it? If so, what population of hypotheses does its reported information gain concern? (§§4.1, 4.10, 5.2)

8. **Is corroboration an acceptable pilot result?** If the machinery works and the evidence supports the published claims—or cannot distinguish them—does Tier 2 pass? The present success and abandonment criteria give consequentially different answers. (§§6.3, 7.3)