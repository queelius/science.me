"""lens-ed and the -ed wrapper theories in `programs/`, run on a synthetic SEIR epidemic seen as ED visits.

The fixture copies `programs/` into a temporary workspace, freezes every program in dependency order (the
admissions seeds too, to show they stay off the ED channel) and publishes 20 issues of an ed-visits stream
for jurisdictions F, A, B and C.  The eventual counts are negative binomial draws (fixed seed, size 15, the
noise lens-ed assumes) around `seir-core`'s own `expected` (loaded by path) with known parameters, at a few
times the scale of the admissions fixture, and the true mechanisms of `seir-x1-s1-ed`.  They are reported
the way ED visits reach the archive: about 82% in the first issue, 97.5% in the second, complete from the
third, rounded.  A `covariate-x` stream (flat at 0 for F, a sine elsewhere) is released 4 weeks ahead and a
`school-term` stream is in session except in weeks 10 and 11.
"""

import ast
import json
import math
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import ModuleType

import numpy as np
import pytest
from helpers import at, covariate_spec, make_mission, publish
from scipy import stats

from scienceme.archive import Archive, ArchiveView
from scienceme.manifest import in_scope, load_manifest
from scienceme.model import Intervention, Isolation, Row, StreamKind, StreamSpec, Target, TargetFilter, Vintage
from scienceme.pmf import Pmf
from scienceme.predict import SkipReason, run_origin
from scienceme.record import PredictionRecord, RecordStore, UnscoredRecord
from scienceme.registry import Registry
from scienceme.worker import build_order, run_order
from scienceme.workspace import Workspace

PROGRAMS = Path(__file__).resolve().parent.parent / "programs"
SEEDS = ("seir-x1-s1", "seir-x1-s0", "seir-x0-s1", "seir-x0-s0")
WRAPPERS = tuple(f"{seed}-ed" for seed in SEEDS)
FREEZE_ORDER = (
    "lens-admissions",
    "seir-core",
    "hub-baseline",
    "flex-loglinear",
    *SEEDS,
    "lens-ed",
    *WRAPPERS,
)

JURISDICTIONS = ("F", "A", "B", "C")
ISSUES = range(1, 21)  # issue i holds weeks 0 .. i-1
WEEKS = range(0, 20)
COVARIATE_LEAD = 4  # covariate issue i holds weeks 0 .. i+3
CLOSED_WEEKS = (10, 11)
COMPLETENESS = (0.82, 0.975)  # share of a week's count reported d+1 issues after it; complete from d = 2
NOISE_SIZE = 15.0  # negative binomial size of the eventual counts around the true model
ED_SCALE = 3.0  # ED visits per admission of the admissions fixture's scale
SEED = 20261023  # the fixture's epidemic
COVERAGE_SEEDS = range(1, 9)  # further epidemics for the calibration test
SUPPORT_MAX = 1_000_000
ORIGIN = 16
HORIZONS = (0, 1, 2, 3)
LAG = 4

ED, X, TERM = "w/ed", "w/x", "w/term"


def ed_spec(**kw) -> StreamSpec:
    """A COUNT stream spec with role `ed-visits` in world `w`; id `w/ed` and the fixture's jurisdictions by default."""
    kw.setdefault("id", ED)
    kw.setdefault("jurisdictions", JURISDICTIONS)
    return StreamSpec(world="w", role="ed-visits", kind=StreamKind.COUNT, support_max=SUPPORT_MAX, **kw)


SPECS = {
    ED: ed_spec(),
    X: covariate_spec(id=X, jurisdictions=JURISDICTIONS),
    TERM: covariate_spec(id=TERM, role="school-term", jurisdictions=JURISDICTIONS),
}
TRUTH = {  # beta0, amplitude, peak_week, s0, i0, scale (before ED_SCALE): as in the admissions fixture
    "F": (0.42, 0.20, 16.0, 0.90, 3e-5, 30000.0),
    "A": (0.50, 0.15, 20.0, 0.85, 1e-4, 8000.0),
    "B": (0.40, 0.25, 14.0, 0.95, 4e-5, 40000.0),
    "C": (0.52, 0.10, 10.0, 0.80, 2e-4, 5000.0),
}


