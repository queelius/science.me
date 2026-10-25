"""Expected information gain and the wanted list.

The wanted list is the platform's main output: the candidate arms worth observing, ranked by how much
they are expected to teach about which program is right.  A candidate is an intervention nobody has
observed yet.  Programs that can condition on it forecast it, and where their forecasts differ the
observation will tell them apart.  The *information gain* of one target is the mutual information
between "which program is right" and the observed count, `H(mixture) - sum w_m H(p_m)` in nats, with
`w` the programs' current mixture weights and `p_m` their raw (unfloored) forecasts.  It is computed
only over the programs whose declared interface supports the intervention, using what they actually
predict for it.

For each claim the same quantity is taken over each matched pair alone, on the targets in the claim's
scope, weighted by how far the pair's evidence already tilts it, and added to the item's priority with the
claim's weight.  Priority
is that sum per unit cost.  Items nobody can forecast are still listed, with gain and priority 0.

Rankings are saved write-once at `scores/<mission>/wanted/<as_of:05d>.json`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path

import numpy as np
from scipy.special import expit

from scienceme.archive import Archive, ArchiveView
from scienceme.claims import ClaimStanding, PairStanding
from scienceme.manifest import ProgramManifest, in_scope, supports
from scienceme.mission import Candidate, Claim, Mission, MissionError, WantedItem, epoch_at, load_wanted, mission_streams
from scienceme.model import Frozen, Isolation
from scienceme.pmf import Pmf, PmfError, mix
from scienceme.predict import require_isolation
from scienceme.record import RANKING_DIR
from scienceme.registry import Registry, RegistryError
from scienceme.weights import Advantages, normalized_weights
from scienceme.worker import build_order, run_order
from scienceme.worker_entry import Prediction
from scienceme.workspace import Workspace, read_model, write_new

_SUFFIX = ".json"


class RankedItem(Frozen):
    """One wanted item as ranked.

    `supporting` are the programs that forecast the candidate's every target; `failed` are the ones that
    should have but did not (a target failed, or the closure changed after its freeze).  Both are closure
    hashes in order, and disjoint.  `gain` is the expected information gain over the supporting programs;
    `targeted` is the gain of each claim that has a pair among them; `priority` is
    `(gain + sum_c weight_c * targeted[c]) / cost`.
    """

    item: str
    supporting: tuple[str, ...]
    failed: tuple[str, ...]
    gain: float
    targeted: dict[str, float]
    priority: float
    cost: float


class Ranking(Frozen):
    """The wanted list of `mission` as ranked at issue `as_of`, best first."""

    mission: str
    as_of: int
    items: tuple[RankedItem, ...]


def information_gain(pmfs: Sequence[Pmf], weights: Sequence[float]) -> float:
    """`H(mixture) - sum w_m H(p_m)` in nats: what observing the count reveals about which `pmf` is right.

    The weights are normalized to sum to 1.  Never negative (floating error is clamped).  PmfError for
    no pmfs, a different number of weights, or weights that are not finite, non-negative and not all zero.
    """
    if len(pmfs) == 0 or len(pmfs) != len(weights):
        raise PmfError("information_gain needs the same non-zero number of pmfs and weights")
    w = np.asarray(weights, dtype=float)
    if w.ndim != 1 or not np.all(np.isfinite(w)) or np.any(w < 0) or not w.sum() > 0:
        raise PmfError("weights must be finite and non-negative, and not all zero")
    w = w / w.sum()
    within = float(w @ np.array([p.entropy() for p in pmfs]))
    return max(0.0, mix(pmfs, w.tolist()).entropy() - within)


def _candidate_supported_by(manifest: ProgramManifest, candidate: Candidate) -> bool:
    """True for a non-library program that conditions on the candidate's intervention and forecasts all its targets."""
    spec = candidate.stream
    return (
        not manifest.library
        and supports(manifest, spec.intervention)
        and all(in_scope(manifest, target, spec) for target in candidate.targets)
    )


def _pair_gain(pair: PairStanding, pmfs: Mapping[str, list[Pmf]], tau: float, targets: Sequence[int]) -> float:
    """Gain of the pair alone on the candidate targets at indices `targets`.

    The asserting side weighs `expit(delta / tau)`: the more the evidence favors the assertion, the more
    weight it carries.
    """
    w_asserts = float(expit(pair.delta_nats / tau))
    return sum(
        information_gain([pmfs[pair.asserts][i], pmfs[pair.denies][i]], [w_asserts, 1.0 - w_asserts]) for i in targets
    )


