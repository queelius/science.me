"""The SEIR core with covariate_x = 0.2 and school = 0.0, observed through the ED-visits lens."""

from scienceme.sdk import Context, Pmf, Target, imports_of

IMPORTS = imports_of(__name__)
MECHANISMS = IMPORTS["core"].Mechanisms(covariate_x=0.2, school=0.0)


def predict(ctx: Context, target: Target) -> Pmf:
    return IMPORTS["core"].predict_target(ctx, target, MECHANISMS, IMPORTS["lens"])
