"""Missions: the captain's standing orders, and the wanted list of arms worth observing.

A `Mission` fixes which streams are forecast, at which horizons, over which
issues, and the scoring parameters.  It is the captain's file and may be
replaced, except that a change of scoring convention (`convention_fields`) is a
new epoch: `begin_epoch` records it in the append-only `epochs.jsonl`, with its
reason and the first origin it governs, and `save_mission` refuses one made any
other way.  Each epoch is scored under its own conventions over its own origins,
so a convention changed after outcomes are seen never re-scores the old record.
The wanted list is an append-only JSONL of `WantedItem`s: arms someone would
like the custodian (or another fulfiller) to run.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path

from pydantic import Field, JsonValue, TypeAdapter, model_validator

from scienceme.model import Frozen, Isolation, StreamKind, StreamSpec, Target, TargetFilter
from scienceme.workspace import Workspace, append_jsonl, read_jsonl, read_model


class MissionError(ValueError):
    """Raised when a mission or wanted-list operation is invalid."""


class Claim(Frozen):
    """A statement the mission wants evidence on, scoped to the targets that bear on it.

    `refines` is the id of a broader claim of the same mission that this one narrows to a sub-scope (the
    same mechanism where, say, it cannot act).  Programs that differ in the mechanism differ on both, so a
    matched pair declared over the two counts for each (`claims.claim_standings`).
    """

    id: str
    statement: str
    scope: TargetFilter
    weight: float = 0.0
    refines: str | None = None


class Candidate(Frozen):
    """A proposed arm: its stream spec (with intervention and parent) and the targets on it."""

    stream: StreamSpec
    targets: tuple[Target, ...]

    @model_validator(mode="after")
    def _check_arm(self) -> Candidate:
        if self.stream.intervention is None:
            raise ValueError("a candidate stream must carry an intervention")
        stray = [t.stream for t in self.targets if t.stream != self.stream.id]
        if stray:
            raise ValueError(f"candidate targets must be on stream {self.stream.id!r}, got {stray[0]!r}")
        return self


class WantedItem(Frozen):
    """One entry of a mission's wanted list."""

    id: str
    proposed_by: str
    candidate: Candidate
    cost: float = Field(1.0, gt=0, allow_inf_nan=False)
    fulfiller: str = "custodian"


# Marks a field that decides how a forecast is scored or a claim judged (`convention_fields`).
_CONVENTION = {"convention": True}


class Mission(Frozen):
    """Standing orders for forecasting a set of streams over a span of issues.

    The fields marked as conventions decide scores and verdicts; changing one is a new epoch.  The others
    (streams, the issue window, the exploration reserve, isolation, timeout) are operational.
    """

    name: str
    epoch: int = Field(1, ge=1)
    captain: str
    streams: tuple[str, ...]
    horizons: tuple[int, ...] = Field(json_schema_extra=_CONVENTION)
    first_issue: int
    last_issue: int
    resolution_lag: int = Field(ge=1, json_schema_extra=_CONVENTION)
    epsilon: float = Field(gt=0, lt=1, json_schema_extra=_CONVENTION)
    tau: float = Field(gt=0, json_schema_extra=_CONVENTION)
    half_life_weeks: float = Field(gt=0, allow_inf_nan=False, json_schema_extra=_CONVENTION)
    coverage_min: float = Field(json_schema_extra=_CONVENTION)
    claim_threshold_nats: float = Field(json_schema_extra=_CONVENTION)
    regime_flag_tv: float = Field(json_schema_extra=_CONVENTION)
    exploration_reserve: float
    required_isolation: Isolation
    run_timeout_s: int = 300
    claims: tuple[Claim, ...] = Field((), json_schema_extra=_CONVENTION)

    @model_validator(mode="after")
    def _check_refinements(self) -> Mission:
        """Each `refines` names another claim of the mission, and no chain of them returns to where it began."""
        broader = {claim.id: claim.refines for claim in self.claims}
        for claim in self.claims:
            if claim.refines is not None and (claim.refines == claim.id or claim.refines not in broader):
                raise ValueError(f"claim {claim.id!r} refines {claim.refines!r}, not another claim of the mission")
        for claim in self.claims:
            seen = {claim.id}
            current = claim.refines
            while current is not None:
                if current in seen:
                    raise ValueError(f"claims refine one another in a cycle through {claim.id!r}")
                seen.add(current)
                current = broader[current]
        return self

    def targets(self, spec: StreamSpec, reference_week: int) -> list[Target]:
        """The targets this mission asks of `spec` at `reference_week`.

        Empty unless `spec` is a COUNT stream and the week is in the mission's
        window and the stream's own.  Jurisdictions in spec order, horizons
        ascending; an arm skips targets that fall before its intervention starts.
        """
        if spec.kind is not StreamKind.COUNT:
            return []
        if not max(self.first_issue, spec.first_issue) <= reference_week <= self.last_issue:
            return []
        candidates = (
            Target(
                stream=spec.id,
                jurisdiction=jurisdiction,
                reference_week=reference_week,
                horizon=horizon,
                resolution_lag=self.resolution_lag,
            )
            for jurisdiction in spec.jurisdictions
            for horizon in sorted(set(self.horizons))
        )
        start = spec.intervention.start_week if spec.intervention is not None else None
        return [t for t in candidates if start is None or t.target_week >= start]


