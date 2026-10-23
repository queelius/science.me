"""The SEIR core with covariate_x = 0.0 and school = 0.2, observed through the admissions lens."""

from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)
MECHANISMS = IMPORTS["core"].Mechanisms(covariate_x=0.0, school=0.2)


def predict(ctx: Context, target: Target) -> Pmf:
    return IMPORTS["core"].predict_target(ctx, target, MECHANISMS, IMPORTS["lens"])
