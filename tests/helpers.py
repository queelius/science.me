"""Shared test builders; import with `from helpers import ...`."""

from datetime import UTC, datetime, timedelta

from scienceme.mission import Mission
from scienceme.model import Isolation, StreamKind, StreamSpec

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    """T0 plus `hours` (an aware UTC datetime)."""
    return T0 + timedelta(hours=hours)


def count_spec(id="w/adm", jurisdictions=("A", "B"), support_max=1000, **kw) -> StreamSpec:
    """A COUNT stream spec with role `admissions`; world defaults to `w`."""
    kw.setdefault("world", "w")
    return StreamSpec(
        id=id,
        role="admissions",
        kind=StreamKind.COUNT,
        jurisdictions=jurisdictions,
        support_max=support_max,
        **kw,
    )


def covariate_spec(id="w/x", role="covariate-x", **kw) -> StreamSpec:
    """A COVARIATE stream spec in world `w`; jurisdictions default to A and B."""
    kw.setdefault("jurisdictions", ("A", "B"))
    return StreamSpec(id=id, world="w", role=role, kind=StreamKind.COVARIATE, **kw)


def make_mission(**overrides) -> Mission:
    """A valid mission over stream `w/adm`; keyword arguments override the defaults."""
    fields = dict(
        name="m",
        captain="test",
        streams=("w/adm",),
        horizons=(0, 1),
        first_issue=1,
        last_issue=10,
        resolution_lag=2,
        epsilon=0.01,
        tau=2.0,
        half_life_weeks=8.0,
        coverage_min=0.8,
        claim_threshold_nats=3.0,
        regime_flag_tv=0.5,
        exploration_reserve=0.2,
        required_isolation=Isolation.NONE,
    )
    return Mission(**{**fields, **overrides})
