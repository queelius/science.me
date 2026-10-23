import hashlib
import json

import pytest
from helpers import CONST, at, write_program

from scienceme.manifest import InterfaceVar, PairDecl, ProgramManifest, Tag
from scienceme.mission import Claim
from scienceme.model import TargetFilter, Timing
from scienceme.readback import (
    CaptainVerdict,
    Readback,
    ReadbackError,
    ReadbackFlag,
    flags,
    load_readback,
    packet,
)
from scienceme.registry import Registry, RegistryError

SCHOOLS = InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",))
CLAIM = Claim(id="school", statement="School terms raise transmission", scope=TargetFilter())


def readback(**overrides) -> Readback:
    fields = dict(
        author_lineage="openai",
        author_agent="codex",
        assumptions=(),
        inferred_tags={"school": Tag.ASSERTS},
        inferred_interface=("schools_closed",),
        summary="",
        captain_verdict=CaptainVerdict.MATCHES,
    )
    return Readback(**{**fields, **overrides})


def label(closure_hash: str) -> str:
    """The label a packet gives a program: the first 12 hex digits of its closure hash."""
    return closure_hash.removeprefix("sha256:")[:12]


def manifest(**overrides) -> ProgramManifest:
    fields = dict(name="p", author_lineage="anthropic", tags={"school": Tag.ASSERTS}, interface=(SCHOOLS,))
    return ProgramManifest(**{**fields, **overrides})


# ---------------------------------------------------------------- packet


def test_packet_hides_the_author_claims(ws):
    d = write_program(
        ws, "p", CONST + "# CODE-MARKER\n", tags={"school": Tag.ASSERTS}, interface=(SCHOOLS,)
    )
    (d / "README.md").write_text("SECRET-README")
    h = Registry(ws).freeze("p", at(0)).closure_hash
    text = packet(ws, h, [Claim(id="school", statement="School terms raise transmission", scope=TargetFilter())])
    assert "CODE-MARKER" in text and "School terms raise transmission" in text
    # R5: '"asserts"' would match the Tag enum in the Readback schema, so test for the manifest key instead.
    assert "SECRET-README" not in text and "schools_closed" not in text and '"tags"' not in text


def test_packet_shows_only_the_allowlisted_manifest_fields(ws):
    partner = write_program(ws, "seir-x0-s0", CONST, tags={"PARTNER-CLAIM": Tag.DENIES})
    partner_hash = Registry(ws).freeze("seir-x0-s0", at(0)).closure_hash
    d = write_program(
        ws,
        "seir-x1-s1",
        CONST,
        tags={"PARTNER-CLAIM": Tag.ASSERTS},
        pairs=(PairDecl(claim="PARTNER-CLAIM", partner=partner_hash),),
        interface=(SCHOOLS,),
        supersedes=partner_hash,
    )
    h = Registry(ws).freeze("seir-x1-s1", at(1)).closure_hash
    text = packet(ws, h, [CLAIM])
    assert partner.is_dir() and d.is_dir()
    for hidden in ("PARTNER-CLAIM", "schools_closed", partner_hash, "seir-x", '"pairs"', '"interface"', '"tags"'):
        assert hidden not in text
    for hidden_key in ('"name"', '"supersedes"'):
        assert hidden_key not in text
    shown = json.loads(_manifest_json(text, label(h)))
    assert shown == {
        "entry": "program.py",
        "library": False,
        "imports": {},
        "lens": None,
        "scope": TargetFilter().model_dump(mode="json"),
    }


def test_packet_hides_the_lineage_of_the_author(ws):
    d = write_program(ws, "p", CONST)
    manifest_file = d / "program.json"
    manifest_file.write_text(
        ProgramManifest(name="p", author_lineage="LINEAGE-MARKER").model_dump_json(), encoding="utf-8"
    )
    h = Registry(ws).freeze("p", at(0)).closure_hash
    assert "LINEAGE-MARKER" not in packet(ws, h, [CLAIM])


def test_packet_labels_programs_by_a_digest_and_never_by_name(ws):
    write_program(ws, "seir-x0-s1-lib", CONST + "# LIB\n")
    lib = Registry(ws).freeze("seir-x0-s1-lib", at(0)).closure_hash
    write_program(ws, "seir-x1-s0", CONST + "# TOP\n", imports={"core": lib})
    h = Registry(ws).freeze("seir-x1-s0", at(1)).closure_hash

    text = packet(ws, h, [CLAIM])

    assert "seir" not in text and "x1-s0" not in text
    headings = [line for line in text.splitlines() if line.startswith("## ")]
    assert headings[:2] == [f"## Program {label(lib)}", f"## Program {label(h)}"]
    assert len({label(lib), label(h)}) == 2


