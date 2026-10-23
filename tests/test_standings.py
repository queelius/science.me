import math
from collections import defaultdict
from types import SimpleNamespace

import numpy as np
import pytest
from helpers import CONST, at, count_spec, covariate_spec, make_mission, publish, write_program
from pydantic import TypeAdapter

from scienceme.claims import Verdict
from scienceme.gain import RankedItem, Ranking, save_ranking
from scienceme.manifest import InterfaceVar, PairDecl, Tag, program_files
from scienceme.mission import Claim, save_mission
from scienceme.calibration import Calibration
from scienceme.model import Intervention, Isolation, Target, TargetFilter, Timing
from scienceme.pmf import Pmf
from scienceme.readback import CaptainVerdict, Readback, ReadbackFlag
from scienceme.record import PredictionRecord, RecordStore, UnscoredRecord
from scienceme.registry import Registry, RegistryError
from scienceme.scoring import resolve
from scienceme.standings import Standings, _fmt, _quantized, _round, check_all, compute, render, write_all
from scienceme.weights import regime_tv, run_mixture
from scienceme.worker import scorer_hash
from scienceme.workspace import Workspace

STREAM = "w/adm"
SCHOOL = Claim(id="school", statement="Closing schools lowers admissions.", scope=TargetFilter())
SCHOOLS_CLOSED = InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("beta",))
STANDINGS = TypeAdapter(list[Standings])


def tgt(week, stream=STREAM, horizon=0) -> Target:
    """A target of the mission's lag of 2, so it resolves at issue week + horizon + 2."""
    return Target(stream=stream, jurisdiction="A", reference_week=week, horizon=horizon, resolution_lag=2)