def load_library(name: str) -> ModuleType:
    """`programs/<name>/program.py` as a plain module, compiled from source (no bytecode is written beside it).

    Only a library that imports no other program loads this way.
    """
    path = PROGRAMS / name / "program.py"
    module = ModuleType("lens_ed_test_" + name.replace("-", "_"))
    module.__file__ = str(path)
    sys.modules[module.__name__] = module  # dataclasses look their module up while the class is created
    exec(compile(path.read_text(encoding="utf-8"), path, "exec"), module.__dict__)
    return module


def covariate(jurisdiction: str, week: int) -> float:
    if jurisdiction == "F":
        return 0.0
    phase = {"A": 0.0, "B": 2.0, "C": 4.0}[jurisdiction]
    return math.sin(2 * math.pi * (week + phase) / 13)


def term(week: int) -> float:
    return 0.0 if week in CLOSED_WEEKS else 1.0


def eventual(core, seed: int) -> dict[str, np.ndarray]:
    """Each jurisdiction's eventual weekly ED visits: negative binomial draws around the true model's expectation."""
    rng = np.random.default_rng(seed)
    truth = core.Mechanisms(covariate_x=0.2, school=0.2)
    school = {w: term(w) for w in WEEKS}
    counts = {}
    for j in JURISDICTIONS:
        beta0, amplitude, peak, s0, i0, scale = TRUTH[j]
        params = core.Params(beta0, amplitude, peak, s0, i0, scale * ED_SCALE)
        mean = core.expected(params, WEEKS, {w: covariate(j, w) for w in WEEKS}, school, truth, (), j)
        counts[j] = rng.negative_binomial(NOISE_SIZE, NOISE_SIZE / (NOISE_SIZE + mean)).astype(float)
    return counts


def reported(count: float, issue: int, week: int) -> float:
    """What issue `issue` reports for a week whose eventual count is `count`."""
    d = issue - week - 1
    return float(round(count * (COMPLETENESS[d] if d < len(COMPLETENESS) else 1.0)))


def issue_rows(counts: dict[str, np.ndarray], issue: int) -> dict[str, dict[tuple[str, int], float]]:
    """What each stream publishes in `issue`, keyed by (jurisdiction, week)."""
    ahead = range(issue + COVARIATE_LEAD)
    return {
        ED: {(j, w): reported(counts[j][w], issue, w) for j in JURISDICTIONS for w in range(issue)},
        X: {(j, w): covariate(j, w) for j in JURISDICTIONS for w in ahead},
        TERM: {(j, w): term(w) for j in JURISDICTIONS for w in ahead},
    }


@pytest.fixture(scope="module")
def ed_ws(tmp_path_factory):
    ws = Workspace.create(tmp_path_factory.mktemp("ed"))
    shutil.copytree(PROGRAMS, ws.programs, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))
    registry = Registry(ws)
    for name in FREEZE_ORDER:  # freezing checks every declared pair against its partner
        registry.freeze(name, at(0))
    counts = eventual(load_library("seir-core"), SEED)
    assert max(float(c.max()) for c in counts.values()) < SUPPORT_MAX
    for issue in ISSUES:
        for stream, rows in issue_rows(counts, issue).items():
            publish(ws, SPECS[stream], issue, rows, at(issue))
    return ws


@pytest.fixture(scope="module")
def origin(ed_ws):
    """One origin at week 16 of an ED mission: (report, records, seconds it took)."""
    mission = make_mission(
        name="ed", streams=(ED, X, TERM), horizons=HORIZONS, first_issue=1, last_issue=20, resolution_lag=LAG
    )
    start = time.perf_counter()
    report = run_origin(ed_ws, mission, ORIGIN, Isolation.NONE, at(30))
    elapsed = time.perf_counter() - start
    return report, RecordStore(ed_ws).all("ed"), elapsed


@pytest.fixture(scope="module")
def lens():
    return load_library("lens-ed")


def hashes(ws) -> dict[str, str]:
    return {f.name: h for h, f in Registry(ws).freezes().items()}


