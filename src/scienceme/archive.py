"""The as-of archive: what each stream had published at a given moment.

A stream's captures live at `archive/<stream id>/<issue:05d>.json` (stream ids
contain "/", so they nest) beside its `stream.json` spec.  Captures are
write-once.  A program run for an origin sees only an `ArchiveView`, built by
`Archive.view`, which keeps the vintages with `issue <= as_of` AND
`published_at <= published_by`.  That double filter is what makes a score
prospective: nothing the program sees could have been known any later.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from scienceme.model import Capture, Frozen, Row, StreamSpec, Target, Vintage, validate_vintage
from scienceme.workspace import Workspace, WriteOnceError, read_model, write_new

_SPEC_FILE = "stream.json"
_CAPTURE_SUFFIX = ".json"


class ArchiveError(Exception):
    """Raised when the archive refuses a stream, a capture or a lookup."""


def _parse_issue(stem: str) -> int | None:
    """The issue a capture file stem names, or None when it is not the canonical `<issue:05d>` form."""
    try:
        issue = int(stem)
    except ValueError:
        return None
    return issue if f"{issue:05d}" == stem else None


class ArchiveView(Frozen):
    """The archive as of issue `as_of`: stream specs and, per stream, the visible vintages sorted by issue."""

    as_of: int
    specs: dict[str, StreamSpec]
    vintages: dict[str, tuple[Vintage, ...]]

    def spec(self, stream: str) -> StreamSpec:
        """The spec of `stream`; ArchiveError when the view does not contain it."""
        try:
            return self.specs[stream]
        except KeyError:
            raise ArchiveError(f"unknown stream {stream!r}") from None

    def history(self, stream: str) -> tuple[Vintage, ...]:
        """Every visible vintage of `stream`, oldest issue first; empty when it has none."""
        return self.vintages.get(stream, ())

    def latest(self, stream: str) -> tuple[Row, ...]:
        """The rows of the newest visible vintage; empty when `stream` has none."""
        history = self.history(stream)
        return history[-1].rows if history else ()

    def series(self, stream: str, jurisdiction: str) -> list[tuple[int, float]]:
        """(week, value) pairs of `jurisdiction` from the newest visible vintage, by week."""
        return sorted((row.week, row.value) for row in self.latest(stream) if row.jurisdiction == jurisdiction)

    def find(self, world: str, role: str) -> StreamSpec | None:
        """The base stream (no intervention) of `world` with `role`; the lowest id if several, None if none."""
        matches = [s for s in self.specs.values() if s.world == world and s.role == role and s.intervention is None]
        return min(matches, key=lambda s: s.id) if matches else None

    def with_candidate(self, spec: StreamSpec) -> ArchiveView:
        """A view that also holds the candidate arm `spec`, whose history is its parent's."""
        if spec.id in self.specs:
            if self.specs[spec.id] == spec:
                return self
            raise ArchiveError(f"candidate {spec.id!r} is already in the view with a different spec")
        if spec.parent is None:
            raise ArchiveError(f"candidate {spec.id!r} has no parent to take its history from")
        if spec.parent not in self.specs:
            raise ArchiveError(f"candidate {spec.id!r}: parent {spec.parent!r} is not in the view")
        return ArchiveView(
            as_of=self.as_of,
            specs={**self.specs, spec.id: spec},
            vintages={**self.vintages, spec.id: self.history(spec.parent)},
        )