def test_the_preamble_names_the_program_under_review_and_tells_the_reader_to_judge_the_code(ws):
    write_program(ws, "lib", CONST)
    lib = Registry(ws).freeze("lib", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"core": lib})
    h = Registry(ws).freeze("p", at(1)).closure_hash

    text = packet(ws, h, [CLAIM])

    preamble = text.split("## Program ", 1)[0]
    assert f"The program under review is {label(h)}; the other programs are its imports." in preamble
    assert label(lib) not in preamble
    assert "Disregard comments, docstrings and names as claims" in " ".join(preamble.split())


def _manifest_json(text: str, program: str) -> str:
    """The body of the `program.json` section of the program labelled `program` in a packet."""
    heading = f"### {program}/program.json\n"
    body = text.split(heading, 1)[1]
    fence = body.split("\n", 1)[0]
    content = body.split("\n", 1)[1]
    return content.split("\n" + fence, 1)[0]


def test_packet_lists_imports_first_then_the_program_with_files_sorted_by_path(ws):
    write_program(ws, "lib", CONST + "# LIB-MARKER\n")
    lib_dir = ws.programs / "lib"
    (lib_dir / "sub").mkdir()
    (lib_dir / "sub" / "helper.py").write_text("# HELPER-MARKER\n")
    lib = Registry(ws).freeze("lib", at(0)).closure_hash
    write_program(ws, "p", CONST + "# PROGRAM-MARKER\n", imports={"core": lib})
    h = Registry(ws).freeze("p", at(1)).closure_hash

    text = packet(ws, h, [CLAIM])

    headings = [line for line in text.splitlines() if line.startswith("### ")]
    assert headings == [
        f"### {label(lib)}/program.json",
        f"### {label(lib)}/program.py",
        f"### {label(lib)}/sub/helper.py",
        f"### {label(h)}/program.json",
        f"### {label(h)}/program.py",
    ]
    assert text.index("LIB-MARKER") < text.index("HELPER-MARKER") < text.index("PROGRAM-MARKER")


def test_packet_orders_a_diamond_closure_once_each(ws):
    write_program(ws, "base", CONST + "# BASE\n")
    base = Registry(ws).freeze("base", at(0)).closure_hash
    write_program(ws, "left", CONST + "# LEFT\n", imports={"base": base})
    left = Registry(ws).freeze("left", at(0)).closure_hash
    write_program(ws, "right", CONST + "# RIGHT\n", imports={"base": base})
    right = Registry(ws).freeze("right", at(0)).closure_hash
    write_program(ws, "top", CONST + "# TOP\n", imports={"left": left, "right": right})
    top = Registry(ws).freeze("top", at(0)).closure_hash

    text = packet(ws, top, [])

    assert text.count("# BASE") == 1
    assert [text.index(f"# {m}") for m in ("BASE", "LEFT", "RIGHT", "TOP")] == sorted(
        text.index(f"# {m}") for m in ("BASE", "LEFT", "RIGHT", "TOP")
    )


def test_packet_names_the_claims_and_includes_the_readback_schema_with_sorted_keys(ws):
    write_program(ws, "p", CONST)
    h = Registry(ws).freeze("p", at(0)).closure_hash
    other = Claim(id="covariate-x", statement="Covariate x leads admissions", scope=TargetFilter())

    text = packet(ws, h, [CLAIM, other])

    assert "school: School terms raise transmission" in text
    assert "covariate-x: Covariate x leads admissions" in text
    assert text.index("school:") < text.index("covariate-x:")  # the caller's order
    schema = json.dumps(Readback.model_json_schema(), sort_keys=True, indent=2)
    assert schema in text
    assert text.rstrip().endswith("```")  # the schema is the last thing in the packet


def test_packet_is_deterministic(ws):
    write_program(ws, "p", CONST)
    h = Registry(ws).freeze("p", at(0)).closure_hash
    assert packet(ws, h, [CLAIM]) == packet(ws, h, [CLAIM])


def test_packet_leaves_out_readback_json_and_pycache(ws):
    d = write_program(ws, "p", CONST)
    (d / "sub").mkdir()
    (d / "sub" / "mod.py").write_text("# MOD\n")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "program.cpython-313.pyc").write_text("PYCACHE")
    h = Registry(ws).freeze("p", at(0)).closure_hash
    (d / "readback.json").write_text(readback().model_dump_json())  # written after freezing; not part of the hash

    text = packet(ws, h, [CLAIM])

    assert f"### {label(h)}/sub/mod.py" in text
    for absent in ("PYCACHE", "readback.json", '"author_agent": "codex"'):
        assert absent not in text


