"""The host side of a run: build a work order, materialize a sandbox, run it under an isolation mode.

A `WorkOrder` carries the closure's manifests, the as-of archive view and the targets.  `prepare_sandbox`
copies exactly the frozen closure beside `order.json`; the sandbox never holds the workspace, the archive
or any other program.  `run_order` then executes it in this process (`NONE`), in a subprocess (`PROCESS`)
or in a docker container with no network (`CONTAINER`).

The outcome of a run is decided by the result file alone, never by an exit code: a missing, unreadable or
invalid `result.json`, or one whose targets are not the order's targets one for one, in order, fails every
target with `no-result`.  A run that outlives its timeout fails every target with `timeout`.  Every run gets
fresh temporary work and output directories, removed afterwards.

Nothing the sandbox reports is trusted.  In `PROCESS` and `CONTAINER` mode the program can write
`result.json` itself, around every check the in-sandbox runner makes, so the host checks again: a forecast
whose pmf leaves its stream's `[0, support_max]` (or whose stream has no support) becomes that target's
Failure, and every failure's reason is cut to its first `MAX_ERROR_CHARS` characters.

A run that cannot happen at all (docker missing, the image absent, the daemon refusing the container) is
not the program's failure: it raises `WorkerError`.

Only `CONTAINER` enforces an information boundary.  `NONE` and `PROCESS` run program code with the host
user's full access to the filesystem and network; they exist for simulation studies and trusted programs.
`NONE` shares even the objects: every program run on one origin is handed the same `ArchiveView` object
(`order.view`, which `ctx.view` is), so a program that mutates it changes what the programs after it see.
Run only trusted programs that way.
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
    MAX_ERROR_CHARS,
    ORDER_FILE,
    PROGRAMS_DIR,
    RESULT_FILE,
    Failure,
    Prediction,
    WorkOrder,
    WorkResult,
    execute,
    outside_support,
    program_dirname,
    support_bounds,
    unbounded,
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
# or 127 when the shell cannot be run, 125 when docker itself failed.  Anything else is decided by `result.json`,
# which the shell writes to stdout once the program is done; the program's own stdout goes to /dev/null.
_CONTAINER_SCRIPT = (
    "command -v python >/dev/null 2>&1 || exit 127; "
    f"python -I -m {_ENTRY_MODULE} {_DOCKER_WORK} {_DOCKER_OUT} >/dev/null; "
    f"cat {_DOCKER_OUT}/{RESULT_FILE} 2>/dev/null; exit 0"
)
# `docker run` exits 125 when the daemon fails, 126 when the command cannot be invoked, 127 when it is not found.
_DOCKER_FAILURES = frozenset({125, 126, 127})
_STDERR_KEPT = 2000
_READ_CHUNK = 1 << 20

# The most a `result.json` may hold.  The file is written by program code into host disk, which the container's
# memory limit does not cover, so it is never read without this bound.
MAX_RESULT_BYTES = 64 * 1024 * 1024
# The size of the container's `/out`, a tmpfs inside the container's memory limit: room for a result one chunk
# over the bound, so an oversized result is seen and refused rather than cut short into something parseable.
_OUT_TMPFS_BYTES = MAX_RESULT_BYTES + _READ_CHUNK

# What one entry of a result may take beyond its target's own JSON: the framing and a pmf's `lo`.  A pmf's
# masses take at most `_MASS_BYTES` each (a float's repr and a comma), a reason `_CHAR_BYTES` per character
# (a control character escaped as `\uXXXX`).
_ENTRY_BYTES = 256
_MASS_BYTES = 32
_CHAR_BYTES = 6


class WorkerError(RuntimeError):
    """The sandbox could not be run at all (docker missing, image absent, daemon error): not a program failure."""


def worker_image() -> str:
    """The docker image of the worker: `$SCIENCEME_WORKER_IMAGE`, or `scienceme-worker:latest`."""
    return os.environ.get(IMAGE_ENV) or DEFAULT_IMAGE


def resolve_image(image: str) -> str:
    """The content id (`sha256:...`) of the local docker image `image`.

    A tag can be moved to other contents; the id cannot, so a run given the id runs exactly the image that was
    resolved, and a record can name it.  WorkerError when docker cannot be run or has no such image.
    """
    try:
        done = subprocess.run(
            ["docker", "image", "inspect", "--format", "{{.Id}}", image],
            capture_output=True, text=True, timeout=_KILL_TIMEOUT_S, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise WorkerError(f"cannot inspect the image {image!r}: {e}") from e
    if done.returncode != 0:
        raise WorkerError(f"no docker image {image!r}: {done.stderr.strip()[:_STDERR_KEPT]}")
    return done.stdout.strip()


def package_hash(directory: Path) -> str:
    """`sha256:` plus a digest of the `*.py` files under `directory`, by relative path and content.

    The same code hashes the same wherever it is installed, so a result can be stamped with the code that
    produced it.
    """
    entries = sorted(
        [path.relative_to(directory).as_posix(), hashlib.sha256(path.read_bytes()).hexdigest()]
        for path in directory.rglob("*.py")
        if path.is_file()
    )
    return "sha256:" + hashlib.sha256(json.dumps(entries, separators=(",", ":")).encode("utf-8")).hexdigest()


def scorer_hash() -> str:
    """The `package_hash` of the installed `scienceme` package: the scorer a result was produced by."""
    return package_hash(_PACKAGE_DIR)


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
            return _host_checked(order, execute(order, work))
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

    Nothing the container writes reaches host disk except the result: its `/out` is a tmpfs of
    `_OUT_TMPFS_BYTES`, and the result comes back on stdout, of which at most `MAX_RESULT_BYTES + 1` bytes are
    kept and written to `out/result.json` (a program can write to that stdout too, which spoils only its own
    result).  The program's exit status never reaches docker's (see `_CONTAINER_SCRIPT`), so the result file
    decides the outcome, while docker's and the shell's failure codes raise WorkerError.  On a timeout the
    container is killed, then TimeoutExpired is raised.
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
        "--log-driver", "none",
        "-v", f"{work}:{_DOCKER_WORK}:ro",
        "--tmpfs", f"{_DOCKER_OUT}:size={_OUT_TMPFS_BYTES}",
        image,
        "sh", "-c", _CONTAINER_SCRIPT,
    ]
    try:
        code, result, stderr = _run_capturing(command, timeout_s)
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
    (out / RESULT_FILE).write_bytes(result)


def _run_capturing(command: list[str], timeout_s: int) -> tuple[int, bytes, str]:
    """Run `command` to completion; return its exit code, the first `MAX_RESULT_BYTES + 1` bytes of its stdout
    and the first `_STDERR_KEPT` characters of its stderr.

    Both streams carry what the program chose to write, so each is drained as it comes and only its head is
    kept, which bounds memory.  Raises TimeoutExpired after killing the process, and WorkerError when it cannot
    be started.
    """
    stdout, stderr = bytearray(), bytearray()
    try:
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except OSError as e:
        raise WorkerError(f"cannot run {command[0]}: {e}") from e

    def drain(stream, head: bytearray, keep: int) -> None:
        for chunk in iter(lambda: stream.read(65536), b""):
            head.extend(chunk[: keep - len(head)])

    readers = [
        threading.Thread(target=drain, args=(process.stdout, stdout, MAX_RESULT_BYTES + 1), daemon=True),
        threading.Thread(target=drain, args=(process.stderr, stderr, 4 * _STDERR_KEPT), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        code = process.wait(timeout=timeout_s)
    except BaseException:  # a timeout, or an interrupt: either way the process must not outlive this call
        process.kill()
        process.wait()
        raise
    finally:
        for reader in readers:
            reader.join()
        process.stdout.close()
        process.stderr.close()
    return code, bytes(stdout), stderr.decode("utf-8", errors="replace")[:_STDERR_KEPT]


def result_cap(order: WorkOrder) -> int:
    """The most bytes an honest result for `order` can take, and never more than `MAX_RESULT_BYTES`.

    Each target's entry holds its target, then either a pmf on the stream's support (at most `support_max + 1`
    masses) or a reason of at most `MAX_ERROR_CHARS` characters.  Validating a result costs host memory well
    beyond its size, so a result is bounded by what its order can need, not only by the global cap.
    """
    bounds = support_bounds(order.view, order.targets)
    total = 0
    for target in order.targets:
        support_max = bounds.get(target.stream)
        masses = 0 if support_max is None else support_max + 1
        body = max(_MASS_BYTES * masses, _CHAR_BYTES * MAX_ERROR_CHARS)
        total += _ENTRY_BYTES + len(target.model_dump_json()) + body
    return min(MAX_RESULT_BYTES, total)


def _entries(data: bytes) -> int | None:
    """How many entries the result `data` lists, or None when it is not `{"results": [...]}`.

    Checked before the result is validated, so validation never runs over more entries than the order has
    targets (each invalid entry costs its own error report).
    """
    parsed = json.loads(data)
    if not isinstance(parsed, dict) or not isinstance(parsed.get("results"), list):
        return None
    return len(parsed["results"])


def _failures(order: WorkOrder, error: str) -> WorkResult:
    return WorkResult(results=tuple(Failure(target=t, error=error) for t in order.targets))


def _read_result(out: Path, order: WorkOrder) -> WorkResult:
    """The result the run left in `out` as the host checked it (`_host_checked`), or `no-result` for every
    target when it is not a valid result for `order`: over `result_cap(order)`, or listing other than one
    entry per target."""
    no_result = _failures(order, _NO_RESULT)
    try:
        data = _read_capped(out / RESULT_FILE, result_cap(order))
        if data is None or _entries(data) != len(order.targets):
            return no_result
        result = WorkResult.model_validate_json(data)
    except (OSError, ValueError, RecursionError):  # missing or unreadable, not UTF-8, not JSON, not a WorkResult
        return no_result
    if tuple(r.target for r in result.results) != order.targets:
        return no_result
    return _host_checked(order, result)


def _host_checked(order: WorkOrder, result: WorkResult) -> WorkResult:
    """`result` with each forecast checked against its stream's support in the order's view, read once.

    A pmf outside `[0, support_max]`, or a forecast of a stream the view cannot bound, becomes that target's
    Failure (with the reasons the in-sandbox runner gives), and every failure's reason is cut to its first
    `MAX_ERROR_CHARS` characters.
    """
    bounds = support_bounds(order.view, order.targets)
    checked: list[Prediction | Failure] = []
    for r in result.results:
        if isinstance(r, Prediction):
            reason = unbounded(bounds, r.target)
            support_max = bounds.get(r.target.stream)
            if reason is None and support_max is not None and not r.pmf.within(0, support_max):
                reason = outside_support(support_max)
            r = r if reason is None else Failure(target=r.target, error=reason)
        if isinstance(r, Failure) and len(r.error) > MAX_ERROR_CHARS:
            r = Failure(target=r.target, error=r.error[:MAX_ERROR_CHARS])
        checked.append(r)
    return WorkResult(results=tuple(checked))


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
