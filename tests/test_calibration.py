import math

import pytest

from scienceme.calibration import Calibration, calibration
from scienceme.scoring import PointScore


def pt(below: float, at: float) -> PointScore:
    return PointScore(log_p=math.log(at - below) if at > below else 0.0, cdf_below=below, cdf_at=at)


def test_calibrated_discrete_forecast_is_uniform():
    pts = [PointScore(log_p=math.log(0.5), cdf_below=0.0, cdf_at=0.5), PointScore(log_p=math.log(0.5), cdf_below=0.5, cdf_at=1.0)]
    assert calibration(pts).pit == pytest.approx((0.1,) * 10)


def test_coverage_of_a_full_interval():
    c = calibration([PointScore(log_p=0.0, cdf_below=0.0, cdf_at=1.0)])
    assert (c.coverage_50, c.coverage_90, c.n) == (pytest.approx(0.5), pytest.approx(0.9), 1)


def test_overconfidence_is_u_shaped():
    pts = [PointScore(log_p=-9.0, cdf_below=0.0, cdf_at=0.01), PointScore(log_p=-9.0, cdf_below=0.99, cdf_at=1.0)]
    c = calibration(pts)
    assert c.pit[0] == pytest.approx(0.5) and c.pit[-1] == pytest.approx(0.5) and c.coverage_90 == pytest.approx(0.0)


def test_no_points_gives_empty_histogram_and_no_coverage():
    c = calibration([])
    assert c == Calibration(pit=(0.0,) * 10, coverage_50=None, coverage_90=None, n=0)
    assert Calibration.model_validate_json(c.model_dump_json()) == c


def test_bins_sets_the_histogram_length():
    assert len(calibration([pt(0.2, 0.6)], bins=4).pit) == 4
    assert calibration([], bins=3).pit == (0.0, 0.0, 0.0)


@pytest.mark.parametrize("bins", [0, -1])
def test_bins_must_be_positive(bins):
    with pytest.raises(ValueError, match="bins"):
        calibration([pt(0.0, 1.0)], bins=bins)


def test_one_bin_holds_everything():
    assert calibration([pt(0.1, 0.3), pt(0.5, 0.9)], bins=1).pit == pytest.approx((1.0,))


def test_partial_overlap_is_computed_exactly():
    c = calibration([pt(0.0, 0.5)])
    assert c.pit == pytest.approx((0.2,) * 5 + (0.0,) * 5)
    assert c.coverage_50 == pytest.approx(0.5)  # [0.25, 0.75] holds 0.25 of the 0.5 width
    assert c.coverage_90 == pytest.approx(0.9)  # [0.05, 0.95] holds 0.45 of the 0.5 width


def test_interval_inside_a_bin_splits_by_width():
    c = calibration([pt(0.1, 0.6)], bins=4)  # bins [0, .25) [.25, .5) [.5, .75) [.75, 1]
    assert c.pit == pytest.approx((0.15 / 0.5, 0.25 / 0.5, 0.1 / 0.5, 0.0))
    assert c.coverage_50 == pytest.approx(0.35 / 0.5)  # [0.25, 0.6]
    assert c.coverage_90 == pytest.approx(1.0)  # [0.05, 0.95] contains the whole interval


def test_pit_sums_to_one():
    pts = [pt(0.05, 0.31), pt(0.31, 0.4), pt(0.4, 0.97), pt(0.97, 1.0), pt(0.0, 1.0)]
    assert sum(calibration(pts, bins=7).pit) == pytest.approx(1.0)


def test_point_mass_lands_in_one_bin():
    c = calibration([PointScore(log_p=0.0, cdf_below=0.35, cdf_at=0.35)])
    assert c.pit == pytest.approx((0.0, 0.0, 0.0, 1.0) + (0.0,) * 6)


def test_point_mass_at_one_lands_in_the_top_bin_and_at_zero_in_the_first():
    assert calibration([PointScore(log_p=0.0, cdf_below=1.0, cdf_at=1.0)]).pit[-1] == pytest.approx(1.0)
    assert calibration([PointScore(log_p=0.0, cdf_below=0.0, cdf_at=0.0)]).pit[0] == pytest.approx(1.0)


def test_point_mass_on_a_bin_edge_goes_to_the_upper_bin():
    assert calibration([PointScore(log_p=0.0, cdf_below=0.3, cdf_at=0.3)]).pit[3] == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("value", "in50", "in90"),
    [(0.25, 1.0, 1.0), (0.75, 1.0, 1.0), (0.5, 1.0, 1.0), (0.1, 0.0, 1.0), (0.05, 0.0, 1.0), (0.04, 0.0, 0.0), (0.96, 0.0, 0.0)],
)
def test_point_mass_is_covered_iff_it_lies_in_the_closed_interval(value, in50, in90):
    c = calibration([PointScore(log_p=0.0, cdf_below=value, cdf_at=value)])
    assert (c.coverage_50, c.coverage_90) == (in50, in90)


def test_mixed_points_average_with_equal_weight():
    c = calibration([pt(0.0, 1.0), PointScore(log_p=0.0, cdf_below=0.5, cdf_at=0.5)])
    assert c.n == 2
    assert c.coverage_50 == pytest.approx((0.5 + 1.0) / 2)
    assert c.pit[5] == pytest.approx((0.1 + 1.0) / 2)


def test_coverage_boundary_at_ninety_percent_upper_edge():
    c = calibration([PointScore(log_p=0.0, cdf_below=0.95, cdf_at=0.95)])
    assert c.coverage_90 == 1.0


def test_point_mass_just_outside_unit_interval_is_clamped_to_the_end_bins():
    assert calibration([PointScore(log_p=0.0, cdf_below=-1e-12, cdf_at=-1e-12)]).pit[0] == pytest.approx(1.0)
    assert calibration([PointScore(log_p=0.0, cdf_below=1 + 1e-12, cdf_at=1 + 1e-12)]).pit[-1] == pytest.approx(1.0)