class Epoch(Frozen):
    """Epoch `epoch` of a mission: its conventions govern the origins from issue `starts_at` to the next epoch's start."""

    epoch: int = Field(ge=1)
    starts_at: int
    reason: str = Field(min_length=1)
    conventions: dict[str, JsonValue]


def convention_fields() -> tuple[str, ...]:
    """The `Mission` fields that decide how a forecast is scored or a claim judged."""
    return tuple(name for name, field in Mission.model_fields.items() if field.json_schema_extra == _CONVENTION)


def conventions(mission: Mission) -> dict[str, JsonValue]:
    """`mission`'s conventions, as JSON values."""
    return mission.model_dump(mode="json", include=set(convention_fields()))


def under(mission: Mission, epoch: Epoch) -> Mission:
    """`mission` with `epoch`'s number and conventions: the mission its origins were scored under."""
    missing = sorted(set(convention_fields()) - set(epoch.conventions))
    extra = sorted(set(epoch.conventions) - set(convention_fields()))
    if missing or extra:
        raise MissionError(f"epoch {epoch.epoch}: missing conventions {missing}; extra conventions {extra}")
    return Mission.model_validate(mission.model_dump(mode="json") | epoch.conventions | {"epoch": epoch.epoch})


_WANTED = TypeAdapter(WantedItem)
_EPOCH = TypeAdapter(Epoch)
FIRST_REASON = "the mission's first conventions"


def _mission_dir(ws: Workspace, name: str) -> Path:
    return ws.missions / name


def list_missions(ws: Workspace) -> list[str]:
    """The names of the workspace's missions, sorted: the directories of `missions/` that hold a `mission.json`."""
    if not ws.missions.is_dir():
        return []
    return sorted(d.name for d in ws.missions.iterdir() if (d / "mission.json").is_file())


def load_mission(ws: Workspace, name: str) -> Mission:
    """Read `missions/<name>/mission.json`."""
    return read_model(_mission_dir(ws, name) / "mission.json", Mission)


def load_epochs(ws: Workspace, name: str) -> list[Epoch]:
    """The mission's epochs, in order (`missions/<name>/epochs.jsonl`); empty when none is recorded."""
    return read_jsonl(_mission_dir(ws, name) / "epochs.jsonl", _EPOCH)


def epoch_at(ws: Workspace, mission_name: str, reference_week: int) -> Mission:
    """The mission under the epoch governing `reference_week`; epoch 1 before the first start."""
    mission = load_mission(ws, mission_name)
    epochs = load_epochs(ws, mission_name)
    if not epochs:
        return mission
    epoch = next((e for e in reversed(epochs) if e.starts_at <= reference_week), epochs[0])
    return under(mission, epoch)


def _changed(a: Mission, b: Mission) -> list[str]:
    ours, theirs = conventions(a), conventions(b)
    return [name for name in convention_fields() if ours[name] != theirs[name]]


def save_mission(ws: Workspace, mission: Mission) -> None:
    """Write the mission file, replacing any earlier one.

    The first save records epoch 1, governing from the mission's first issue.  Later saves may change only
    operational fields: MissionError, writing nothing, when a convention or the epoch number differs from the
    latest epoch (a change of convention is `begin_epoch`'s), a stream is dropped, or a first save is not epoch 1.
    """
    if (_mission_dir(ws, mission.name) / "mission.json").is_file():
        dropped = sorted(set(load_mission(ws, mission.name).streams) - set(mission.streams))
        if dropped:
            raise MissionError(f"cannot drop {', '.join(dropped)}: a stream once scored stays scored")
    epochs = load_epochs(ws, mission.name)
    if not epochs:
        if mission.epoch != 1:
            raise MissionError(f"mission {mission.name!r} has no epochs yet, so it must be saved as epoch 1")
        append_jsonl(
            _mission_dir(ws, mission.name) / "epochs.jsonl",
            Epoch(epoch=1, starts_at=mission.first_issue, reason=FIRST_REASON, conventions=conventions(mission)),
        )
    else:
        latest = epochs[-1]
        current = under(mission, latest)
        if mission.epoch != latest.epoch or _changed(mission, current):
            changed = _changed(mission, current) or ["epoch"]
            raise MissionError(
                f"mission {mission.name!r}: changing {', '.join(changed)} is a change of scoring convention, "
                f"so it is a new epoch: use `scienceme new-epoch`"
            )
    _write(ws, mission)