def forecast(program, target, value, mission="m") -> PredictionRecord:
    return PredictionRecord(
        mission=mission, program=program, target=target, pmf=Pmf.point(value), scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def failed(program, target, mission="m") -> UnscoredRecord:
    return UnscoredRecord(
        mission=mission, program=program, target=target, reason="boom", scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def store(ws, *records) -> None:
    """Write `records`, one file per (mission, program, stream, reference week)."""
    files = defaultdict(list)
    for r in records:
        files[(r.mission, r.program, r.target.stream, r.target.reference_week)].append(r)
    for (mission, program, stream, week), rs in files.items():
        RecordStore(ws).write(mission, stream, week, program, rs)


def freeze(ws, name, **fields) -> str:
    """Write and freeze program `name` (distinct content per name); return its closure hash."""
    write_program(ws, name, CONST + f"#{name}\n", **fields)
    return Registry(ws).freeze(name, at(0)).closure_hash


def publish_through(ws, stream, last_issue=5) -> None:
    """Publish issues 3..last_issue of `stream`, each showing the value 5 for every earlier week."""
    spec = count_spec(id=stream, jurisdictions=("A",), support_max=99)
    for issue in range(3, last_issue + 1):
        publish(ws, spec, issue, {("A", w): 5.0 for w in range(1, issue)}, at(issue))


@pytest.fixture
def world(ws):
    """Programs `good` (forecasts 5) and `bad` (forecasts 9) on three targets that all realize 5.

    The mission has one claim, `school`, with no matched pair.
    """
    publish_through(ws, STREAM)
    good = freeze(ws, "good", author_lineage="alpha", interface=(SCHOOLS_CLOSED,))
    bad = freeze(ws, "bad", author_lineage="beta")
    store(ws, *(forecast(good, tgt(w), 5) for w in (1, 2, 3)), *(forecast(bad, tgt(w), 9) for w in (1, 2, 3)))
    return SimpleNamespace(good=good, bad=bad, mission=make_mission(claims=(SCHOOL,)))


def only_stream(s: Standings):
    (stream,) = s.streams
    return stream


# --- the brief's behaviors ---


def test_compute_and_render_are_deterministic(ws, world):
    assert render([compute(ws, world.mission, 5)]) == render([compute(ws, world.mission, 5)])
    assert compute(ws, world.mission, 5) == compute(ws, world.mission, 5)


def test_programs_sorted_by_cumulative_weight(ws, world):
    stream = only_stream(compute(ws, world.mission, 5))
    assert [p.name for p in stream.programs] == ["good", "bad"]
    assert stream.programs[0].w_cumulative > stream.programs[1].w_cumulative
    text = render([compute(ws, world.mission, 5)])
    assert text.index("| good |") < text.index("| bad |")


def test_render_sorts_by_weight_then_name_whatever_the_stored_order(ws, world):
    s = compute(ws, world.mission, 5)
    stream = only_stream(s)
    reversed_ = s.model_copy(update={"streams": (stream.model_copy(update={"programs": stream.programs[::-1]}),)})
    assert render([reversed_]) == render([s])
    tied = [p.model_copy(update={"w_cumulative": 0.5}) for p in stream.programs]
    tie = s.model_copy(update={"streams": (stream.model_copy(update={"programs": tuple(tied)}),)})
    text = render([tie])
    assert text.index("| bad |") < text.index("| good |")  # equal weights: by name


def test_claim_without_pairs_reads_insufficient(ws, world):
    s = compute(ws, world.mission, 5)
    assert [(c.claim, c.pairs, c.verdict) for c in s.claims] == [("school", (), Verdict.INSUFFICIENT)]
    text = render([s])
    assert "insufficient evidence" in text
    assert SCHOOL.statement in text


def test_pending_targets_are_counted(ws, world):
    # week 4 resolves at issue 6, which is not published
    store(ws, forecast(world.good, tgt(4), 5))
    stream = only_stream(compute(ws, world.mission, 5))
    assert (stream.n_resolved, stream.n_pending) == (3, 1)
    assert "pending 1" in render([compute(ws, world.mission, 5)])


def test_pending_counts_distinct_targets_not_records(ws, world):
    # both programs forecast the same pending target: one target, two records
    store(ws, forecast(world.good, tgt(4), 5), forecast(world.bad, tgt(4), 9))
    stream = only_stream(compute(ws, world.mission, 5))
    assert (stream.n_resolved, stream.n_pending) == (3, 1)
    store(ws, forecast(world.good, tgt(5), 5))
    assert only_stream(compute(ws, world.mission, 5)).n_pending == 2


def test_check_detects_staleness(ws, world):
    save_mission(ws, world.mission)
    write_all(ws)
    assert check_all(ws)
    store(ws, forecast(world.good, tgt(4), 5))
    assert not check_all(ws)
    write_all(ws)
    assert check_all(ws)


def test_json_round_trip(ws, world):
    save_mission(ws, world.mission)
    write_all(ws)
    (loaded,) = STANDINGS.validate_json((ws.root / "standings.json").read_text())
    assert loaded.mission == "m"
    assert [loaded] == [compute(ws, world.mission, 5)]


def test_json_round_trip_keeps_pairs_rankings_and_missing_coverage(ws, world):
    yes, no = pair(ws)
    publish_through(ws, "w/adm2")
    store(ws, failed(world.bad, tgt(1, stream="w/adm2")))  # a stream where a program has no calibration
    save_ranking(ws, Ranking(mission="m", as_of=5, items=(ranked(0, supporting=(yes,), failed_=(no,)),)))
    s = compute(ws, make_mission(streams=(STREAM, "w/adm2"), claims=(SCHOOL,)), 5)
    assert s.claims[0].pairs and s.ranking is not None and s.streams[1].programs[0].calibration.coverage_90 is None
    assert STANDINGS.validate_json(STANDINGS.dump_json([s], indent=2)) == [s]


# --- what compute reports ---


def test_program_standings_report_the_registry_and_the_record(ws, world):
    s = compute(ws, world.mission, 5)
    assert (s.mission, s.epoch, s.as_of, s.scorer) == ("m", 1, 5, scorer_hash())
    good, bad = only_stream(s).programs
    assert (good.program, good.name, good.lineage) == (world.good, "good", "alpha")
    assert (bad.program, bad.name, bad.lineage) == (world.bad, "bad", "beta")
    assert good.w_cumulative + bad.w_cumulative == pytest.approx(1.0)
    assert good.w_current + bad.w_current == pytest.approx(1.0)
    assert good.advantage_cumulative > 0 > bad.advantage_cumulative
    assert good.advantage_current > 0 > bad.advantage_current
    assert (good.n_predicted, bad.n_predicted) == (3, 3)
    assert (good.coverage, bad.coverage) == (1.0, 1.0)
    assert good.calibration.n == bad.calibration.n == 3


def test_length_is_the_size_of_every_closure_file(ws, world):
    lib = freeze(ws, "lib", library=True)
    write_program(ws, "top", CONST + "#top\n", imports={"lib": lib})
    top = Registry(ws).freeze("top", at(0)).closure_hash
    store(ws, forecast(top, tgt(1), 5))
    by_name = {p.name: p for p in only_stream(compute(ws, world.mission, 5)).programs}

    def size(name):
        return sum((ws.programs / name / rel).stat().st_size for rel in program_files(ws.programs / name))

    assert by_name["good"].length_bytes == size("good")
    assert by_name["top"].length_bytes == size("top") + size("lib") > size("top")


def test_calibration_is_the_programs_own_on_the_stream(ws, world):
    good, bad = only_stream(compute(ws, world.mission, 5)).programs
    # `good` put its mass where the count fell; `bad` put it far above
    assert good.calibration.n == 3 and bad.calibration.n == 3
    assert good.calibration.coverage_90 != bad.calibration.coverage_90


def test_mixture_fields_come_from_the_mixture_steps(ws, world):
    mission = world.mission
    resolution = resolve(ws, mission, 5)
    adv = run_mixture(resolution.resolved, mission.tau, mission.half_life_weeks, 5)
    stream = only_stream(compute(ws, mission, 5))
    assert stream.stream == STREAM
    assert stream.n_resolved == 3
    assert stream.mixture_log_score == pytest.approx(sum(step.score.log_p for step in adv.steps))
    assert stream.mixture_calibration.n == 3


def test_coverage_counts_unscored_records_on_every_stream(ws, world):
    publish_through(ws, "w/adm2")
    mission = make_mission(streams=(STREAM, "w/adm2"))
    store(ws, failed(world.bad, tgt(1, stream="w/adm2")))
    by_stream = {s.stream: {p.name: p for p in s.programs} for s in compute(ws, mission, 5).streams}
    assert by_stream[STREAM]["bad"].coverage == pytest.approx(3 / 4)  # mission wide, in every table
    assert by_stream["w/adm2"]["bad"].coverage == pytest.approx(3 / 4)
    assert by_stream[STREAM]["good"].coverage == 1.0
    assert set(by_stream["w/adm2"]) == {"bad"}


def test_a_program_with_only_unscored_records_is_awake_without_calibration(ws, world):
    publish_through(ws, "w/adm2")
    store(ws, failed(world.bad, tgt(1, stream="w/adm2")))
    s = compute(ws, make_mission(streams=(STREAM, "w/adm2")), 5)
    adm, adm2 = s.streams
    (bad,) = adm2.programs
    assert (bad.w_cumulative, bad.w_current) == (1.0, 1.0)  # alone on this stream
    # advantages are the mission's: the program's record on every stream, whichever table shows it
    bad_on_adm = next(p for p in adm.programs if p.name == "bad")
    assert (bad.advantage_cumulative, bad.advantage_current) == (
        bad_on_adm.advantage_cumulative, bad_on_adm.advantage_current
    )
    assert bad.advantage_cumulative < 0
    assert bad.calibration.n == 0 and bad.calibration.coverage_90 is None
    assert (adm2.n_resolved, adm2.n_pending) == (0, 0)
    assert adm2.mixture_log_score == 0.0 and adm2.mixture_calibration.n == 0
    assert f"| bad | 1.000 | 1.000 | {bad.advantage_cumulative:.2f} | 3 | 0.75 | n/a | missing |" in render([s])


def test_a_program_that_failed_every_target_is_listed_with_no_coverage(ws, world):
    before = only_stream(compute(ws, world.mission, 5))
    flaky = freeze(ws, "flaky")
    store(ws, *(failed(flaky, tgt(w)) for w in (1, 2, 3)))
    s = compute(ws, world.mission, 5)
    stream = only_stream(s)
    by_name = {p.name: p for p in stream.programs}
    assert set(by_name) == {"good", "bad", "flaky"}
    assert (by_name["flaky"].n_predicted, by_name["flaky"].coverage) == (0, 0.0)
    assert by_name["flaky"].calibration.n == 0 and by_name["flaky"].calibration.coverage_90 is None
    assert (by_name["flaky"].advantage_cumulative, by_name["flaky"].advantage_current) == (0.0, 0.0)
    for weights in ({p.name: p.w_cumulative for p in stream.programs}, {p.name: p.w_current for p in stream.programs}):
        assert all(math.isfinite(w) and 0 < w < 1 for w in weights.values())
        assert sum(weights.values()) == pytest.approx(1.0)
    # it has no score, so it neither changes the mixture nor anyone's advantage
    assert stream.mixture_log_score == before.mixture_log_score
    assert by_name["good"].advantage_cumulative == next(p for p in before.programs if p.name == "good").advantage_cumulative
    text = render([s])
    assert "| flaky |" in text and "| 0 | 0.00 | n/a | missing |" in text


def test_withdrawn_programs_are_not_awake(ws, world):
    Registry(ws).withdraw(world.bad, at(6), "test")
    s = compute(ws, world.mission, 5)
    (good,) = only_stream(s).programs
    assert (good.name, good.w_cumulative, good.w_current) == ("good", 1.0, 1.0)
    assert only_stream(s).n_withdrawn == 1
    assert "| bad |" not in render([s])


def test_a_stream_whose_programs_are_all_withdrawn_has_no_active_programs(ws, world):
    for program in (world.good, world.bad):
        Registry(ws).withdraw(program, at(6), "test")
    s = compute(ws, world.mission, 5)
    stream = only_stream(s)
    assert (stream.programs, stream.n_withdrawn, stream.n_resolved) == ((), 2, 3)
    text = render([s])
    assert "No active programs." in text and "No forecasts yet." not in text
    assert s.indicators.interface_weight_share == 0.0


def test_a_stream_without_records_has_no_forecasts_yet(ws):
    publish_through(ws, STREAM)
    stream = only_stream(compute(ws, make_mission(), 5))
    assert (stream.programs, stream.n_withdrawn) == ((), 0)
    text = render([compute(ws, make_mission(), 5)])
    assert "No forecasts yet." in text and "No active programs." not in text


def test_regime_flag_is_total_variation_above_the_mission_threshold(ws, world):
    stream = only_stream(compute(ws, world.mission, 5))
    w_cum = {p.program: p.w_cumulative for p in stream.programs}
    w_cur = {p.program: p.w_current for p in stream.programs}
    tv = stream.regime_tv
    assert tv == pytest.approx(regime_tv(w_cum, w_cur), abs=1e-9) and tv > 0
    for threshold, flag in ((tv / 2, True), (tv, False), (tv * 2, False)):
        got = only_stream(compute(ws, make_mission(claims=(SCHOOL,), regime_flag_tv=threshold), 5))
        assert got.regime_flag is flag


def test_regime_shift_is_rendered(ws, world):
    quiet = render([compute(ws, make_mission(claims=(SCHOOL,), regime_flag_tv=0.5), 5)])
    shifted = render([compute(ws, make_mission(claims=(SCHOOL,), regime_flag_tv=0.0), 5)])
    assert "regime shift" not in quiet and "regime shift" in shifted


def test_flags_come_from_the_readback_sorted_by_value(ws, world):
    assert [p.flags for p in only_stream(compute(ws, world.mission, 5)).programs] == [
        (ReadbackFlag.MISSING,),
        (ReadbackFlag.MISSING,),
    ]
    readback = Readback(
        author_lineage="alpha", author_agent="reader", assumptions=(), inferred_tags={"school": Tag.ASSERTS},
        inferred_interface=("schools_closed",), summary="s",
    )
    (ws.programs / "good" / "readback.json").write_text(readback.model_dump_json(), encoding="utf-8")
    good, _ = only_stream(compute(ws, world.mission, 5)).programs
    assert good.flags == (ReadbackFlag.PENDING, ReadbackFlag.SAME_LINEAGE, ReadbackFlag.TAG_MISMATCH)
    assert "pending, same-lineage, tag-mismatch" in render([compute(ws, world.mission, 5)])


def clean_readback(ws, name, lineage="reader", interface=()):
    readback = Readback(
        author_lineage=lineage, author_agent="reader", assumptions=(), inferred_tags={},
        inferred_interface=interface, summary="s", captain_verdict=CaptainVerdict.MATCHES,
    )
    (ws.programs / name / "readback.json").write_text(readback.model_dump_json(), encoding="utf-8")


def test_indicators_cover_the_top_set(ws, world):
    # a large tau keeps the weights near 1/2 each, so the top set (weight reaching 0.9) is both programs
    mission = make_mission(claims=(SCHOOL,), tau=1000.0)
    clean_readback(ws, "good", interface=("schools_closed",))
    s = compute(ws, mission, 5)
    good, bad = only_stream(s).programs
    total = good.w_cumulative + bad.w_cumulative
    assert 0.5 < good.w_cumulative < 0.9
    assert s.indicators.interface_weight_share == pytest.approx(good.w_cumulative / total)
    assert s.indicators.readback_clean_share == 0.5  # `good` has no flags, `bad` has no read-back
    q = [good.w_cumulative / total, bad.w_cumulative / total]  # alpha and beta
    assert s.indicators.lineage_entropy == pytest.approx(-sum(x * math.log(x) for x in q))
    assert s.indicators.lineage_entropy == pytest.approx(math.log(2), abs=1e-3)


def test_indicators_stop_at_the_fewest_programs_reaching_ninety_percent(ws, world):
    s = compute(ws, world.mission, 5)
    good, _ = only_stream(s).programs
    assert good.w_cumulative >= 0.9
    assert s.indicators.interface_weight_share == 1.0  # `good` alone: it declares an interface
    assert s.indicators.readback_clean_share == 0.0  # and has no read-back
    assert s.indicators.lineage_entropy == 0.0


def test_indicators_are_zero_without_programs(ws):
    publish_through(ws, STREAM)
    s = compute(ws, make_mission(), 5)
    assert only_stream(s).programs == ()
    assert (s.indicators.interface_weight_share, s.indicators.readback_clean_share) == (0.0, 0.0)
    assert s.indicators.lineage_entropy == 0.0


def test_indicators_use_the_first_base_count_stream(ws, world):
    publish_through(ws, "w/adm2")
    only_adm2 = freeze(ws, "only-adm2", author_lineage="gamma")
    store(ws, *(forecast(only_adm2, tgt(w, stream="w/adm2"), 5) for w in (1, 2, 3)))
    first = compute(ws, make_mission(streams=(STREAM, "w/adm2")), 5)
    second = compute(ws, make_mission(streams=("w/adm2", STREAM)), 5)
    assert first.indicators.interface_weight_share == 1.0  # w/adm: `good` alone, and it declares an interface
    assert second.indicators.interface_weight_share == 0.0  # w/adm2: `only-adm2` alone, and it declares none
    assert [x.stream for x in first.streams] == [STREAM, "w/adm2"] == [x.stream for x in second.streams]


def test_indicators_skip_streams_that_are_not_archived_or_not_base(ws, world):
    arm = count_spec(
        id="w/adm/s1", jurisdictions=("A",), support_max=99, parent=STREAM,
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=2),
    )
    publish(ws, arm, 4, {("A", 1): 5.0}, at(4))
    store(ws, forecast(world.good, tgt(1, stream="w/adm/s1"), 5))
    skipped = compute(ws, make_mission(streams=("w/nope", "w/adm/s1", STREAM)), 5)
    assert skipped.indicators.interface_weight_share == 1.0  # measured on w/adm: `good` declares an interface
    arms_only = compute(ws, make_mission(streams=("w/adm/s1",)), 5)
    assert [x.stream for x in arms_only.streams] == ["w/adm/s1"] and arms_only.streams[0].programs
    assert arms_only.indicators == compute(ws, make_mission(streams=()), 5).indicators
    assert arms_only.indicators.interface_weight_share == 0.0


# --- quantization ---


def test_round_keeps_twelve_significant_digits():
    assert _round(0.12345678901234567) == 0.123456789012
    assert _round(1234567.8901234567) == 1234567.89012
    assert _round(-3.0000000000004e-9) == -3.0e-9
    assert _round(0.1 + 0.2) == 0.3
    assert _round(0.0) == 0.0 and math.copysign(1.0, _round(-0.0)) == -1.0
    assert _round(0.5) == 0.5 and _round(1e300) == 1e300


def test_round_reaches_every_float_in_nested_data_and_nothing_else():
    data = {"a": (0.1 + 0.2, [1 / 3]), "n": 3, "s": "x", "none": None, "flag": True, "inner": {"x": 2 / 3}}
    assert _round(data) == {
        "a": (0.3, [0.333333333333]), "n": 3, "s": "x", "none": None, "flag": True, "inner": {"x": 0.666666666667}
    }
    assert type(_round(data)["flag"]) is bool and type(_round(data)["n"]) is int


def test_quantized_models_round_their_nested_floats_and_leave_the_rest():
    c = Calibration(pit=(1 / 3, 2 / 3), coverage_50=0.1 + 0.2, coverage_90=None, n=2)
    assert _quantized(c) == Calibration(pit=(0.333333333333, 0.666666666667), coverage_50=0.3, coverage_90=None, n=2)


def floats_in(data) -> list[float]:
    if isinstance(data, float):
        return [data]
    if isinstance(data, dict):
        return [x for v in data.values() for x in floats_in(v)]
    if isinstance(data, (list, tuple)):
        return [x for v in data for x in floats_in(v)]
    return []


def test_every_float_in_the_standings_has_at_most_twelve_significant_digits(ws, world):
    pair(ws)
    save_ranking(ws, Ranking(mission="m", as_of=5, items=(ranked(0, supporting=(world.good,)),)))
    s = compute(ws, make_mission(claims=(SCHOOL,)), 5)
    values = floats_in(s.model_dump())
    assert len(values) > 50  # weights, advantages, pit bins, deltas, gains...
    assert all(float(f"{x:.12g}") == x for x in values)
    assert any(x not in (0.0, 1.0) for x in values)


def test_compute_dump_validate_dump_is_byte_stable(ws, world):
    pair(ws)
    s = compute(ws, make_mission(claims=(SCHOOL,)), 5)
    first = STANDINGS.dump_json([s], indent=2)
    again = STANDINGS.validate_json(first)
    assert again == [s]
    assert STANDINGS.dump_json(again, indent=2) == first


def test_the_files_do_not_depend_on_the_last_bit_of_a_float(ws, world, monkeypatch):
    """A last-ulp difference in a weight or an advantage (another CPU's exp or log) leaves the files unchanged."""
    import scienceme.standings as module

    save_mission(ws, world.mission)
    write_all(ws)
    real_mixture, real_weights = module.run_mixture, module.normalized_weights

    def bump(table):
        return {k: float(np.nextafter(v, np.inf)) for k, v in table.items()}

    def noisy_mixture(*args, **kwargs):
        adv = real_mixture(*args, **kwargs)
        return adv.model_copy(update={"cumulative": bump(adv.cumulative), "current": bump(adv.current)})

    def noisy_weights(*args, **kwargs):
        return bump(real_weights(*args, **kwargs))

    monkeypatch.setattr(module, "run_mixture", noisy_mixture)
    monkeypatch.setattr(module, "normalized_weights", noisy_weights)
    assert check_all(ws)


def test_the_regime_flag_is_decided_on_the_quantized_total_variation(ws, world):
    tv = only_stream(compute(ws, world.mission, 5)).regime_tv
    assert float(f"{tv:.12g}") == tv
    assert only_stream(compute(ws, make_mission(claims=(SCHOOL,), regime_flag_tv=tv), 5)).regime_flag is False


# --- streams, arms and as_of ---


def test_arms_of_a_mission_stream_get_their_own_table(ws, world):
    arm = count_spec(
        id="w/adm/s1", jurisdictions=("A",), support_max=99, parent=STREAM,
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=2),
    )
    publish(ws, arm, 4, {("A", 1): 5.0}, at(4))
    store(ws, forecast(world.good, tgt(1, stream="w/adm/s1"), 5))
    s = compute(ws, world.mission, 5)
    assert [x.stream for x in s.streams] == [STREAM, "w/adm/s1"]
    assert [p.name for p in s.streams[1].programs] == ["good"]


