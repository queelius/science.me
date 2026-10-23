"""Missions: the captain's standing orders, and the wanted list of arms worth observing.

A `Mission` fixes which streams are forecast, at which horizons, over which
issues, and the scoring parameters.  It is the captain's file and may be
replaced.  The wanted list is an append-only JSONL of `WantedItem`s: arms
someone would like the custodian (or another fulfiller) to run.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from pydantic import Field, TypeAdapter, model_validator

from scienceme.model import Frozen, Isolation, StreamKind, StreamSpec, Target, TargetFilter
from scienceme.workspace import Workspace, append_jsonl, read_jsonl, read_model


class MissionError(ValueError):
    """Raised when a mission or wanted-list operation is invalid."""


class Claim(Frozen):
    """A statement the mission wants evidence on, scoped to the targets that bear on it."""

    id: str
    statement: str
    scope: TargetFilter
    weight: float = 0.0


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


class Mission(Frozen):
    """Standing orders for forecasting a set of streams over a span of issues."""

    name: str
    epoch: int = 1
    captain: str
    streams: tuple[str, ...]
    horizons: tuple[int, ...]
    first_issue: int
    last_issue: int
    resolution_lag: int = Field(ge=1)
    epsilon: float = Field(gt=0, lt=1)
    tau: float = Field(gt=0)
    half_life_weeks: float = Field(gt=0, allow_inf_nan=False)
    coverage_min: float
    claim_threshold_nats: float
    regime_flag_tv: float
    exploration_reserve: float
    required_isolation: Isolation
    run_timeout_s: int = 300
    claims: tuple[Claim, ...] = ()

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


_WANTED = TypeAdapter(WantedItem)


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


def save_mission(ws: Workspace, mission: Mission) -> None:
    """Write the mission file, replacing any earlier one (it is the captain's file, not an append-only store)."""
    path = _mission_dir(ws, mission.name) / "mission.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(mission.model_dump_json(), encoding="utf-8")


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