def pmfs_of(records, program: str) -> dict[Target, Pmf]:
    return {r.target: r.pmf for r in records if isinstance(r, PredictionRecord) and r.program == program}


def moments(pmf: Pmf) -> tuple[float, float]:
    y = np.arange(pmf.lo, pmf.hi + 1)
    p = np.asarray(pmf.p)
    mean = float(np.dot(y, p))
    return mean, float(np.dot((y - mean) ** 2, p))


def total_variation(p: Pmf, q: Pmf) -> float:
    lo, hi = min(p.lo, q.lo), max(p.hi, q.hi)
    return 0.5 * sum(abs(p.prob(y) - q.prob(y)) for y in range(lo, hi + 1))


def quantile(pmf: Pmf, level: float) -> int:
    """The smallest y with P(Y <= y) >= level."""
    cdf = np.cumsum(pmf.p)
    return pmf.lo + int(np.searchsorted(cdf, level - 1e-12))


def forecast(ws, program: str, view, targets) -> list[Pmf]:
    result = run_order(ws, build_order(ws, hashes(ws)[program], view, targets), Isolation.NONE, 300)
    assert all(r.kind == "prediction" for r in result.results), result.results
    return [r.pmf for r in result.results]


# --- the wrappers are their admissions counterparts with another lens and scope ---


def code_without_docstring(path: Path) -> str:
    """The module's code as an AST dump, its docstring left out."""
    body = ast.parse(path.read_text(encoding="utf-8")).body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    return ast.dump(ast.Module(body=body, type_ignores=[]))


@pytest.mark.parametrize("seed", SEEDS)
def test_wrapper_runs_the_counterparts_code(seed):
    assert code_without_docstring(PROGRAMS / f"{seed}-ed" / "program.py") == code_without_docstring(
        PROGRAMS / seed / "program.py"
    )


@pytest.mark.parametrize("seed", SEEDS)
def test_wrapper_changes_only_lens_scope_and_partners(ed_ws, seed):
    names = hashes(ed_ws)
    name_of = {h: n for n, h in names.items()}
    old, new = load_manifest(PROGRAMS / seed), load_manifest(PROGRAMS / f"{seed}-ed")
    assert new.name == f"{seed}-ed"
    assert new.imports == {**old.imports, old.lens: names["lens-ed"]}  # the same frozen seir-core
    assert new.lens == old.lens
    assert new.scope == TargetFilter(roles=("ed-visits",))
    assert (new.author_lineage, new.entry, new.library) == (old.author_lineage, old.entry, old.library)
    assert (new.interface, new.tags, new.supersedes) == (old.interface, old.tags, None)
    assert [(p.claim, name_of[p.partner]) for p in new.pairs] == [
        (p.claim, f"{name_of[p.partner]}-ed") for p in old.pairs
    ]


def test_scopes_keep_the_channels_apart():
    adm_spec = StreamSpec(
        id="w/adm", world="w", role="admissions", kind=StreamKind.COUNT, jurisdictions=("A",), support_max=SUPPORT_MAX
    )
    on_ed = Target(stream=ED, jurisdiction="A", reference_week=ORIGIN, horizon=0)
    on_adm = Target(stream=adm_spec.id, jurisdiction="A", reference_week=ORIGIN, horizon=0)
    for seed, wrapper in zip(SEEDS, WRAPPERS, strict=True):
        old, new = load_manifest(PROGRAMS / seed), load_manifest(PROGRAMS / wrapper)
        assert in_scope(new, on_ed, SPECS[ED]) and not in_scope(new, on_adm, adm_spec)
        assert in_scope(old, on_adm, adm_spec) and not in_scope(old, on_ed, SPECS[ED])


# --- the wrappers on the ED channel ---


