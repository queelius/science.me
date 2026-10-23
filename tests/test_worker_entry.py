import hashlib
import importlib.util
import py_compile
import subprocess
import sys

import numpy as np
import pytest
from helpers import PER_TARGET, count_spec, covariate_spec, order, sandbox, write_program

from scienceme.archive import ArchiveView
from scienceme.manifest import ProgramManifest, closure_hash
from scienceme.model import Target
from scienceme.pmf import Pmf
from scienceme.sdk import Context, imports_of, register_imports
from scienceme.worker_entry import (
    Failure,
    Prediction,
    WorkOrder,
    WorkResult,
    derive_seed,
    execute,
    main,
    program_dirname,
)

STREAM = "w/adm"


def tgt(jurisdiction="A", horizon=0, stream=STREAM) -> Target:
    return Target(stream=stream, jurisdiction=jurisdiction, reference_week=1, horizon=horizon)


@pytest.fixture
def view() -> ArchiveView:
    return ArchiveView(as_of=3, specs={STREAM: count_spec()}, vintages={})


def run(ws, tmp_path, view, name, targets, *also):
    """Execute program `name` (after copying it and any `also` programs into a sandbox) on `targets`."""
    work = sandbox(ws, tmp_path, *also, name)
    return execute(order(ws, name, view, targets), work).results


# --- the brief's tests ---


def test_execute_returns_one_result_per_target_and_isolates_failures(ws, tmp_path, view):
    write_program(ws, "p", PER_TARGET)
    results = run(ws, tmp_path, view, "p", [tgt("A", 0), tgt("A", 1), tgt("B", 0)])
    kinds = [(r.kind, getattr(r, "pmf", None)) for r in results]
    assert kinds == [("prediction", Pmf.point(0)), ("prediction", Pmf.point(1)), ("failure", None)]
    assert [r.target for r in results] == [tgt("A", 0), tgt("A", 1), tgt("B", 0)]
    assert results[2].error == "RuntimeError: boom"


def test_imports_resolve_through_the_sdk(ws, tmp_path, view):
    write_program(ws, "core", "def level():\n    return 3\n", library=True)
    hc = closure_hash(ws.programs / "core")
    code = (
        "from scienceme.sdk import Pmf, imports_of\n"
        "IMPORTS = imports_of(__name__)\n"
        "def predict(ctx, target):\n"
        "    return Pmf.point(IMPORTS['core'].level())\n"
    )
    write_program(ws, "p", code, imports={"core": hc})
    results = run(ws, tmp_path, view, "p", [tgt()], "core")
    assert results[0].pmf == Pmf.point(3)


@pytest.mark.parametrize(
    "body,needle",
    [
        ("return Pmf.point(5000)", "support"),  # support_max is 1000
        ("return 7", "Pmf"),
        ("return Pmf.point(-1)", "support"),
    ],
)
def test_invalid_returns_fail_only_their_target(ws, tmp_path, view, body, needle):
    code = (
        "from scienceme.sdk import Pmf\n"
        "def predict(ctx, target):\n"
        f"    if target.jurisdiction == 'A':\n        {body}\n"
        "    return Pmf.point(1)\n"
    )
    write_program(ws, "p", code)
    a, b = run(ws, tmp_path, view, "p", [tgt("A"), tgt("B")])
    assert a.kind == "failure" and needle in a.error and b.kind == "prediction"


def test_load_error_fails_every_target(ws, tmp_path, view):
    write_program(ws, "p", "def predict(ctx, target:\n")
    results = run(ws, tmp_path, view, "p", [tgt("A"), tgt("B")])
    assert len(results) == 2
    assert all(r.kind == "failure" and r.error.startswith("load:") for r in results)


def test_seed_is_deterministic_and_target_specific():
    t0, t1 = (Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=h) for h in (0, 1))
    assert derive_seed("sha256:ab", t0) == derive_seed("sha256:ab", t0) != derive_seed("sha256:ab", t1)


