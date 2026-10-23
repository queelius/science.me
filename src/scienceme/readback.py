"""Read-back: the platform's text audit of what a program's code literally assumes.

A reader of a different model lineage is given the program's code and its
imports, but not what the author claimed about it (README, tags, pairs,
interface).  The reader writes a `Readback`; `flags` then compares it with the
author's manifest, so disagreement is found mechanically rather than by a
second reading.  The packet handed to the reader must therefore be blind.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from enum import StrEnum
from itertools import groupby
from pathlib import Path

from scienceme.manifest import MANIFEST_FILE, READBACK_FILE, ProgramManifest, Tag, program_files
from scienceme.mission import Claim
from scienceme.model import Frozen
from scienceme.registry import Registry
from scienceme.workspace import Workspace, read_model

README_FILE = "README.md"
# The manifest fields in which the author says what the program claims; the reader must not see them.
_AUTHOR_CLAIMS = frozenset({"tags", "pairs", "interface"})

_PREAMBLE = """\
# Read-back packet

You are an independent reader. Below is the source of a forecasting program and of
every program it imports, followed by the claims the mission wants evidence on. You
are deliberately not told what the program's author says about it. Read the code
and report what it literally assumes.

Answer with one JSON document that conforms to the schema at the end of this
packet:

- assumptions: each assumption the code makes about the world or the data, one
  sentence each.
- inferred_tags: for every claim listed below, keyed by claim id, whether the code
  asserts the claim, denies it, or says nothing about it (unspecified).
- inferred_interface: the names of the intervention variables the code responds to.
- summary: a short plain description of what the program does.
- author_lineage and author_agent: the model lineage and the agent name of you, the
  reader (not of the program's author).
- captain_verdict: leave it as "pending"; the captain sets it.
"""


class CaptainVerdict(StrEnum):
    """The captain's judgement of whether the read-back agrees with what the author claimed."""

    PENDING = "pending"
    MATCHES = "matches"
    MISMATCH = "mismatch"


class Readback(Frozen):
    """What an independent reader says a program assumes.

    `author_lineage` and `author_agent` identify the *reader* (the author of this read-back), not the
    program's author; comparing the lineage with the program's own is how a same-lineage read is caught.
    """

    author_lineage: str
    author_agent: str
    assumptions: tuple[str, ...]
    inferred_tags: dict[str, Tag]
    inferred_interface: tuple[str, ...]
    summary: str
    captain_verdict: CaptainVerdict = CaptainVerdict.PENDING


class ReadbackFlag(StrEnum):
    """A reason to doubt, or to still check, a program's read-back."""

    MISSING = "missing"
    SAME_LINEAGE = "same-lineage"
    TAG_MISMATCH = "tag-mismatch"
    INTERFACE_MISMATCH = "interface-mismatch"
    CAPTAIN_MISMATCH = "captain-mismatch"
    PENDING = "pending"


class ReadbackError(ValueError):
    """Raised by `load_readback` when `readback.json` exists but cannot be read or is invalid."""


def load_readback(program_dir: Path) -> Readback | None:
    """Read `program_dir / "readback.json"`: None when there is none, ReadbackError when it is present but invalid."""
    path = program_dir / READBACK_FILE
    try:
        return read_model(path, Readback)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        raise ReadbackError(f"{path}: invalid read-back: {e}") from e


def flags(manifest: ProgramManifest, readback: Readback | None) -> frozenset[ReadbackFlag]:
    """The flags raised by comparing `readback` with the author's `manifest`; `{MISSING}` when there is no read-back.

    Tags are compared over every claim either side names (a claim without a tag is UNSPECIFIED), and the
    interface as the set of variable names.
    """
    if readback is None:
        return frozenset({ReadbackFlag.MISSING})
    raised: set[ReadbackFlag] = set()
    if readback.author_lineage == manifest.author_lineage:
        raised.add(ReadbackFlag.SAME_LINEAGE)
    claims = manifest.tags.keys() | readback.inferred_tags.keys()
    if any(
        manifest.tags.get(c, Tag.UNSPECIFIED) is not readback.inferred_tags.get(c, Tag.UNSPECIFIED) for c in claims
    ):
        raised.add(ReadbackFlag.TAG_MISMATCH)
    if set(readback.inferred_interface) != {v.variable for v in manifest.interface}:
        raised.add(ReadbackFlag.INTERFACE_MISMATCH)
    match readback.captain_verdict:
        case CaptainVerdict.PENDING:
            raised.add(ReadbackFlag.PENDING)
        case CaptainVerdict.MISMATCH:
            raised.add(ReadbackFlag.CAPTAIN_MISMATCH)
    return frozenset(raised)


def packet(ws: Workspace, program: str, claims: Sequence[Claim]) -> str:
    """The text handed to the reading agent for the frozen program `program` (a closure hash).

    It holds the source of every program in the closure, imports first and `program` last, each file under a
    heading naming the program and the file, then the claims (id and statement) and the `Readback` schema.
    `README.md` and `readback.json` are left out, and each `program.json` is shown without the fields in
    which the author states what the program claims (`tags`, `pairs`, `interface`).  Every member of the
    closure is verified first (RegistryError when one is modified, unfrozen or unreadable).  Deterministic.
    """
    registry = Registry(ws)
    members = registry.closure(program)
    for member in members:
        registry.verify(member)
    sections = [_PREAMBLE, *(_program_section(registry, member) for member in members)]
    sections.append("## Claims\n\n" + "\n".join(f"- {c.id}: {c.statement}" for c in claims) + "\n")
    schema = json.dumps(Readback.model_json_schema(), sort_keys=True, indent=2)
    sections.append("## Readback schema\n\n" + _fenced(schema))
    return "\n".join(sections)


def _program_section(registry: Registry, closure_hash: str) -> str:
    """One program's name and its files (see `packet`), as text."""
    program_dir = registry.program_dir(closure_hash)
    manifest = registry.manifest(closure_hash)
    name = manifest.name
    parts = [f"## Program {name}\n"]
    for rel in program_files(program_dir):
        if rel.name == README_FILE:
            continue
        if rel == Path(MANIFEST_FILE):
            content = manifest.model_dump_json(exclude=_AUTHOR_CLAIMS, indent=2)
        else:
            content = (program_dir / rel).read_text(encoding="utf-8", errors="replace")
        parts.append(f"### {name}/{rel.as_posix()}\n{_fenced(content)}")
    return "\n".join(parts)


def _fenced(text: str) -> str:
    """`text` in a Markdown code fence longer than any run of backticks inside it."""
    longest = max((len(list(run)) for char, run in groupby(text) if char == "`"), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text.rstrip('\n')}\n{fence}\n"
