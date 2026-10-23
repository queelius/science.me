"""Running an origin: the prospective record for one reference week.

For each COUNT stream the mission forecasts that has a vintage at the reference week, every eligible program
is run once on the as-of view and every target gets a write-once `PredictionRecord` or `UnscoredRecord`.
A program is eligible for a stream when it was frozen strictly before that stream published the week's
vintage (`Registry.active` at the vintage's `published_at`): nothing it forecasts could have been tuned on
data published later.  The view it sees is cut at the same instant, so it holds nothing published after.

Re-running is safe.  A (stream, program) whose file exists is skipped, so a run after new freezes or new arms
writes only what is missing.  A program whose directory (or any import's) changed after freezing is skipped and
never scored under its old hash.  `WorkerError` (the sandbox could not run at all) is not a program's failure:
it propagates, the files already written stay, and a re-run fills the rest.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from scienceme.archive import Archive, ArchiveView
from scienceme.manifest import in_scope, supports
from scienceme.mission import Mission, MissionError, mission_streams
from scienceme.model import Frozen, Isolation, StreamKind
from scienceme.record import PredictionRecord, Record, RecordStore, UnscoredRecord
from scienceme.registry import Registry, RegistryError
from scienceme.worker import build_order, run_order, scorer_hash
from scienceme.worker_entry import Failure, Prediction
from scienceme.workspace import Workspace


class SkipReason(StrEnum):
    ALREADY_RECORDED = "already-recorded"
    MODIFIED_AFTER_FREEZE = "modified-after-freeze"
    OUT_OF_SCOPE = "out-of-scope"
    UNSUPPORTED_INTERVENTION = "unsupported-intervention"


class Skip(Frozen):
    """An eligible program that was not run on `stream`, and why."""

    stream: str
    program: str
    reason: SkipReason


class Run(Frozen):
    """A program that was run on `stream` and recorded `n_targets` targets."""

    stream: str
    program: str
    n_targets: int


class OriginReport(Frozen):
    """What `run_origin` did, in (stream id, closure hash) order."""

    mission: str
    reference_week: int
    ran: tuple[Run, ...]
    skipped: tuple[Skip, ...]


def _require_isolation(mission: Mission, isolation: Isolation) -> None:
    if not isolation.at_least(mission.required_isolation):
        raise MissionError(
            f"mission {mission.name!r} requires isolation {mission.required_isolation.value!r}, "
            f"not the weaker {isolation.value!r}"
        )


def _is_library(registry: Registry, program: str) -> bool:
    """True when the program's manifest says it is a library.  An unreadable manifest is not: `verify` reports it."""
    try:
        return registry.manifest(program).library
    except RegistryError:
        return False


def _records(
    mission: Mission,
    program: str,
    results: tuple[Prediction | Failure, ...],
    scorer: str,
    isolation: Isolation,
    now: datetime,
) -> list[Record]:
    """One record per result: a prediction, or an unscored record carrying the failure's error."""
    stamp = dict(mission=mission.name, program=program, scorer=scorer, isolation=isolation, recorded_at=now)
    return [
        PredictionRecord(target=r.target, pmf=r.pmf, **stamp)
        if isinstance(r, Prediction)
        else UnscoredRecord(target=r.target, reason=r.error, **stamp)
        for r in results
    ]


def run_origin(
    ws: Workspace, mission: Mission, reference_week: int, isolation: Isolation, now: datetime
) -> OriginReport:
    """Run every eligible program on every COUNT stream of `mission` that has a vintage at `reference_week`.

    MissionError when `isolation` is weaker than the mission requires.  Streams are visited by id and programs
    by closure hash.  WorkerError propagates; the files written before it stay.
    """
    _require_isolation(mission, isolation)
    archive, registry, store = Archive(ws), Registry(ws), RecordStore(ws)
    specs = mission_streams(mission, archive.specs())
    stream_ids = [s.id for s in specs]
    programs = [h for h in sorted(registry.freezes()) if not _is_library(registry, h)]
    scorer = scorer_hash()
    ran: list[Run] = []
    skipped: list[Skip] = []

    for spec in specs:
        if spec.kind is not StreamKind.COUNT:
            continue
        cutoff = archive.published_at(spec.id, reference_week)
        if cutoff is None:
            continue
        targets = mission.targets(spec, reference_week)
        view: ArchiveView | None = None
        for program in programs:
            if not registry.active(program, cutoff):
                continue
            if store.has(mission.name, spec.id, reference_week, program):
                skipped.append(Skip(stream=spec.id, program=program, reason=SkipReason.ALREADY_RECORDED))
                continue
            try:
                registry.verify(program)
                manifest = registry.manifest(program)
            except RegistryError:
                skipped.append(Skip(stream=spec.id, program=program, reason=SkipReason.MODIFIED_AFTER_FREEZE))
                continue
            if not supports(manifest, spec.intervention):
                skipped.append(Skip(stream=spec.id, program=program, reason=SkipReason.UNSUPPORTED_INTERVENTION))
                continue
            mine = [t for t in targets if in_scope(manifest, t, spec)]
            if not mine:
                skipped.append(Skip(stream=spec.id, program=program, reason=SkipReason.OUT_OF_SCOPE))
                continue
            if view is None:
                view = archive.view(stream_ids, as_of=reference_week, published_by=cutoff)
            try:
                result = run_order(ws, build_order(ws, program, view, mine), isolation, mission.run_timeout_s)
            except RegistryError:  # a member of the closure changed after freezing (R8)
                skipped.append(Skip(stream=spec.id, program=program, reason=SkipReason.MODIFIED_AFTER_FREEZE))
                continue
            records = _records(mission, program, result.results, scorer, isolation, now)
            store.write(mission.name, spec.id, reference_week, program, records)
            ran.append(Run(stream=spec.id, program=program, n_targets=len(mine)))

    return OriginReport(mission=mission.name, reference_week=reference_week, ran=tuple(ran), skipped=tuple(skipped))


def run_all(ws: Workspace, mission: Mission, isolation: Isolation, now: datetime) -> list[OriginReport]:
    """`run_origin` for every reference week from `first_issue` to `min(last_issue, latest published issue)`.

    The latest published issue is the newest capture of any COUNT stream the mission forecasts.
    """
    _require_isolation(mission, isolation)
    archive = Archive(ws)
    latest = max(
        (
            issue
            for spec in mission_streams(mission, archive.specs())
            if spec.kind is StreamKind.COUNT
            for issue in archive.issues(spec.id)
        ),
        default=None,
    )
    if latest is None:
        return []
    last = min(mission.last_issue, latest)
    return [run_origin(ws, mission, week, isolation, now) for week in range(mission.first_issue, last + 1)]
