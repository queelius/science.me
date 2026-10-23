"""The host side of a run: build a work order, materialize a sandbox, run it under an isolation mode.

A `WorkOrder` carries the closure's manifests, the as-of archive view and the targets.  `prepare_sandbox`
copies exactly the frozen closure beside `order.json`; the sandbox never holds the workspace, the archive
or any other program.  `run_order` then executes it in this process (`NONE`), in a subprocess (`PROCESS`)
or in a docker container with no network (`CONTAINER`).

The outcome of a run is decided by the result file alone, never by an exit code: a missing, unreadable or
invalid `result.json`, or one whose targets are not the order's targets one for one, in order, fails every
target with `no-result`.  A run that outlives its timeout fails every target with `timeout`.  Every run gets
fresh temporary work and output directories, removed afterwards.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Sequence
from pathlib import Path

from scienceme.archive import ArchiveView
from scienceme.manifest import program_files
from scienceme.model import Isolation, Target
from scienceme.registry import Registry
from scienceme.worker_entry import (
    ORDER_FILE,
    PROGRAMS_DIR,
    RESULT_FILE,
    Failure,
    WorkOrder,
    WorkResult,
    execute,
    program_dirname,
)
from scienceme.workspace import Workspace, read_model, write_new

DEFAULT_IMAGE = "scienceme-worker:latest"
IMAGE_ENV = "SCIENCEME_WORKER_IMAGE"

_PACKAGE_DIR = Path(__file__).resolve().parent
_ENTRY_MODULE = "scienceme.worker_entry"
_DOCKER_WORK = "/work"
_DOCKER_OUT = "/out"
_KILL_TIMEOUT_S = 30
_NO_RESULT = "no-result"
_TIMEOUT = "timeout"


def worker_image() -> str:
    """The docker image of the worker: `$SCIENCEME_WORKER_IMAGE`, or `scienceme-worker:latest`."""
    return os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE


def scorer_hash() -> str:
    """`sha256:` plus a digest of the installed `scienceme` package's `*.py` files, by relative path and content.

    The same code hashes the same wherever it is installed, so a result can be stamped with the scorer that
    produced it.
    """
    entries = sorted(
        [path.relative_to(_PACKAGE_DIR).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
        for path in _PACKAGE_DIR.rglob("*.py")
        if path.is_file()
    )
    return "sha256:" + hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode("utf-8")).hexdigest()


def build_order(ws: Workspace, program: str, view: ArchiveView, targets: Sequence[Target]) -> WorkOrder:
    """The work order for the frozen program `program` on `targets`, as seen through `view`.

    Every member of the closure, imports included, must still be exactly what was frozen: a RegistryError
    (`modified-after-freeze`, or `not frozen`) propagates.
    """
    registry = Registry(ws)
    members = registry.closure(program)
    for member in members:
        registry.verify(member)
    return WorkOrder(
        program=program,
        manifests={member: registry.manifest(member) for member in members},
        view=view,
        targets=tuple(targets),
    )


def prepare_sandbox(ws: Workspace, order: WorkOrder, dest: Path) -> None:
    """Write `dest/order.json` and copy each program of the order's closure into `dest/programs/<hex>/`.

    Only the files that make up a program are copied (no top-level `readback.json`, no `__pycache__`).
    """
    registry = Registry(ws)
    for member in order.manifests:
        source = registry.program_dir(member)
        target = dest / PROGRAMS_DIR / program_dirname(member)
        for rel in program_files(source):
            (target / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source / rel, target / rel)
    write_new(dest / ORDER_FILE, order)


def run_order(
    ws: Workspace, order: WorkOrder, isolation: Isolation, timeout_s: int, image: str | None = None
) -> WorkResult:
    """Run `order` under `isolation` and return one result per target, in the order's sequence.

    `NONE` runs in this process and has no timeout (simulation studies only).  `PROCESS` and `CONTAINER`
    kill the run after `timeout_s` seconds.  `image` is the container image (default `worker_image()`).
    """
    with tempfile.TemporaryDirectory(prefix="scienceme-work-") as work_name:
        work = Path(work_name)
        prepare_sandbox(ws, order, work)
        if isolation is Isolation.NONE:
            return execute(order, work)
        with tempfile.TemporaryDirectory(prefix="scienceme-out-") as out_name:
            out = Path(out_name)
            try:
                if isolation is Isolation.PROCESS:
                    _run_process(work, out, timeout_s)
                else:
                    _run_container(work, out, timeout_s, image or worker_image())
            except subprocess.TimeoutExpired:
                return _failures(order, _TIMEOUT)
            return _read_result(out, order)


def _run_process(work: Path, out: Path, timeout_s: int) -> None:
    """Run the sandbox `work` in a subprocess: isolated interpreter, the sandbox as cwd, an environment of PATH only.

    The exit code is ignored (the result file decides).  Raises TimeoutExpired after killing the process.
    """
    subprocess.run(
        [sys.executable, "-I", "-m", _ENTRY_MODULE, str(work), str(out)],
        cwd=work,
        env={"PATH": os.defpath},
        timeout=timeout_s,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_container(work: Path, out: Path, timeout_s: int, image: str) -> None:
    """Run the sandbox `work` in a docker container: no network, read-only root and work mount, bounded resources.

    The container runs as the caller, so the files it writes to `out` can be removed afterwards.  The exit
    code is ignored (the result file decides).  On a timeout the container is killed, then TimeoutExpired is raised.
    """
    name = f"sm-{uuid.uuid4().hex}"
    command = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none",
        "--read-only",
        "--tmpfs", "/tmp:size=256m",
        "--memory", "2g",
        "--cpus", "1",
        "--pids-limit", "256",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{work}:{_DOCKER_WORK}:ro",
        "-v", f"{out}:{_DOCKER_OUT}",
        image,
        "python", "-I", "-m", _ENTRY_MODULE, _DOCKER_WORK, _DOCKER_OUT,
    ]
    try:
        subprocess.run(command, timeout=timeout_s, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        # subprocess.run killed the docker client, not the container it started
        try:
            subprocess.run(
                ["docker", "kill", name], timeout=_KILL_TIMEOUT_S, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
        except subprocess.TimeoutExpired:
            pass
        raise


def _failures(order: WorkOrder, error: str) -> WorkResult:
    return WorkResult(results=tuple(Failure(target=t, error=error) for t in order.targets))


def _read_result(out: Path, order: WorkOrder) -> WorkResult:
    """The result the run left in `out`, or `no-result` for every target when it is not a valid result for `order`.

    The file was written by code that may be hostile and the run has ended, so it is read only if it is a
    regular file (a FIFO or device would block or never end).
    """
    no_result = _failures(order, _NO_RESULT)
    path = out / RESULT_FILE
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return no_result
        result = read_model(path, WorkResult)
    except (OSError, ValueError):  # missing or unreadable, not UTF-8, not JSON, not a WorkResult
        return no_result
    return result if tuple(r.target for r in result.results) == order.targets else no_result