def test_main_round_trips_files(ws, tmp_path, view):
    write_program(ws, "p", PER_TARGET)
    work = sandbox(ws, tmp_path, "p")
    out = tmp_path / "out"
    o = order(ws, "p", view, [tgt("A", 1), tgt("B", 0)])
    (work / "order.json").write_text(o.model_dump_json())
    assert main([str(work), str(out)]) == 0
    result = WorkResult.model_validate_json((out / "result.json").read_text())
    assert [r.kind for r in result.results] == ["prediction", "failure"]
    assert result.results[0].pmf == Pmf.point(1)
    assert result == execute(o, work)


# --- beyond the brief ---


def test_seed_is_the_first_eight_bytes_of_the_digest_big_endian():
    t = tgt()
    digest = hashlib.sha256(("sha256:ab" + "|" + t.model_dump_json()).encode("utf-8")).digest()
    assert derive_seed("sha256:ab", t) == int.from_bytes(digest[:8], "big")
    assert derive_seed("sha256:cd", t) != derive_seed("sha256:ab", t)


def test_ctx_rng_follows_the_derived_seed(ws, tmp_path, view):
    code = (
        "from scienceme.sdk import Pmf\n"
        "def predict(ctx, target):\n"
        "    return Pmf.point(int(ctx.rng().integers(0, 1000)))\n"
    )
    write_program(ws, "p", code)
    targets = [tgt("A", 0), tgt("A", 1)]
    first = run(ws, tmp_path, view, "p", targets)
    second = execute(order(ws, "p", view, targets), tmp_path / "work").results
    assert first == second
    h = closure_hash(ws.programs / "p")
    for target, result in zip(targets, first):
        assert result.pmf == Pmf.point(int(np.random.default_rng(derive_seed(h, target)).integers(0, 1000)))


def test_context_exposes_view_and_seed(view):
    ctx = Context(view=view, seed=5)
    assert ctx.view is view and ctx.seed == 5
    assert ctx.rng().integers(0, 10**9) == Context(view=view, seed=5).rng().integers(0, 10**9)


def test_program_sees_the_orders_view(ws, tmp_path, view):
    code = "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(ctx.view.as_of)\n"
    write_program(ws, "p", code)
    assert run(ws, tmp_path, view, "p", [tgt()])[0].pmf == Pmf.point(3)


def test_modules_are_named_after_the_hash_and_imports_are_loaded_once(ws, tmp_path, view):
    core = (
        "from pathlib import Path\n"
        "with Path(__file__).with_name('loads.txt').open('a') as f:\n    f.write('x')\n"
        "def level():\n    return 3\n"
    )
    write_program(ws, "core", core, library=True)
    hc = closure_hash(ws.programs / "core")
    mid = (
        "from scienceme.sdk import imports_of\n"
        "IMPORTS = imports_of(__name__)\n"
        "CORE = IMPORTS['c']\n"
    )
    write_program(ws, "mid", mid, library=True, imports={"c": hc})
    hm = closure_hash(ws.programs / "mid")
    prog = (
        "from scienceme.sdk import Pmf, imports_of\n"
        "IMPORTS = imports_of(__name__)\n"
        "NAME = __name__\n"
        "def predict(ctx, target):\n"
        "    shared = IMPORTS['core'] is IMPORTS['core_again'] is IMPORTS['mid'].CORE\n"
        "    raise RuntimeError(f'{NAME} {shared}')\n"
    )
    write_program(ws, "p", prog, imports={"core": hc, "core_again": hc, "mid": hm})
    hp = closure_hash(ws.programs / "p")
    work = sandbox(ws, tmp_path, "core", "mid", "p")
    (result,) = execute(order(ws, "p", view, [tgt()]), work).results
    assert result.error == f"RuntimeError: scienceme_program_{program_dirname(hp)[:16]} True"
    loads = work / "programs" / program_dirname(hc) / "loads.txt"
    assert loads.read_text() == "x"


@pytest.mark.parametrize("where", ["relative", "absolute"])
def test_entry_outside_the_program_directory_is_a_load_failure(ws, tmp_path, view, where):
    evil = tmp_path / "evil.py"
    evil.write_text("from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(1)\n")
    entry = str(evil) if where == "absolute" else "../../../evil.py"
    write_program(ws, "p", "x = 1\n", entry=entry)  # "../../../evil.py" from work/programs/<hex> is tmp_path/evil.py
    work = sandbox(ws, tmp_path, "p")
    (result,) = execute(order(ws, "p", view, [tgt()]), work).results
    assert result.kind == "failure" and result.error.startswith("load:") and "outside" in result.error


