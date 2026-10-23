"""Predictive distributions over non-negative integer counts.

A `Pmf` is the value a program returns for one target: a probability mass
function on a contiguous integer interval `[lo, hi]`.  It is a frozen pydantic
model, so it serializes to and from JSON with no extra code.

Scoring uses the floored distribution `(1 - eps) * pmf + eps * Uniform{0..support_max}`
(see `floored_log_prob` and `floored_cdf`), which bounds the log loss of any
single target at `log(eps / (support_max + 1))`.  All logarithms are natural, so
scores and entropies are in nats.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import numpy as np
from pydantic import BaseModel, ConfigDict, model_validator
from scipy.special import entr

# Tolerance on a normalized, stored Pmf.
_SUM_TOL = 1e-9
# Tolerance on raw input to `from_probs` and `mix` before renormalizing.
_RAW_SUM_TOL = 1e-6


class PmfError(ValueError):
    """Raised when probabilities do not form a valid distribution."""


def _check_probs(probs: np.ndarray, tol: float, what: str) -> None:
    """Raise PmfError unless `probs` is a non-empty finite non-negative vector summing to 1 within `tol`."""
    if probs.ndim != 1 or probs.size == 0:
        raise PmfError(f"{what} must be a non-empty one-dimensional sequence")
    if not np.all(np.isfinite(probs)):
        raise PmfError(f"{what} must be finite")
    if np.any(probs < 0):
        raise PmfError(f"{what} must be non-negative")
    total = float(probs.sum())
    if abs(total - 1.0) > tol:
        raise PmfError(f"{what} must sum to 1 within {tol:g}, got {total!r}")


class Pmf(BaseModel):
    """Probability mass on the integers `lo .. hi` (inclusive); `p[i]` is the mass at `lo + i`.

    Invariants: every mass is finite and non-negative, the masses sum to 1
    within 1e-9, and both end masses are strictly positive (zero tails are
    trimmed; interior zeros are kept).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    lo: int
    p: tuple[float, ...]

    @model_validator(mode="after")
    def _check_invariants(self) -> Pmf:
        arr = np.asarray(self.p, dtype=float)
        _check_probs(arr, _SUM_TOL, "p")
        if arr[0] <= 0 or arr[-1] <= 0:
            raise PmfError("p[0] and p[-1] must be positive (trim zero tails)")
        return self

    @classmethod
    def from_probs(cls, lo: int, probs: Sequence[float]) -> Pmf:
        """Build from raw masses starting at `lo`; trims zero tails and renormalizes.

        The raw masses must sum to 1 within 1e-6.
        """
        arr = np.asarray(probs, dtype=float)
        _check_probs(arr, _RAW_SUM_TOL, "probs")
        nonzero = np.flatnonzero(arr > 0)
        first, last = int(nonzero[0]), int(nonzero[-1])
        trimmed = arr[first : last + 1]
        trimmed = trimmed / trimmed.sum()
        return cls(lo=lo + first, p=tuple(trimmed.tolist()))

    @classmethod
    def point(cls, value: int) -> Pmf:
        """All mass on `value`."""
        return cls(lo=value, p=(1.0,))

    @classmethod
    def uniform(cls, lo: int, hi: int) -> Pmf:
        """Equal mass on every integer in `lo .. hi` (inclusive)."""
        if hi < lo:
            raise PmfError(f"uniform needs lo <= hi, got lo={lo}, hi={hi}")
        n = hi - lo + 1
        return cls.from_probs(lo, np.full(n, 1.0 / n))

    @classmethod
    def from_samples(cls, samples: Sequence[int]) -> Pmf:
        """Empirical distribution of integer `samples` (interior zeros are kept)."""
        arr = np.asarray(samples)
        if arr.ndim != 1 or arr.size == 0:
            raise PmfError("samples must be a non-empty one-dimensional sequence")
        if not np.issubdtype(arr.dtype, np.integer):
            raise PmfError("samples must be integers")
        lo = int(arr.min())
        counts = np.bincount(arr - lo)
        return cls.from_probs(lo, counts / counts.sum())

    @property
    def hi(self) -> int:
        """Largest integer in the support (inclusive)."""
        return self.lo + len(self.p) - 1

    def prob(self, y: int) -> float:
        """P(Y = y); zero outside the support."""
        if y < self.lo or y > self.hi:
            return 0.0
        return self.p[y - self.lo]

    def cdf(self, y: int) -> float:
        """P(Y <= y)."""
        if y < self.lo:
            return 0.0
        if y >= self.hi:
            return 1.0
        return float(np.asarray(self.p)[: y - self.lo + 1].sum())

    def entropy(self) -> float:
        """Shannon entropy in nats."""
        return float(entr(np.asarray(self.p)).sum())

    def within(self, lo: int, hi: int) -> bool:
        """True when the whole support lies inside `[lo, hi]`."""
        return lo <= self.lo and self.hi <= hi


def mix(pmfs: Sequence[Pmf], weights: Sequence[float]) -> Pmf:
    """Weighted mixture of `pmfs`, with supports aligned on their common span.

    The weights must be finite, non-negative and sum to 1 within 1e-6.
    """
    if len(pmfs) == 0 or len(pmfs) != len(weights):
        raise PmfError("mix needs the same non-zero number of pmfs and weights")
    w = np.asarray(weights, dtype=float)
    _check_probs(w, _RAW_SUM_TOL, "weights")
    lo = min(m.lo for m in pmfs)
    hi = max(m.hi for m in pmfs)
    acc = np.zeros(hi - lo + 1)
    for m, wi in zip(pmfs, w.tolist()):
        acc[m.lo - lo : m.hi - lo + 1] += wi * np.asarray(m.p)
    return Pmf.from_probs(lo, acc)


def _check_floor(eps: float, support_max: int) -> None:
    if not 0 < eps <= 1:
        raise PmfError(f"eps must be in (0, 1], got {eps!r}")
    if support_max < 0:
        raise PmfError(f"support_max must be >= 0, got {support_max!r}")


def floored_log_prob(pmf: Pmf, y: int, eps: float, support_max: int) -> float:
    """Log mass (nats) of `y` under `(1 - eps) * pmf + eps * Uniform{0..support_max}`."""
    _check_floor(eps, support_max)
    return math.log((1 - eps) * pmf.prob(y) + eps / (support_max + 1))


def floored_cdf(pmf: Pmf, y: int, eps: float, support_max: int) -> float:
    """P(Y <= y) under `(1 - eps) * pmf + eps * Uniform{0..support_max}`."""
    _check_floor(eps, support_max)
    uniform_cdf = (min(max(y, -1), support_max) + 1) / (support_max + 1)
    return (1 - eps) * pmf.cdf(y) + eps * uniform_cdf