def _write(ws: Workspace, mission: Mission) -> None:
    path = _mission_dir(ws, mission.name) / "mission.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mission.model_dump_json(), encoding="utf-8")


def begin_epoch(
    ws: Workspace, name: str, changes: Mapping[str, object], starts_at: int, reason: str, published: int | None
) -> Mission:
    """Start the mission's next epoch: `changes` to its conventions, governing origins from issue `starts_at`.

    `published` is the latest issue already published on the mission's streams (None for none): the new
    epoch must start after it, and after the latest epoch's start, so no origin whose data anyone has seen
    is scored under conventions chosen since.  MissionError, writing nothing, when a change is not to a
    convention, changes nothing, or the start is too early; ValueError when the changed mission is invalid.
    The epoch log is authoritative: retry an interrupted change to materialize it before starting another.
    """
    mission = load_mission(ws, name)
    epochs = load_epochs(ws, name)
    if not epochs:
        raise MissionError(f"mission {name!r} has no epoch record; save it once to record epoch 1")
    latest = epochs[-1]
    current = under(mission, latest)
    if mission.epoch != current.epoch or _changed(mission, current):
        previous = under(mission, epochs[-2]) if len(epochs) > 1 else current
        try:
            requested = Mission.model_validate(previous.model_dump(mode="json") | dict(changes) | {"epoch": latest.epoch})
        except ValueError:
            requested = None
        matches = not (set(changes) - set(convention_fields())) and requested == current
        if starts_at == latest.starts_at and reason == latest.reason and matches:
            _write(ws, current)
            return current
        raise MissionError(f"mission {name!r}: retry the interrupted change before starting another epoch")
    mission = current
    stray = sorted(set(changes) - set(convention_fields()))
    if stray:
        raise MissionError(f"{', '.join(stray)} is not a scoring convention; change it by saving the mission")
    following = Mission.model_validate(mission.model_dump(mode="json") | dict(changes) | {"epoch": latest.epoch + 1})
    if not _changed(mission, following):
        raise MissionError(f"the changes to mission {name!r} change no convention")
    if published is not None and starts_at <= published:
        raise MissionError(f"a new epoch must start after issue {published}, the latest one published")
    if starts_at <= latest.starts_at:
        raise MissionError(f"a new epoch must start after epoch {latest.epoch}'s start, issue {latest.starts_at}")
    append_jsonl(
        _mission_dir(ws, name) / "epochs.jsonl",
        Epoch(epoch=following.epoch, starts_at=starts_at, reason=reason, conventions=conventions(following)),
    )
    _write(ws, following)
    return following


def epoch_problems(ws: Workspace, name: str) -> list[str]:
    """What is wrong with the mission's epoch record: one line each; empty when the mission follows it."""
    epochs = load_epochs(ws, name)
    if not epochs:
        return [f"missions/{name}: no epochs.jsonl; save the mission once to record epoch 1"]
    found = []
    if [e.epoch for e in epochs] != list(range(1, len(epochs) + 1)):
        found.append(f"missions/{name}/epochs.jsonl: epochs are not numbered 1, 2, ...")
    if any(later.starts_at <= earlier.starts_at for earlier, later in zip(epochs, epochs[1:])):
        found.append(f"missions/{name}/epochs.jsonl: epochs do not start in increasing order")
    mission, latest = load_mission(ws, name), epochs[-1]
    for epoch in epochs:
        try:
            current = under(mission, epoch)
        except ValueError as error:
            found.append(f"missions/{name}/epochs.jsonl: epoch {epoch.epoch}: {error}")
            if epoch == latest:
                return found
    changed = _changed(mission, current)
    if changed or mission.epoch != latest.epoch:
        found.append(
            f"missions/{name}/mission.json differs from its epoch {latest.epoch} in {', '.join(changed or ['epoch'])}: "
            f"a change of convention is a new epoch (`scienceme new-epoch`)"
        )
    return found


def mission_streams(mission: Mission, specs: Iterable[StreamSpec]) -> list[StreamSpec]:
    """The specs named by the mission plus the arms whose parent it names, sorted by id."""
    wanted = set(mission.streams)
    return sorted((s for s in specs if s.id in wanted or s.parent in wanted), key=lambda s: s.id)


def load_wanted(ws: Workspace, mission: str) -> list[WantedItem]:
    """Every wanted item of `mission`, in the order appended."""
    return read_jsonl(_mission_dir(ws, mission) / "wanted.jsonl", _WANTED)


def append_wanted(ws: Workspace, mission: str, item: WantedItem) -> None:
    """Append `item` to the mission's wanted list; MissionError if its id is already there."""
    if any(existing.id == item.id for existing in load_wanted(ws, mission)):
        raise MissionError(f"wanted item {item.id!r} already exists in mission {mission!r}")
    append_jsonl(_mission_dir(ws, mission) / "wanted.jsonl", item)
