"""Read-back: the platform's text audit of what a program's code literally assumes.

A reader of a different model lineage is given the program's code and its
imports, but not what the author claimed about it (README, tags, pairs,
interface).  The reader writes a `Readback`; `flags` then compares it with the
author's manifest, so disagreement is found mechanically rather than by a
second reading.  The packet handed to the reader must therefore be blind.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from enum import StrEnum
from itertools import groupby
from pathlib import Path

from scienceme.manifest import MANIFEST_FILE, READBACK_FILE, ProgramManifest, Tag, program_files
from scienceme.mission import Claim
from scienceme.model import Frozen
from scienceme.registry import Registry
from scienceme.worker_entry import program_dirname
from scienceme.workspace import Workspace, read_model

_README_STEM = "readme"
# The extensions of a README that is prose (lowercased; "" for none).  A file named like a README with any
# other extension (`readme.py`) is code, and the reader sees it.
_README_SUFFIXES = frozenset({"", ".md", ".markdown", ".txt", ".rst"})
_LABEL_HEX = 12
# The only manifest fields the reader sees.  An allowlist, so a field added to the manifest later (a name, a
# stance, a note) stays hidden until someone decides the reader should see it.
_SHOWN_MANIFEST_FIELDS = frozenset({"entry", "library", "imports", "lens", "scope"})

_PREAMBLE = """\
# Read-back packet

You are an independent reader. Below is the source of a forecasting program and of
every program it imports, followed by the claims the mission wants evidence on. You
are deliberately not told what the program's author says about it, and the programs
are labelled by a digest of their content, not by name. Judge what the code does and
report what it literally assumes. Disregard comments, docstrings and names as
claims: they are what someone says the code does, not what it does.

{subject}

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
    program's author; comparing the lineage's family with the program's own is how a same-lineage read is
    caught.
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


def lineage_family(lineage: str) -> str:
    """The family of a `vendor/family` lineage: its first `/`-separated segment, trimmed and lowercased.

    `anthropic`, `Anthropic/claude` and `anthropic/opus` are one family: a reader from the author's vendor is
    not independent of the author, whatever model name follows.
    """
    return lineage.split("/", 1)[0].strip().lower()


def flags(manifest: ProgramManifest, readback: Readback | None) -> frozenset[ReadbackFlag]:
    """The flags raised by comparing `readback` with the author's `manifest`; `{MISSING}` when there is no read-back.

    The reader's lineage is compared with the author's by family (`lineage_family`).  Tags are compared over
    every claim either side names (a claim without a tag is UNSPECIFIED), and the interface as the set of
    variable names.
    """
    if readback is None:
        return frozenset({ReadbackFlag.MISSING})
    raised: set[ReadbackFlag] = set()
    if lineage_family(readback.author_lineage) == lineage_family(manifest.author_lineage):
        raised.add(ReadbackFlag.SAME_LINEAGE)
    claims = manifest.tags.keys() | readback.inferred_tags.keys()
    if any(
        manifest.tags.get(c, Tag.UNSPECIFIED) != readback.inferred_tags.get(c, Tag.UNSPECIFIED) for c in claims
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
    Programs are labelled by the first 12 hex digits of their closure hash, never by name, since a name can
    encode the author's stance.  README files in prose (stem `readme` in any case, no extension or `.md`,
    `.markdown`, `.txt` or `.rst`, at any depth) and `readback.json` are left out; each `program.json` is
    shown through an allowlist (`entry`, `library`, `imports`, `lens`, `scope`), so the name, lineage, tags,
    pairs, interface and `supersedes` are hidden; a file that is not UTF-8 text is shown as its size and
    sha256.  Every member of the closure is verified first
    (RegistryError when one is modified, unfrozen or unreadable).  Deterministic.
    """
    registry = Registry(ws)
    members = registry.closure(program)
    for member in members:
        registry.verify(member)
    subject = f"The program under review is {_label(program)}; the other programs are its imports."
    sections = [_PREAMBLE.format(subject=subject), *(_program_section(registry, member) for member in members)]
    sections.append("## Claims\n\n" + "\n".join(f"- {c.id}: {c.statement}" for c in claims) + "\n")
    schema = json.dumps(Readback.model_json_schema(), sort_keys=True, indent=2)
    sections.append("## Readback schema\n\n" + _fenced(schema))
    return "\n".join(sections)


def _label(closure_hash: str) -> str:
    """The neutral, content-derived label of a program: the first 12 hex digits of its closure hash."""
    return program_dirname(closure_hash)[:_LABEL_HEX]


def _program_section(registry: Registry, closure_hash: str) -> str:
    """One program's files (see `packet`), as text under its label."""
    program_dir = registry.program_dir(closure_hash)
    manifest = registry.manifest(closure_hash)
    label = _label(closure_hash)
    parts = [f"## Program {label}\n"]
    for rel in program_files(program_dir):
        if _is_readme(rel):
            continue
        if rel == Path(MANIFEST_FILE):
            body = _fenced(manifest.model_dump_json(include=_SHOWN_MANIFEST_FIELDS, indent=2))
        else:
            body = _file_body(program_dir / rel)
        parts.append(f"### {label}/{rel.as_posix()}\n{body}")
    return "\n".join(parts)


def _is_readme(rel: Path) -> bool:
    """True for a README in prose: stem `readme` and a prose extension (`_README_SUFFIXES`), in any case."""
    return rel.stem.lower() == _README_STEM and rel.suffix.lower() in _README_SUFFIXES


def _file_body(path: Path) -> str:
    """The file's text in a code fence, or one line with its size and sha256 when it is not UTF-8 text."""
    data = path.read_bytes()
    try:
        return _fenced(data.decode("utf-8"))
    except UnicodeDecodeError:
        return f"(binary file, {len(data)} bytes, sha256 {hashlib.sha256(data).hexdigest()})\n"


def _fenced(text: str) -> str:
    """`text` in a Markdown code fence longer than any run of backticks inside it."""
    longest = max((len(list(run)) for char, run in groupby(text) if char == "`"), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}\n{text.rstrip('\n')}\n{fence}\n"