def test_streams_without_forecasts_are_listed_empty(ws, world):
    publish(ws, covariate_spec(), 3, {("A", 1): 1.0}, at(3))  # not a COUNT stream: no table
    publish_through(ws, "w/adm2")
    s = compute(ws, make_mission(streams=(STREAM, "w/x", "w/adm2")), 5)
    assert [x.stream for x in s.streams] == [STREAM, "w/adm2"]
    assert s.streams[1].programs == ()
    assert "No forecasts yet." in render([s])


def test_as_of_is_the_largest_issue_published_on_a_count_stream(ws, world):
    save_mission(ws, world.mission)
    write_all(ws)
    assert STANDINGS.validate_json((ws.root / "standings.json").read_text())[0].as_of == 5
    publish(ws, covariate_spec(), 9, {("A", 1): 1.0}, at(9))
    save_mission(ws, make_mission(claims=(SCHOOL,), streams=(STREAM, "w/x")))
    write_all(ws)
    assert STANDINGS.validate_json((ws.root / "standings.json").read_text())[0].as_of == 5  # covariates do not count
    arm = count_spec(
        id="w/adm/s1", jurisdictions=("A",), support_max=99, parent=STREAM,
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=2),
    )
    publish(ws, arm, 7, {("A", 1): 5.0}, at(7))
    write_all(ws)
    assert STANDINGS.validate_json((ws.root / "standings.json").read_text())[0].as_of == 7


