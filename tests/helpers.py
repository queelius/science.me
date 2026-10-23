"""Shared test builders; import with `from helpers import ...`."""

from datetime import UTC, datetime, timedelta

from scienceme.model import StreamKind, StreamSpec

T0 = datetime(2026, 10, 1, tzinfo=UTC)


def at(hours: float) -> datetime:
    """T0 plus `hours` (an aware UTC datetime)."""
    return T0 + timedelta(hours=hours)


def count_spec(id="w/adm", jurisdictions=("A", "B"), support_max=1000, **kw) -> StreamSpec:
    """A COUNT stream spec with role `admissions` in world `w`."""
    return StreamSpec(
        id=id,
        world="w",
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
