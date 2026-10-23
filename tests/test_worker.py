import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest
from helpers import CONST, PER_TARGET, at, count_spec, covariate_spec, publish, write_program

import scienceme.worker
from scienceme.archive import Archive, ArchiveView
from scienceme.manifest import closure_hash
from scienceme.model import Isolation, Target
from scienceme.pmf import Pmf
from scienceme.registry import Registry, RegistryError
from scienceme.worker import (
    MAX_ERROR_CHARS,
    MAX_RESULT_BYTES,
    WorkerError,
    _read_result,
    build_order,
    package_hash,
    prepare_sandbox,
    run_order,
    scorer_hash,
    worker_image,
)
from scienceme.worker_entry import ORDER_FILE, Failure, Prediction, WorkOrder, WorkResult, program_dirname
from scienceme.workspace import read_model

STREAM = "w/adm"


def tgt(jurisdiction="A", horizon=0) -> Target:
    return Target(stream=STREAM, jurisdiction=jurisdiction, reference_week=2, horizon=horizon)


@pytest.fixture
def view(ws):
    publish(ws, count_spec(), 3, {("A", 1): 5, ("B", 1): 6}, at(1))
    return Archive(ws).view([STREAM], as_of=3, published_by=at(2))


def frozen(ws, name, code, **fields) -> str:
    """Write and freeze program `name`; return its closure hash."""
    write_program(ws, name, code, **fields)
    return Registry(ws).freeze(name, at(0)).closure_hash


def run(ws, view, name, code, isolation=Isolation.PROCESS, timeout_s=30, targets=None) -> tuple:
    """Freeze `code` as program `name`, run it on `targets` (default one target) and return the results."""
    h = frozen(ws, name, code)
    order = build_order(ws, h, view, targets or [tgt()])
    return run_order(ws, order, isolation, timeout_s).results