@pytest.mark.parametrize(
    "name", ["README.md", "readme.md", "Readme.TXT", "README", "README.rst", "sub/README.md", "sub/deeper/readme.rst"]
)
def test_packet_leaves_out_readme_files_in_any_case_extension_and_depth(ws, name):
    d = write_program(ws, "p", CONST)
    path = d / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("SECRET-README")
    h = Registry(ws).freeze("p", at(0)).closure_hash

    text = packet(ws, h, [CLAIM])

    assert "SECRET-README" not in text and f"{label(h)}/{name}" not in text


@pytest.mark.parametrize(
    "name", ["readme_helper.py", "notreadme.md", "docs.md", "sub/readmes.txt", "README.d/notes.md"]
)
def test_packet_shows_files_that_only_resemble_a_readme(ws, name):
    d = write_program(ws, "p", CONST)
    path = d / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("VISIBLE-FILE")
    h = Registry(ws).freeze("p", at(0)).closure_hash

    text = packet(ws, h, [CLAIM])

    assert "VISIBLE-FILE" in text and f"### {label(h)}/{name}\n" in text


def test_packet_shows_a_file_that_is_not_utf8_text_as_its_size_and_digest(ws):
    d = write_program(ws, "p", CONST)
    blob = b"\xff\xfe\x00BIN\x80"
    (d / "weights.bin").write_bytes(blob)
    h = Registry(ws).freeze("p", at(0)).closure_hash

    text = packet(ws, h, [CLAIM])

    digest = hashlib.sha256(blob).hexdigest()
    assert f"### {label(h)}/weights.bin\n(binary file, {len(blob)} bytes, sha256 {digest})\n" in text
    assert "\ufffd" not in text and "\x00" not in text and "BIN" not in text


def test_packet_survives_code_that_contains_a_markdown_fence(ws):
    write_program(ws, "p", CONST + '"""\n```\nINSIDE-FENCE\n```\n"""\n')
    h = Registry(ws).freeze("p", at(0)).closure_hash

    text = packet(ws, h, [CLAIM])

    start = text.index(f"### {label(h)}/program.py\n")
    fence = text[start:].split("\n", 2)[1]
    assert set(fence) == {"`"} and len(fence) > 3
    body = text[start:].split("\n", 2)[2]
    assert body.split("\n" + fence, 1)[0].endswith('"""')


def test_packet_refuses_a_modified_program(ws):
    d = write_program(ws, "p", CONST)
    h = Registry(ws).freeze("p", at(0)).closure_hash
    (d / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        packet(ws, h, [CLAIM])


def test_packet_refuses_a_modified_import(ws):
    lib_dir = write_program(ws, "lib", CONST)
    lib = Registry(ws).freeze("lib", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"core": lib})
    h = Registry(ws).freeze("p", at(1)).closure_hash
    (lib_dir / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        packet(ws, h, [CLAIM])


def test_packet_refuses_a_program_that_is_not_frozen(ws):
    with pytest.raises(RegistryError, match="not frozen"):
        packet(ws, "sha256:" + "0" * 64, [CLAIM])


# ---------------------------------------------------------------- load_readback


def test_load_readback_is_none_when_absent(ws):
    d = write_program(ws, "p", CONST)
    assert load_readback(d) is None


def test_load_readback_reads_a_valid_file(ws):
    d = write_program(ws, "p", CONST)
    rb = readback(captain_verdict=CaptainVerdict.PENDING, assumptions=("a weekly cycle",), summary="s")
    (d / "readback.json").write_text(rb.model_dump_json())
    assert load_readback(d) == rb


def test_load_readback_defaults_the_verdict_to_pending(ws):
    d = write_program(ws, "p", CONST)
    data = json.loads(readback().model_dump_json())
    del data["captain_verdict"]
    (d / "readback.json").write_text(json.dumps(data))
    loaded = load_readback(d)
    assert loaded is not None and loaded.captain_verdict is CaptainVerdict.PENDING


@pytest.mark.parametrize(
    "content",
    [
        "not json",
        "[]",
        '{"author_lineage": "openai"}',
        json.dumps({**json.loads(readback().model_dump_json()), "surprise": 1}),
        json.dumps({**json.loads(readback().model_dump_json()), "inferred_tags": {"school": "maybe"}}),
    ],
)
def test_load_readback_raises_a_value_error_when_invalid(ws, content):
    d = write_program(ws, "p", CONST)
    (d / "readback.json").write_text(content)
    with pytest.raises(ReadbackError, match="readback.json") as info:
        load_readback(d)
    assert isinstance(info.value, ValueError)


def test_load_readback_raises_when_the_file_cannot_be_read(ws):
    d = write_program(ws, "p", CONST)
    (d / "readback.json").mkdir()
    with pytest.raises(ReadbackError, match="readback.json"):
        load_readback(d)


def test_a_readback_file_does_not_change_the_closure_hash(ws):
    d = write_program(ws, "p", CONST)
    h = Registry(ws).freeze("p", at(0)).closure_hash
    (d / "readback.json").write_text(readback().model_dump_json())
    Registry(ws).verify(h)


# ---------------------------------------------------------------- flags


def test_flags():
    m = ProgramManifest(
        name="p",
        author_lineage="anthropic",
        tags={"school": Tag.ASSERTS},
        interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=()),),
    )
    rb = Readback(
        author_lineage="openai",
        author_agent="codex",
        assumptions=(),
        inferred_tags={"school": Tag.ASSERTS},
        inferred_interface=("schools_closed",),
        summary="",
        captain_verdict=CaptainVerdict.MATCHES,
    )
    assert flags(m, rb) == frozenset() and flags(m, None) == {ReadbackFlag.MISSING}
    assert flags(m, rb.model_copy(update={"inferred_tags": {}})) == {ReadbackFlag.TAG_MISMATCH}
    assert flags(m, rb.model_copy(update={"author_lineage": "anthropic"})) == {ReadbackFlag.SAME_LINEAGE}
    assert flags(m, rb.model_copy(update={"inferred_interface": ()})) == {ReadbackFlag.INTERFACE_MISMATCH}


