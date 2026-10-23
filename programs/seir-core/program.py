"""A seasonally forced SEIR model of weekly hospital admissions, fitted per jurisdiction.

The state is the share of the population susceptible, exposed and infectious, stepped daily.  A day
infects `S * (1 - exp(-beta * I))`; exposed people become infectious after a mean latent period of 2
days and infectious people recover after a mean infectious period of 3 days (daily transition
probabilities 1/2 and 1/3).  Transmission is constant within a week:

    beta = beta0 * (1 + amplitude * cos(2 pi (week - peak_week) / 52))
                 * exp(-covariate_x * x[week]) * (1 - school * closed[week])

with `closed = 1 - term[week]`, overridden by an active `schools_closed` intervention.  A
`vaccinate_fraction` intervention moves that fraction of the susceptibles to recovered at the start of
its start week.  Expected admissions in a week are `scale * new infections` that week.

`Mechanisms` carries the published effect sizes a theory program asserts (0.0 means the mechanism is
absent).  A library: theory programs call `predict_target` with their mechanisms and the lens.

A forecast carries two uncertainties: the lens's observation noise around the expected count, and the
fit's uncertainty about the parameters.  The second is the fit's Laplace approximation, regularized by a
uniform prior over the parameter box (below) and truncated to it, represented by draws at deterministic
quasi-random points (so a forecast is a function of its data).  Each draw is simulated to the target
week; the simulation, not a linearization, carries the parameters' uncertainty into the forecast, so a
draw that runs out of susceptibles early and one that keeps growing are both honoured.  Weeks of data
rarely determine when susceptibles run out, so extrapolation is where the draws disagree, and the
forecast widens with the lead past the data by itself.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import ModuleType
from typing import TYPE_CHECKING

import numpy as np
from scipy import stats
from scipy.linalg import solve_triangular
from scipy.optimize import least_squares

from scienceme.sdk import Context, Pmf, Target

if TYPE_CHECKING:
    from scienceme.archive import ArchiveView
    from scienceme.model import Intervention

LATENT_DAYS = 2.0
INFECTIOUS_DAYS = 3.0
DAYS_PER_WEEK = 7
WEEKS_PER_YEAR = 52.0
SCHOOLS_CLOSED = "schools_closed"
VACCINATE_FRACTION = "vaccinate_fraction"
COVARIATE_ROLE = "covariate-x"
TERM_ROLE = "school-term"
# Parameter draws (a power of 2, for the Sobol points) and the fixed scrambling of their sequence.
_DRAWS = 256
_QMC_SEED = 0
# Under Poisson noise a residual weighted by sqrt(1 + count) has variance about 1: no fit is taken as
# closer than that, so an exact fit (no residual at all) still has a spread.
_POISSON_RESIDUAL_VARIANCE = 1.0
# Fewer draws inside the box than this cannot describe the parameters' spread; the forecast is the fit alone.
_MIN_DRAWS = 32
# A ridge of this share of the mean diagonal restores a precision that rounding left not positive definite.
_RIDGE = 1e-8

# Fitting works on theta = (log beta0, a, b, s0, log i0, log scale), where the seasonal term
# amplitude * cos(2 pi (week - peak_week) / 52) is written a * cos(2 pi week / 52) + b * sin(2 pi week / 52):
# smooth in (a, b), with no wrap-around in the peak week.  Bounds keep amplitude below 1 and R0 = 3 * beta0
# between 0.15 and 9.
# The box is also the prior: uniform over it, so its precision as a Gaussian is 12 / width^2.
_LOWER = np.array([math.log(0.05), -0.7, -0.7, 0.05, math.log(1e-9), math.log(1e-3)])
_UPPER = np.array([math.log(3.0), 0.7, 0.7, 1.0, math.log(0.05), math.log(1e12)])
_PRIOR_PRECISION = np.diag(12.0 / (_UPPER - _LOWER) ** 2)
_STARTS = tuple((beta0, i0) for beta0 in (0.4, 0.8) for i0 in (1e-5, 1e-3))
_START_S0 = 0.9


@dataclass(frozen=True)
class Mechanisms:
    """Published effect sizes; 0.0 means the mechanism is absent."""

    covariate_x: float
    school: float


@dataclass(frozen=True)
class Params:
    """A jurisdiction's fitted epidemic: transmission, seasonality, initial state (at the first fitted week), scale."""

    beta0: float
    amplitude: float
    peak_week: float
    s0: float
    i0: float
    scale: float