# --- claims, wanted items and names ---


def pair(ws, claim="school"):
    """Freeze `yes-x` (asserts the claim) and `no-x` (denies it, declaring the pair); record both on all targets."""
    yes = freeze(ws, "yes-x", tags={claim: Tag.ASSERTS})
    no = freeze(ws, "no-x", tags={claim: Tag.DENIES}, pairs=(PairDecl(claim=claim, partner=yes),))
    store(ws, *(forecast(yes, tgt(w), 5) for w in (1, 2, 3)), *(forecast(no, tgt(w), 9) for w in (1, 2, 3)))
    return yes, no


def test_the_claims_table_names_programs_never_hashes(ws, world):
    yes, no = pair(ws)
    s = compute(ws, world.mission, 5)
    (claim,) = s.claims
    assert (claim.verdict, [(p.asserts, p.denies) for p in claim.pairs]) == (Verdict.SUPPORTS, [(yes, no)])
    text = render([s])
    assert "| school | Closing schools lowers admissions. | supports | yes-x | no-x |" in text
    for program in (yes, no, world.good, world.bad):
        assert program not in text


def test_claims_are_listed_with_their_pairs_in_mission_order(ws, world):
    pair(ws)
    other = Claim(id="aaa", statement="Another.", scope=TargetFilter())
    text = render([compute(ws, make_mission(claims=(other, SCHOOL)), 5)])
    assert text.index("| aaa |") < text.index("| school |")
    assert "| aaa | Another. | insufficient evidence |" in text


