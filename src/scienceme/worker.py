"""The host side of a run: build a work order, materialize a sandbox, run it under an isolation mode.

A `WorkOrder` carries the closure's manifests, the as-of archive view and the targets.  `prepare_sandbox`
copies exactly the frozen closure beside `order.json`; the sandbox never holds the workspace, the archive
or any other program.  `run_order` then executes it in this process (`NONE`), in a subprocess (`PROCESS`)
or in a docker container with no network (`CONTAINER`).

The outcome of a run is decided by the result file alone, never by an exit code: a missing, unreadable or
invalid `result.json`, or one whose targets are not the order's targets one for one, in order, fails every
target with `no-result`.  A run that outlives its timeout fails every target with `timeout`.  Every run gets
fresh temporary work and output directories, removed afterwards.

A run that cannot happen at all (docker missing, the image absent, the daemon refusing the container) is
not the program's failure: it raises `WorkerError`.

Only `CONTAINER` enforces an information boundary.  `NONE` and `PROCESS` run program code with the host
user's full access to the filesystem and network; they exist for simulation studies and trusted programs.
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
import threading
import uuid
from collections.abc import Sequence
from pathlib import Path

from scienceme.archive import ArchiveView
from scienceme.manifest import ClosureError, closure_hash, program_files
from scienceme.model import Isolation, Target
from scienceme.registry import Registry, RegistryError
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
from scienceme.workspace import Workspace, write_new

DEFAULT_IMAGE = "scienceme-worker:latest"
IMAGE_ENV = "SCIENCEME_WORKER_IMAGE"

_PACKAGE_DIR = Path(__file__).resolve().parent
_ENTRY_MODULE = "scienceme.worker_entry"
_DOCKER_WORK = "/work"
_DOCKER_OUT = "/out"
_KILL_TIMEOUT_S = 30
_NO_RESULT = "no-result"
_TIMEOUT = "timeout"
# What the container runs.  The shell discards the program's own exit status (a program can `os._exit(126)`),
# so the status `docker run` returns is docker's or the shell's: 127 when python is missing from the image, 126
# or 127 when the shell cannot be run, 125 when docker itself failed.  Anything else is decided by `result.json`.
_CONTAINER_SCRIPT = (
    "command -v python >/dev/null 2>&1 || exit 127; "
    f"python -I -m {_ENTRY_MODULE} {_DOCKER_WORK} {_DOCKER_OUT}; exit 0"
)
# `docker run` exits 125 when the daemon fails, 126 when the command cannot be invoked, 127 when it is not found.
_DOCKER_FAILURES = frozenset({125, 126, 127})
_STDERR_KEPT = 2000
_READ_CHUNK = 1 << 20

# The most a `result.json` may hold.  The file is written by program code into host disk, which the container's
# memory limit does not cover, so it is never read without this bound.
MAX_RESULT_BYTES = 64 * 1024 * 1024


class WorkerError(RuntimeError):
    """The sandbox could not be run at all (docker missing, image absent, daemon error): not a program failure."""


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

    Only the files that make up a program are copied (no top-level `readback.json`, no `__pycache__`).  Each
    copy is hashed again and must equal the member's closure hash, so what the sandbox holds is what was
    frozen even if the program changed after `build_order` verified it: RegistryError (`modified-after-freeze`).
    """
    registry = Registry(ws)
    for member in order.manifests:
        source = registry.program_dir(member)
        target = dest / PROGRAMS_DIR / program_dirname(member)
        try:
            for rel in program_files(source):
                (target / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source / rel, target / rel)
            copied = closure_hash(target)
        except (ClosureError, FileNotFoundError) as e:
            raise RegistryError(f"modified-after-freeze: {source.name} changed while it was copied: {e}") from e
        if copied != member:
            raise RegistryError(
                f"modified-after-freeze: {source.name} was frozen as {member} but its copy hashes to {copied}"
            )
    write_new(dest / ORDER_FILE, order)