def _closed(week: int, term: Mapping[int, float], interventions: Sequence[Intervention], jurisdiction: str) -> float:
    """The share of schools closed in `week`: an active intervention's value, else `1 - term[week]` (in session
    when unknown)."""
    closed = 1.0 - term.get(week, 1.0)
    for intervention in interventions:
        if intervention.variable == SCHOOLS_CLOSED and intervention.active(week, jurisdiction):
            closed = intervention.value
    return closed


def _check(interventions: Sequence[Intervention]) -> None:
    for intervention in interventions:
        if intervention.variable not in (SCHOOLS_CLOSED, VACCINATE_FRACTION):
            raise ValueError(f"the SEIR core does not model the intervention variable {intervention.variable!r}")


def expected(
    params: Params,
    weeks: Sequence[int],
    x: Mapping[int, float],
    term: Mapping[int, float],
    mech: Mechanisms,
    interventions: Sequence[Intervention],
    jurisdiction: str,
) -> np.ndarray:
    """Expected admissions in each of `weeks`, simulating from the start of the earliest of them.

    The state `(s0, i0)` is the one at the start of `min(weeks)`, with exposed `i0 * 2 / 3` (the ratio of
    the latent and infectious periods).  A week missing from `x` has covariate 0; one missing from `term`
    is in session.  ValueError for an intervention variable the model does not have.
    """
    _check(interventions)
    weeks = list(weeks)
    if not weeks:
        return np.zeros(0)
    first, last = min(weeks), max(weeks)
    s, e, i = params.s0, params.i0 * LATENT_DAYS / INFECTIOUS_DAYS, params.i0
    by_week: dict[int, float] = {}
    for week in range(first, last + 1):
        for intervention in interventions:
            if (
                intervention.variable == VACCINATE_FRACTION
                and intervention.start_week == week
                and intervention.active(week, jurisdiction)
            ):
                s -= intervention.value * s
        seasonal = 1.0 + params.amplitude * math.cos(2 * math.pi * (week - params.peak_week) / WEEKS_PER_YEAR)
        covariate = math.exp(-mech.covariate_x * x.get(week, 0.0))
        school = 1.0 - mech.school * _closed(week, term, interventions, jurisdiction)
        beta = max(0.0, params.beta0 * seasonal * covariate * school)
        infected = 0.0
        for _ in range(DAYS_PER_WEEK):
            infections = s * -math.expm1(-beta * i)
            onsets = e / LATENT_DAYS
            recoveries = i / INFECTIOUS_DAYS
            s -= infections
            e += infections - onsets
            i += onsets - recoveries
            infected += infections
        by_week[week] = params.scale * infected
    return np.array([by_week[w] for w in weeks])


def _params(theta: np.ndarray) -> Params:
    log_beta0, a, b, s0, log_i0, log_scale = (float(v) for v in theta)
    peak = (WEEKS_PER_YEAR / (2 * math.pi)) * math.atan2(b, a) % WEEKS_PER_YEAR
    return Params(
        beta0=math.exp(log_beta0),
        amplitude=math.hypot(a, b),
        peak_week=peak,
        s0=s0,
        i0=math.exp(log_i0),
        scale=math.exp(log_scale),
    )


def fit(
    series: Sequence[tuple[int, float]],
    x: Mapping[int, float],
    term: Mapping[int, float],
    mech: Mechanisms,
    interventions: Sequence[Intervention] = (),
    jurisdiction: str = "",
) -> Params:
    """Least-squares fit on `log1p` of the (week, count) `series`, with the mechanisms held at `mech`.

    Each week's residual is weighted by `sqrt(1 + count)`, its precision on the log scale under Poisson
    noise, so a week of a few admissions does not count as much as a week of hundreds.  The initial state
    is the one at the series' first week.  `interventions` that acted on the series
    (an arm's own history) are simulated in the fit as they will be in the forecast.  Several starting
    points are tried and the best fit kept.  ValueError for an empty series.
    """
    return _params(_Problem(series, x, term, mech, interventions, jurisdiction).best().x)