def _targeted(
    standings: Sequence[ClaimStanding],
    claims: Mapping[str, Claim],
    candidate: Candidate,
    pmfs: Mapping[str, list[Pmf]],
    tau: float,
) -> dict[str, float]:
    """Per claim with at least one pair whose members both forecast the candidate: the pairs' gains summed.

    Only the candidate targets in the claim's scope count, as only in-scope targets count toward its
    standing.  A standing whose claim the mission does not list has no scope, so every target counts.
    """
    targeted: dict[str, float] = {}
    for standing in standings:
        pairs = [p for p in standing.pairs if p.asserts in pmfs and p.denies in pmfs]
        if not pairs:
            continue
        claim = claims.get(standing.claim)
        in_scope_targets = [
            i
            for i, target in enumerate(candidate.targets)
            if claim is None or claim.scope.matches(target, candidate.stream)
        ]
        targeted[standing.claim] = sum(_pair_gain(p, pmfs, tau, in_scope_targets) for p in pairs)
    return targeted


def _forecasts(
    ws: Workspace,
    mission: Mission,
    item: WantedItem,
    view: ArchiveView,
    programs: Mapping[str, ProgramManifest | None],
    isolation: Isolation,
) -> tuple[dict[str, list[Pmf]], list[str]]:
    """Run each program that supports the item once; return (hash to its pmf per target, hashes that failed).

    A program fails when it is no longer what was frozen (its manifest cannot be verified or read, or its
    closure changed), or any target got no forecast.  WorkerError propagates.
    """
    candidate = item.candidate
    pmfs: dict[str, list[Pmf]] = {}
    failed: list[str] = []
    for program, manifest in programs.items():
        if manifest is None:
            failed.append(program)
            continue
        if not _candidate_supported_by(manifest, candidate):
            continue
        try:
            result = run_order(ws, build_order(ws, program, view, candidate.targets), isolation, mission.run_timeout_s)
        except RegistryError:  # a member of the closure changed after freezing (R8)
            failed.append(program)
            continue
        predictions = [r for r in result.results if isinstance(r, Prediction)]
        if len(predictions) == len(result.results):
            pmfs[program] = [r.pmf for r in predictions]
        else:
            failed.append(program)
    return pmfs, failed


def _rank_item(
    ws: Workspace,
    mission: Mission,
    item: WantedItem,
    base: ArchiveView,
    programs: Mapping[str, ProgramManifest | None],
    isolation: Isolation,
    advantages: Advantages,
    claims: Sequence[ClaimStanding],
) -> RankedItem:
    pmfs, failed = _forecasts(ws, mission, item, base.with_candidate(item.candidate.stream), programs, isolation)
    ok = list(pmfs)  # in closure-hash order
    claim_by_id = {c.id: c for c in mission.claims}
    gain = 0.0
    targeted: dict[str, float] = {}
    if ok:
        w = normalized_weights(advantages.current, ok, mission.tau)
        gain = sum(
            information_gain([pmfs[p][t] for p in ok], [w[p] for p in ok]) for t in range(len(item.candidate.targets))
        )
        targeted = _targeted(claims, claim_by_id, item.candidate, pmfs, mission.tau)
    # a claim the mission does not list weighs nothing
    weighted = sum(claim_by_id[c].weight * v for c, v in targeted.items() if c in claim_by_id)
    priority = (gain + weighted) / item.cost
    return RankedItem(
        item=item.id,
        supporting=tuple(ok),
        failed=tuple(failed),
        gain=gain,
        targeted=targeted,
        priority=priority,
        cost=item.cost,
    )


