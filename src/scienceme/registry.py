"""The freeze registry: the platform's append-only record of when each program's closure was frozen.

A program may be scored only for origins published after it was frozen, so
`Registry.active` is the platform's eligibility test.  The registry is a JSONL
log of `Freeze` and `Withdrawal` entries that only ever grows; a withdrawal
ends a program's eligibility without erasing its freeze.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from scienceme.manifest import (
    ClosureError,
    PairDecl,
    PairError,
    ProgramManifest,
    Tag,
    closure_hash as hash_directory,
    load_manifest,
    validate_pair,
)
from scienceme.model import Frozen
from scienceme.workspace import Workspace, append_jsonl, read_jsonl


class Freeze(Frozen):
    """Program `name` was frozen at `frozen_at` with closure hash `closure_hash`."""

    kind: Literal["freeze"] = "freeze"
    name: str
    closure_hash: str
    frozen_at: AwareDatetime


class Withdrawal(Frozen):
    """The frozen program `closure_hash` stopped being eligible at `at`."""

    kind: Literal["withdraw"] = "withdraw"
    closure_hash: str
    at: AwareDatetime
    reason: str


class RegistryError(Exception):
    """Raised when a freeze, withdrawal or verification is refused."""


_ENTRIES = TypeAdapter(Annotated[Freeze | Withdrawal, Field(discriminator="kind")])


class Registry:
    """Reads and appends the workspace's freeze log."""

    def __init__(self, ws: Workspace) -> None:
        self._ws = ws

    def entries(self) -> list[Freeze | Withdrawal]:
        """Every entry, in the order it was appended."""
        return read_jsonl(self._ws.registry, _ENTRIES)

    def freezes(self) -> dict[str, Freeze]:
        """The freezes, keyed by closure hash."""
        return {e.closure_hash: e for e in self.entries() if isinstance(e, Freeze)}

    def by_name(self, name: str) -> Freeze | None:
        """The freeze recorded under `name`, if any."""
        return next((f for f in self.freezes().values() if f.name == name), None)

    def program_dir(self, closure_hash: str) -> Path:
        """The directory of the frozen program `closure_hash`."""
        return self._ws.programs / self._frozen(closure_hash).name

    def manifest(self, closure_hash: str) -> ProgramManifest:
        """The manifest of the frozen program, as currently on disk (call `verify` to know it is unmodified)."""
        return load_manifest(self.program_dir(closure_hash))

    def freeze(self, name: str, now: datetime) -> Freeze:
        """Freeze `programs/<name>` at `now` and return the record.

        Re-freezing unchanged content returns the existing record.  Every
        refusal is a RegistryError; nothing is appended unless all checks pass.
        """
        if Path(name).parts != (name,) or name == "..":
            raise RegistryError(f"{name!r} is not a single directory name")
        program_dir = self._ws.programs / name
        try:
            manifest = load_manifest(program_dir)
        except (OSError, ValueError) as e:
            raise RegistryError(f"{name}: cannot load program.json: {e}") from e
        if manifest.name != name:
            raise RegistryError(f"program.json names {manifest.name!r}, which does not match its directory {name!r}")
        try:
            digest = hash_directory(program_dir)
        except (OSError, ClosureError) as e:
            raise RegistryError(f"{name}: cannot hash the program: {e}") from e

        frozen = self.freezes()
        existing = self.by_name(name)
        if existing is not None:
            if existing.closure_hash == digest:
                return existing
            raise RegistryError(
                f"{name!r} is already frozen with different content; the frozen closure cannot change, "
                f"so freeze the edited program under a new name"
            )
        if digest in frozen:
            raise RegistryError(f"this closure is already frozen under the name {frozen[digest].name!r}")
        for alias, dependency in manifest.imports.items():
            if dependency not in frozen:
                raise RegistryError(f"import {alias!r} ({dependency}) is not frozen")
        for decl in manifest.pairs:
            self._check_pair(manifest, decl)

        record = Freeze(name=name, closure_hash=digest, frozen_at=now)
        append_jsonl(self._ws.registry, record)
        return record

    def withdraw(self, closure_hash: str, now: datetime, reason: str) -> Withdrawal:
        """Record that the frozen program stops being eligible at `now`."""
        self._frozen(closure_hash)
        record = Withdrawal(closure_hash=closure_hash, at=now, reason=reason)
        append_jsonl(self._ws.registry, record)
        return record

    def active(self, closure_hash: str, at: datetime) -> bool:
        """True when the program was frozen strictly before `at` and not withdrawn strictly before `at`."""
        entries = self.entries()
        frozen_at = [e.frozen_at for e in entries if isinstance(e, Freeze) and e.closure_hash == closure_hash]
        if not frozen_at or not frozen_at[0] < at:
            return False
        return not any(isinstance(e, Withdrawal) and e.closure_hash == closure_hash and e.at < at for e in entries)

    def verify(self, closure_hash: str) -> None:
        """Raise RegistryError("modified-after-freeze") unless the directory still hashes to `closure_hash`."""
        program_dir = self.program_dir(closure_hash)
        try:
            current = hash_directory(program_dir)
        except (OSError, ClosureError) as e:
            raise RegistryError(f"modified-after-freeze: {program_dir.name} cannot be hashed any more: {e}") from e
        if current != closure_hash:
            raise RegistryError(
                f"modified-after-freeze: {program_dir.name} was frozen as {closure_hash} but now hashes to {current}"
            )

    def closure(self, closure_hash: str) -> list[str]:
        """The program's transitive imports first (depth first, each once), then the program itself."""
        order: list[str] = []

        def visit(h: str) -> None:
            if h in order:
                return
            for dependency in self.manifest(h).imports.values():
                visit(dependency)
            order.append(h)

        visit(closure_hash)
        return order

    def _frozen(self, closure_hash: str) -> Freeze:
        freeze = self.freezes().get(closure_hash)
        if freeze is None:
            raise RegistryError(f"{closure_hash} is not frozen")
        return freeze

    def _check_pair(self, manifest: ProgramManifest, decl: PairDecl) -> None:
        """Validate the declared pair, oriented by which side asserts `decl.claim` (R2: PairError becomes RegistryError)."""
        try:
            self.verify(decl.partner)
        except RegistryError as e:
            raise RegistryError(f"pair partner of claim {decl.claim!r}: {e}") from e
        partner = self.manifest(decl.partner)
        stance = manifest.tags.get(decl.claim, Tag.UNSPECIFIED)
        if stance is Tag.ASSERTS:
            asserts, denies = manifest, partner
        elif stance is Tag.DENIES:
            asserts, denies = partner, manifest
        else:
            raise RegistryError(f"{manifest.name!r} declares a pair on {decl.claim!r} but neither asserts nor denies it")
        try:
            validate_pair(asserts, denies, decl.claim)
        except PairError as e:
            raise RegistryError(f"{manifest.name!r} is not a matched pair with {partner.name!r}: {e}") from e