def test_entry_that_is_not_a_file_is_a_load_failure(ws, tmp_path, view):
    write_program(ws, "p", "x = 1\n", entry="missing.py")
    (result,) = run(ws, tmp_path, view, "p", [tgt()])
    assert result.kind == "failure" and result.error.startswith("load:") and "missing.py" in result.error


def test_entry_may_live_in_a_subdirectory(ws, tmp_path, view):
    d = write_program(ws, "p", "x = 1\n", entry="src/main.py")
    (d / "src").mkdir()
    (d / "src" / "main.py").write_text(
        "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(4)\n"
    )
    assert run(ws, tmp_path, view, "p", [tgt()])[0].pmf == Pmf.point(4)


def test_missing_program_directory_is_a_load_failure(ws, tmp_path, view):
    write_program(ws, "p", PER_TARGET)
    o = order(ws, "p", view, [tgt()])
    (result,) = execute(o, tmp_path / "empty-work").results
    assert result.kind == "failure" and result.error.startswith("load:")


def test_program_without_predict_is_a_load_failure(ws, tmp_path, view):
    write_program(ws, "p", "x = 1\n")
    (result,) = run(ws, tmp_path, view, "p", [tgt()])
    assert result.kind == "failure" and result.error.startswith("load:") and "predict" in result.error


def test_import_hash_absent_from_the_order_is_a_load_failure(ws, tmp_path, view):
    write_program(ws, "core", "def level():\n    return 3\n", library=True)
    hc = closure_hash(ws.programs / "core")
    code = "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(1)\n"
    write_program(ws, "p", code, imports={"core": hc})
    work = sandbox(ws, tmp_path, "core", "p")
    full = order(ws, "p", view, [tgt()])
    only_p = {full.program: full.manifests[full.program]}
    partial = WorkOrder(program=full.program, manifests=only_p, view=view, targets=full.targets)
    (result,) = execute(partial, work).results
    assert result.kind == "failure" and result.error.startswith("load:") and "manifest" in result.error


def test_failing_import_names_the_library(ws, tmp_path, view):
    write_program(ws, "core", "raise ValueError('bad core')\n", library=True)
    hc = closure_hash(ws.programs / "core")
    write_program(ws, "p", PER_TARGET, imports={"core": hc})
    (result,) = run(ws, tmp_path, view, "p", [tgt()], "core")
    assert result.error.startswith("load: core: ValueError: bad core")


def test_import_cycle_is_a_load_failure(tmp_path, view):
    ha, hb = "sha256:" + "a" * 64, "sha256:" + "b" * 64
    manifests = {
        ha: ProgramManifest(name="a", author_lineage="t", imports={"b": hb}),
        hb: ProgramManifest(name="b", author_lineage="t", imports={"a": ha}),
    }
    for h in (ha, hb):
        d = tmp_path / "work" / "programs" / program_dirname(h)
        d.mkdir(parents=True)
        (d / "program.py").write_text("x = 1\n")
    o = WorkOrder(program=ha, manifests=manifests, view=view, targets=(tgt(),))
    (result,) = execute(o, tmp_path / "work").results
    assert result.kind == "failure" and result.error.startswith("load:") and "cycle" in result.error


def test_program_hash_cannot_name_a_path_outside_programs(tmp_path, view):
    h = "sha256:../outside"
    o = WorkOrder(program=h, manifests={h: ProgramManifest(name="a", author_lineage="t")}, view=view, targets=(tgt(),))
    (result,) = execute(o, tmp_path).results
    assert result.kind == "failure" and result.error.startswith("load:")


def test_program_dirname_is_the_hex_after_the_prefix():
    assert program_dirname("sha256:" + "ab" * 32) == "ab" * 32
    for bad in ("ab" * 32, "sha256:", "sha256:../x", "sha1:abc", "sha256:ABC", "sha256:a/b"):
        with pytest.raises(ValueError):
            program_dirname(bad)