def test_only_the_wrappers_forecast_the_ed_stream(ed_ws, origin):
    report, records, _ = origin
    names = hashes(ed_ws)
    assert sorted(r.program for r in report.ran) == sorted(names[w] for w in WRAPPERS)
    assert {r.stream for r in report.ran} == {ED}
    assert all(r.n_targets == len(JURISDICTIONS) * len(HORIZONS) for r in report.ran)
    out_of_scope = {s.program for s in report.skipped if s.reason is SkipReason.OUT_OF_SCOPE}
    assert out_of_scope == {names[n] for n in ("hub-baseline", "flex-loglinear", *SEEDS)}
    assert [r for r in records if isinstance(r, UnscoredRecord)] == []
    assert len(records) == len(WRAPPERS) * len(JURISDICTIONS) * len(HORIZONS)
    assert all(r.pmf.within(0, SUPPORT_MAX) for r in records)


def test_forecasts_carry_at_least_the_lens_noise(ed_ws, origin, lens):
    # every forecast's variance is at least the negative binomial's at the lens's narrowest size
    _, records, _ = origin
    for record in records:
        mean, variance = moments(record.pmf)
        assert variance >= 0.99 * (mean + mean**2 / lens.MAX_DISPERSION), record.target


def test_school_assertion_changes_arm_predictions(ed_ws):
    # the candidate arm closes schools in A for weeks 17-19; its target (week 18) lies past the view's as_of
    arm = ed_spec(
        id="w/ed/close",
        jurisdictions=("A",),
        parent=ED,
        intervention=Intervention(
            variable="schools_closed", value=1.0, start_week=17, end_week=19, jurisdictions=("A",)
        ),
    )
    view = Archive(ed_ws).view([ED, X, TERM], ORIGIN, at(30)).with_candidate(arm)
    on_arm = Target(stream=arm.id, jurisdiction="A", reference_week=17, horizon=1, resolution_lag=LAG)
    on_base = Target(stream=ED, jurisdiction="A", reference_week=17, horizon=1, resolution_lag=LAG)

    def means(program: str) -> tuple[float, float]:
        arm_pmf, base_pmf = forecast(ed_ws, program, view, [on_arm, on_base])
        return moments(arm_pmf)[0], moments(base_pmf)[0]

    closed, baseline = means("seir-x1-s1-ed")
    assert closed < 0.95 * baseline
    closed, baseline = means("seir-x1-s0-ed")
    assert closed == pytest.approx(baseline, rel=0.01)


def test_flat_covariate_pair_is_indistinguishable(ed_ws, origin):
    _, records, _ = origin
    names = hashes(ed_ws)
    asserts, denies = pmfs_of(records, names["seir-x1-s1-ed"]), pmfs_of(records, names["seir-x0-s1-ed"])
    flat = [t for t in asserts if t.jurisdiction == "F"]
    assert sorted(t.horizon for t in flat) == list(HORIZONS)
    for target in flat:
        assert total_variation(asserts[target], denies[target]) < 1e-3


def test_one_origin_runs_in_under_30_seconds(origin):
    _, _, elapsed = origin
    assert elapsed < 30


def memory_view(counts: dict[str, np.ndarray]) -> ArchiveView:
    """The view at the origin of the epidemic with eventual `counts`: issues 1 .. ORIGIN, held in memory."""
    published = [issue_rows(counts, issue) for issue in range(1, ORIGIN + 1)]
    vintages = {
        stream: tuple(
            Vintage(
                stream=stream,
                issue=issue,
                rows=tuple(Row(jurisdiction=j, week=w, value=v) for (j, w), v in sorted(rows[stream].items())),
            )
            for issue, rows in enumerate(published, start=1)
        )
        for stream in SPECS
    }
    return ArchiveView(as_of=ORIGIN, specs=SPECS, vintages=vintages)


def coverage(ws, program: str, seeds: range) -> float:
    """Share of the realized values inside the program's 90% central intervals, at every jurisdiction and
    horizon of an origin at week 16, pooled over one fresh epidemic per seed (each an in-memory view)."""
    targets = [
        Target(stream=ED, jurisdiction=j, reference_week=ORIGIN, horizon=h, resolution_lag=LAG)
        for j in JURISDICTIONS
        for h in HORIZONS
    ]
    core = load_library("seir-core")
    inside = 0
    for seed in seeds:
        counts = eventual(core, seed)
        view = memory_view(counts)
        for target, pmf in zip(targets, forecast(ws, program, view, targets), strict=True):
            week = target.target_week
            realized = reported(counts[target.jurisdiction][week], target.resolution_issue, week)
            inside += quantile(pmf, 0.05) <= realized <= quantile(pmf, 0.95)
    return inside / (len(seeds) * len(targets))