class Archive:
    """Reads and appends the workspace's archive of streams and captures."""

    def __init__(self, ws: Workspace) -> None:
        self._ws = ws

    def create_stream(self, spec: StreamSpec) -> None:
        """Record `spec`.  The same spec again is a no-op; a different spec under the same id raises."""
        path = self._stream_dir(spec.id) / _SPEC_FILE
        try:
            write_new(path, spec)
        except WriteOnceError:
            if read_model(path, StreamSpec) != spec:
                raise ArchiveError(f"stream {spec.id!r} already exists with a different spec") from None

    def spec(self, stream: str) -> StreamSpec:
        """The spec of `stream`; ArchiveError when it has not been created."""
        path = self._stream_dir(stream) / _SPEC_FILE
        if not path.is_file():
            raise ArchiveError(f"unknown stream {stream!r}")
        return read_model(path, StreamSpec)

    def specs(self) -> list[StreamSpec]:
        """Every stream spec, at any depth of the archive, sorted by id."""
        found = (read_model(path, StreamSpec) for path in self._ws.archive.rglob(_SPEC_FILE) if path.is_file())
        return sorted(found, key=lambda spec: spec.id)

    def add(self, capture: Capture) -> None:
        """Store `capture` under its stream and issue; an unknown stream, malformed vintage or repeated issue raises."""
        vintage = capture.vintage
        validate_vintage(self.spec(vintage.stream), vintage)
        try:
            write_new(self._capture_path(vintage.stream, vintage.issue), capture)
        except WriteOnceError:
            raise ArchiveError("issue already captured; source corrections are a tier 2 feature") from None

    def issues(self, stream: str) -> list[int]:
        """The captured issues of `stream`, ascending; empty when it has none."""
        directory = self._stream_dir(stream)
        if not directory.is_dir():
            return []
        stems = [
            p.name.removesuffix(_CAPTURE_SUFFIX)
            for p in directory.iterdir()
            if p.is_file() and p.name.endswith(_CAPTURE_SUFFIX) and p.name != _SPEC_FILE
        ]
        parsed = {stem: _parse_issue(stem) for stem in stems}
        stray = sorted(stem for stem, issue in parsed.items() if issue is None)
        if stray:
            raise ArchiveError(f"unexpected files in the archive directory of {stream!r}: {stray}")
        return sorted(issue for issue in parsed.values() if issue is not None)

    def published_at(self, stream: str, issue: int) -> datetime | None:
        """When issue `issue` of `stream` was published, or None if it was not captured."""
        capture = self._capture(stream, issue)
        return None if capture is None else capture.published_at

    def view(self, streams: Iterable[str], as_of: int, published_by: datetime) -> ArchiveView:
        """What `streams` showed as of issue `as_of`, counting only captures published at or before `published_by`."""
        if published_by.utcoffset() is None:
            raise ArchiveError("published_by must be timezone-aware")
        specs: dict[str, StreamSpec] = {}
        vintages: dict[str, tuple[Vintage, ...]] = {}
        for stream in streams:
            specs[stream] = self.spec(stream)
            captures = (self._load(stream, issue) for issue in self.issues(stream) if issue <= as_of)
            vintages[stream] = tuple(c.vintage for c in captures if c.published_at <= published_by)
        return ArchiveView(as_of=as_of, specs=specs, vintages=vintages)

    def realized(self, target: Target) -> int | None:
        """The value the resolution vintage reports for `target`; None while that vintage or row is absent."""
        capture = self._capture(target.stream, target.resolution_issue)
        if capture is None:
            return None
        for row in capture.vintage.rows:
            if row.jurisdiction == target.jurisdiction and row.week == target.target_week:
                if not row.value.is_integer():
                    raise ArchiveError(f"realized value {row.value!r} for {target} is not an integer")
                return int(row.value)
        return None

    def _stream_dir(self, stream: str) -> Path:
        """`archive/<stream>`; the id's "/" segments are directories.  Ids that could leave the archive are refused."""
        segments = stream.split("/")
        if any(not segment or set(segment) == {"."} for segment in segments):
            raise ArchiveError(f"invalid stream id {stream!r}")
        return self._ws.archive.joinpath(*segments)

    def _capture_path(self, stream: str, issue: int) -> Path:
        return self._stream_dir(stream) / f"{issue:05d}{_CAPTURE_SUFFIX}"

    def _capture(self, stream: str, issue: int) -> Capture | None:
        return self._load(stream, issue) if self._capture_path(stream, issue).is_file() else None

    def _load(self, stream: str, issue: int) -> Capture:
        """Read a capture that must exist, checking that the file holds the vintage its name claims."""
        path = self._capture_path(stream, issue)
        capture = read_model(path, Capture)
        if capture.vintage.stream != stream or capture.vintage.issue != issue:
            held = f"issue {capture.vintage.issue} of {capture.vintage.stream!r}"
            raise ArchiveError(f"{path} holds {held}, not issue {issue} of {stream!r}")
        return capture
