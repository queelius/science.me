"""Shared test builders; import with `from helpers import ...`."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

from scienceme.manifest import ProgramManifest
from scienceme.mission import Mission
from scienceme.model import Isolation, StreamKind, StreamSpec
from scienceme.workspace import Workspace

T0 = datetime(2026, 10, 1, tzinfo=UTC)

# A program that forecasts the constant 7 for every target.
CONST = "from scienceme.pmf import Pmf\ndef predict(ctx, target):\n    return Pmf.point(7)\n"


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


def write_program(ws: Workspace, name: str, code: str, **fields) -> Path:
    """Write `programs/<name>/` (manifest, `program.py` holding `code`, README) and return its directory."""
    d = ws.programs / name
    d.mkdir(parents=True, exist_ok=True)
    manifest = ProgramManifest(name=name, author_lineage="test", **fields)
    (d / "program.json").write_text(manifest.model_dump_json(), encoding="utf-8")
    (d / "program.py").write_text(code, encoding="utf-8")
    (d / "README.md").write_text("test program", encoding="utf-8")
    return d