@pytest.fixture(scope="module")
def coverages(ed_ws):
    """Pooled 90% coverage of the same theory on the same ED epidemics, through lens-ed and lens-admissions.

    seir-x1-s1 is scoped to admissions, so the kernel would never hand it ED targets; run directly, it shows
    what the admissions lens makes of ED data.
    """
    return {program: coverage(ed_ws, program, COVERAGE_SEEDS) for program in ("seir-x1-s1-ed", "seir-x1-s1")}


def test_ed_lens_covers_more_than_the_admissions_lens(coverages):
    assert coverages["seir-x1-s1-ed"] > coverages["seir-x1-s1"], coverages


def test_ed_interval_coverage_does_not_regress(coverages):
    measured = coverages["seir-x1-s1-ed"]
    # measured 0.508 (0.469 through lens-admissions): seir-core is under-dispersed (see its README); pins today's
    # behavior against regressions, not good calibration
    assert measured >= 0.48, f"pooled 90% interval coverage {measured:.3f}"


# --- the lens's contract ---


def test_completeness_recovers_the_ed_reporting_curve(ed_ws, lens):
    view = Archive(ed_ws).view([ED], ORIGIN, at(30))
    c = lens.completeness(view, ED)
    assert len(c) == lens.MAX_LAG + 1 and c[-1] == 1.0
    assert c[: len(COMPLETENESS)] == pytest.approx(COMPLETENESS, abs=0.01)
    assert c[len(COMPLETENESS) :] == pytest.approx(1.0)
    for j in JURISDICTIONS:
        latest = dict(view.series(ED, j))
        assert dict(lens.nowcast(view, ED, j)) == {w: v / c[min(ORIGIN - w - 1, lens.MAX_LAG)] for w, v in latest.items()}
        assert lens.reported_fraction(view, ED, j, 1) == c[0]
        assert lens.reported_fraction(view, ED, j, LAG) == c[LAG - 1]
        assert lens.reported_fraction(view, ED, j, 50) == 1.0


def two_jurisdiction_view(as_of: int = 10) -> ArchiveView:
    """An ED view in which A reports hundreds of visits a week on the fixture's curve and Z reports one or two,
    too few for rounding to show any revision."""
    eventual_a = [200.0 + 40 * w for w in range(as_of)]
    vintages = tuple(
        Vintage(
            stream=ED,
            issue=issue,
            rows=tuple(
                [Row(jurisdiction="A", week=w, value=reported(eventual_a[w], issue, w)) for w in range(issue)]
                + [Row(jurisdiction="Z", week=w, value=float(1 + w % 2)) for w in range(issue)]
            ),
        )
        for issue in range(1, as_of + 1)
    )
    return ArchiveView(as_of=as_of, specs={ED: ed_spec(jurisdictions=("A", "Z"))}, vintages={ED: vintages})


def test_completeness_is_pooled_over_jurisdictions(lens):
    view = two_jurisdiction_view()
    c = lens.completeness(view, ED)
    assert c[: len(COMPLETENESS)] == pytest.approx(COMPLETENESS, abs=0.01)
    assert lens.reported_fraction(view, ED, "Z", 1) == lens.reported_fraction(view, ED, "A", 1) == c[0]
    last_week, last_value = view.series(ED, "Z")[-1]
    assert dict(lens.nowcast(view, ED, "Z"))[last_week] == pytest.approx(last_value / c[0])
    # the admissions lens, per jurisdiction, sees no revision in Z and would take its latest week as complete
    assert load_library("lens-admissions").completeness(view, ED, "Z")[0] == 1.0


def test_completeness_without_revisions_is_flat(lens):
    view = ArchiveView(as_of=0, specs={ED: SPECS[ED]}, vintages={})
    assert list(lens.completeness(view, ED)) == [1.0] * (lens.MAX_LAG + 1)
    assert lens.nowcast(view, ED, "A") == []


