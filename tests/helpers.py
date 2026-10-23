"""Shared test builders; import with `from helpers import ...`."""

import shutil
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from scienceme.archive import Archive, ArchiveView
from scienceme.manifest import ProgramManifest, closure_hash, load_manifest
from scienceme.mission import Mission
from scienceme.model import Capture, Isolation, Row, StreamKind, StreamSpec, Target, Vintage
from scienceme.scoring import PointScore, ResolvedTarget
from scienceme.worker_entry import WorkOrder, program_dirname
from scienceme.workspace import Workspace

T0 = datetime(2026, 10, 1, tzinfo=UTC)

# A program that forecasts the constant 7 for every target.
CONST = "from scienceme.pmf import Pmf\ndef predict(ctx, target):\n    return Pmf.point(7)\n"

# A program that forecasts its target's horizon, except that it raises for jurisdiction B.
PER_TARGET = (
    "from scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n"
    "    if target.jurisdiction == 'B':\n        raise RuntimeError('boom')\n"
    "    return Pmf.point(target.horizon)\n"
)


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


def publish(
    ws: Workspace, spec: StreamSpec, issue: int, values: Mapping[tuple[str, int], float], when: datetime
) -> Capture:
    """Create the stream if needed, capture `issue` (rows keyed by (jurisdiction, week)) at `when`, return it."""
    archive = Archive(ws)
    archive.create_stream(spec)
    rows = tuple(Row(jurisdiction=j, week=w, value=v) for (j, w), v in sorted(values.items()))
    capture = Capture.make(Vintage(stream=spec.id, issue=issue, rows=rows), when, source="test")
    archive.add(capture)
    return capture


def sandbox(ws: Workspace, tmp_path: Path, *names: str) -> Path:
    """Copy each named program into `<tmp_path>/work/programs/<hex>/`, as the container sees them; return `work`."""
    work = tmp_path / "work"
    for name in names:
        source = ws.programs / name
        target = work / "programs" / program_dirname(closure_hash(source))
        shutil.copytree(source, target, ignore=shutil.ignore_patterns("__pycache__"))
    return work


def order(ws: Workspace, name: str, view: ArchiveView, targets: Iterable[Target]) -> WorkOrder:
    """A WorkOrder for program `name`, with the manifest of it and of every import found in `ws.programs`."""
    by_hash = {closure_hash(d): d for d in ws.programs.iterdir() if d.is_dir()}
    program = closure_hash(ws.programs / name)
    manifests: dict[str, ProgramManifest] = {}
    pending = [program]
    while pending:
        h = pending.pop()
        if h not in manifests and h in by_hash:
            manifests[h] = load_manifest(by_hash[h])
            pending.extend(manifests[h].imports.values())
    return WorkOrder(program=program, manifests=manifests, view=view, targets=tuple(targets))


def rt(ref: int, ri: int, scores: Mapping[str, float], j: str = "A", h: int = 0) -> ResolvedTarget:
    """A target of `w/adm` at reference week `ref`, horizon `h`, resolved by issue `ri`, scored with `scores` (log_p).

    The cdfs are dummies (0 below, 1 at) and the realized value is 0.
    """
    target = Target(stream="w/adm", jurisdiction=j, reference_week=ref, horizon=h, resolution_lag=ri - ref - h)
    points = {m: PointScore(log_p=v, cdf_below=0.0, cdf_at=1.0) for m, v in scores.items()}
    return ResolvedTarget(target=target, realized=0, scores=points)
