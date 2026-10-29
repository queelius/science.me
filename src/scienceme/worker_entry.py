"""The in-sandbox runner: load a program and its imports, call `predict` once per target.

This is the code that runs INSIDE the sandbox (a subprocess or a container).
It reads a `WorkOrder` (`order.json`), loads the program from
`work/programs/<hex>/` and writes a `WorkResult` (`result.json`).  A target
that goes wrong (the program raises, returns something that is not a valid
`Pmf`, or puts mass outside `[0, support_max]`) becomes a `Failure` for that
target alone; a program that cannot be loaded fails every target with an
error starting `load:`.  Loaded modules stay in `sys.modules` for the life of
the process, since the sandbox runs one `execute` per process.

Program code is untrusted, so what it can raise is contained: `Exception` and
`SystemExit` (a program calling `sys.exit`) become Failures; `KeyboardInterrupt`
and `GeneratorExit` are not the program's to answer for and propagate.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import string
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from types import CodeType, ModuleType
from typing import Annotated, Literal

from pydantic import Field

from scienceme.archive import ArchiveView
from scienceme.manifest import ProgramManifest
from scienceme.model import Frozen, Target
from scienceme.pmf import Pmf
from scienceme.sdk import Context, register_imports
from scienceme.workspace import read_model

ORDER_FILE = "order.json"
RESULT_FILE = "result.json"
PROGRAMS_DIR = "programs"

_HASH_PREFIX = "sha256:"
_MODULE_PREFIX = "scienceme_program_"
_MODULE_HEX = 16
_ENCODING = "utf-8"
# What program code may raise without taking the runner down.
_CONTAINED = (Exception, SystemExit)


class WorkOrder(Frozen):
    """What the sandbox needs.

    `program` is the closure hash to run; `manifests` holds the manifest of every member of its
    closure, keyed by closure hash.
    """

    program: str
    manifests: dict[str, ProgramManifest]
    view: ArchiveView
    targets: tuple[Target, ...]


class Prediction(Frozen):
    """The program's forecast for one target."""

    kind: Literal["prediction"] = "prediction"
    target: Target
    pmf: Pmf


# The most of a failure's reason that is kept, in characters.  The reason is the program's to choose (an
# exception's message) and it is stored in the record, so it is cut here and again by the host.
MAX_ERROR_CHARS = 2000


class Failure(Frozen):
    """One target that got no forecast, and why."""

    kind: Literal["failure"] = "failure"
    target: Target
    error: str


class WorkResult(Frozen):
    """One result per target of the order, in the order's sequence."""

    results: tuple[Annotated[Prediction | Failure, Field(discriminator="kind")], ...]


class LoadError(Exception):
    """A program or one of its imports cannot be loaded."""


class _Rejected(Exception):
    """What `predict` returned is unusable; the message is the target's error."""


class _SourceLoader(importlib.machinery.SourceFileLoader):
    """Compiles the source every time.

    `closure_hash` ignores `__pycache__`, so a stale or planted `.pyc` beside the source
    must never run in place of the hashed source.
    """

    def get_code(self, fullname: str) -> CodeType:
        return self.source_to_code(self.get_data(self.path), self.path)


def _describe(error: BaseException) -> str:
    """`Type: message`, or just `Type` when the program's own `__str__` raises."""
    name = type(error).__name__
    try:
        return f"{name}: {error}"
    except _CONTAINED:
        return name


def program_dirname(closure_hash: str) -> str:
    """The directory name of a program under `work/programs/`: the hex digest after `sha256:`."""
    digest = closure_hash.removeprefix(_HASH_PREFIX)
    if digest == closure_hash or not digest or not set(digest) <= set(string.hexdigits.lower()):
        raise ValueError(f"not a closure hash: {closure_hash!r}")
    return digest


def derive_seed(program: str, target: Target) -> int:
    """A 64-bit seed fixed by the program and the target: the first 8 bytes of sha256(program + "|" + target JSON)."""
    digest = hashlib.sha256(f"{program}|{target.model_dump_json()}".encode(_ENCODING)).digest()
    return int.from_bytes(digest[:8], "big")