def test_table_cells_escape_pipes(ws, world):
    claim = Claim(id="c", statement="a | b\nc", scope=TargetFilter())
    text = render([compute(ws, make_mission(claims=(claim,)), 5)])
    assert "| c | a \\| b c | insufficient evidence |" in text


def ranked(n, supporting=(), failed_=()) -> RankedItem:
    return RankedItem(
        item=f"item-{n:02d}", supporting=tuple(supporting), failed=tuple(failed_), gain=0.5, targeted={},
        priority=100.0 - n, cost=1.0,
    )


def test_the_top_ten_wanted_items_are_listed_with_program_names(ws, world):
    assert compute(ws, world.mission, 5).ranking is None
    assert "No wanted ranking yet." in render([compute(ws, world.mission, 5)])
    items = (ranked(0, supporting=(world.good,), failed_=(world.bad,)), *(ranked(n) for n in range(1, 12)))
    ranking = Ranking(mission="m", as_of=4, items=items)
    save_ranking(ws, ranking)
    save_ranking(ws, Ranking(mission="m", as_of=2, items=()))
    s = compute(ws, world.mission, 5)
    assert s.ranking == ranking  # the latest
    text = render([s])
    assert "| 1 | item-00 | 100.00 | 0.50 | 1.00 | good | bad |" in text
    assert "item-09" in text and "item-10" not in text
    assert world.good not in text and world.bad not in text