class _Problem:
    """The least-squares problem of one series: weighted residuals on the `log1p` scale, as a function of theta."""

    def __init__(
        self,
        series: Sequence[tuple[int, float]],
        x: Mapping[int, float],
        term: Mapping[int, float],
        mech: Mechanisms,
        interventions: Sequence[Intervention],
        jurisdiction: str,
    ) -> None:
        if not series:
            raise ValueError("cannot fit an empty series")
        weeks = [w for w, _ in series]
        self.observed = np.log1p(np.array([max(v, 0.0) for _, v in series]))
        self.weights = np.sqrt(np.expm1(self.observed) + 1.0)
        self.span = range(min(weeks), max(weeks) + 1)
        self.index = [w - self.span.start for w in weeks]
        self.inputs = (x, term, mech, interventions, jurisdiction)

    def simulate(self, theta: np.ndarray) -> np.ndarray:
        return expected(_params(theta), self.span, *self.inputs)[self.index]

    def residuals(self, theta: np.ndarray) -> np.ndarray:
        return (np.log1p(self.simulate(theta)) - self.observed) * self.weights

    def best(self):  # -> scipy.optimize.OptimizeResult
        """The best of the least-squares fits from each starting point."""
        best = None
        for beta0, i0 in _STARTS:
            theta = np.array([math.log(beta0), 0.0, 0.0, _START_S0, math.log(i0), 0.0])
            total = float(self.simulate(theta).sum())  # the start's admissions at scale 1 set its starting scale
            theta[5] = math.log(max(float(np.expm1(self.observed).sum()), 1.0) / total) if total > 0 else 0.0
            result = least_squares(self.residuals, np.clip(theta, _LOWER, _UPPER), bounds=(_LOWER, _UPPER))
            if best is None or result.cost < best.cost:
                best = result
        return best



def _draws(best, size: int) -> np.ndarray:
    """Draws of theta (rows) from the fit's Laplace approximation, regularized by the box prior and truncated to it.

    `best` is the least-squares result over `size` residuals.  The approximation is
    `N(theta_hat, (J'J / sigma^2 + prior precision)^-1)`, with `sigma^2` the residual variance on the
    parameters' degrees of freedom (at least one), never below `_POISSON_RESIDUAL_VARIANCE`; the prior keeps
    a direction the data cannot determine from an unbounded variance.  Draws are `theta_hat + L^-T z` for
    the Cholesky factor `L` of the precision, so the precision is never inverted.  The fitted theta is the
    first draw, and the only one when fewer than `_MIN_DRAWS` fall inside the box or the precision cannot
    be factored at all: the forecast then has the lens's observation noise alone.
    """
    fitted = best.x[None, :]
    sigma2 = max(2.0 * best.cost / max(size - best.x.size, 1), _POISSON_RESIDUAL_VARIANCE)
    root = _cholesky(best.jac.T @ best.jac / sigma2 + _PRIOR_PRECISION)
    if root is None:
        return fitted
    sobol = stats.qmc.Sobol(d=best.x.size, scramble=True, seed=_QMC_SEED).random(_DRAWS)
    z = np.vstack([np.zeros(best.x.size), stats.norm.ppf(sobol)])
    draws = best.x + solve_triangular(root, z.T, lower=True, trans="T").T
    inside = draws[np.all((draws >= _LOWER) & (draws <= _UPPER), axis=1)]
    return inside if len(inside) >= _MIN_DRAWS else fitted


def _cholesky(precision: np.ndarray) -> np.ndarray | None:
    """The lower Cholesky factor of `precision`, with a `_RIDGE` added if rounding left it not positive
    definite; None when it is not finite or even the ridge does not help."""
    if not np.all(np.isfinite(precision)):
        return None
    for ridge in (0.0, _RIDGE * float(np.mean(np.diag(precision)))):
        try:
            return np.linalg.cholesky(precision + ridge * np.eye(len(precision)))
        except np.linalg.LinAlgError:
            continue
    return None


def _covariate(view: ArchiveView, world: str, role: str, jurisdiction: str) -> dict[int, float]:
    """week -> value of the world's base stream with `role` for `jurisdiction`; empty when the world has none."""
    spec = view.find(world, role)
    return {} if spec is None else dict(view.series(spec.id, jurisdiction))


def _carried(values: Mapping[int, float], weeks: range) -> dict[int, float]:
    """`values` over `weeks`, each missing week taking the latest known value before it (the earliest known
    value before any is known).  Empty when nothing is known."""
    if not values:
        return {}
    before = [k for k in values if k <= weeks.start]
    current = values[max(before)] if before else values[min(values)]
    filled: dict[int, float] = {}
    for week in weeks:
        current = values.get(week, current)
        filled[week] = current
    return filled