class _Loader:
    """Loads a program and its import closure from `work/programs/`, each closure member once."""

    def __init__(self, order: WorkOrder, work: Path) -> None:
        self._manifests = order.manifests
        self._programs = work / PROGRAMS_DIR
        self._loaded: dict[str, ModuleType] = {}
        self._loading: list[str] = []

    def predict_of(self, program: str) -> Callable[[Context, Target], Pmf]:
        """The `predict` function of `program`."""
        predict = getattr(self.load(program), "predict", None)
        if not callable(predict):
            raise LoadError("the program defines no predict function")
        return predict

    def load(self, program: str) -> ModuleType:
        if program in self._loaded:
            return self._loaded[program]
        if program in self._loading:
            raise LoadError(f"import cycle: {' -> '.join([*self._loading, program])}")
        manifest = self._manifests.get(program)
        if manifest is None:
            raise LoadError(f"no manifest for {program} in the work order")
        entry = self._entry(program, manifest)
        self._loading.append(program)
        try:
            imports = {alias: self.load(imported) for alias, imported in manifest.imports.items()}
        finally:
            self._loading.pop()
        module = self._execute(program, manifest, entry, imports)
        self._loaded[program] = module
        return module

    def _entry(self, program: str, manifest: ProgramManifest) -> Path:
        """The entry file of `program`, which must lie inside the program's own directory."""
        directory = (self._programs / program_dirname(program)).resolve()
        if not directory.is_dir():
            raise LoadError(f"{manifest.name}: no program directory {directory.name}")
        entry = (directory / manifest.entry).resolve()
        if not entry.is_relative_to(directory):
            raise LoadError(f"{manifest.name}: entry {manifest.entry!r} is outside the program directory")
        if not entry.is_file():
            raise LoadError(f"{manifest.name}: entry {manifest.entry!r} is not a file")
        return entry

    @staticmethod
    def _execute(program: str, manifest: ProgramManifest, entry: Path, imports: dict[str, ModuleType]) -> ModuleType:
        name = _MODULE_PREFIX + program_dirname(program)[:_MODULE_HEX]
        loader = _SourceLoader(name, str(entry))
        module = importlib.util.module_from_spec(importlib.util.spec_from_file_location(name, entry, loader=loader))
        register_imports(name, imports)
        sys.modules[name] = module
        try:
            loader.exec_module(module)
        except _CONTAINED as e:
            sys.modules.pop(name, None)
            raise LoadError(f"{manifest.name}: {_describe(e)}") from e
        return module


def support_bounds(view: ArchiveView, targets: Sequence[Target]) -> dict[str, int | None]:
    """`support_max` of each target stream the view knows, read once so a program cannot move the bounds."""
    return {t.stream: view.specs[t.stream].support_max for t in targets if t.stream in view.specs}


def unbounded(bounds: dict[str, int | None], target: Target) -> str | None:
    """Why `target` can have no forecast under `bounds` (from `support_bounds`), or None when it can."""
    if target.stream not in bounds:
        return f"unknown stream {target.stream!r}"
    if bounds[target.stream] is None:
        return f"stream {target.stream!r} has no support (it is not a count stream)"
    return None


def outside_support(support_max: int) -> str:
    """The reason given for a pmf with mass outside `[0, support_max]`."""
    return f"pmf outside support [0, {support_max}]"


def _checked(result: object, support_max: int) -> Pmf:
    """`result` as a validated Pmf inside `[0, support_max]`; `_Rejected` says why when it is not."""
    if not isinstance(result, Pmf):
        raise _Rejected(f"predict returned {type(result).__name__}, expected Pmf")
    try:  # a Pmf built around its validation (model_construct), or a subclass that misbehaves, must not get through
        pmf = Pmf.model_validate(result.model_dump())
    except _CONTAINED as e:
        raise _Rejected(f"invalid Pmf: {_describe(e)}") from e
    if not pmf.within(0, support_max):
        raise _Rejected(outside_support(support_max))
    return pmf


def _forecast(
    predict: Callable[[Context, Target], Pmf], order: WorkOrder, bounds: dict[str, int | None], target: Target
) -> Prediction | Failure:
    """Run `predict` on one target; anything wrong with the target or the return value is that target's Failure."""
    reason = unbounded(bounds, target)
    if reason is not None:
        return Failure(target=target, error=reason)
    support_max = bounds[target.stream]
    assert support_max is not None  # `unbounded` said so
    try:
        result = predict(Context(view=order.view, seed=derive_seed(order.program, target)), target)
        return Prediction(target=target, pmf=_checked(result, support_max))
    except _Rejected as e:
        return Failure(target=target, error=str(e)[:MAX_ERROR_CHARS])
    except _CONTAINED as e:
        return Failure(target=target, error=_describe(e)[:MAX_ERROR_CHARS])


def execute(order: WorkOrder, work: Path) -> WorkResult:
    """Run the order's program on every target; the programs live in `work/programs/<hex>/`."""
    try:
        predict = _Loader(order, work).predict_of(order.program)
    except _CONTAINED as e:
        error = (f"load: {e}" if isinstance(e, LoadError) else f"load: {_describe(e)}")[:MAX_ERROR_CHARS]
        return WorkResult(results=tuple(Failure(target=t, error=error) for t in order.targets))
    bounds = support_bounds(order.view, order.targets)
    return WorkResult(results=tuple(_forecast(predict, order, bounds, t) for t in order.targets))


def main(argv: Sequence[str] | None = None) -> int:
    """`worker_entry WORK_DIR OUT_DIR`: read `WORK_DIR/order.json`, write `OUT_DIR/result.json`."""
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: python -m scienceme.worker_entry WORK_DIR OUT_DIR", file=sys.stderr)
        return 2
    work, out = Path(args[0]), Path(args[1])
    result = execute(read_model(work / ORDER_FILE, WorkOrder), work)
    out.mkdir(parents=True, exist_ok=True)
    (out / RESULT_FILE).write_text(result.model_dump_json(), encoding=_ENCODING)
    return 0


if __name__ == "__main__":
    sys.exit(main())
