import pytest
from helpers import CONST, count_spec, covariate_spec, write_program
from pydantic import ValidationError

from scienceme.manifest import (
    ClosureError,
    InterfaceVar,
    PairDecl,
    PairError,
    ProgramManifest,
    Tag,
    closure_hash,
    in_scope,
    load_manifest,
    program_files,
    supports,
    validate_pair,
)
from scienceme.model import Intervention, Target, TargetFilter, Timing

LENS_HASH = "sha256:" + "1" * 64


def target(jurisdiction="A", horizon=0):
    return Target(stream="w/adm", jurisdiction=jurisdiction, reference_week=1, horizon=horizon)


def test_hash_ignores_readback_and_pycache(ws):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / "readback.json").write_text("{}")
    (d / "__pycache__").mkdir()
    (d / "__pycache__" / "x.pyc").write_bytes(b"x")
    assert closure_hash(d) == h and h.startswith("sha256:") and len(h) == 71


def test_hash_ignores_nested_pycache(ws):
    d = write_program(ws, "p", CONST)
    (d / "lib").mkdir()
    (d / "lib" / "util.py").write_text("X = 1\n")
    h = closure_hash(d)
    (d / "lib" / "__pycache__").mkdir()
    (d / "lib" / "__pycache__" / "util.cpython-313.pyc").write_bytes(b"x")
    assert closure_hash(d) == h


@pytest.mark.parametrize("edit", ["program.py", "README.md", "program.json"])
def test_hash_changes_with_any_frozen_file(ws, edit):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / edit).write_text((d / edit).read_text() + "\n")
    assert closure_hash(d) != h


def test_hash_changes_with_added_nested_file_and_with_renames(ws):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / "lib").mkdir()
    (d / "lib" / "a.py").write_text("X = 1\n")
    with_a = closure_hash(d)
    assert with_a != h
    (d / "lib" / "a.py").rename(d / "lib" / "b.py")
    assert closure_hash(d) not in (h, with_a)


def test_hash_ignores_only_the_top_level_readback(ws):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    (d / "lib").mkdir()
    (d / "lib" / "readback.json").write_text("{}")
    assert closure_hash(d) != h


def test_program_files_are_the_hashed_files_in_posix_order(ws):
    d = write_program(ws, "p", CONST)
    for rel in ("a/b.py", "a-b.py", "a.py", "lib/readback.json", "lib/__pycache__/x.pyc", "readback.json"):
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text("x")
    assert [f.as_posix() for f in program_files(d)] == [
        "README.md",
        "a-b.py",
        "a.py",
        "a/b.py",
        "lib/readback.json",
        "program.json",
        "program.py",
    ]


def test_hash_depends_on_content_not_on_directory_name_or_location(ws, tmp_path):
    a = write_program(ws, "a", CONST)
    copy = tmp_path / "elsewhere" / "b"
    copy.mkdir(parents=True)
    for f in a.iterdir():
        (copy / f.name).write_bytes(f.read_bytes())
    assert closure_hash(copy) == closure_hash(a)


def test_hash_rejects_a_symlinked_file(ws, tmp_path):
    d = write_program(ws, "p", CONST)
    outside = tmp_path / "shared.py"
    outside.write_text("X = 1\n")
    (d / "shared.py").symlink_to(outside)
    with pytest.raises(ClosureError, match="shared.py"):
        closure_hash(d)


def test_hash_rejects_a_symlinked_directory(ws, tmp_path):
    d = write_program(ws, "p", CONST)
    shared = tmp_path / "shared"
    shared.mkdir()
    (shared / "util.py").write_text("X = 1\n")
    (d / "lib").symlink_to(shared, target_is_directory=True)
    with pytest.raises(ClosureError, match="lib"):
        closure_hash(d)


def test_hash_rejects_a_nested_or_dangling_symlink(ws, tmp_path):
    d = write_program(ws, "p", CONST)
    (d / "lib").mkdir()
    (d / "lib" / "gone.py").symlink_to(tmp_path / "does-not-exist.py")
    with pytest.raises(ClosureError, match="gone.py"):
        closure_hash(d)


def test_hash_of_a_missing_directory_is_an_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        closure_hash(tmp_path / "nope")


def test_import_hashes_are_committed_through_program_json(ws):
    a = write_program(ws, "a", CONST, imports={"lens": LENS_HASH}, lens="lens")
    b = write_program(ws, "b", CONST, imports={"lens": "sha256:" + "2" * 64}, lens="lens")
    assert closure_hash(a) != closure_hash(b)


def test_manifest_round_trips_through_load_manifest(ws):
    fields = dict(
        library=False,
        imports={"lens": LENS_HASH},
        lens="lens",
        scope=TargetFilter(roles=("admissions",), horizons=(0, 1)),
        interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",)),),
        tags={"school": Tag.ASSERTS, "covariate-x": Tag.DENIES},
        pairs=(PairDecl(claim="school", partner="sha256:" + "3" * 64),),
        supersedes="sha256:" + "4" * 64,
    )
    d = write_program(ws, "p", CONST, **fields)
    m = load_manifest(d)
    assert m == ProgramManifest(name="p", author_lineage="test", **fields)
    assert m.entry == "program.py"