@dataclass(frozen=True)
class _Fit:
    draws: np.ndarray  # draws of theta, one per row, the fitted theta first
    dispersion: float  # the lens's observation size around the fit
    first_week: int


# Fits of this run, by (stream, jurisdiction, as_of, mechanisms): every target of a jurisdiction shares one.
_FITS: dict[tuple[str, str, int, Mechanisms], _Fit] = {}


def _inputs(
    ctx: Context, target: Target, weeks: range
) -> tuple[tuple[Intervention, ...], dict[int, float], dict[int, float]]:
    """The target stream's intervention, and the world's covariate and school term over `weeks` (carried forward)."""
    view = ctx.view
    spec = view.spec(target.stream)
    interventions = () if spec.intervention is None else (spec.intervention,)
    x = _carried(_covariate(view, spec.world, COVARIATE_ROLE, target.jurisdiction), weeks)
    term = _carried(_covariate(view, spec.world, TERM_ROLE, target.jurisdiction), weeks)
    return interventions, x, term


def _fit_stream(ctx: Context, target: Target, mech: Mechanisms, lens: ModuleType) -> _Fit:
    """Fit the target's jurisdiction on its stream, and the observation size of the latest vintage around the fit."""
    view, stream, jurisdiction = ctx.view, target.stream, target.jurisdiction
    series = lens.nowcast(view, stream, jurisdiction)
    if not series:
        raise ValueError(f"no data for {jurisdiction!r} in {stream!r}")
    span = range(series[0][0], series[-1][0] + 1)
    interventions, x, term = _inputs(ctx, target, span)
    problem = _Problem(series, x, term, mech, interventions, jurisdiction)
    best = problem.best()

    # the size is fitted to the raw counts against the fit as each was reported, `latest - week` issues on
    latest = view.history(stream)[-1].issue
    raw = view.series(stream, jurisdiction)
    model = expected(_params(best.x), [w for w, _ in raw], x, term, mech, interventions, jurisdiction)
    shares = np.array([lens.reported_fraction(view, stream, jurisdiction, latest - w) for w, _ in raw])
    dispersion = lens.fit_dispersion(np.array([v for _, v in raw]), model * shares)
    return _Fit(draws=_draws(best, len(series)), dispersion=dispersion, first_week=span.start)


def _predictive_size(means: np.ndarray, observation: float) -> float:
    """The negative binomial size matching the variance of the equal mixture of NB(`means`, `observation`).

    The mixture's variance is `M + E[mu^2] / observation + Var(mu)` around its mean `M`; the size whose
    variance `M + M^2 / size` equals it is returned (infinite when the mixture is Poisson).
    """
    mean = float(means.mean())
    second = float(np.mean(means**2))
    excess = second / observation + max(second - mean**2, 0.0)
    return math.inf if excess == 0 else mean**2 / excess


def predict_target(ctx: Context, target: Target, mech: Mechanisms, lens: ModuleType) -> Pmf:
    """The forecast of `target` by the SEIR model with mechanisms `mech`, observed through `lens`.

    The model is fitted to the lens's nowcast of the target's stream (an arm's history is its parent's),
    with covariates from the world's `covariate-x` and `school-term` streams (each week past the data
    carries the latest value forward) and the stream's own intervention.  Each parameter draw's expected
    count is scaled to what the resolution vintage will show (`lens.reported_fraction` at
    `resolution_lag`); the forecast is the lens's negative binomial with the mixture's mean and variance
    (`_predictive_size`), whatever the target's reference week.
    """
    view = ctx.view
    key = (target.stream, target.jurisdiction, view.as_of, mech)
    if key not in _FITS:
        _FITS[key] = _fit_stream(ctx, target, mech, lens)
    fitted = _FITS[key]
    if target.target_week < fitted.first_week:
        raise ValueError(f"target week {target.target_week} is before the data starts (week {fitted.first_week})")
    weeks = range(fitted.first_week, target.target_week + 1)
    interventions, x, term = _inputs(ctx, target, weeks)
    reported = lens.reported_fraction(view, target.stream, target.jurisdiction, target.resolution_lag)
    inputs = (x, term, mech, interventions, target.jurisdiction)
    means = reported * np.array([expected(_params(theta), weeks, *inputs)[-1] for theta in fitted.draws])
    size = _predictive_size(means, fitted.dispersion)
    return lens.observe_pmf(float(means.mean()), size, view.spec(target.stream).support_max)