def rank_wanted(
    ws: Workspace,
    mission: Mission,
    as_of: int,
    now: datetime,
    isolation: Isolation,
    advantages: Advantages,
    claims: Sequence[ClaimStanding],
) -> list[RankedItem]:
    """The mission's open wanted items, best first (priority descending, then id).

    An item is open when no archive stream `fulfills` it and its intervention starts after `as_of`.  The
    programs that bear on an item are those active at `now` (each verified against its freeze first; one
    that was modified is `failed`), not libraries, supporting the intervention and
    forecasting every candidate target.  Each runs once, in closure-hash order, under `isolation` on the
    archive as of `as_of` and published by `now`, plus the candidate arm.  A program that fails moves from
    `supporting` to `failed`; an item with no supporting program is listed with gain and priority 0.
    Weights are the programs' current advantages (`advantages.current`); `claims` are the claim standings
    whose pairs make an item more valuable.

    MissionError when `isolation` is weaker than the mission requires; WorkerError propagates.
    """
    require_isolation(mission, isolation)
    archive, registry = Archive(ws), Registry(ws)
    specs = archive.specs()
    fulfilled = {spec.fulfills for spec in specs if spec.fulfills is not None}
    open_items = [
        item
        for item in load_wanted(ws, mission.name)
        if item.id not in fulfilled and item.candidate.stream.intervention.start_week > as_of
    ]
    if not open_items:
        return []
    base = archive.view([s.id for s in mission_streams(mission, specs)], as_of, now)
    programs: dict[str, ProgramManifest | None] = {}
    for program in sorted(registry.freezes()):
        if registry.active(program, now):
            try:
                registry.verify(program)  # a manifest edited after the freeze must not change what it supports (R8)
                programs[program] = registry.manifest(program)
            except RegistryError:  # cannot tell what it supports; it is reported failed, as `run_origin` reports it
                programs[program] = None
    ranked = [_rank_item(ws, mission, item, base, programs, isolation, advantages, claims) for item in open_items]
    return sorted(ranked, key=lambda r: (-r.priority, r.item))


def choose(ranked: Sequence[RankedItem], reserve: float, rng: np.random.Generator) -> RankedItem:
    """With probability `reserve` a uniformly random item (exploration), otherwise the first.

    One `rng.random()` is always drawn, and `rng.integers` only on the exploration branch.  ValueError
    when `ranked` is empty.
    """
    if not ranked:
        raise ValueError("there is nothing to choose from")
    if rng.random() < reserve:
        return ranked[int(rng.integers(len(ranked)))]
    return ranked[0]


def _ranking_dir(ws: Workspace, mission: str) -> Path:
    """`scores/<mission>/wanted`; MissionError for a name that is not a single real directory name."""
    if Path(mission).parts != (mission,) or set(mission) == {"."}:
        raise MissionError(f"invalid mission name {mission!r}")
    return ws.scores / mission / RANKING_DIR


def _as_of_of(filename: str) -> int | None:
    """The `as_of` a ranking file name `<as_of:05d>.json` names, or None when it is not that form."""
    stem = filename.removesuffix(_SUFFIX)
    if stem == filename:
        return None
    try:
        as_of = int(stem)
    except ValueError:
        return None
    return as_of if f"{as_of:05d}" == stem else None


def save_ranking(ws: Workspace, ranking: Ranking) -> None:
    """Write `ranking` to `scores/<mission>/wanted/<as_of:05d>.json`; WriteOnceError if it exists."""
    write_new(_ranking_dir(ws, ranking.mission) / f"{ranking.as_of:05d}{_SUFFIX}", ranking)


def load_latest_ranking(ws: Workspace, mission: str, epoch: int | None = None) -> Ranking | None:
    """The ranking with the highest `as_of`, or None when `mission` has none.

    When `epoch` is given, only rankings whose `as_of` belongs to it are considered.
    MissionError when the file holds a different mission or `as_of` than its path claims.
    """
    directory = _ranking_dir(ws, mission)
    if not directory.is_dir():
        return None
    files = {
        as_of: path
        for path in directory.iterdir()
        if path.is_file() and (as_of := _as_of_of(path.name)) is not None
    }
    if epoch is not None:
        files = {week: path for week, path in files.items() if epoch_at(ws, mission, week).epoch == epoch}
    if not files:
        return None
    as_of = max(files)
    ranking = read_model(files[as_of], Ranking)
    if (ranking.mission, ranking.as_of) != (mission, as_of):
        held = f"as_of {ranking.as_of} of {ranking.mission!r}"
        raise MissionError(f"{files[as_of]} holds {held}, not as_of {as_of} of {mission!r}")
    return ranking