def test_a_different_stance_on_a_claim_is_a_tag_mismatch():
    assert flags(manifest(), readback(inferred_tags={"school": Tag.DENIES})) == {ReadbackFlag.TAG_MISMATCH}


def test_a_claim_only_the_reader_tagged_is_a_tag_mismatch():
    rb = readback(inferred_tags={"school": Tag.ASSERTS, "covariate-x": Tag.ASSERTS})
    assert flags(manifest(), rb) == {ReadbackFlag.TAG_MISMATCH}


def test_a_claim_only_the_author_tagged_is_a_tag_mismatch():
    m = manifest(tags={"school": Tag.ASSERTS, "covariate-x": Tag.DENIES})
    assert flags(m, readback()) == {ReadbackFlag.TAG_MISMATCH}


def test_a_missing_tag_equals_unspecified_on_either_side():
    m = manifest(tags={"school": Tag.ASSERTS, "covariate-x": Tag.UNSPECIFIED})
    rb = readback(inferred_tags={"school": Tag.ASSERTS, "other": Tag.UNSPECIFIED})
    assert flags(m, rb) == frozenset()


def test_the_interface_is_compared_as_a_set_of_variable_names():
    both = (SCHOOLS, InterfaceVar(variable="vaccinate_fraction", timing=Timing.START_OF_WEEK, alters=()))
    m = manifest(interface=both)
    assert flags(m, readback(inferred_interface=("vaccinate_fraction", "schools_closed"))) == frozenset()
    duplicated = readback(inferred_interface=("schools_closed", "schools_closed", "vaccinate_fraction"))
    assert flags(m, duplicated) == frozenset()
    assert flags(m, readback(inferred_interface=("schools_closed",))) == {ReadbackFlag.INTERFACE_MISMATCH}
    assert flags(m, readback(inferred_interface=("schools_closed", "other", "vaccinate_fraction"))) == {
        ReadbackFlag.INTERFACE_MISMATCH
    }


def test_an_author_with_no_interface_matches_a_reader_who_finds_none():
    assert flags(manifest(interface=()), readback(inferred_interface=())) == frozenset()


def test_the_captain_verdict_sets_its_own_flags():
    assert flags(manifest(), readback(captain_verdict=CaptainVerdict.PENDING)) == {ReadbackFlag.PENDING}
    assert flags(manifest(), readback(captain_verdict=CaptainVerdict.MISMATCH)) == {ReadbackFlag.CAPTAIN_MISMATCH}
    assert flags(manifest(), readback(captain_verdict=CaptainVerdict.MATCHES)) == frozenset()


def test_flags_accumulate():
    rb = readback(
        author_lineage="anthropic",
        inferred_tags={},
        inferred_interface=(),
        captain_verdict=CaptainVerdict.MISMATCH,
    )
    assert flags(manifest(), rb) == {
        ReadbackFlag.SAME_LINEAGE,
        ReadbackFlag.TAG_MISMATCH,
        ReadbackFlag.INTERFACE_MISMATCH,
        ReadbackFlag.CAPTAIN_MISMATCH,
    }


def test_no_readback_means_only_missing():
    assert flags(manifest(), None) == frozenset({ReadbackFlag.MISSING})


def test_a_readback_defaults_to_a_pending_verdict():
    rb = Readback(
        author_lineage="openai",
        author_agent="codex",
        assumptions=(),
        inferred_tags={},
        inferred_interface=(),
        summary="",
    )
    assert rb.captain_verdict is CaptainVerdict.PENDING
