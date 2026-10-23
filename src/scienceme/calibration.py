"""Calibration of discrete forecasts: the nonrandomized PIT histogram and central-interval coverage.

Each observation contributes a uniform distribution on `[cdf_below, cdf_at]` (Czado, Gneiting and
Held 2009), the span the realized value occupies in the forecast's CDF.  The histogram is the average
mass that distribution puts in each equal-width bin of `[0, 1]`; coverage at level `L` is the average
mass inside the central interval `[(1 - L) / 2, (1 + L) / 2]`.  A calibrated forecaster has a flat
histogram and coverage equal to `L`.  Everything is exact interval arithmetic, no sampling.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence

from scienceme.model import Frozen
from scienceme.scoring import PointScore

class Calibration(Frozen):
    """PIT histogram (`bins` masses summing to 1) and central-interval coverage over `n` points.

    Both coverages are None when there are no points.
    """

    pit: tuple[float, ...]
    coverage_50: float | None
    coverage_90: float | None
    n: int


def _overlap(a: float, b: float, lo: float, hi: float) -> float:
    """Length of `[a, b]` inside `[lo, hi]`."""
    return max(0.0, min(b, hi) - max(a, lo))


def _closed_mass(point: PointScore, lo: float, hi: float) -> float:
    """Mass the point's uniform puts in the closed interval `[lo, hi]`; a point mass is all or nothing."""
    a, b = point.cdf_below, point.cdf_at
    if a == b:
        return 1.0 if lo <= a <= hi else 0.0
    return _overlap(a, b, lo, hi) / (b - a)


def _coverage(points: Sequence[PointScore], level: float) -> float:
    """Average mass the points put in the central interval of the given level."""
    lo, hi = (1 - level) / 2, (1 + level) / 2
    return sum(_closed_mass(p, lo, hi) for p in points) / len(points)


def calibration(points: Sequence[PointScore], bins: int = 10) -> Calibration:
    """The PIT histogram over `bins` equal-width bins, and 50% and 90% coverage, of `points`."""
    if bins < 1:
        raise ValueError(f"bins must be at least 1, got {bins}")
    n = len(points)
    if n == 0:
        return Calibration(pit=(0.0,) * bins, coverage_50=None, coverage_90=None, n=0)
    edges = [i / bins for i in range(bins + 1)]
    hist = [0.0] * bins
    for p in points:
        a, b = p.cdf_below, p.cdf_at
        if a == b:
            # A point mass belongs to one bin: the one holding it, the top bin for 1.0.
            hist[min(max(bisect_right(edges, a) - 1, 0), bins - 1)] += 1.0
            continue
        for i in range(bins):
            hist[i] += _overlap(a, b, edges[i], edges[i + 1]) / (b - a)
    return Calibration(
        pit=tuple(h / n for h in hist), coverage_50=_coverage(points, 0.5), coverage_90=_coverage(points, 0.9), n=n
    )
