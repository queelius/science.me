import math
from collections import defaultdict

import pytest
import scipy.stats
from helpers import at, count_spec, make_mission, publish

from scienceme.model import Isolation, Target
from scienceme.pmf import Pmf, floored_cdf, floored_log_prob
from scienceme.record import PredictionRecord, RecordStore, UnscoredRecord
from scienceme.scoring import PointScore, ResolvedTarget, point_score, resolve

P = "sha256:" + "aa" * 32
Q = "sha256:" + "bb" * 32
STREAM = "w/adm"


def tgt(jurisdiction="A", week=1, horizon=1, stream=STREAM) -> Target:
    """A target with the mission's lag of 2: resolved by issue week + horizon + 2."""
    return Target(stream=stream, jurisdiction=jurisdiction, reference_week=week, horizon=horizon, resolution_lag=2)


def forecast(program, target, pmf=Pmf.point(5)) -> PredictionRecord:
    return PredictionRecord(
        mission="m", program=program, target=target, pmf=pmf, scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def failed(program, target) -> UnscoredRecord:
    return UnscoredRecord(
        mission="m", program=program, target=target, reason="boom", scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def store(ws, *records) -> None:
    """Write `records`, one file per (program, stream, reference week), in the order given."""
    files = defaultdict(list)
    for r in records:
        files[(r.program, r.target.stream, r.target.reference_week)].append(r)
    for (program, stream, week), rs in files.items():
        RecordStore(ws).write("m", stream, week, program, rs)


# --- the scoring rule ---


def test_log_score_beats_the_codex_counterexample():  # review finding 2
    truth = Pmf.from_probs(0, [0.9] + [0.0] * 9 + [0.1])
    nb = scipy.stats.nbinom(0.125, 1 / 9)  # mean 1, variance 9
    inflated = Pmf.from_probs(0, list(nb.pmf(range(100)) / nb.cdf(99)))

    def expected(p):
        return sum(truth.prob(y) * floored_log_prob(p, y, 0.01, 99) for y in range(100))

    assert expected(truth) - expected(inflated) > 0.3


def test_honest_report_is_within_the_floor_compromise_of_optimal():
    q = Pmf.from_probs(0, [0.5, 0.3, 0.2])
    eps, S = 0.01, 2
    best = Pmf.from_probs(0, [(q.prob(y) - eps / (S + 1)) / (1 - eps) for y in range(3)])

    def expected(p):
        return sum(q.prob(y) * floored_log_prob(p, y, eps, S) for y in range(3))

    assert expected(best) >= expected(q) >= expected(best) - 2 * eps


def test_point_score_uses_the_floored_distribution_for_every_field():
    pmf, eps, S = Pmf.from_probs(2, [0.25, 0.75]), 0.1, 9
    s = point_score(pmf, 3, eps, S)
    assert s.log_p == pytest.approx(math.log(0.9 * 0.75 + 0.1 / 10))
    assert s.cdf_at == pytest.approx(0.9 * 1.0 + 0.1 * 4 / 10)
    assert s.cdf_below == pytest.approx(0.9 * 0.25 + 0.1 * 3 / 10)
    assert s == PointScore(
        log_p=floored_log_prob(pmf, 3, eps, S),
        cdf_below=floored_cdf(pmf, 2, eps, S),
        cdf_at=floored_cdf(pmf, 3, eps, S),
    )


def test_point_score_outside_the_forecast_support_is_bounded_by_the_floor():
    s = point_score(Pmf.point(0), 0, 0.01, 99)
    assert s.cdf_below == 0.0  # nothing lies below zero, not even the floor's mass
    far = point_score(Pmf.point(0), 50, 0.01, 99)
    assert far.log_p == pytest.approx(math.log(0.01 / 100))
    assert (far.cdf_below, far.cdf_at) == pytest.approx((0.99 + 0.01 * 50 / 100, 0.99 + 0.01 * 51 / 100))


def test_a_resolved_target_needs_a_score():
    with pytest.raises(ValueError):
        ResolvedTarget(target=tgt(), realized=0, scores={})


# --- resolve ---


def test_resolve_keeps_unresolved_targets_pending(ws):
    # prediction at week 1, horizon 1, lag 2: resolved by issue 4
    spec = count_spec(jurisdictions=("A",), support_max=99)
    publish(ws, spec, 1, {("A", 0): 3.0}, at(1))
    store(ws, forecast(P, tgt()))
    before = resolve(ws, make_mission(), 3)
    assert (before.resolved, before.pending, before.predicted) == ((), 1, {P: 1})
    publish(ws, spec, 4, {("A", 2): 5.0}, at(4))
    after = resolve(ws, make_mission(), 4)
    assert after.pending == 0
    assert [(r.target, r.realized, set(r.scores)) for r in after.resolved] == [(tgt(), 5, {P})]


def test_a_published_resolution_vintage_waits_for_as_of(ws):
    spec = count_spec(jurisdictions=("A",), support_max=99)
    publish(ws, spec, 4, {("A", 2): 5.0}, at(4))
    store(ws, forecast(P, tgt()))
    res = resolve(ws, make_mission(), 3)
    assert (res.resolved, res.pending) == ((), 1)


def test_a_resolution_vintage_missing_the_row_stays_pending(ws):
    spec = count_spec(jurisdictions=("A", "B"), support_max=99)
    publish(ws, spec, 4, {("A", 1): 5.0, ("B", 2): 6.0}, at(4))
    store(ws, forecast(P, tgt("A")))
    for as_of in (4, 10):
        res = resolve(ws, make_mission(), as_of)
        assert (res.resolved, res.pending, res.predicted) == ((), 1, {P: 1})


def test_pending_counts_each_prediction_record(ws):
    publish(ws, count_spec(jurisdictions=("A",), support_max=99), 1, {("A", 0): 3.0}, at(1))
    store(ws, forecast(P, tgt()), forecast(Q, tgt()), forecast(P, tgt(horizon=0)))
    res = resolve(ws, make_mission(), 3)
    assert (res.resolved, res.pending, res.predicted) == ((), 3, {P: 2, Q: 1})


def test_resolve_scores_every_program_under_the_mission_floor_and_stream_support(ws):
    publish(ws, count_spec(jurisdictions=("A",), support_max=49), 4, {("A", 2): 5.0}, at(4))
    p_pmf, q_pmf = Pmf.from_probs(4, [0.5, 0.5]), Pmf.point(9)
    store(ws, forecast(P, tgt(), p_pmf), forecast(Q, tgt(), q_pmf))
    (resolved,) = resolve(ws, make_mission(epsilon=0.05), 4).resolved
    assert resolved.scores == {P: point_score(p_pmf, 5, 0.05, 49), Q: point_score(q_pmf, 5, 0.05, 49)}


def test_unscored_records_are_counted_and_never_scored(ws):
    publish(ws, count_spec(jurisdictions=("A",), support_max=99), 4, {("A", 2): 5.0}, at(4))
    store(ws, forecast(P, tgt(horizon=1)), failed(P, tgt(horizon=0)))
    store(ws, failed(Q, tgt(horizon=0)), failed(Q, tgt(horizon=1)))
    res = resolve(ws, make_mission(), 4)
    assert [(r.target, set(r.scores)) for r in res.resolved] == [(tgt(horizon=1), {P})]
    assert (res.pending, res.predicted, res.unscored) == (0, {P: 1, Q: 0}, {P: 1, Q: 2})


def test_resolve_with_no_records(ws):
    res = resolve(ws, make_mission(), 4)
    assert (res.resolved, res.pending, res.predicted, res.unscored) == ((), 0, {}, {})


def test_resolved_targets_are_sorted_by_week_stream_jurisdiction_horizon(ws):
    for stream in (STREAM, "w/adm2"):
        spec = count_spec(id=stream, jurisdictions=("A", "B"), support_max=99)
        for issue in (3, 4, 5):
            publish(ws, spec, issue, {(j, w): 1.0 for j in "AB" for w in range(issue)}, at(issue))
    # files come back in (stream, week, program) path order, records in file order: neither is the sorted order
    store(
        ws,
        forecast(P, tgt("B", week=1, horizon=0)), forecast(P, tgt("A", week=1, horizon=1)),
        forecast(P, tgt("A", week=1, horizon=0)), forecast(P, tgt("A", week=2, horizon=0)),
        forecast(P, tgt("A", week=1, horizon=0, stream="w/adm2")),
    )
    res = resolve(ws, make_mission(streams=(STREAM, "w/adm2")), 5)
    keys = [(r.target.reference_week, r.target.stream, r.target.jurisdiction, r.target.horizon) for r in res.resolved]
    assert keys == [
        (1, STREAM, "A", 0), (1, STREAM, "A", 1), (1, STREAM, "B", 0), (1, "w/adm2", "A", 0), (2, STREAM, "A", 0)
    ]


# --- per-stream tallies ---


def test_pending_and_programs_are_tallied_per_stream(ws):
    for stream in (STREAM, "w/adm2"):
        publish(ws, count_spec(id=stream, jurisdictions=("A",), support_max=99), 4, {("A", 2): 5.0}, at(4))
    store(
        ws,
        forecast(P, tgt(stream=STREAM)),  # resolved
        forecast(P, tgt(stream="w/adm2", horizon=3)),  # pending: its vintage is not published
        forecast(Q, tgt(stream="w/adm2", horizon=3)),  # pending
        failed(Q, tgt(stream="w/adm2", horizon=0)),  # a record, but no forecast
        failed(Q, tgt(stream=STREAM, horizon=0)),
    )
    res = resolve(ws, make_mission(streams=(STREAM, "w/adm2")), 4)
    assert res.pending == 2
    assert res.pending_by_stream == {STREAM: 0, "w/adm2": 2}
    assert res.programs_by_stream == {STREAM: (P, Q), "w/adm2": (P, Q)}


def test_programs_by_stream_includes_programs_with_only_unscored_records(ws):
    publish(ws, count_spec(jurisdictions=("A",), support_max=99), 4, {("A", 2): 5.0}, at(4))
    store(ws, forecast(P, tgt()), failed(Q, tgt(horizon=0)))
    res = resolve(ws, make_mission(), 4)
    assert res.programs_by_stream == {STREAM: (P, Q)}
    assert res.pending_by_stream == {STREAM: 0}


def test_per_stream_tallies_are_empty_without_records(ws):
    res = resolve(ws, make_mission(), 4)
    assert (res.pending_by_stream, res.programs_by_stream) == ({}, {})
