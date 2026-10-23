"""What a program imports: `from scienceme.sdk import Context, Pmf, Target, imports_of`.

A program is a module defining `predict(ctx: Context, target: Target) -> Pmf`.
Its manifest maps import aliases to other programs (libraries); the loader in
`worker_entry` executes those first and registers them here, so a program
reaches them with `IMPORTS = imports_of(__name__)` at module level.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType, ModuleType

import numpy as np

from scienceme.archive import ArchiveView
from scienceme.model import Target
from scienceme.pmf import Pmf

__all__ = ["Context", "Pmf", "Target", "imports_of"]

_IMPORTS: dict[str, Mapping[str, ModuleType]] = {}


@dataclass(frozen=True)
class Context:
    """What `predict` receives besides the target: the as-of archive view and a per-target seed."""

    view: ArchiveView
    seed: int

    def rng(self) -> np.random.Generator:
        """A fresh generator seeded with `seed`; the same seed always gives the same stream of draws."""
        return np.random.default_rng(self.seed)


def imports_of(module_name: str) -> Mapping[str, ModuleType]:
    """The loaded imports (alias to module) of the program module `module_name`; use `imports_of(__name__)`."""
    try:
        return _IMPORTS[module_name]
    except KeyError:
        raise LookupError(f"no imports registered for {module_name!r}; the sandbox runner loads programs") from None


def register_imports(module_name: str, imports: Mapping[str, ModuleType]) -> None:
    """Record the imports of `module_name`.  Called by the loader before it executes the module, not by programs."""
    _IMPORTS[module_name] = MappingProxyType(dict(imports))