def test_program_names_cover_every_hash_the_standings_mention(ws, world):
    yes, no = pair(ws)
    save_ranking(ws, Ranking(mission="m", as_of=5, items=(ranked(0, supporting=(yes,), failed_=(no,)),)))
    s = compute(ws, world.mission, 5)
    assert s.program_names == {world.good: "good", world.bad: "bad", yes: "yes-x", no: "no-x"}
    assert list(s.program_names) == sorted(s.program_names)


# --- render ---


def test_render_formats_weights_and_nats(ws, world):
    s = compute(ws, world.mission, 5)
    good = only_stream(s).programs[0]
    row = (
        f"| good | {good.w_cumulative:.3f} | {good.w_current:.3f} | {good.advantage_cumulative:.2f} | 3 | "
        f"{good.coverage:.2f} | {good.calibration.coverage_90:.2f} | missing |"
    )
    text = render([s])
    assert row in text
    assert "| program | w cum | w cur | advantage | n | coverage | cov90 | flags |" in text
    assert "As of week 5" in text and scorer_hash() in text
    assert f"{only_stream(s).mixture_log_score:.2f} nats" in text


def test_render_has_a_section_for_each_mission_and_the_indicators(ws, world):
    text = render([compute(ws, world.mission, 5), compute(ws, make_mission(name="n"), 5)])
    assert text.startswith("# Standings\n")
    assert text.index("## Mission m") < text.index("## Mission n")
    assert text.count("### Indicators") == 2
    assert "Interface weight share" in text and "Lineage entropy" in text and "nats" in text
    assert "\u2014" not in text


