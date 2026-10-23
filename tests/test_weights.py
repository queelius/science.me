import math
import warnings

import pytest
from helpers import rt

from scienceme.model import Target
from scienceme.scoring import PointScore, ResolvedTarget
from scienceme.weights import normalized_weights, regime_tv, run_mixture

GOOD, BAD = math.log(0.8), math.log(0.2)


def test_first_target_has_equal_weights():
    adv = run_mixture([rt(1, 2, {"a": math.log(0.8), "b": math.log(0.2)})], tau=1.0, half_life=1e9, as_of=2)
    assert adv.steps[0].weights == {"a": 0.5, "b": 0.5}
    assert adv.cumulative == pytest.approx({"a": math.log(1.6), "b": math.log(0.4)})


def test_newcomer_cannot_outrank_an_incumbent_that_beat_the_mixture():  # review finding 3
    good, bad = math.log(0.8), math.log(0.2)
    ks = [rt(r, r + 1, {"a": good, "b": bad}) for r in range(1, 6)] + [rt(6, 7, {"a": good, "b": bad, "c": good})]
    adv = run_mixture(ks, tau=1.0, half_life=1e9, as_of=7)
    w = normalized_weights(adv.cumulative, {"a", "b", "c"}, 1.0)
    assert w["a"] > w["c"] > w["b"]


def test_weights_wait_for_resolution():
    ks = [
        rt(1, 3, {"a": math.log(0.9), "b": math.log(0.1)}, j="A"),
        rt(2, 4, {"a": math.log(0.5), "b": math.log(0.5)}, j="B"),
        rt(3, 5, {"a": math.log(0.5), "b": math.log(0.5)}, j="C"),
    ]
    steps = run_mixture(ks, tau=1.0, half_life=1e9, as_of=5).steps
    assert steps[1].weights == {"a": 0.5, "b": 0.5} and steps[2].weights["a"] > 0.5


def test_targets_of_one_week_share_one_weight_table():
    ks = [rt(1, 2, {"a": math.log(0.9), "b": math.log(0.1)}, j="A"), rt(1, 2, {"a": GOOD, "b": BAD}, j="B")]
    ks.append(rt(2, 3, {"a": GOOD, "b": BAD}))
    steps = run_mixture(ks, tau=1.0, half_life=1e9, as_of=3).steps
    assert steps[0].weights == steps[1].weights == {"a": 0.5, "b": 0.5}
    # week 2 sees both week-1 targets: a's advantage is log(1.8) + log(1.6)
    assert steps[2].weights["a"] == pytest.approx(1.8 * 1.6 / (1.8 * 1.6 + 0.2 * 0.4))


def test_forgetting_halves_per_half_life():
    adv = run_mixture([rt(4, 5, {"a": math.log(0.8), "b": math.log(0.2)})], tau=1.0, half_life=4.0, as_of=8)
    assert adv.current["a"] == pytest.approx(0.5 * adv.cumulative["a"])


def test_forgetting_counts_from_the_target_week():
    adv = run_mixture([rt(2, 5, {"a": GOOD, "b": BAD}, h=2)], tau=1.0, half_life=4.0, as_of=8)  # target week 4
    assert adv.current == pytest.approx({m: 0.5 * v for m, v in adv.cumulative.items()})


def test_the_weights_forget_too():
    # j's target week is 1; at reference week 3 with half-life 1 its advantage counts a quarter
    ks = [rt(1, 2, {"a": GOOD, "b": BAD}), rt(3, 4, {"a": GOOD, "b": BAD})]
    adv = run_mixture(ks, tau=1.0, half_life=1.0, as_of=4)
    expected = normalized_weights({"a": 0.25 * math.log(1.6), "b": 0.25 * math.log(0.4)}, {"a", "b"}, 1.0)
    assert adv.steps[1].weights == pytest.approx(expected)


def test_sleeping_program_is_absent():
    adv = run_mixture([rt(1, 2, {"a": 0.0})], tau=1.0, half_life=1e9, as_of=2)
    assert "z" not in normalized_weights(adv.cumulative, {"a"}, 1.0)


