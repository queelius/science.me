"""The prospective record: what each program forecast, written once, before the outcome was known.

For one (mission, stream, reference week, program) the origin run writes a single file,
`scores/<mission>/<stream>/<week:05d>/<hex>.json`, holding a `PredictionRecord` or an
`UnscoredRecord` for every target the program was run on.  A file is never replaced: the
store is what makes a score depend only on a forecast made before the data existed.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from scienceme.model import Frozen, Isolation, Target
from scienceme.pmf import Pmf
from scienceme.worker_entry import program_dirname
from scienceme.workspace import Workspace, read_model, write_new

_SUFFIX = ".json"


class RecordError(ValueError):
    """Raised when a record or an id for the record store is unusable."""


class PredictionRecord(Frozen):
    """Program `program` forecast `target` with `pmf`, run under `isolation` by the scorer `scorer`."""

    kind: Literal["prediction"] = "prediction"
    mission: str
    program: str
    target: Target
    pmf: Pmf
    scorer: str
    isolation: Isolation
    recorded_at: AwareDatetime


class UnscoredRecord(Frozen):
    """Program `program` was run on `target` and produced no usable forecast; `reason` is the failure's error."""

    kind: Literal["unscored"] = "unscored"
    mission: str
    program: str
    target: Target
    reason: str
    scorer: str
    isolation: Isolation
    recorded_at: AwareDatetime


Record = Annotated[PredictionRecord | UnscoredRecord, Field(discriminator="kind")]


class RecordFile(Frozen):
    """The contents of one record file: every record of one program on one stream at one reference week."""

    records: tuple[Record, ...]


def _segments(what: str, value: str, single: bool = False) -> list[str]:
    """The "/"-separated segments of `value`; RecordError unless each is a real directory name.

    With `single`, `value` must be exactly one segment.
    """
    segments = value.split("/")
    if (single and len(segments) > 1) or any(not s or set(s) == {"."} for s in segments):
        raise RecordError(f"invalid {what} {value!r}")
    return segments


class RecordStore:
    """Reads and writes the workspace's `scores/` tree."""

    def __init__(self, ws: Workspace) -> None:
        self._ws = ws

    def path(self, mission: str, stream: str, reference_week: int, program: str) -> Path:
        """`scores/<mission>/<stream>/<week:05d>/<hex>.json`; the stream id's "/" segments are directories.

        RecordError for a mission or stream id that could leave its directory; ValueError for a malformed hash.
        """
        _segments("mission name", mission, single=True)
        segments = _segments("stream id", stream)
        filename = f"{program_dirname(program)}{_SUFFIX}"
        return self._ws.scores.joinpath(mission, *segments, f"{reference_week:05d}", filename)

    def has(self, mission: str, stream: str, reference_week: int, program: str) -> bool:
        """True when the program's records for this stream and reference week were written."""
        return self.path(mission, stream, reference_week, program).is_file()

    def write(
        self, mission: str, stream: str, reference_week: int, program: str, records: Sequence[Record]
    ) -> None:
        """Write `records` as the one file for this program, stream and reference week.

        Write-once: a second write raises `WriteOnceError`.  The records must be non-empty, all be this
        mission's and program's, be for targets of this stream and reference week, and name no target twice
        (RecordError); nothing is written otherwise.
        """
        path = self.path(mission, stream, reference_week, program)
        if not records:
            raise RecordError("a record file must hold at least one record")
        for record in records:
            target = record.target
            if (record.mission, record.program) != (mission, program):
                raise RecordError(f"record is for {record.mission!r}/{record.program}, not {mission!r}/{program}")
            if (target.stream, target.reference_week) != (stream, reference_week):
                got = f"{target.stream!r} week {target.reference_week}"
                raise RecordError(f"record is for {got}, not {stream!r} week {reference_week}")
        if len({r.target for r in records}) != len(records):
            raise RecordError("a target appears twice in one record file")
        write_new(path, RecordFile(records=tuple(records)))

    def all(self, mission: str) -> list[Record]:
        """Every record of `mission`: files in path order (stream, week, program), records in file order."""
        _segments("mission name", mission, single=True)
        root = self._ws.scores / mission
        paths = sorted(p for p in root.rglob("*" + _SUFFIX) if p.is_file())
        return [record for p in paths for record in read_model(p, RecordFile).records]