def test_render_without_standings_says_so():
    assert "No mission has published data." in render([])


def test_nothing_is_rendered_as_negative_zero():
    assert _fmt(-0.0, 2) == "0.00" and _fmt(-0.001, 2) == "0.00" and _fmt(-1.234, 2) == "-1.23"
    assert _fmt(0.12345, 3) == "0.123"


# --- the generated files ---


def test_write_all_without_missions_writes_an_empty_list(ws):
    write_all(ws)
    assert (ws.root / "standings.json").read_text() == "[]\n"
    assert "No mission has published data." in (ws.root / "STANDINGS.md").read_text()
    assert check_all(ws)


def test_missions_with_nothing_published_are_omitted(ws):
    save_mission(ws, make_mission())
    write_all(ws)
    assert (ws.root / "standings.json").read_text() == "[]\n"
    publish_through(ws, STREAM)
    write_all(ws)
    assert [s.mission for s in STANDINGS.validate_json((ws.root / "standings.json").read_text())] == ["m"]


def test_missions_are_written_in_name_order(ws):
    publish_through(ws, STREAM)
    for name in ("zed", "m", "alpha"):
        save_mission(ws, make_mission(name=name))
    write_all(ws)
    names = [s.mission for s in STANDINGS.validate_json((ws.root / "standings.json").read_text())]
    assert names == ["alpha", "m", "zed"]
    md = (ws.root / "STANDINGS.md").read_text()
    assert md.index("## Mission alpha") < md.index("## Mission m") < md.index("## Mission zed")