def test_a_sleeping_program_neither_gains_nor_loses():
    ks = [rt(1, 2, {"a": GOOD, "b": BAD}), rt(2, 3, {"a": GOOD}), rt(3, 4, {"a": BAD, "b": GOOD})]
    adv = run_mixture(ks, tau=1.0, half_life=1e9, as_of=4)
    assert adv.steps[1].weights == {"a": 1.0}  # alone, a is the mixture: zero advantage at step 1
    mix_2 = adv.steps[2].score.log_p
    assert adv.cumulative == pytest.approx({"a": math.log(1.6) + BAD - mix_2, "b": math.log(0.4) + GOOD - mix_2})


def test_mixture_score_is_the_weighted_mixture():
    t1 = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=0)
    t2 = Target(stream="w/adm", jurisdiction="A", reference_week=2, horizon=0)
    sa = PointScore(log_p=math.log(0.6), cdf_below=0.2, cdf_at=0.8)
    sb = PointScore(log_p=math.log(0.1), cdf_below=0.7, cdf_at=0.8)
    ks = [ResolvedTarget(target=t, realized=3, scores={"a": sa, "b": sb}) for t in (t1, t2)]
    steps = run_mixture(ks, tau=2.0, half_life=1e9, as_of=3).steps
    assert steps[0].score.log_p == pytest.approx(math.log(0.35))
    assert (steps[0].score.cdf_below, steps[0].score.cdf_at) == pytest.approx((0.45, 0.8))
    w = steps[1].weights
    assert w == pytest.approx(normalized_weights({"a": math.log(0.6 / 0.35), "b": math.log(0.1 / 0.35)}, w, 2.0))
    assert steps[1].score.log_p == pytest.approx(math.log(w["a"] * 0.6 + w["b"] * 0.1))
    assert steps[1].score.cdf_below == pytest.approx(w["a"] * 0.2 + w["b"] * 0.7)


def test_advantages_are_against_the_mixture():
    ks = [rt(r, r + 1, {"a": GOOD, "b": BAD, "c": math.log(0.5)}) for r in range(1, 4)]
    adv = run_mixture(ks, tau=1.0, half_life=1e9, as_of=4)
    for k, step in zip(ks, adv.steps):
        # the mixture's own expected advantage is zero: sum_m w_m * p_m / p_mix = 1
        total = sum(w * math.exp(k.scores[m].log_p - step.score.log_p) for m, w in step.weights.items())
        assert total == pytest.approx(1.0)


def test_steps_follow_week_stream_jurisdiction_horizon_order():
    ks = [rt(2, 4, {"a": 0.0}), rt(1, 3, {"a": 0.0}, j="B"), rt(1, 3, {"a": 0.0}, h=1), rt(1, 2, {"a": 0.0})]
    steps = run_mixture(ks, tau=1.0, half_life=1e9, as_of=4).steps
    keys = [(s.target.reference_week, s.target.jurisdiction, s.target.horizon) for s in steps]
    assert keys == [(1, "A", 0), (1, "A", 1), (1, "B", 0), (2, "A", 0)]


def test_no_targets_no_advantages():
    adv = run_mixture([], tau=1.0, half_life=8.0, as_of=4)
    assert (adv.cumulative, adv.current, adv.steps) == ({}, {}, ())


def test_tau_tempers():
    assert normalized_weights({"a": 2.0, "b": 0.0}, {"a", "b"}, 2.0)["a"] == pytest.approx(math.e / (math.e + 1))


def test_normalized_weights_cover_exactly_the_awake_programs():
    assert normalized_weights({"a": 1.0, "z": 5.0}, set(), 1.0) == {}
    assert normalized_weights({"a": 0.0, "z": 5.0}, {"a", "new"}, 1.0) == {"a": 0.5, "new": 0.5}


def test_a_dominant_program_leaves_the_mixture_finite():
    ks = [rt(1, 2, {"a": GOOD, "b": BAD}), rt(2, 3, {"a": BAD, "b": GOOD})]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        adv = run_mixture(ks, tau=1e-6, half_life=1e9, as_of=3)  # a's weight at step 1 is exp(log(1.6) / 1e-6)
    assert adv.steps[1].weights == {"a": 1.0, "b": 0.0}
    assert adv.steps[1].score.log_p == pytest.approx(BAD)


def test_regime_tv():
    assert regime_tv({"a": 1.0}, {"b": 1.0}) == 1.0 and regime_tv({"a": 0.5, "b": 0.5}, {"a": 0.5, "b": 0.5}) == 0.0
    assert regime_tv({"a": 0.7, "b": 0.3}, {"a": 0.4, "c": 0.6}) == pytest.approx(0.6)
