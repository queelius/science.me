"""The ED-visits lens: how a weekly count of emergency-department visits is reported, and the noise around it.

A week's count is first published in the issue after the week and revised upward in the next issue or two
as late records arrive.  `completeness` estimates the share of a week's eventual count that is reported
`d + 1` issues after the week by the chain ladder over consecutive vintages, pooled over every jurisdiction
of the stream (one curve per stream); `nowcast` divides the latest vintage by it.  `observe_pmf` is the
negative binomial observation model and `fit_dispersion` its method-of-moments size, never narrower than
MAX_DISPERSION.

`observe_pmf` and `truncate` cut the upper tail of every pmf they build where it holds less than `TAIL` of
the mass.  What is cut is left to the uniform floor the scorer mixes into every forecast.

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

# A pmf is cut where its upper tail holds less than this much mass: a long, almost empty tail costs memory and
# time out of proportion to the probability it holds, and the scoring floor covers it.
TAIL = 1e-6
# Revisions are followed for this many issues after a week's first report; a week reported MAX_LAG + 1 or more
# issues after it is taken as complete.  In the archive an ED week is complete by its third report.
MAX_LAG = 4
# The widest observation noise the lens fits: a negative binomial size below 1 is not estimated.
MIN_DISPERSION = 1.0
# The narrowest observation noise the lens fits: ED counts vary at least this much beyond Poisson.  Fitted to
# the w-alpha ED archive through issue 10 (maximum likelihood around a smooth weekly curve, pooled over the
# jurisdictions with counts in the hundreds, corrected for the curve's parameters: sizes 12 to 21).
MAX_DISPERSION = 15.0


def completeness(view: ArchiveView, stream: str, max_lag: int = MAX_LAG) -> np.ndarray:
    """`c[d]`: the share of a week's eventual count reported `d + 1` issues after the week, for d = 0 .. max_lag.

    Weeks `max_lag + 1` or more issues old are taken as complete, so `c[max_lag]` is 1.0 (and so is every
    later lag).  Each development factor `c[d + 1] / c[d]` is the ratio of summed values that weeks of every
    jurisdiction showed in consecutive issues at lags d and d + 1 (chain ladder, pooled over jurisdictions).
    A lag with no such pairs, or whose earlier sum is zero, has factor 1: nothing shows it revising.
    """
    vintages = {v.issue: {(r.jurisdiction, r.week): r.value for r in v.rows} for v in view.history(stream)}
    later = np.zeros(max_lag)
    earlier = np.zeros(max_lag)
    for issue, rows in vintages.items():
        following = vintages.get(issue + 1)
        if following is None:
            continue
        for (jurisdiction, week), value in rows.items():
            d = issue - week - 1
            if 0 <= d < max_lag and (jurisdiction, week) in following:
                earlier[d] += value
                later[d] += following[jurisdiction, week]
    factors = np.divide(later, earlier, out=np.ones(max_lag), where=(earlier > 0) & (later > 0))
    c = np.ones(max_lag + 1)
    for d in reversed(range(max_lag)):
        c[d] = c[d + 1] / factors[d]
    return c


def _at_lag(c: np.ndarray, lag: int) -> float:
    """The completeness `c` of a week reported `lag` issues after it (`lag` >= 1); lags past the table are complete."""
    return float(c[min(lag - 1, len(c) - 1)])


def reported_fraction(view: ArchiveView, stream: str, jurisdiction: str, lag: int) -> float:
    """The share of a week's eventual count reported `lag` issues after the week (`lag` >= 1).

    The curve is the stream's, so it is the same for every `jurisdiction`.
    """
    return _at_lag(completeness(view, stream), lag)


def nowcast(view: ArchiveView, stream: str, jurisdiction: str) -> list[tuple[int, float]]:
    """(week, estimated eventual count) for every week of the latest vintage: its value divided by completeness."""
    history = view.history(stream)
    if not history:
        return []
    latest = history[-1].issue
    c = completeness(view, stream)
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
    above `support_max`, and the rest renormalized; the lower end is not touched.  ValueError for a mean that
    is not finite and non-negative or a size that is not positive.
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


def truncate(pmf: Pmf) -> Pmf:
    """`pmf` with its upper tail cut at its `1 - TAIL` quantile (the smallest y with `P(Y <= y) >= 1 - TAIL`)
    and renormalized.  The lower end is not touched, and a pmf with no tail that thin is returned as it is.
    """
    cdf = np.cumsum(pmf.p)
    keep = int(np.searchsorted(cdf, 1 - TAIL)) + 1
    if keep >= len(pmf.p):
        return pmf
    p = np.asarray(pmf.p[:keep])
    return Pmf.from_probs(pmf.lo, p / p.sum())


def fit_dispersion(observed: np.ndarray, expected: np.ndarray) -> float:
    """Method-of-moments negative binomial size of `observed` around `expected`, within MIN_DISPERSION ..
    MAX_DISPERSION.

    With `phi = sum((o - e)**2 - e) / sum(e**2)`, the size is `1 / phi`, but never more than MAX_DISPERSION:
    a theory fitted to a few weeks takes part of the noise into its parameters, so its residuals may widen
    the noise the archive shows but not narrow it.  Counts that vary no more than Poisson noise would get
    MAX_DISPERSION; with no positive expectation to estimate from, the widest size, MIN_DISPERSION.
    """
    o = np.asarray(observed, dtype=float)
    e = np.asarray(expected, dtype=float)
    scale = float(np.sum(e**2))
    if scale <= 0:
        return MIN_DISPERSION
    excess = float(np.sum((o - e) ** 2 - e))
    if excess <= 0:
        return MAX_DISPERSION
    return min(MAX_DISPERSION, max(MIN_DISPERSION, scale / excess))