def test_fit_dispersion_is_the_method_of_moments_within_its_bounds(lens):
    expected = np.full(200, 500.0)
    rng = np.random.default_rng(0)
    noisy = rng.negative_binomial(5, 5 / 505, size=200)  # noisier than the lens's narrowest noise
    assert 3 < lens.fit_dispersion(noisy, expected) < 8
    quiet = rng.negative_binomial(200, 200 / 700, size=200)  # quieter than it: the residuals cannot narrow it
    assert lens.fit_dispersion(quiet, expected) == lens.MAX_DISPERSION
    assert lens.fit_dispersion(expected, expected) == lens.MAX_DISPERSION  # no more spread than Poisson
    assert lens.fit_dispersion(np.array([0.0, 5000.0]), np.array([100.0, 100.0])) == lens.MIN_DISPERSION
    assert lens.fit_dispersion(np.array([3.0, 0.0]), np.array([0.0, 0.0])) == lens.MIN_DISPERSION
    assert lens.MIN_DISPERSION < lens.MAX_DISPERSION


def test_observe_pmf_never_leaves_the_support(lens):
    pmf = lens.observe_pmf(5000.0, 2.0, 100)
    assert pmf.within(0, 100)
    assert sum(pmf.p) == pytest.approx(1.0)
    assert lens.observe_pmf(0.0, 3.0, 100) == Pmf.point(0)


@pytest.mark.parametrize("mean, size", [(2000.0, 15.0), (5.0, 0.7), (40000.0, 3.0), (0.5, math.inf)])
def test_observe_pmf_truncation_removes_at_most_a_millionth(lens, mean, size):
    dist = stats.poisson(mean) if math.isinf(size) else stats.nbinom(size, size / (size + mean))
    pmf = lens.observe_pmf(mean, size, SUPPORT_MAX)
    assert dist.sf(pmf.hi) <= 1e-6  # what is cut holds at most 1e-6 of the mass
    assert dist.sf(pmf.hi - 1) > 1e-6  # and the cut is the first place that holds
    assert pmf.lo == 0  # the lower end is untouched
    kept = 1 - dist.sf(pmf.hi)
    assert pmf.prob(0) == pytest.approx(dist.pmf(0) / kept, rel=1e-9)


@pytest.mark.parametrize("mean, dispersion", [(-1.0, 2.0), (math.nan, 2.0), (math.inf, 2.0), (5.0, 0.0)])
def test_observe_pmf_refuses_an_invalid_distribution(lens, mean, dispersion):
    with pytest.raises(ValueError):
        lens.observe_pmf(mean, dispersion, 100)


def test_observe_pmf_returns_quickly_for_a_tiny_size():
    # scipy's nbinom.ppf stalls near this size; a subprocess makes a regression fail instead of hanging the suite
    path = PROGRAMS / "lens-ed" / "program.py"
    code = (
        "import json, sys, time, types\n"
        f"path = {str(path)!r}\n"
        "lens = types.ModuleType('lens'); sys.modules['lens'] = lens\n"
        "exec(compile(open(path, encoding='utf-8').read(), path, 'exec'), lens.__dict__)\n"
        "start = time.perf_counter(); pmf = lens.observe_pmf(460.0, 5.6e-12, 20000)\n"
        "print(json.dumps({'seconds': time.perf_counter() - start, 'hi': pmf.hi}))\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, check=True)
    result = json.loads(done.stdout)
    assert result["seconds"] < 1.0 and result["hi"] <= 20000


def test_truncate_cuts_a_pmf_at_its_upper_tail(lens):
    bulk = np.full(50, 0.02 * (1 - 2.5e-6))
    pmf = Pmf.from_probs(7, [*bulk, 0.0, 0.0, 2e-6, 0.0, 5e-7])  # atoms of 2e-6 and 5e-7 above the bulk
    cut = lens.truncate(pmf)
    assert (cut.lo, cut.hi) == (7, 7 + 52)  # the 2e-6 atom stays (dropping it removes more than 1e-6)
    assert 1 - pmf.cdf(cut.hi) <= 1e-6
    assert lens.truncate(Pmf.point(3)) == Pmf.point(3)
