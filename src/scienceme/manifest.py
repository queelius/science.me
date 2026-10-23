"""Program manifests, closure hashing and matched pairs.

A program is a directory holding `program.json` (a `ProgramManifest`), the
entry module and a README.  Its identity is the *closure hash*: a digest of
every file in the directory.  `program.json` records the closure hash of each
import, so the hash commits to the program's whole dependency closure.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path

from pydantic import model_validator

from scienceme.model import Frozen, Intervention, StreamSpec, Target, TargetFilter, Timing
from scienceme.workspace import read_model

MANIFEST_FILE = "program.json"
_READBACK_FILE = "readback.json"
_PYCACHE = "__pycache__"


class Tag(StrEnum):
    """What a program says about a claim."""

    ASSERTS = "asserts"
    DENIES = "denies"
    UNSPECIFIED = "unspecified"


class InterfaceVar(Frozen):
    """An intervention variable the program responds to, and which mechanisms it alters."""

    variable: str
    timing: Timing
    alters: tuple[str, ...]


class PairDecl(Frozen):
    """A declared matched-pair partner for `claim`, by closure hash."""

    claim: str
    partner: str


class ProgramManifest(Frozen):
    """The contents of `program.json`.  Hashes in `imports`, `pairs` and `supersedes` are closure hashes."""

    name: str
    author_lineage: str
    entry: str = "program.py"
    library: bool = False
    imports: dict[str, str] = {}
    lens: str | None = None
    scope: TargetFilter = TargetFilter()
    interface: tuple[InterfaceVar, ...] = ()
    tags: dict[str, Tag] = {}
    pairs: tuple[PairDecl, ...] = ()
    supersedes: str | None = None

    @model_validator(mode="after")
    def _lens_is_an_import(self) -> ProgramManifest:
        if self.lens is not None and self.lens not in self.imports:
            raise ValueError(f"lens {self.lens!r} is not one of the imports {sorted(self.imports)}")
        return self


class PairError(ValueError):
    """Raised by `validate_pair` when two programs are not a matched pair for a claim."""


def load_manifest(program_dir: Path) -> ProgramManifest:
    """Read `program_dir / "program.json"`."""
    return read_model(program_dir / MANIFEST_FILE, ProgramManifest)


def closure_hash(program_dir: Path) -> str:
    """`sha256:` plus the digest of every file under `program_dir`, by relative path and content.

    `readback.json` (at the top level; it is written after freezing) and
    anything under a `__pycache__` directory are not part of the program.
    """
    if not program_dir.is_dir():
        raise FileNotFoundError(f"not a program directory: {program_dir}")
    entries = []
    for path in program_dir.rglob("*"):
        rel = path.relative_to(program_dir)
        if not path.is_file() or rel == Path(_READBACK_FILE) or _PYCACHE in rel.parts:
            continue
        entries.append([rel.as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()])
    entries.sort()
    return "sha256:" + hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode("utf-8")).hexdigest()


def supports(manifest: ProgramManifest, intervention: Intervention | None) -> bool:
    """True when the program can condition on `intervention` (always true for no intervention)."""
    return intervention is None or any(
        v.variable == intervention.variable and v.timing == intervention.timing for v in manifest.interface
    )


def in_scope(manifest: ProgramManifest, target: Target, spec: StreamSpec) -> bool:
    """True when the program should forecast `target` (of the stream `spec`): not a library, and in its scope."""
    return not manifest.library and manifest.scope.matches(target, spec)


def validate_pair(asserts: ProgramManifest, denies: ProgramManifest, claim: str) -> None:
    """Raise PairError unless the two programs differ only in their stance on `claim`.

    `asserts` must assert `claim` and `denies` must deny it; every other
    claim must be tagged identically (a missing tag is UNSPECIFIED); the scopes
    must be equal; and the lenses must be both absent or the same import.
    """
    if _tag(asserts, claim) is not Tag.ASSERTS:
        raise PairError(f"{asserts.name!r} does not assert {claim!r}")
    if _tag(denies, claim) is not Tag.DENIES:
        raise PairError(f"{denies.name!r} does not deny {claim!r}")
    for other in sorted((set(asserts.tags) | set(denies.tags)) - {claim}):
        if _tag(asserts, other) is not _tag(denies, other):
            raise PairError(f"the pair differs on claim {other!r}, not only on {claim!r}")
    if asserts.scope != denies.scope:
        raise PairError("the pair has different scopes")
    if _lens_hash(asserts) != _lens_hash(denies):
        raise PairError("the pair has different lenses")


def _tag(manifest: ProgramManifest, claim: str) -> Tag:
    return manifest.tags.get(claim, Tag.UNSPECIFIED)


def _lens_hash(manifest: ProgramManifest) -> str | None:
    return None if manifest.lens is None else manifest.imports[manifest.lens]
