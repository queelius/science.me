"""Seasonally forced SEIR forecasts of admissions with a covariate effect and a school-closure effect.

Transmission is scaled by `exp(-COVARIATE_EFFECT * x)` and cut by `SCHOOL_EFFECT` times the share of schools
closed, whether the closure is scheduled or imposed.  Vaccination campaigns remove susceptibles.  Counts are
observed through the admissions lens.
"""

from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)

COVARIATE_EFFECT = 0.2
SCHOOL_EFFECT = 0.0  # fixed at the published value rather than fitted
MECHANISMS = IMPORTS["core"].Mechanisms(covariate_x=COVARIATE_EFFECT, school=SCHOOL_EFFECT)
CONDITIONED_AWAY = frozenset({"schools_closed"})


def _conditioned(ctx: Context, target: Target) -> Context:
    """The context with the target stream's intervention kept only when the forecast conditions on it."""
    spec = ctx.view.spec(target.stream)
    if spec.intervention is None or spec.intervention.variable not in CONDITIONED_AWAY:
        return ctx
    specs = {**ctx.view.specs, spec.id: spec.model_copy(update={"intervention": None})}
    return Context(view=ctx.view.model_copy(update={"specs": specs}), seed=ctx.seed)


def predict(ctx: Context, target: Target) -> Pmf:
    return IMPORTS["core"].predict_target(_conditioned(ctx, target), target, MECHANISMS, IMPORTS["lens"])
