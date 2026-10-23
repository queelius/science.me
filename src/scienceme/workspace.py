"""The on-disk workspace and its write-once JSON helpers.

Every persisted object is a pydantic model stored as JSON (one object per
file) or JSONL (one object per line).  Stores are append-only: `write_new`
refuses to replace a file and `append_jsonl` only ever adds lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, TypeAdapter

_ENCODING = "utf-8"


class WriteOnceError(FileExistsError):
    """Raised when a write would overwrite an existing file."""


@dataclass(frozen=True)
class Workspace:
    """Directory layout under one root."""

    root: Path

    @property
    def programs(self) -> Path:
        return self.root / "programs"

    @property
    def missions(self) -> Path:
        return self.root / "missions"

    @property
    def archive(self) -> Path:
        return self.root / "archive"

    @property
    def scores(self) -> Path:
        return self.root / "scores"

    @property
    def registry(self) -> Path:
        """The append-only freeze log."""
        return self.root / "registry" / "freezes.jsonl"

    @classmethod
    def create(cls, root: Path) -> Workspace:
        """Make the directories (idempotent) and return the workspace."""
        ws = cls(root)
        for d in (ws.programs, ws.missions, ws.archive, ws.scores, ws.registry.parent):
            d.mkdir(parents=True, exist_ok=True)
        return ws


def write_new(path: Path, model: BaseModel) -> None:
    """Write `model` as JSON to a new file, creating parents; raise WriteOnceError if `path` exists."""
    data = model.model_dump_json()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding=_ENCODING) as f:
            f.write(data)
    except FileExistsError as e:
        raise WriteOnceError(f"refusing to overwrite {path}") from e


def read_model[M: BaseModel](path: Path, cls: type[M]) -> M:
    """Read and validate one JSON model."""
    return cls.model_validate_json(path.read_text(encoding=_ENCODING))


def append_jsonl(path: Path, model: BaseModel) -> None:
    """Append `model` as one line of JSON, creating parents."""
    line = model.model_dump_json() + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding=_ENCODING) as f:
        f.write(line)


def read_jsonl[T](path: Path, adapter: TypeAdapter[T]) -> list[T]:
    """Read every line of a JSONL file through `adapter`; empty when the file is absent."""
    if not path.exists():
        return []
    with path.open(encoding=_ENCODING) as f:
        return [adapter.validate_json(line) for line in f if line.strip()]