def test_manifest_defaults(ws):
    m = load_manifest(write_program(ws, "p", CONST))
    assert (m.entry, m.library, m.imports, m.lens) == ("program.py", False, {}, None)
    assert (m.scope, m.interface, m.tags, m.pairs, m.supersedes) == (TargetFilter(), (), {}, (), None)


def test_lens_must_be_an_import():
    with pytest.raises(ValidationError, match="lens"):
        ProgramManifest(name="p", author_lineage="t", lens="lens")
    with pytest.raises(ValidationError, match="lens"):
        ProgramManifest(name="p", author_lineage="t", imports={"other": LENS_HASH}, lens="lens")
    ProgramManifest(name="p", author_lineage="t", imports={"lens": LENS_HASH}, lens="lens")


def test_manifest_forbids_unknown_fields():
    with pytest.raises(ValidationError):
        ProgramManifest(name="p", author_lineage="t", surprise=1)


def test_supports_by_variable_and_timing():
    m = ProgramManifest(
        name="p",
        author_lineage="t",
        interface=(InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",)),),
    )
    assert supports(m, None)
    assert supports(m, Intervention(variable="schools_closed", value=1.0, start_week=3))
    assert not supports(m, Intervention(variable="vaccinate_fraction", value=0.8, start_week=3))


def test_a_program_with_no_interface_supports_only_no_intervention():
    m = ProgramManifest(name="p", author_lineage="t")
    assert supports(m, None)
    assert not supports(m, Intervention(variable="schools_closed", value=1.0, start_week=3))


def test_library_programs_are_never_in_scope():
    t = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=0)
    assert not in_scope(ProgramManifest(name="l", author_lineage="t", library=True), t, count_spec())


def test_in_scope_follows_the_scope_filter():
    m = ProgramManifest(name="p", author_lineage="t", scope=TargetFilter(jurisdictions=("A",), roles=("admissions",)))
    assert in_scope(m, target("A"), count_spec())
    assert not in_scope(m, target("B"), count_spec())
    assert not in_scope(m, target("A"), covariate_spec())
    assert in_scope(ProgramManifest(name="p", author_lineage="t"), target("B"), count_spec())


def _pair():
    a = ProgramManifest(
        name="a",
        author_lineage="t",
        imports={"lens": LENS_HASH},
        lens="lens",
        tags={"covariate-x": Tag.ASSERTS, "school": Tag.ASSERTS},
    )
    d = a.model_copy(update={"name": "d", "tags": {"covariate-x": Tag.DENIES, "school": Tag.ASSERTS}})
    return a, d


def test_validate_pair():
    a, d = _pair()
    validate_pair(a, d, "covariate-x")
    for bad in (
        a.model_copy(update={"name": "d"}),
        d.model_copy(update={"tags": {"covariate-x": Tag.DENIES, "school": Tag.DENIES}}),
        d.model_copy(update={"imports": {"lens": "sha256:" + "2" * 64}}),
        d.model_copy(update={"scope": TargetFilter(jurisdictions=("A",))}),
    ):
        with pytest.raises(PairError):
            validate_pair(a, bad, "covariate-x")


def test_validate_pair_requires_the_claim_to_be_split_the_right_way_round():
    a, d = _pair()
    with pytest.raises(PairError, match="covariate-x"):
        validate_pair(d, a, "covariate-x")
    with pytest.raises(PairError, match="covariate-x"):
        validate_pair(a, a, "covariate-x")
    unspecified = d.model_copy(update={"tags": {"school": Tag.ASSERTS}})
    with pytest.raises(PairError, match="covariate-x"):
        validate_pair(a, unspecified, "covariate-x")


def test_validate_pair_treats_a_missing_tag_as_unspecified():
    a = ProgramManifest(name="a", author_lineage="t", tags={"x": Tag.ASSERTS, "other": Tag.UNSPECIFIED})
    d = ProgramManifest(name="d", author_lineage="t", tags={"x": Tag.DENIES})
    validate_pair(a, d, "x")  # "other" is explicit UNSPECIFIED on one side, missing on the other
    with pytest.raises(PairError, match="other"):
        validate_pair(
            a.model_copy(update={"tags": {"x": Tag.ASSERTS, "other": Tag.ASSERTS}}), d, "x"
        )
    with pytest.raises(PairError, match="other"):
        validate_pair(
            a, d.model_copy(update={"tags": {"x": Tag.DENIES, "other": Tag.DENIES}}), "x"
        )


def test_validate_pair_lens_rules():
    a, d = _pair()
    bare_a = a.model_copy(update={"imports": {}, "lens": None})
    bare_d = d.model_copy(update={"imports": {}, "lens": None})
    validate_pair(bare_a, bare_d, "covariate-x")  # no lens on either side
    with pytest.raises(PairError, match="lens"):
        validate_pair(a, bare_d, "covariate-x")  # lens on one side only
    with pytest.raises(PairError, match="lens"):
        validate_pair(bare_a, d, "covariate-x")
    # The alias may differ as long as it resolves to the same hash.
    renamed = d.model_copy(update={"imports": {"other-name": LENS_HASH}, "lens": "other-name"})
    validate_pair(a, renamed, "covariate-x")
