"""The hub baseline: next weeks look like the last week, with the spread recent weeks have shown.

The mean is the lens's nowcast of the latest week, scaled to what the resolution vintage will report.
Log counts are treated as a driftless random walk: the variance of one step is the mean square of the
last 8 differences of `log1p` of the nowcast, and a target `n` steps past the latest week has `n` times
that.  A log-scale variance `v` is matched by a negative binomial of size `1 / (exp(v) - 1)`.
"""

from __future__ import annotations

import math

import numpy as np

from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)
DIFFERENCES = 8
# With no difference to learn the spread from, the widest size the lens fits.
NO_SPREAD_DISPERSION = 1.0


def predict(ctx: Context, target: Target) -> Pmf:
    lens = IMPORTS["lens"]
    view = ctx.view
    series = lens.nowcast(view, target.stream, target.jurisdiction)
    if not series:
        raise ValueError(f"no data for {target.jurisdiction!r} in {target.stream!r}")
    last_week, level = series[-1]
    steps = max(0, target.target_week - last_week)
    diffs = np.diff(np.log1p([max(v, 0.0) for _, v in series[-(DIFFERENCES + 1) :]]))
    if diffs.size == 0:
        dispersion = NO_SPREAD_DISPERSION
    else:
        variance = steps * float(np.mean(diffs**2))
        dispersion = math.inf if variance == 0 else 1.0 / math.expm1(variance)
    mean = level * lens.reported_fraction(view, target.stream, target.jurisdiction, target.resolution_lag)
    return lens.observe_pmf(mean, dispersion, view.spec(target.stream).support_max)