def files_under(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


# --- build_order ---


def test_build_order_holds_the_manifest_of_every_closure_member(ws, view):
    core = frozen(ws, "core", "X = 1\n", library=True)
    p = frozen(ws, "p", CONST, imports={"core": core})
    frozen(ws, "unrelated", CONST + "#u\n")
    order = build_order(ws, p, view, [tgt(), tgt(horizon=1)])
    assert order.program == p
    assert set(order.manifests) == {core, p}
    assert order.manifests[p].imports == {"core": core}
    assert order.view == view
    assert order.targets == (tgt(), tgt(horizon=1))


def test_build_order_refuses_a_program_modified_after_freezing(ws, view):
    h = frozen(ws, "p", CONST)
    (ws.programs / "p" / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        build_order(ws, h, view, [tgt()])


def test_build_order_refuses_a_modified_import(ws, view):
    core = frozen(ws, "core", "X = 1\n", library=True)
    p = frozen(ws, "p", CONST, imports={"core": core})
    (ws.programs / "core" / "program.py").write_text("X = 2\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        build_order(ws, p, view, [tgt()])


def test_build_order_refuses_a_hash_that_is_not_frozen(ws, view):
    with pytest.raises(RegistryError, match="not frozen"):
        build_order(ws, "sha256:" + "a" * 64, view, [tgt()])


# --- prepare_sandbox ---


def test_sandbox_contains_only_the_closure(ws, view, tmp_path):
    core_dir = write_program(ws, "core", "X = 1\n", library=True)
    (core_dir / "sub").mkdir()
    (core_dir / "sub" / "util.py").write_text("Y = 2\n")
    (core_dir / "sub" / "readback.json").write_text("{}")  # only the top-level readback is excluded
    core = Registry(ws).freeze("core", at(0)).closure_hash
    p = frozen(ws, "p", CONST, imports={"core": core})
    frozen(ws, "unrelated", CONST + "#u\n")
    (core_dir / "readback.json").write_text("{}")  # written after freezing
    (core_dir / "__pycache__").mkdir()
    (core_dir / "__pycache__" / "x.pyc").write_bytes(b"x")

    order = build_order(ws, p, view, [tgt()])
    dest = tmp_path / "sandbox"
    prepare_sandbox(ws, order, dest)

    core_dirname, p_dirname = program_dirname(core), program_dirname(p)
    assert files_under(dest / "programs") == {
        f"{core_dirname}/program.json",
        f"{core_dirname}/program.py",
        f"{core_dirname}/README.md",
        f"{core_dirname}/sub/util.py",
        f"{core_dirname}/sub/readback.json",
        f"{p_dirname}/program.json",
        f"{p_dirname}/program.py",
        f"{p_dirname}/README.md",
    }
    assert {child.name for child in dest.iterdir()} == {"programs", "order.json"}
    assert read_model(dest / ORDER_FILE, WorkOrder) == order


def test_sandbox_copy_hashes_like_the_frozen_program(ws, view, tmp_path):
    h = frozen(ws, "p", CONST)
    dest = tmp_path / "sandbox"
    prepare_sandbox(ws, build_order(ws, h, view, [tgt()]), dest)
    assert closure_hash(dest / "programs" / program_dirname(h)) == h


def test_sandbox_refuses_a_program_edited_after_the_order_was_built(ws, view, tmp_path):
    h = frozen(ws, "p", CONST)
    order = build_order(ws, h, view, [tgt()])
    (ws.programs / "p" / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        prepare_sandbox(ws, order, tmp_path / "sandbox")


def test_sandbox_refuses_an_import_edited_after_the_order_was_built(ws, view, tmp_path):
    core = frozen(ws, "core", "X = 1\n", library=True)
    p = frozen(ws, "p", CONST, imports={"core": core})
    order = build_order(ws, p, view, [tgt()])
    (ws.programs / "core" / "extra.py").write_text("Y = 2\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        prepare_sandbox(ws, order, tmp_path / "sandbox")


def test_sandbox_refuses_a_symlink_added_after_the_order_was_built(ws, view, tmp_path):
    h = frozen(ws, "p", CONST)
    order = build_order(ws, h, view, [tgt()])
    (ws.programs / "p" / "link.py").symlink_to(tmp_path)
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        prepare_sandbox(ws, order, tmp_path / "sandbox")


def test_sandbox_refuses_a_program_directory_emptied_after_the_order_was_built(ws, view, tmp_path):
    h = frozen(ws, "p", CONST)
    order = build_order(ws, h, view, [tgt()])
    for f in (ws.programs / "p").iterdir():
        f.unlink()
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        prepare_sandbox(ws, order, tmp_path / "sandbox")


def test_run_order_refuses_a_program_edited_after_the_order_was_built_and_cleans_up(ws, view, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    h = frozen(ws, "p", CONST)
    order = build_order(ws, h, view, [tgt()])
    (ws.programs / "p" / "program.py").write_text(CONST + "# edit\n")
    for isolation in (Isolation.NONE, Isolation.PROCESS, Isolation.CONTAINER):
        with pytest.raises(RegistryError, match="modified-after-freeze"):
            run_order(ws, order, isolation, 30)
    assert list(scratch.iterdir()) == []


# --- run_order: PROCESS ---


def test_process_mode_end_to_end(ws, view):
    targets = [tgt("A", 0), tgt("A", 1), tgt("B", 0)]
    results = run(ws, view, "p", PER_TARGET, targets=targets)
    assert [r.target for r in results] == targets
    assert results[0] == Prediction(target=targets[0], pmf=Pmf.point(0))
    assert results[1] == Prediction(target=targets[1], pmf=Pmf.point(1))
    assert isinstance(results[2], Failure) and "boom" in results[2].error


def test_process_mode_runs_a_program_with_imports(ws, view):
    core = frozen(ws, "core", "def level():\n    return 3\n", library=True)
    code = (
        "from scienceme.sdk import Pmf, imports_of\n"
        "IMPORTS = imports_of(__name__)\n"
        "def predict(ctx, target):\n    return Pmf.point(IMPORTS['core'].level())\n"
    )
    p = frozen(ws, "p", code, imports={"core": core})
    results = run_order(ws, build_order(ws, p, view, [tgt()]), Isolation.PROCESS, 30).results
    assert results[0].pmf == Pmf.point(3)


def test_process_timeout_fails_every_target(ws, view):
    code = "import time\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    time.sleep(10)\n    return Pmf.point(1)\n"
    targets = [tgt("A"), tgt("B")]
    results = run(ws, view, "p", code, timeout_s=1, targets=targets)
    assert results == (Failure(target=targets[0], error="timeout"), Failure(target=targets[1], error="timeout"))


@pytest.mark.parametrize(
    "probe",
    [
        pytest.param("'SCIENCEME_SECRET' not in os.environ", id="clean-environment"),
        pytest.param("os.path.isfile('order.json')", id="cwd-is-the-sandbox"),
        pytest.param("'pytest' not in sys.modules", id="separate-process"),
    ],
)
def test_process_mode_sandbox_properties(ws, view, monkeypatch, probe):
    monkeypatch.setenv("SCIENCEME_SECRET", "x")
    code = f"import os, sys\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(int({probe}))\n"
    assert run(ws, view, "p", code)[0].pmf == Pmf.point(1)


def test_process_mode_gives_the_program_no_stdin(ws, view):
    code = "import os\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(int(os.read(0, 1) == b''))\n"
    assert run(ws, view, "p", code)[0].pmf == Pmf.point(1)


# --- run_order: NONE ---


def test_none_mode_runs_in_this_process(ws, view):
    code = "import sys\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(int('pytest' in sys.modules))\n"
    assert run(ws, view, "p", code, Isolation.NONE)[0].pmf == Pmf.point(1)


def test_none_mode_isolates_failures_per_target(ws, view):
    targets = [tgt("A", 1), tgt("B", 0)]
    results = run(ws, view, "p", PER_TARGET, Isolation.NONE, targets=targets)
    assert results[0].pmf == Pmf.point(1)
    assert isinstance(results[1], Failure) and "boom" in results[1].error


# --- run_order: the result file decides ---

# Run inside the sandbox: `sys.argv[2]` is the output directory.
_SCRIBBLE = (
    "import os, sys\n"
    "from scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n"
    "    out = os.path.join(sys.argv[2], 'result.json')\n"
    "{body}"
    "    os._exit(0)\n"
)


def _scribble(body: str) -> str:
    return _SCRIBBLE.format(body="".join(f"    {line}\n" for line in body.splitlines()))


NO_RESULT_PROGRAMS = {
    "never-written": _scribble("pass"),
    "invalid-json": _scribble("open(out, 'w').write('{not json')"),
    "invalid-model": _scribble("open(out, 'w').write('{\"results\": [{\"kind\": \"nonsense\"}]}')"),
    "not-utf8": _scribble("open(out, 'wb').write(b'\\xff\\xfe')"),
    "fifo": _scribble("os.mkfifo(out)"),
    "directory": _scribble("os.mkdir(out)"),
    "oversize-sparse-file": _scribble("open(out, 'w').truncate(2**41)"),
}


@pytest.mark.parametrize("code", NO_RESULT_PROGRAMS.values(), ids=NO_RESULT_PROGRAMS)
def test_missing_or_invalid_result_fails_every_target_as_no_result(ws, view, code):
    targets = [tgt("A"), tgt("B")]
    results = run(ws, view, "p", code, targets=targets)
    assert results == (Failure(target=targets[0], error="no-result"), Failure(target=targets[1], error="no-result"))


def test_a_result_for_other_targets_is_no_result(ws, view):
    other = WorkResult(results=(Prediction(target=tgt("B", 1), pmf=Pmf.point(2)),))
    code = _scribble(f"open(out, 'w').write({other.model_dump_json()!r})")
    results = run(ws, view, "p", code, targets=[tgt("A")])
    assert results == (Failure(target=tgt("A"), error="no-result"),)


def test_a_result_with_the_targets_in_another_order_is_no_result(ws, view):
    a, b = tgt("A"), tgt("B")
    swapped = WorkResult(results=(Prediction(target=b, pmf=Pmf.point(2)), Prediction(target=a, pmf=Pmf.point(2))))
    code = _scribble(f"open(out, 'w').write({swapped.model_dump_json()!r})")
    results = run(ws, view, "p", code, targets=[a, b])
    assert results == (Failure(target=a, error="no-result"), Failure(target=b, error="no-result"))


def test_a_symlinked_result_is_no_result_even_when_it_points_at_a_valid_one(ws, view):
    valid = WorkResult(results=(Prediction(target=tgt("A"), pmf=Pmf.point(2)),))
    code = _scribble(
        f"open(os.path.join(sys.argv[2], 'real.json'), 'w').write({valid.model_dump_json()!r})\n"
        "os.symlink('real.json', out)"
    )
    assert run(ws, view, "p", code, targets=[tgt("A")]) == (Failure(target=tgt("A"), error="no-result"),)


def test_the_result_cap_is_inclusive(tmp_path, view, monkeypatch):
    order = WorkOrder(program="sha256:" + "a" * 64, manifests={}, view=view, targets=(tgt("A"),))
    result = WorkResult(results=(Prediction(target=tgt("A"), pmf=Pmf.point(2)),))
    data = result.model_dump_json().encode()
    (tmp_path / "result.json").write_bytes(data)
    monkeypatch.setattr(scienceme.worker, "MAX_RESULT_BYTES", len(data))
    assert _read_result(tmp_path, order) == result
    monkeypatch.setattr(scienceme.worker, "MAX_RESULT_BYTES", len(data) - 1)
    assert _read_result(tmp_path, order) == WorkResult(results=(Failure(target=tgt("A"), error="no-result"),))


@pytest.mark.skipif(not Path("/proc/self/fd").is_dir(), reason="counts open descriptors through /proc")
@pytest.mark.parametrize("make", [os.mkdir, os.mkfifo, lambda path: path.write_text("{not json")], ids=["directory", "fifo", "invalid"])
def test_reading_a_bad_result_leaks_no_descriptor(tmp_path, make):
    order = WorkOrder(program="sha256:" + "a" * 64, manifests={}, view=ArchiveView(as_of=0, specs={}, vintages={}), targets=(tgt("A"),))
    make(tmp_path / "result.json")
    before = len(os.listdir("/proc/self/fd"))
    for _ in range(5):
        assert _read_result(tmp_path, order) == WorkResult(results=(Failure(target=tgt("A"), error="no-result"),))
    assert len(os.listdir("/proc/self/fd")) == before


def test_the_result_cap_is_64_mebibytes():
    assert MAX_RESULT_BYTES == 64 * 1024 * 1024


# --- run_order: the host trusts nothing the sandbox reports ---


def test_a_forged_pmf_outside_the_support_fails_only_its_target(ws, view):
    """A program that writes `result.json` itself bypasses the sandbox's checks; the host checks again."""
    a, b = tgt("A"), tgt("B")
    forged = WorkResult(
        results=(Prediction(target=a, pmf=Pmf(lo=10**15, p=(1.0,))), Prediction(target=b, pmf=Pmf.point(3)))
    )
    code = _scribble(f"open(out, 'w').write({forged.model_dump_json()!r})")
    results = run(ws, view, "p", code, targets=[a, b])
    assert results == (Failure(target=a, error="pmf outside support [0, 1000]"), Prediction(target=b, pmf=Pmf.point(3)))


@pytest.mark.parametrize("pmf", [Pmf(lo=-1, p=(0.5, 0.5)), Pmf(lo=1000, p=(0.5, 0.5)), Pmf(lo=10**15, p=(1.0,))])
def test_reading_a_result_rechecks_every_pmf_against_its_stream_support(tmp_path, view, pmf):
    order = WorkOrder(program="sha256:" + "a" * 64, manifests={}, view=view, targets=(tgt("A"),))
    (tmp_path / "result.json").write_text(WorkResult(results=(Prediction(target=tgt("A"), pmf=pmf),)).model_dump_json())
    assert _read_result(tmp_path, order) == WorkResult(
        results=(Failure(target=tgt("A"), error="pmf outside support [0, 1000]"),)
    )


def test_reading_a_result_keeps_a_pmf_on_the_edges_of_the_support(tmp_path, view):
    order = WorkOrder(program="sha256:" + "a" * 64, manifests={}, view=view, targets=(tgt("A"),))
    result = WorkResult(results=(Prediction(target=tgt("A"), pmf=Pmf(lo=0, p=(0.5,) + (0.0,) * 999 + (0.5,))),))
    (tmp_path / "result.json").write_text(result.model_dump_json())
    assert _read_result(tmp_path, order) == result


def test_a_forged_forecast_of_a_stream_the_view_cannot_bound_is_a_failure(tmp_path):
    """The sandbox fails a target whose stream is unknown or has no support; a forged forecast of one does too."""
    covariate = covariate_spec()
    view = ArchiveView(as_of=1, specs={covariate.id: covariate}, vintages={covariate.id: ()})
    unknown = Target(stream="w/elsewhere", jurisdiction="A", reference_week=1, horizon=0)
    unbounded = Target(stream=covariate.id, jurisdiction="A", reference_week=1, horizon=0)
    order = WorkOrder(program="sha256:" + "a" * 64, manifests={}, view=view, targets=(unknown, unbounded))
    forged = WorkResult(results=tuple(Prediction(target=t, pmf=Pmf.point(1)) for t in order.targets))
    (tmp_path / "result.json").write_text(forged.model_dump_json())
    first, second = _read_result(tmp_path, order).results
    assert isinstance(first, Failure) and "unknown stream" in first.error
    assert isinstance(second, Failure) and "has no support" in second.error


@pytest.mark.parametrize("isolation", [Isolation.NONE, Isolation.PROCESS])
def test_a_failure_reason_is_cut_to_its_first_2000_characters(ws, view, isolation):
    code = "def predict(ctx, target):\n    raise RuntimeError('x' * 100_000)\n"
    (failure,) = run(ws, view, "p", code, isolation)
    assert isinstance(failure, Failure)
    assert failure.error == ("RuntimeError: " + "x" * 100_000)[:MAX_ERROR_CHARS]
    assert MAX_ERROR_CHARS == 2000


def test_a_forged_failure_reason_is_cut_to_its_first_2000_characters(ws, view):
    forged = WorkResult(results=(Failure(target=tgt("A"), error="y" * 5000),))
    code = _scribble(f"open(out, 'w').write({forged.model_dump_json()!r})")
    assert run(ws, view, "p", code, targets=[tgt("A")]) == (Failure(target=tgt("A"), error="y" * 2000),)


def test_the_exit_code_does_not_decide_the_outcome(ws, view):
    code = "import atexit, os\nfrom scienceme.sdk import Pmf\natexit.register(os._exit, 3)\ndef predict(ctx, target):\n    return Pmf.point(4)\n"
    assert run(ws, view, "p", code)[0].pmf == Pmf.point(4)


# --- run_order: housekeeping ---


@pytest.mark.parametrize("isolation", [Isolation.NONE, Isolation.PROCESS])
def test_run_cleans_up_its_directories(ws, view, tmp_path, monkeypatch, isolation):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    assert run(ws, view, "p", CONST, isolation)[0].pmf == Pmf.point(7)
    assert list(scratch.iterdir()) == []


def test_run_cleans_up_after_a_timeout(ws, view, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    code = "import time\nfrom scienceme.sdk import Pmf\ndef predict(ctx, target):\n    time.sleep(10)\n    return Pmf.point(1)\n"
    assert run(ws, view, "p", code, timeout_s=1)[0] == Failure(target=tgt(), error="timeout")
    assert list(scratch.iterdir()) == []


# --- CONTAINER mode against a stand-in `docker` (the real daemon is exercised in test_worker_docker.py) ---

FAKE_DOCKER = """#!{python}
import json, os, sys, time
config = json.load(open(os.environ["FAKE_DOCKER_CONFIG"]))
with open(config["log"], "a") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
if sys.argv[1] == "kill" and config.get("hang_kill"):
    time.sleep(60)
if sys.argv[1] == "run":
    sys.stderr.write(config.get("stderr", ""))
    sys.stderr.flush()
    if config.get("hang"):
        time.sleep(60)
    sys.exit(config.get("exit", 0))
"""


class FakeDocker:
    """A `docker` first on PATH that logs its arguments and behaves as `configure` says."""

    def __init__(self, tmp_path: Path, monkeypatch) -> None:
        bin_dir = tmp_path / "fake-bin"
        bin_dir.mkdir()
        script = bin_dir / "docker"
        script.write_text(FAKE_DOCKER.format(python=sys.executable))
        script.chmod(0o755)
        self.log = tmp_path / "docker.log"
        self.config = tmp_path / "docker.json"
        monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("FAKE_DOCKER_CONFIG", str(self.config))
        self.configure()

    def configure(self, **behaviour) -> None:
        self.config.write_text(json.dumps({"log": str(self.log), **behaviour}))

    def calls(self) -> list[list[str]]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []


@pytest.fixture
def fake_docker(tmp_path, monkeypatch) -> FakeDocker:
    return FakeDocker(tmp_path, monkeypatch)


def run_container(ws, view, targets=None, timeout_s=30, image="worker:test"):
    h = frozen(ws, "p", CONST)  # freezing the same content again returns the existing freeze
    order = build_order(ws, h, view, targets or [tgt()])
    return run_order(ws, order, Isolation.CONTAINER, timeout_s, image).results


def test_container_command_line(ws, view, fake_docker):
    run_container(ws, view)
    (call,) = fake_docker.calls()
    assert call[0] == "run"

    def after(flag):
        return [call[i + 1] for i, arg in enumerate(call) if arg == flag]

    assert "--rm" in call and "--read-only" in call
    assert after("--network") == ["none"]
    assert after("--pull") == ["never"]
    assert after("--cap-drop") == ["ALL"]
    assert after("--security-opt") == ["no-new-privileges"]
    assert after("--memory") == ["2g"] and after("--cpus") == ["1"] and after("--pids-limit") == ["256"]
    assert after("--tmpfs") == ["/tmp:size=256m"]
    assert after("--user") == [f"{os.getuid()}:{os.getgid()}"]
    (name,) = after("--name")
    assert re.fullmatch(r"sm-[0-9a-f]{32}", name)
    work_mount, out_mount = after("-v")
    assert work_mount.endswith(":/work:ro") and out_mount.endswith(":/out")
    assert call[-4:] == [
        "worker:test",
        "sh",
        "-c",
        "command -v python >/dev/null 2>&1 || exit 127; python -I -m scienceme.worker_entry /work /out; exit 0",
    ]


def test_container_names_are_unique_per_run(ws, view, fake_docker):
    run_container(ws, view)
    run_container(ws, view)
    names = [call[call.index("--name") + 1] for call in fake_docker.calls()]
    assert len(set(names)) == 2


def test_container_run_uses_the_worker_image_by_default(ws, view, fake_docker, monkeypatch):
    monkeypatch.setenv("SCIENCEME_WORKER_IMAGE", "from-env:1")
    h = frozen(ws, "p", CONST)
    run_order(ws, build_order(ws, h, view, [tgt()]), Isolation.CONTAINER, 30)
    assert fake_docker.calls()[0][-4] == "from-env:1"


@pytest.mark.parametrize("code", [1, 2, 137])
def test_a_container_that_dies_without_a_result_is_no_result(ws, view, fake_docker, code):
    fake_docker.configure(exit=code, stderr="killed")
    assert run_container(ws, view) == (Failure(target=tgt(), error="no-result"),)


@pytest.mark.parametrize("code", [125, 126, 127])
def test_docker_failing_to_run_the_container_is_a_worker_error_not_a_program_failure(ws, view, fake_docker, code):
    fake_docker.configure(exit=code, stderr="docker: Error response from daemon: no such image")
    with pytest.raises(WorkerError) as error:
        run_container(ws, view)
    assert f"exit code {code}" in str(error.value)
    assert "no such image" in str(error.value)


def test_the_worker_error_message_truncates_docker_stderr(ws, view, fake_docker):
    fake_docker.configure(exit=125, stderr="x" * 5000)
    with pytest.raises(WorkerError) as error:
        run_container(ws, view)
    assert "x" * 2000 in str(error.value) and "x" * 2001 not in str(error.value)


def test_a_flood_on_stderr_neither_stalls_nor_decides_the_run(ws, view, fake_docker):
    fake_docker.configure(exit=0, stderr="y" * 5_000_000)
    assert run_container(ws, view) == (Failure(target=tgt(), error="no-result"),)


def test_missing_docker_is_a_worker_error(ws, view, tmp_path, monkeypatch):
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    with pytest.raises(WorkerError, match="docker"):
        run_container(ws, view)


def test_container_timeout_kills_the_named_container_and_fails_every_target(ws, view, fake_docker):
    fake_docker.configure(hang=True)
    targets = [tgt("A"), tgt("B")]
    results = run_container(ws, view, targets=targets, timeout_s=1)
    assert results == (Failure(target=targets[0], error="timeout"), Failure(target=targets[1], error="timeout"))
    run_call, kill_call = fake_docker.calls()
    assert kill_call == ["kill", run_call[run_call.index("--name") + 1]]


def test_a_docker_kill_that_hangs_does_not_hang_the_run(ws, view, fake_docker, monkeypatch):
    monkeypatch.setattr(scienceme.worker, "_KILL_TIMEOUT_S", 1)
    fake_docker.configure(hang=True, hang_kill=True)
    assert run_container(ws, view, timeout_s=1) == (Failure(target=tgt(), error="timeout"),)


def test_container_run_cleans_up_its_directories(ws, view, fake_docker, tmp_path, monkeypatch):
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    fake_docker.configure(exit=125, stderr="boom")
    with pytest.raises(WorkerError):
        run_container(ws, view)
    assert list(scratch.iterdir()) == []


# --- worker_image and scorer_hash ---


def test_worker_image_defaults_and_honours_the_environment(monkeypatch):
    monkeypatch.delenv("SCIENCEME_WORKER_IMAGE", raising=False)
    assert worker_image() == "scienceme-worker:latest"
    monkeypatch.setenv("SCIENCEME_WORKER_IMAGE", "registry.example/worker:1")
    assert worker_image() == "registry.example/worker:1"


def test_scorer_hash_has_the_closure_hash_format_and_is_stable():
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", scorer_hash())
    assert scorer_hash() == scorer_hash()


def test_scorer_hash_covers_paths_and_python_content_only(tmp_path, monkeypatch):
    package = tmp_path / "scienceme"
    (package / "sub").mkdir(parents=True)
    (package / "a.py").write_text("A = 1\n")
    (package / "sub" / "b.py").write_text("B = 1\n")
    monkeypatch.setattr(scienceme.worker, "_PACKAGE_DIR", package)
    base = scorer_hash()

    (package / "notes.txt").write_text("not python")
    (package / "__pycache__").mkdir()
    (package / "__pycache__" / "a.cpython-313.pyc").write_bytes(b"x")
    assert scorer_hash() == base

    (package / "a.py").write_text("A = 2\n")
    edited = scorer_hash()
    assert edited != base
    (package / "a.py").write_text("A = 1\n")
    assert scorer_hash() == base

    (package / "sub" / "b.py").rename(package / "sub" / "c.py")
    assert scorer_hash() not in (base, edited)


def test_scorer_hash_is_over_the_installed_package(monkeypatch):
    real = scorer_hash()
    monkeypatch.setattr(scienceme.worker, "_PACKAGE_DIR", Path(scienceme.__file__).parent)
    assert scorer_hash() == real


def test_package_hash_is_the_scorer_hash_of_any_package_directory(tmp_path):
    """The scorer hash is `package_hash` of the installed `scienceme`; another package hashes the same way."""
    assert package_hash(Path(scienceme.__file__).parent) == scorer_hash()
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "notes.txt").write_text("not python")
    base = package_hash(tmp_path)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", base) and base != scorer_hash()
    (tmp_path / "notes.txt").write_text("still not python")
    assert package_hash(tmp_path) == base
    (tmp_path / "a.py").write_text("A = 2\n")
    assert package_hash(tmp_path) != base
