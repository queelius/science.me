"""The data model every other module builds on: streams, vintages, captures, targets.

A *stream* is a time series published weekly.  Each publication (an *issue*)
is a `Vintage`: every row the stream shows as of that issue, so later issues
may revise earlier weeks.  A `Capture` pins a vintage to its publication time
and a content hash.  A `Target` names one future value of a COUNT stream.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator


class Frozen(BaseModel):
    """Base of every persisted object: immutable, no unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class ModelError(ValueError):
    """Raised by `validate_vintage` when a vintage does not fit its stream spec."""


class Isolation(StrEnum):
    """How strongly a program is isolated; members are declared in increasing strength."""

    NONE = "none"
    PROCESS = "process"
    CONTAINER = "container"

    def at_least(self, other: Isolation) -> bool:
        """True when `self` is at least as strong as `other`."""
        order = tuple(type(self))
        return order.index(self) >= order.index(other)


class Timing(StrEnum):
    START_OF_WEEK = "start_of_week"


class Intervention(Frozen):
    """A change imposed on a stream's world from `start_week` (and through `end_week`, inclusive, when given)."""

    variable: str
    value: float
    start_week: int
    end_week: int | None = None
    jurisdictions: tuple[str, ...] | None = None
    timing: Timing = Timing.START_OF_WEEK

    def active(self, week: int, jurisdiction: str) -> bool:
        """True when the intervention applies in `jurisdiction` during `week`."""
        if week < self.start_week or (self.end_week is not None and week > self.end_week):
            return False
        return self.jurisdictions is None or jurisdiction in self.jurisdictions


class StreamKind(StrEnum):
    COUNT = "count"
    COVARIATE = "covariate"


# One or more path segments of [a-z0-9.~-] joined by "/"; a stream id becomes a directory path.
_STREAM_ID_PATTERN = r"^[a-z0-9.~-]+(/[a-z0-9.~-]+)*$"


class StreamSpec(Frozen):
    """What a stream is.  An *arm* is a COUNT stream with an `intervention` and a `parent`."""

    id: str = Field(pattern=_STREAM_ID_PATTERN)
    world: str
    role: str
    kind: StreamKind
    jurisdictions: tuple[str, ...]
    support_max: int | None = None
    intervention: Intervention | None = None
    parent: str | None = None
    first_issue: int = 0
    fulfills: str | None = None

    @field_validator("id")
    @classmethod
    def _no_dot_segments(cls, v: str) -> str:
        if any(set(seg) == {"."} for seg in v.split("/")):
            raise ValueError("stream id segments must not consist only of dots")
        return v

    @model_validator(mode="after")
    def _check_kind_fields(self) -> StreamSpec:
        if self.kind is StreamKind.COUNT and (self.support_max is None or self.support_max < 0):
            raise ValueError("a COUNT stream needs support_max >= 0")
        if self.intervention is not None and self.parent is None:
            raise ValueError("a stream with an intervention needs a parent")
        return self


class Row(Frozen):
    """One value of one jurisdiction-week."""

    jurisdiction: str
    week: int
    value: float = Field(allow_inf_nan=False)


class Vintage(Frozen):
    """Everything stream `stream` shows as of issue `issue`."""

    stream: str
    issue: int
    rows: tuple[Row, ...]


def _digest(vintage: Vintage) -> str:
    return "sha256:" + hashlib.sha256(vintage.model_dump_json().encode("utf-8")).hexdigest()


class Capture(Frozen):
    """A vintage as published at `published_at`, with the content hash of the vintage."""

    vintage: Vintage
    published_at: AwareDatetime
    source: str
    sha256: str

    @model_validator(mode="after")
    def _check_hash(self) -> Capture:
        if self.sha256 != _digest(self.vintage):
            raise ValueError("sha256 does not match the vintage content")
        return self

    @classmethod
    def make(cls, vintage: Vintage, published_at: datetime, source: str) -> Capture:
        """Capture `vintage`, computing its hash."""
        return cls(vintage=vintage, published_at=published_at, source=source, sha256=_digest(vintage))


class Target(Frozen):
    """One future value to forecast: `horizon` weeks past `reference_week`, as reported `resolution_lag` weeks later."""

    stream: str
    jurisdiction: str
    reference_week: int
    horizon: int = Field(ge=0)
    resolution_lag: int = Field(default=1, ge=1)

    @property
    def target_week(self) -> int:
        return self.reference_week + self.horizon

    @property
    def resolution_issue(self) -> int:
        """The issue whose vintage resolves this target."""
        return self.target_week + self.resolution_lag


class TargetFilter(Frozen):
    """Selects targets; a field left as None matches anything."""

    streams: tuple[str, ...] | None = None
    roles: tuple[str, ...] | None = None
    jurisdictions: tuple[str, ...] | None = None
    horizons: tuple[int, ...] | None = None

    def matches(self, target: Target, spec: StreamSpec) -> bool:
        """True when `target` (a target of the stream described by `spec`) passes every restriction."""
        return all(
            allowed is None or got in allowed
            for allowed, got in (
                (self.streams, target.stream),
                (self.roles, spec.role),
                (self.jurisdictions, target.jurisdiction),
                (self.horizons, target.horizon),
            )
        )


def validate_vintage(spec: StreamSpec, vintage: Vintage) -> None:
    """Raise ModelError unless `vintage` is a well-formed publication of the stream `spec`."""
    if vintage.stream != spec.id:
        raise ModelError(f"vintage is for stream {vintage.stream!r}, spec is {spec.id!r}")
    seen: set[tuple[str, int]] = set()
    for row in vintage.rows:
        if row.jurisdiction not in spec.jurisdictions:
            raise ModelError(f"unknown jurisdiction {row.jurisdiction!r} for stream {spec.id!r}")
        key = (row.jurisdiction, row.week)
        if key in seen:
            raise ModelError(f"duplicate row for {key} in stream {spec.id!r}")
        seen.add(key)
        if spec.kind is StreamKind.COUNT:
            _validate_count_row(spec, vintage, row)


def _validate_count_row(spec: StreamSpec, vintage: Vintage, row: Row) -> None:
    where = f"{spec.id!r} issue {vintage.issue} {row.jurisdiction!r} week {row.week}"
    if row.week >= vintage.issue:
        raise ModelError(f"{where}: a count for week {row.week} cannot be published in issue {vintage.issue}")
    if not row.value.is_integer():
        raise ModelError(f"{where}: count {row.value!r} is not integer-valued")
    if not 0 <= row.value <= spec.support_max:
        raise ModelError(f"{where}: count {row.value!r} outside [0, {spec.support_max}]")