def test_a_stale_bytecode_file_is_never_run_in_place_of_the_source(ws, tmp_path, view):
    write_program(ws, "p", "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(1)\n")
    work = sandbox(ws, tmp_path, "p")
    d = next((work / "programs").iterdir())
    planted = tmp_path / "planted.py"
    planted.write_text("from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(666)\n")
    pyc = importlib.util.cache_from_source(str(d / "program.py"))
    unchecked = py_compile.PycInvalidationMode.UNCHECKED_HASH
    py_compile.compile(str(planted), cfile=pyc, doraise=True, invalidation_mode=unchecked)
    (result,) = execute(order(ws, "p", view, [tgt()]), work).results
    assert result.pmf == Pmf.point(1)


@pytest.mark.parametrize("masses", ["(float('nan'), 1.0)", "(0.5, -0.5, 1.0)", "(float('inf'), 1.0)"])
def test_a_pmf_built_around_validation_is_rejected(ws, tmp_path, view, masses):
    code = (
        "from scienceme.sdk import Pmf\n"
        "def predict(ctx, target):\n"
        f"    return Pmf.model_construct(lo=0, p={masses})\n"
    )
    write_program(ws, "p", code)
    (result,) = run(ws, tmp_path, view, "p", [tgt()])
    assert result.kind == "failure" and "Pmf" in result.error


def test_unknown_stream_fails_that_target(ws, tmp_path, view):
    write_program(ws, "p", PER_TARGET)
    a, b = run(ws, tmp_path, view, "p", [tgt("A", 0, stream="w/nope"), tgt("A", 1)])
    assert a.kind == "failure" and "w/nope" in a.error and b.kind == "prediction"


def test_target_of_a_covariate_stream_has_no_support(ws, tmp_path):
    view = ArchiveView(as_of=3, specs={"w/x": covariate_spec()}, vintages={})
    write_program(ws, "p", PER_TARGET)
    (result,) = run(ws, tmp_path, view, "p", [tgt(stream="w/x")])
    assert result.kind == "failure" and "support" in result.error


def test_exit_requests_are_not_swallowed(ws, tmp_path, view):
    code = "def predict(ctx, target):\n    raise SystemExit(3)\n"
    write_program(ws, "p", code)
    with pytest.raises(SystemExit):
        run(ws, tmp_path, view, "p", [tgt()])


def test_imports_of_requires_registration_and_is_read_only():
    with pytest.raises(LookupError, match="no imports registered"):
        imports_of("scienceme_program_unregistered")
    register_imports("scienceme_program_registered", {})
    assert dict(imports_of("scienceme_program_registered")) == {}
    with pytest.raises(TypeError):
        imports_of("scienceme_program_registered")["x"] = None  # type: ignore[index]


def test_results_serialize_with_a_kind_discriminator(view):
    result = WorkResult(results=(Prediction(target=tgt(), pmf=Pmf.point(2)), Failure(target=tgt("B"), error="boom")))
    again = WorkResult.model_validate_json(result.model_dump_json())
    assert again == result and [type(r) for r in again.results] == [Prediction, Failure]


def test_main_creates_the_output_directory_and_rejects_bad_usage(ws, tmp_path, view, capsys):
    write_program(ws, "p", PER_TARGET)
    work = sandbox(ws, tmp_path, "p")
    (work / "order.json").write_text(order(ws, "p", view, []).model_dump_json())
    out = tmp_path / "deep" / "out"
    assert main([str(work), str(out)]) == 0
    assert WorkResult.model_validate_json((out / "result.json").read_text()).results == ()
    assert main([str(work)]) == 2
    assert "usage" in capsys.readouterr().err


def test_runs_as_a_module_in_a_fresh_process(ws, tmp_path, view):
    write_program(ws, "p", PER_TARGET)
    work = sandbox(ws, tmp_path, "p")
    (work / "order.json").write_text(order(ws, "p", view, [tgt("A", 1), tgt("B", 0)]).model_dump_json())
    out = tmp_path / "out"
    command = [sys.executable, "-m", "scienceme.worker_entry", str(work), str(out)]
    done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    kinds = [r.kind for r in WorkResult.model_validate_json((out / "result.json").read_text()).results]
    assert kinds == ["prediction", "failure"]
