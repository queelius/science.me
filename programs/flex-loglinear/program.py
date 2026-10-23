"""A flexible statistical baseline: an AR(2) on log counts, forecast by residual bootstrap.

`z = log1p` of the lens's nowcast over the last 16 weeks is regressed on its two previous values (with an
intercept) by least squares.  4000 paths are run forward from the last two weeks to the target week, each
step adding a residual drawn with replacement.  Each path's end is turned back into a count, scaled to
what the resolution vintage will report, rounded, and the paths' empirical distribution is the forecast.
"""

from __future__ import annotations

import numpy as np

from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)
WINDOW = 16
PATHS = 4000
ORDER = 2
# An intercept and ORDER lags, with at least one residual degree of freedom.
MIN_POINTS = 2 * ORDER + 2


def predict(ctx: Context, target: Target) -> Pmf:
    lens = IMPORTS["lens"]
    view = ctx.view
    support_max = view.spec(target.stream).support_max
    series = lens.nowcast(view, target.stream, target.jurisdiction)[-WINDOW:]
    if len(series) < MIN_POINTS:
        raise ValueError(f"an AR({ORDER}) needs {MIN_POINTS} weeks of data, {target.jurisdiction!r} has {len(series)}")
    z = np.log1p([max(v, 0.0) for _, v in series])
    n = len(z)
    lags = np.column_stack([z[ORDER - k : n - k] for k in range(1, ORDER + 1)])  # column k-1 is z lagged k weeks
    design = np.column_stack([np.ones(n - ORDER), lags])
    coef, *_ = np.linalg.lstsq(design, z[ORDER:])
    residuals = z[ORDER:] - design @ coef

    ceiling = np.log1p(support_max)  # no path's count exceeds the support
    rng = ctx.rng()
    state = np.tile(z[::-1][:ORDER], (PATHS, 1))  # per path, the last ORDER values, newest first
    for _ in range(target.target_week - series[-1][0]):
        step = coef[0] + state @ coef[1:] + rng.choice(residuals, PATHS)
        state = np.column_stack([np.clip(step, 0.0, ceiling), state[:, :-1]])
    fraction = lens.reported_fraction(view, target.stream, target.jurisdiction, target.resolution_lag)
    counts = np.clip(np.rint(np.expm1(state[:, 0]) * fraction), 0, support_max).astype(np.int64)
    return Pmf.from_samples(counts)
