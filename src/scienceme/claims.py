"""Claims over matched pairs.

A claim's standing is model-relative predictive support, read from *matched pairs* only: two frozen
programs that differ solely in their stance on the claim, or on a set of claims declared together that
are one mechanism at several scopes (`validate_pair`, enforced when the pair is frozen).  For a pair,
`delta_nats` is the summed log-score difference `log_p[asserts] - log_p[denies]` over the resolved
targets in the claim's scope that both programs predicted.  Tempered by the mission's `tau`, a delta of
at least `threshold` supports the claim and one of at most `-threshold` contradicts it; anything between
is insufficient evidence.

A pair declared over several claims counts for a claim only when every one of them is the claim itself,
a claim that refines it, or the claim it refines (`Claim.refines`): a pair that also differs in an
unrelated mechanism is confounded and left out.  A pair is also dropped when either member covers too few
of its targets (`mission.coverage_min`), so a pair that mostly failed to run cannot speak for the claim.
Programs are identified by closure hash throughout.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum

from scienceme.manifest import PairError, orient_pair
from scienceme.mission import Claim, Mission
from scienceme.model import Frozen, StreamSpec
from scienceme.registry import Registry, RegistryError
from scienceme.scoring import Resolution, ResolvedTarget
from scienceme.workspace import Workspace


class Verdict(StrEnum):
    """What the evidence says about a claim, or about one matched pair."""

    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    INSUFFICIENT = "insufficient evidence"
    MIXED = "mixed"


class PairStanding(Frozen):
    """One matched pair's evidence on `claim`: `delta_nats` of `asserts` over `denies` across `n_targets` targets."""

    claim: str
    asserts: str
    denies: str
    delta_nats: float
    n_targets: int
    verdict: Verdict


class ClaimStanding(Frozen):
    """A mission claim with the standing of each of its (well-covered) matched pairs and the overall verdict."""

    claim: str
    statement: str
    pairs: tuple[PairStanding, ...]
    verdict: Verdict


def pair_standing(
    claim: Claim,
    asserts: str,
    denies: str,
    resolved: Sequence[ResolvedTarget],
    specs: Mapping[str, StreamSpec],
    tau: float,
    threshold: float,
) -> PairStanding:
    """The pair's standing on `claim`, over the targets in the claim's scope that both programs predicted.

    `specs` must hold the spec of every stream in `resolved`.  With no such target the delta is 0 and
    the verdict is INSUFFICIENT.
    """
    shared = [
        k.scores[asserts].log_p - k.scores[denies].log_p
        for k in resolved
        if asserts in k.scores and denies in k.scores and claim.scope.matches(k.target, specs[k.target.stream])
    ]
    delta = sum(shared)
    if delta / tau >= threshold:
        verdict = Verdict.SUPPORTS
    elif delta / tau <= -threshold:
        verdict = Verdict.CONTRADICTS
    else:
        verdict = Verdict.INSUFFICIENT
    return PairStanding(
        claim=claim.id, asserts=asserts, denies=denies, delta_nats=delta, n_targets=len(shared), verdict=verdict
    )


def summarize(pairs: Sequence[PairStanding]) -> Verdict:
    """The verdict the decisive pairs share; MIXED if they disagree, INSUFFICIENT if none is decisive."""
    decisive = {p.verdict for p in pairs} & {Verdict.SUPPORTS, Verdict.CONTRADICTS}
    if not decisive:
        return Verdict.INSUFFICIENT
    return decisive.pop() if len(decisive) == 1 else Verdict.MIXED


def find_pair_sets(ws: Workspace, claim_id: str) -> list[tuple[str, str, frozenset[str]]]:
    """Every matched pair declared for `claim_id` by a frozen program, as (asserts, denies, claims).

    `claims` is the set the pair was declared over: every claim the declarer pairs with that partner (R9),
    unioned over the pair's declarations.  A pair is oriented by the declaring program's own tag
    (`orient_pair`), so it is the same pair whichever side declared it, and it appears once however often
    it is declared.  Sorted by (asserts, denies).  Withdrawn programs are included.  Every frozen program's
    manifest is read, so each is `verify`d first: RegistryError ("modified-after-freeze") when any directory
    changed since its freeze, since an edited stance or pair declaration would otherwise re-sign scores
    recorded under the old hash.  Also RegistryError when a manifest cannot be loaded, or declares a pair on
    a claim it neither asserts nor denies (`freeze` refuses that, so only a registry written around it can
    hold one).
    """
    registry = Registry(ws)
    found: dict[tuple[str, str], set[str]] = {}
    for closure in registry.freezes():
        registry.verify(closure)
        manifest = registry.manifest(closure)
        claims_by_partner: dict[str, set[str]] = {}
        for decl in manifest.pairs:
            claims_by_partner.setdefault(decl.partner, set()).add(decl.claim)
        for partner, claims in claims_by_partner.items():
            if claim_id not in claims:
                continue
            try:
                pair = orient_pair(manifest, closure, partner, claim_id)
            except PairError as e:
                raise RegistryError(str(e)) from e
            found.setdefault(pair, set()).update(claims)
    return [(asserts, denies, frozenset(found[asserts, denies])) for asserts, denies in sorted(found)]


def find_pairs(ws: Workspace, claim_id: str) -> list[tuple[str, str]]:
    """Every matched pair declared for `claim_id`, as sorted (asserts, denies) closure hashes (`find_pair_sets`)."""
    return [(asserts, denies) for asserts, denies, _ in find_pair_sets(ws, claim_id)]


def _family(claim: Claim, claims: Sequence[Claim]) -> frozenset[str]:
    """The claims a pair counted for `claim` may also differ on: itself, those that refine it, the one it refines."""
    refining = {other.id for other in claims if other.refines == claim.id}
    return frozenset({claim.id, *refining, *([claim.refines] if claim.refines is not None else [])})


def _coverage(resolution: Resolution, program: str) -> float:
    """Share of the program's records that are predictions; 0 for a program with no records."""
    predicted = resolution.predicted.get(program, 0)
    total = predicted + resolution.unscored.get(program, 0)
    return predicted / total if total else 0.0


def claim_standings(
    ws: Workspace, mission: Mission, resolution: Resolution, specs: Mapping[str, StreamSpec]
) -> list[ClaimStanding]:
    """One standing per mission claim, in mission order.

    A pair is left out when it was declared over a claim outside the claim's family (`_family`), or when
    either member's coverage, `predicted / (predicted + unscored)`, is below `mission.coverage_min`.  A
    claim with no remaining pair is INSUFFICIENT.
    """
    standings = []
    for claim in mission.claims:
        pairs = tuple(
            pair_standing(
                claim, asserts, denies, resolution.resolved, specs, mission.tau, mission.claim_threshold_nats
            )
            for asserts, denies, declared in find_pair_sets(ws, claim.id)
            if declared <= _family(claim, mission.claims)
            and min(_coverage(resolution, asserts), _coverage(resolution, denies)) >= mission.coverage_min
        )
        standings.append(
            ClaimStanding(claim=claim.id, statement=claim.statement, pairs=pairs, verdict=summarize(pairs))
        )
    return standings