def run_order(
    ws: Workspace, order: WorkOrder, isolation: Isolation, timeout_s: int, image: str | None = None
) -> WorkResult:
    """Run `order` under `isolation` and return one result per target, in the order's sequence.

    Only `CONTAINER` enforces an information boundary: the program sees the sandbox, not the host.  `PROCESS`
    and `NONE` run it with the host user's access to files and network.  `NONE` runs in this process and has
    no timeout (simulation studies only); `PROCESS` and `CONTAINER` kill the run after `timeout_s` seconds.
    `image` is the container image (default `worker_image()`).

    A program that crashes, hangs or writes a bad result fails its targets; the host failing to run the
    sandbox at all raises `WorkerError`, and a closure that no longer matches its freeze raises RegistryError.
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
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _run_container(work: Path, out: Path, timeout_s: int, image: str) -> None:
    """Run the sandbox `work` in a docker container: no network, no capabilities, read-only root and work mount.

    The container runs as the caller, so the files it writes to `out` can be removed afterwards.  The program's
    exit status never reaches docker's (see `_CONTAINER_SCRIPT`), so the result file decides the outcome, while
    docker's and the shell's failure codes raise WorkerError.  On a timeout the container is killed, then
    TimeoutExpired is raised.
    """
    name = f"sm-{uuid.uuid4().hex}"
    command = [
        "docker", "run", "--rm", "--name", name,
        "--pull", "never",
        "--network", "none",
        "--read-only",
        "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges",
        "--tmpfs", "/tmp:size=256m",
        "--memory", "2g",
        "--cpus", "1",
        "--pids-limit", "256",
        "--user", f"{os.getuid()}:{os.getgid()}",
        "-v", f"{work}:{_DOCKER_WORK}:ro",
        "-v", f"{out}:{_DOCKER_OUT}",
        image,
        "sh", "-c", _CONTAINER_SCRIPT,
    ]
    try:
        code, stderr = _run_keeping_stderr_head(command, timeout_s)
    except subprocess.TimeoutExpired:
        # the run killed the docker client, not the container it started
        try:
            subprocess.run(
                ["docker", "kill", name],
                timeout=_KILL_TIMEOUT_S,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            pass
        raise
    if code in _DOCKER_FAILURES:
        raise WorkerError(f"docker run failed with exit code {code} (docker, or no sh or python in the image): {stderr}")


def _run_keeping_stderr_head(command: list[str], timeout_s: int) -> tuple[int, str]:
    """Run `command` to completion; return its exit code and the first `_STDERR_KEPT` characters of its stderr.

    The stderr of a container carries the program's output, so it is drained as it comes and only the head is
    kept, which bounds memory.  Raises TimeoutExpired after killing the process, and WorkerError when it cannot
    be started.
    """
    head = bytearray()
    try:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE
        )
    except OSError as e:
        raise WorkerError(f"cannot run {command[0]}: {e}") from e

    def drain() -> None:
        for chunk in iter(lambda: process.stderr.read(65536), b""):
            head.extend(chunk[: 4 * _STDERR_KEPT - len(head)])

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    try:
        code = process.wait(timeout=timeout_s)
    except BaseException:  # a timeout, or an interrupt: either way the process must not outlive this call
        process.kill()
        process.wait()
        raise
    finally:
        reader.join()
        process.stderr.close()
    return code, head.decode("utf-8", errors="replace")[:_STDERR_KEPT]


def _failures(order: WorkOrder, error: str) -> WorkResult:
    return WorkResult(results=tuple(Failure(target=t, error=error) for t in order.targets))


def _read_result(out: Path, order: WorkOrder) -> WorkResult:
    """The result the run left in `out`, or `no-result` for every target when it is not a valid result for `order`."""
    no_result = _failures(order, _NO_RESULT)
    try:
        data = _read_capped(out / RESULT_FILE, MAX_RESULT_BYTES)
        if data is None:
            return no_result
        result = WorkResult.model_validate_json(data)
    except (OSError, ValueError):  # missing or unreadable, not UTF-8, not JSON, not a WorkResult
        return no_result
    return result if tuple(r.target for r in result.results) == order.targets else no_result


def _read_capped(path: Path, cap: int) -> bytes | None:
    """The bytes of `path` if it is a regular file (not a symlink) of at most `cap` bytes, else None.

    The file was written by code that may be hostile, so it is opened without following a final symlink or
    blocking on a FIFO, its size is taken from the open descriptor before anything is read, and at most
    `cap + 1` bytes are ever read.
    """
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > cap:
            return None
        chunks: list[bytes] = []
        remaining = cap + 1
        while remaining > 0 and (chunk := os.read(fd, min(remaining, _READ_CHUNK))):
            chunks.append(chunk)
            remaining -= len(chunk)
    finally:
        os.close(fd)
    data = b"".join(chunks)
    return data if len(data) <= cap else None
