"""Scoring: turn stored forecasts into floored log scores once their targets resolve.

A target resolves when its resolution issue is at or before `as_of` and that
issue's vintage holds the target's row.  Until then every forecast of it is
*pending*: counted, never scored (a missing value is not a zero).  Scores use
the floored distribution `(1 - eps) * pmf + eps * Uniform{0..support_max}`, with
`eps` the mission's and `support_max` the stream's.
"""

from __future__ import annotations

from collections import Counter

from pydantic import field_validator

from scienceme.archive import Archive
from scienceme.mission import Mission
from scienceme.model import Frozen, Target
from scienceme.pmf import Pmf, floored_cdf, floored_log_prob
from scienceme.record import PredictionRecord, RecordStore
from scienceme.workspace import Workspace


class PointScore(Frozen):
    """One forecast against its realized value `y`, all under the floored distribution.

    `log_p` is log P(Y = y) in nats, `cdf_below` is P(Y < y) and `cdf_at` is P(Y <= y).
    """

    log_p: float
    cdf_below: float
    cdf_at: float


def point_score(pmf: Pmf, y: int, eps: float, support_max: int) -> PointScore:
    """Score `pmf` against the realized value `y` under the floor `eps` on `{0..support_max}`."""
    return PointScore(
        log_p=floored_log_prob(pmf, y, eps, support_max),
        cdf_below=floored_cdf(pmf, y - 1, eps, support_max),
        cdf_at=floored_cdf(pmf, y, eps, support_max),
    )


def target_order(target: Target) -> tuple[int, str, str, int]:
    """The order targets are scored and mixed in: reference week, stream, jurisdiction, horizon."""
    return (target.reference_week, target.stream, target.jurisdiction, target.horizon)


class ResolvedTarget(Frozen):
    """A target with its realized value and the score of every program that forecast it."""

    target: Target
    realized: int
    scores: dict[str, PointScore]

    @field_validator("scores")
    @classmethod
    def _some_score(cls, v: dict[str, PointScore]) -> dict[str, PointScore]:
        if not v:
            raise ValueError("a resolved target needs at least one score")
        return v


class Resolution(Frozen):
    """A mission's record as of an issue.

    `resolved` is sorted by `target_order`.  `pending` counts prediction records whose target has not
    resolved.  `predicted` and `unscored` count each program's prediction records (resolved or pending)
    and unscored records; both are keyed by every program with any record.  `pending_targets_by_stream`
    counts the distinct targets still pending on each stream (the unit of `resolved`, where `pending`
    counts records) and `programs_by_stream` lists, sorted, the programs with any record (prediction or
    unscored) on the stream; both are keyed by every stream with any record.
    """

    resolved: tuple[ResolvedTarget, ...]
    pending: int
    predicted: dict[str, int]
    unscored: dict[str, int]
    pending_targets_by_stream: dict[str, int] = {}
    programs_by_stream: dict[str, tuple[str, ...]] = {}


def resolve(ws: Workspace, mission: Mission, as_of: int, origins: range | None = None) -> Resolution:
    """Score every prediction record of `mission` whose target resolved by issue `as_of`.

    With `origins`, only the records of targets whose reference week is in it: one epoch's record.
    """
    archive = Archive(ws)
    realized: dict[Target, int | None] = {}
    support: dict[str, int] = {}
    scores: dict[Target, dict[str, PointScore]] = {}
    predicted: Counter[str] = Counter()
    unscored: Counter[str] = Counter()
    pending = 0
    pending_targets: dict[str, set[Target]] = {}
    on_stream: dict[str, set[str]] = {}
    for record in RecordStore(ws).all(mission.name):
        if origins is not None and record.target.reference_week not in origins:
            continue
        stream = record.target.stream
        on_stream.setdefault(stream, set()).add(record.program)
        pending_targets.setdefault(stream, set())
        if not isinstance(record, PredictionRecord):
            unscored[record.program] += 1
            continue
        predicted[record.program] += 1
        target = record.target
        if target not in realized:
            realized[target] = archive.realized(target) if target.resolution_issue <= as_of else None
        y = realized[target]
        if y is None:
            pending += 1
            pending_targets[stream].add(target)
            continue
        if target.stream not in support:
            support[target.stream] = archive.spec(target.stream).support_max
        scores.setdefault(target, {})[record.program] = point_score(
            record.pmf, y, mission.epsilon, support[target.stream]
        )
    resolved = tuple(
        ResolvedTarget(target=t, realized=realized[t], scores=scores[t]) for t in sorted(scores, key=target_order)
    )
    programs = sorted(predicted.keys() | unscored.keys())
    return Resolution(
        resolved=resolved,
        pending=pending,
        predicted={p: predicted[p] for p in programs},
        unscored={p: unscored[p] for p in programs},
        pending_targets_by_stream={s: len(pending_targets[s]) for s in sorted(pending_targets)},
        programs_by_stream={s: tuple(sorted(on_stream[s])) for s in sorted(on_stream)},
    )
