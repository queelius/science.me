"""The admissions lens: how a weekly count is reported, and the observation noise around it.

A week's count is first published in the issue after the week and revised upward in later issues as
reports complete.  `completeness` estimates, per jurisdiction, the share of a week's eventual count that is
reported `d + 1` issues after the week (chain ladder over consecutive vintages); `nowcast` divides the
latest vintage by it.  `observe_pmf` is the negative binomial observation model and `fit_dispersion` its
method-of-moments size.

A library: it has no `predict` and is imported by the programs that forecast.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
from scipy import stats

from scienceme.sdk import Pmf

if TYPE_CHECKING:
    from scienceme.archive import ArchiveView

# The negative binomial is cut where its upper tail holds less than this much mass.
TAIL = 1e-12
# The widest observation noise the lens fits: a negative binomial size below 1 is not estimated.
MIN_DISPERSION = 1.0


def _vintages(view: ArchiveView, stream: str, jurisdiction: str) -> dict[int, dict[int, float]]:
    """issue -> {week: value} for `jurisdiction` in every visible vintage of `stream`."""
    return {
        v.issue: {r.week: r.value for r in v.rows if r.jurisdiction == jurisdiction} for v in view.history(stream)
    }


def completeness(view: ArchiveView, stream: str, jurisdiction: str, max_lag: int = 8) -> np.ndarray:
    """`c[d]`: the share of a week's eventual count reported `d + 1` issues after the week, for d = 0 .. max_lag.

    Weeks `max_lag + 1` or more issues old are taken as complete, so `c[max_lag]` is 1.0 (and so is every
    later lag).  Each development factor `c[d + 1] / c[d]` is the ratio of summed values a week showed in
    consecutive issues at lags d and d + 1 (chain ladder).  A lag with no such pairs, or whose earlier sum
    is zero, has factor 1: nothing shows it revising.
    """
    vintages = _vintages(view, stream, jurisdiction)
    later = np.zeros(max_lag)
    earlier = np.zeros(max_lag)
    for issue, rows in vintages.items():
        following = vintages.get(issue + 1)
        if following is None:
            continue
        for week, value in rows.items():
            d = issue - week - 1
            if 0 <= d < max_lag and week in following:
                earlier[d] += value
                later[d] += following[week]
    factors = np.divide(later, earlier, out=np.ones(max_lag), where=(earlier > 0) & (later > 0))
    c = np.ones(max_lag + 1)
    for d in reversed(range(max_lag)):
        c[d] = c[d + 1] / factors[d]
    return c


def _at_lag(c: np.ndarray, lag: int) -> float:
    """The completeness `c` of a week reported `lag` issues after it (`lag` >= 1); lags past the table are complete."""
    return float(c[min(lag - 1, len(c) - 1)])


def reported_fraction(view: ArchiveView, stream: str, jurisdiction: str, lag: int) -> float:
    """The share of a week's eventual count reported `lag` issues after the week (`lag` >= 1)."""
    return _at_lag(completeness(view, stream, jurisdiction), lag)


def nowcast(view: ArchiveView, stream: str, jurisdiction: str) -> list[tuple[int, float]]:
    """(week, estimated eventual count) for every week of the latest vintage: its value divided by completeness."""
    history = view.history(stream)
    if not history:
        return []
    latest = history[-1].issue
    c = completeness(view, stream, jurisdiction)
    return [(week, value / _at_lag(c, latest - week)) for week, value in view.series(stream, jurisdiction)]


def _upper_cut(dist: stats.rv_discrete, support_max: int) -> int:
    """The `1 - TAIL` quantile of `dist`, or `support_max` when that is lower: the smallest y in
    0 .. support_max with `P(Y <= y) >= 1 - TAIL`.

    Found by bisection on the cdf, since `ppf` can stall for a negative binomial of tiny size.
    """
    if dist.cdf(support_max) < 1 - TAIL:
        return support_max
    lo, hi = 0, support_max  # the cut lies in lo .. hi
    while lo < hi:
        mid = (lo + hi) // 2
        if dist.cdf(mid) >= 1 - TAIL:
            hi = mid
        else:
            lo = mid + 1
    return hi


def observe_pmf(mean: float, dispersion: float, support_max: int) -> Pmf:
    """Negative binomial with `mean` and size `dispersion` (variance `mean + mean**2 / dispersion`) on 0 .. support_max.

    An infinite size is the Poisson.  The upper tail beyond the `1 - TAIL` quantile is cut, as is anything
    above `support_max`, and the rest renormalized.  ValueError for a mean that is not finite and
    non-negative or a size that is not positive.
    """
    if not (math.isfinite(mean) and mean >= 0):
        raise ValueError(f"mean must be finite and non-negative, got {mean!r}")
    if not dispersion > 0:
        raise ValueError(f"dispersion must be positive, got {dispersion!r}")
    if mean == 0:
        return Pmf.point(0)
    if math.isinf(dispersion):
        dist = stats.poisson(mean)
    else:
        dist = stats.nbinom(dispersion, dispersion / (dispersion + mean))
    hi = _upper_cut(dist, support_max)
    log_p = dist.logpmf(np.arange(hi + 1))
    p = np.exp(log_p - log_p.max())
    return Pmf.from_probs(0, p / p.sum())


def fit_dispersion(observed: np.ndarray, expected: np.ndarray) -> float:
    """Method-of-moments negative binomial size of `observed` around `expected`, floored at MIN_DISPERSION.

    With `phi = sum((o - e)**2 - e) / sum(e**2)`, the size is `1 / phi`: infinite (Poisson) when the
    counts vary no more than Poisson noise would.  With no positive expectation to estimate from, the
    widest size, MIN_DISPERSION.
    """
    o = np.asarray(observed, dtype=float)
    e = np.asarray(expected, dtype=float)
    scale = float(np.sum(e**2))
    if scale <= 0:
        return MIN_DISPERSION
    excess = float(np.sum((o - e) ** 2 - e))
    if excess <= 0:
        return math.inf
    return max(MIN_DISPERSION, scale / excess)
