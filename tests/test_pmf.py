import math
import pytest
from scienceme.pmf import Pmf, PmfError, mix, floored_log_prob, floored_cdf

def test_from_probs_trims_zero_tails():
    p = Pmf.from_probs(3, [0.0, 0.25, 0.75, 0.0])
    assert (p.lo, p.p, p.hi) == (4, (0.25, 0.75), 5)

@pytest.mark.parametrize("probs", [[-0.1, 1.1], [float("nan"), 1.0], [0.5, 0.4]])
def test_from_probs_rejects_invalid(probs):
    with pytest.raises(PmfError):
        Pmf.from_probs(0, probs)

def test_prob_and_cdf_outside_support():
    p = Pmf.from_probs(2, [0.5, 0.5])
    assert (p.prob(1), p.prob(3), p.cdf(1), p.cdf(2), p.cdf(99)) == (0.0, 0.5, 0.0, 0.5, 1.0)

def test_mix_aligns_supports():
    m = mix([Pmf.point(0), Pmf.point(10)], [0.9, 0.1])
    assert (m.lo, m.hi) == (0, 10)
    assert m.prob(0) == pytest.approx(0.9) and m.prob(10) == pytest.approx(0.1)

def test_entropy_in_nats():
    assert mix([Pmf.point(0), Pmf.point(1)], [0.5, 0.5]).entropy() == pytest.approx(math.log(2))

def test_floor_bounds_the_loss():
    assert floored_log_prob(Pmf.point(0), 50, eps=0.01, support_max=99) == pytest.approx(math.log(0.01 / 100))

def test_floored_cdf():
    assert floored_cdf(Pmf.point(0), 0, eps=0.01, support_max=99) == pytest.approx(0.99 + 0.01 / 100)

def test_from_samples_keeps_interior_zeros():
    p = Pmf.from_samples([1, 1, 2, 4])
    assert (p.lo, p.p) == (1, (0.5, 0.25, 0.0, 0.25))

def test_json_round_trip():
    p = Pmf.from_probs(5, [0.2, 0.3, 0.5])
    assert Pmf.model_validate_json(p.model_dump_json()) == p

def test_point_and_uniform():
    assert (Pmf.point(7).lo, Pmf.point(7).hi, Pmf.point(7).p) == (7, 7, (1.0,))
    u = Pmf.uniform(2, 5)
    assert (u.lo, u.hi) == (2, 5)
    assert u.p == pytest.approx((0.25,) * 4)

def test_uniform_rejects_reversed_bounds():
    with pytest.raises(PmfError):
        Pmf.uniform(5, 2)

@pytest.mark.parametrize("probs", [[], [[0.5, 0.5]], [float("inf"), 0.0]])
def test_from_probs_rejects_malformed_shape(probs):
    with pytest.raises(PmfError):
        Pmf.from_probs(0, probs)

def test_from_probs_renormalizes_small_drift():
    p = Pmf.from_probs(0, [0.5, 0.5 + 5e-7])
    assert sum(p.p) == pytest.approx(1.0, abs=1e-12)

@pytest.mark.parametrize("samples", [[], [1.5, 2.0], [[1, 2]]])
def test_from_samples_rejects_invalid(samples):
    with pytest.raises(PmfError):
        Pmf.from_samples(samples)

@pytest.mark.parametrize(
    "p", [(0.0, 1.0), (1.0, 0.0), (0.5, 0.4), (), (float("nan"),), (-0.5, 1.5)]
)
def test_direct_construction_enforces_invariants(p):
    with pytest.raises(ValueError):
        Pmf(lo=0, p=p)

def test_deserialization_enforces_invariants():
    with pytest.raises(ValueError):
        Pmf.model_validate_json('{"lo": 0, "p": [0.5, 0.4]}')

def test_pmf_is_frozen_and_rejects_extra_fields():
    p = Pmf.point(0)
    with pytest.raises(ValueError):
        p.lo = 1
    with pytest.raises(ValueError):
        Pmf.model_validate({"lo": 0, "p": [1.0], "extra": 1})

def test_entropy_of_point_mass_is_zero():
    assert Pmf.point(3).entropy() == 0.0

def test_within_checks_whole_support():
    p = Pmf.from_probs(2, [0.5, 0.5])
    assert p.within(2, 3) and p.within(0, 99)
    assert not p.within(3, 99) and not p.within(0, 2)

@pytest.mark.parametrize(
    "weights", [[1.0], [0.5, 0.4], [-0.5, 1.5], [float("nan"), 1.0]]
)
def test_mix_rejects_invalid_weights(weights):
    with pytest.raises(PmfError):
        mix([Pmf.point(0), Pmf.point(1)], weights)

def test_mix_rejects_empty():
    with pytest.raises(PmfError):
        mix([], [])

def test_mix_zero_weight_component_does_not_widen_support():
    m = mix([Pmf.point(0), Pmf.point(10)], [1.0, 0.0])
    assert (m.lo, m.hi) == (0, 0)

@pytest.mark.parametrize("eps, support_max", [(0.0, 9), (1.5, 9), (0.1, -1)])
def test_floor_rejects_invalid_parameters(eps, support_max):
    with pytest.raises(PmfError):
        floored_log_prob(Pmf.point(0), 0, eps=eps, support_max=support_max)
    with pytest.raises(PmfError):
        floored_cdf(Pmf.point(0), 0, eps=eps, support_max=support_max)

def test_floored_cdf_is_clamped_outside_support_max():
    p = Pmf.point(0)
    assert floored_cdf(p, -5, eps=0.2, support_max=9) == 0.0
    assert floored_cdf(p, 500, eps=0.2, support_max=9) == pytest.approx(1.0)