def test_the_files_are_what_render_and_the_adapter_produce(ws, world):
    save_mission(ws, world.mission)
    write_all(ws)
    s = compute(ws, world.mission, 5)
    assert (ws.root / "STANDINGS.md").read_text() == render([s])
    assert (ws.root / "standings.json").read_bytes() == STANDINGS.dump_json([s], indent=2) + b"\n"


def test_write_all_replaces_stale_files(ws, world):
    save_mission(ws, world.mission)
    (ws.root / "standings.json").write_text("stale")
    (ws.root / "STANDINGS.md").write_text("stale")
    write_all(ws)
    assert check_all(ws)


@pytest.mark.parametrize("name", ["standings.json", "STANDINGS.md"])
def test_check_fails_for_a_missing_or_hand_edited_file(ws, world, name):
    save_mission(ws, world.mission)
    write_all(ws)
    path = ws.root / name
    path.write_text(path.read_text() + " ")
    assert not check_all(ws)
    path.unlink()
    assert not check_all(ws)
    write_all(ws)
    assert check_all(ws)


def test_check_does_not_write(ws, world):
    save_mission(ws, world.mission)
    assert not check_all(ws)
    assert not (ws.root / "standings.json").exists() and not (ws.root / "STANDINGS.md").exists()


def test_check_sees_a_readback_change(ws, world):
    save_mission(ws, world.mission)
    write_all(ws)
    clean_readback(ws, "good")
    assert not check_all(ws)


def test_a_program_with_records_that_is_not_frozen_stops_the_standings(ws, world):
    store(ws, forecast("sha256:" + "cc" * 32, tgt(1), 5))
    with pytest.raises(RegistryError, match="not frozen"):
        compute(ws, world.mission, 5)


def test_a_ranking_naming_an_unfrozen_program_stops_the_standings(ws, world):
    save_ranking(ws, Ranking(mission="m", as_of=5, items=(ranked(0, supporting=("sha256:" + "cc" * 32,)),)))
    with pytest.raises(RegistryError, match="not frozen"):
        compute(ws, world.mission, 5)


def test_an_empty_latest_ranking_is_reported(ws, world):
    save_ranking(ws, Ranking(mission="m", as_of=5, items=()))
    assert "No open wanted items as of week 5." in render([compute(ws, world.mission, 5)])


def test_a_workspace_without_a_missions_directory_has_no_standings(tmp_path):
    bare = Workspace(tmp_path)
    write_all(bare)
    assert (tmp_path / "standings.json").read_text() == "[]\n"
    assert check_all(bare)


# --- a program edited after its freeze ---


@pytest.mark.parametrize("claims", [(SCHOOL,), ()])
def test_a_program_edited_after_freezing_stops_the_standings(ws, world, claims):
    mission = make_mission(claims=claims)
    save_mission(ws, mission)
    write_all(ws)
    with (ws.programs / "good" / "program.py").open("a") as f:
        f.write("#edited\n")
    for call in (lambda: compute(ws, mission, 5), lambda: write_all(ws), lambda: check_all(ws)):
        with pytest.raises(RegistryError, match="modified-after-freeze"):
            call()


def test_an_import_edited_after_freezing_stops_the_standings(ws, world):
    lib = freeze(ws, "lib", library=True)
    write_program(ws, "top", CONST + "#top\n", imports={"lib": lib})
    top = Registry(ws).freeze("top", at(0)).closure_hash
    store(ws, forecast(top, tgt(1), 5))
    with (ws.programs / "lib" / "program.py").open("a") as f:
        f.write("#edited\n")
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        compute(ws, make_mission(), 5)
