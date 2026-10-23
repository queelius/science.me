import math

import numpy as np
import pytest
from helpers import CONST, at, count_spec, make_mission, publish, write_program
from scipy.special import expit

import scienceme.gain
from scienceme.archive import Archive
from scienceme.claims import ClaimStanding, PairStanding, Verdict
from scienceme.gain import (
    Ranking,
    RankedItem,
    choose,
    information_gain,
    load_latest_ranking,
    rank_wanted,
    save_ranking,
)
from scienceme.manifest import InterfaceVar
from scienceme.mission import Candidate, Claim, MissionError, WantedItem, append_wanted
from scienceme.model import Intervention, Isolation, Target, TargetFilter, Timing
from scienceme.pmf import Pmf, PmfError
from scienceme.record import PredictionRecord, RecordStore
from scienceme.registry import Registry
from scienceme.weights import Advantages
from scienceme.worker import WorkerError
from scienceme.workspace import WriteOnceError

STREAM = "w/adm"
SCHOOLS = InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",))
EMPTY = Advantages(cumulative={}, current={}, steps=())
RAISES = "def predict(ctx, target):\n    raise RuntimeError('boom')\n"
HISTORY = (
    "from scienceme.sdk import Pmf\n"
    "def predict(ctx, target):\n    return Pmf.point(len(ctx.view.history(target.stream)))\n"
)


def point_code(value: int) -> str:
    return f"from scienceme.pmf import Pmf\ndef predict(ctx, target):\n    return Pmf.point({value})\n"


def entropy2(w: float) -> float:
    """Entropy (nats) of a coin with probability `w`."""
    return -w * math.log(w) - (1 - w) * math.log(1 - w)


def frozen(ws, name, code=CONST, when=at(0), **fields) -> str:
    """Write and freeze program `name` at `when`; return its closure hash."""
    write_program(ws, name, code, **fields)
    return Registry(ws).freeze(name, when).closure_hash


def supporter(ws, name, value, **fields) -> str:
    """A frozen program that declares `schools_closed` and forecasts the constant `value`."""
    return frozen(ws, name, point_code(value), interface=(SCHOOLS,), **fields)


def arm(id="w/adm/s1", start=3, variable="schools_closed", **kw):
    return count_spec(
        id=id,
        jurisdictions=("A",),
        parent=STREAM,
        intervention=Intervention(variable=variable, value=1.0, start_week=start),
        **kw,
    )


def candidate(spec=None, horizons=(1, 2)) -> Candidate:
    spec = spec or arm()
    targets = tuple(
        Target(stream=spec.id, jurisdiction="A", reference_week=2, horizon=h, resolution_lag=2) for h in horizons
    )
    return Candidate(stream=spec, targets=targets)


def want(ws, item_id="a", spec=None, horizons=(1, 2), cost=1.0, mission="m") -> WantedItem:
    item = WantedItem(id=item_id, proposed_by="test", candidate=candidate(spec, horizons), cost=cost)
    append_wanted(ws, mission, item)
    return item


@pytest.fixture
def world(ws):
    """The base stream `w/adm` with issues 1 and 2 published early."""
    spec = count_spec(jurisdictions=("A",))
    publish(ws, spec, 1, {("A", 0): 3.0}, at(1))
    publish(ws, spec, 2, {("A", 1): 4.0}, at(2))
    return ws


def rank(ws, mission=None, as_of=2, now=at(9), isolation=Isolation.NONE, advantages=EMPTY, claims=()):
    return rank_wanted(ws, mission or make_mission(), as_of, now, isolation, advantages, claims)


# --- information_gain ---


def test_disjoint_point_masses_carry_one_bit():  # review finding 11
    assert information_gain([Pmf.point(0), Pmf.point(10)], [0.5, 0.5]) == pytest.approx(math.log(2))


def test_identical_predictions_carry_nothing():
    assert information_gain([Pmf.point(3), Pmf.point(3)], [0.3, 0.7]) == pytest.approx(0.0)


def test_gain_of_disjoint_forecasts_is_the_entropy_of_the_weights():
    assert information_gain([Pmf.point(0), Pmf.point(9)], [0.9, 0.1]) == pytest.approx(entropy2(0.9))


def test_gain_removes_the_within_forecast_spread():
    # a mixture of two fair coins on {0,1} and two fair coins on {2,3}: H(mix) = log 4, mean H = log 2
    low, high = Pmf.uniform(0, 1), Pmf.uniform(2, 3)
    assert information_gain([low, high], [0.5, 0.5]) == pytest.approx(math.log(2))


def test_gain_is_symmetric_in_the_order_of_the_programs():
    a, b, c = Pmf.uniform(0, 3), Pmf.uniform(2, 6), Pmf.point(5)
    assert information_gain([a, b, c], [0.2, 0.5, 0.3]) == pytest.approx(information_gain([c, a, b], [0.3, 0.2, 0.5]))


def test_gain_normalizes_the_weights():
    pmfs = [Pmf.point(0), Pmf.point(10)]
    assert information_gain(pmfs, [1.0, 3.0]) == pytest.approx(information_gain(pmfs, [0.25, 0.75]))


def test_gain_with_one_program_is_zero():
    assert information_gain([Pmf.uniform(0, 4)], [1.0]) == 0.0


def test_gain_is_never_negative():
    rng = np.random.default_rng(0)
    for _ in range(200):
        pmf = Pmf.from_probs(0, rng.dirichlet(np.ones(7)))
        w = rng.dirichlet(np.ones(5))
        assert information_gain([pmf] * 5, w.tolist()) >= 0.0


@pytest.mark.parametrize(
    "pmfs,weights",
    [
        ([], []),
        ([Pmf.point(0)], [0.5, 0.5]),
        ([Pmf.point(0), Pmf.point(1)], [1.0]),
        ([Pmf.point(0), Pmf.point(1)], [-0.5, 1.5]),
        ([Pmf.point(0), Pmf.point(1)], [0.0, 0.0]),
        ([Pmf.point(0), Pmf.point(1)], [math.nan, 1.0]),
        ([Pmf.point(0), Pmf.point(1)], [math.inf, 1.0]),
    ],
)
def test_gain_rejects_invalid_input(pmfs, weights):
    with pytest.raises(PmfError):
        information_gain(pmfs, weights)


# --- rank_wanted ---


def test_rank_wanted_uses_the_supporting_subset(world):
    h_lo, h_hi = supporter(world, "lo", 0), supporter(world, "hi", 10)
    frozen(world, "flat", point_code(5))  # declares no interface
    want(world, cost=4.0)
    [item] = rank(world)
    assert item.item == "a"
    assert set(item.supporting) == {h_lo, h_hi} and item.failed == ()
    assert item.gain == pytest.approx(2 * math.log(2))
    assert item.cost == 4.0 and item.priority == pytest.approx(item.gain / item.cost)
    assert item.targeted == {}


def test_supporting_and_failed_are_sorted_by_closure_hash(world):
    hashes = [supporter(world, name, v) for name, v in (("p1", 1), ("p2", 2), ("p3", 3))]
    want(world)
    [item] = rank(world)
    assert item.supporting == tuple(sorted(hashes))


def test_gain_weights_the_programs_by_their_current_advantage(world):
    h_lo, h_hi = supporter(world, "lo", 0), supporter(world, "hi", 10)
    want(world)
    advantages = Advantages(cumulative={}, current={h_lo: 2.0, h_hi: 0.0}, steps=())
    [item] = rank(world, advantages=advantages)  # tau = 2: weights proportional to exp(1) and exp(0)
    w = float(expit(1.0))
    assert item.gain == pytest.approx(2 * entropy2(w))


def test_the_mixture_runs_over_the_raw_forecasts(world):
    # point masses far apart keep their full separation: a floored forecast would blur them
    supporter(world, "lo", 0)
    supporter(world, "hi", 1000)
    want(world, horizons=(1,))
    [item] = rank(world)
    assert item.gain == pytest.approx(math.log(2))


def test_fulfilled_and_started_items_are_excluded(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    Archive(world).create_stream(arm(id="w/adm/s1", fulfills="a"))
    want(world, "a", spec=arm(id="w/adm/s1", fulfills="a"))
    want(world, "b", spec=arm(id="w/adm/s2", start=2))  # starts at week 2, not after as_of 2
    assert rank(world, as_of=2) == []


def test_an_item_starting_after_as_of_is_ranked(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world, "b", spec=arm(id="w/adm/s2", start=3))
    assert [i.item for i in rank(world, as_of=2)] == ["b"]
    assert rank(world, as_of=3) == []


def test_items_with_no_supporting_programs_are_listed_with_zero_gain(world):
    frozen(world, "flat", point_code(5))
    want(world)
    [item] = rank(world)
    assert (item.supporting, item.failed, item.gain, item.priority, item.targeted) == ((), (), 0.0, 0.0, {})


def test_a_single_supporting_program_has_nothing_to_discriminate(world):
    h = supporter(world, "solo", 4)
    want(world)
    [item] = rank(world)
    assert item.supporting == (h,) and item.gain == 0.0 and item.priority == 0.0


def test_the_intervention_must_match_the_programs_interface(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world, spec=arm(variable="vaccinate_fraction"))
    [item] = rank(world)
    assert item.supporting == () and item.gain == 0.0


def test_ineligible_programs_are_neither_supporting_nor_failed(world):
    h_lo, h_hi = supporter(world, "lo", 0), supporter(world, "hi", 10)
    frozen(world, "late", point_code(5), when=at(10), interface=(SCHOOLS,))  # frozen after `now`
    h_gone = supporter(world, "gone", 6)
    Registry(world).withdraw(h_gone, at(5), "retired")
    frozen(world, "lib", point_code(7), interface=(SCHOOLS,), library=True)
    frozen(world, "other", point_code(8), interface=(SCHOOLS,), scope=TargetFilter(jurisdictions=("B",)))
    frozen(world, "short", point_code(9), interface=(SCHOOLS,), scope=TargetFilter(horizons=(1,)))
    want(world)
    [item] = rank(world, now=at(9))
    assert set(item.supporting) == {h_lo, h_hi} and item.failed == ()


def test_a_library_never_supports_even_a_candidate_without_targets(world):
    h_user = supporter(world, "user", 1)
    frozen(world, "lib", point_code(2), interface=(SCHOOLS,), library=True)
    want(world, horizons=())
    [item] = rank(world)
    assert item.supporting == (h_user,) and item.gain == 0.0


def test_a_program_failing_one_target_is_failed_and_leaves_the_mixture(world):
    h_lo, h_hi = supporter(world, "lo", 0), supporter(world, "hi", 10)
    h_bad = frozen(
        world,
        "bad",
        "from scienceme.pmf import Pmf\ndef predict(ctx, target):\n"
        "    if target.horizon == 2:\n        raise RuntimeError('boom')\n    return Pmf.point(3)\n",
        interface=(SCHOOLS,),
    )
    want(world)
    [item] = rank(world)
    assert item.failed == (h_bad,)
    assert set(item.supporting) == {h_lo, h_hi}
    assert h_bad not in item.supporting
    assert item.gain == pytest.approx(2 * math.log(2))  # lo and hi at equal weight; bad's other target is unused


def test_a_program_that_cannot_load_is_failed(world):
    supporter(world, "lo", 0)
    h_broken = frozen(world, "broken", "this is not python (", interface=(SCHOOLS,))
    want(world)
    [item] = rank(world)
    assert item.failed == (h_broken,) and len(item.supporting) == 1


def test_a_program_modified_after_freezing_is_failed_not_raised(world):
    h_lo, h_hi = supporter(world, "lo", 0), supporter(world, "hi", 10)
    (world.programs / "hi" / "program.py").write_text(point_code(99), encoding="utf-8")
    want(world)
    [item] = rank(world)
    assert item.failed == (h_hi,) and item.supporting == (h_lo,)
    assert item.gain == 0.0


def test_an_import_modified_after_freezing_fails_its_importer(world):
    write_program(world, "lens", point_code(1), library=True)
    lens = Registry(world).freeze("lens", at(0)).closure_hash
    h_user = frozen(world, "user", point_code(2), interface=(SCHOOLS,), imports={"lens": lens})
    supporter(world, "plain", 3)
    (world.programs / "lens" / "program.py").write_text(point_code(5), encoding="utf-8")
    want(world)
    [item] = rank(world)
    assert item.failed == (h_user,) and len(item.supporting) == 1


def test_a_program_with_an_unreadable_manifest_is_failed(world):
    supporter(world, "lo", 0)
    h_gone = supporter(world, "hi", 10)
    (world.programs / "hi" / "program.json").unlink()
    want(world)
    [item] = rank(world)
    assert item.failed == (h_gone,)


def test_worker_errors_propagate(world, monkeypatch):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world)

    def no_docker(*args, **kwargs):
        raise WorkerError("docker is missing")

    monkeypatch.setattr(scienceme.gain, "run_order", no_docker)
    with pytest.raises(WorkerError):
        rank(world)


def test_the_view_is_cut_at_as_of(world):
    publish(world, count_spec(jurisdictions=("A",)), 3, {("A", 2): 5.0}, at(3))
    frozen(world, "seen", HISTORY, interface=(SCHOOLS,))
    supporter(world, "two", 2)
    want(world, horizons=(1,))
    [item] = rank(world, as_of=2)  # the candidate sees its parent's issues 1 and 2, not 3
    assert item.gain == 0.0


def test_the_view_is_cut_at_now(ws):
    spec = count_spec(jurisdictions=("A",))
    publish(ws, spec, 1, {("A", 0): 3.0}, at(1))
    publish(ws, spec, 2, {("A", 1): 4.0}, at(20))
    frozen(ws, "seen", HISTORY, interface=(SCHOOLS,))
    supporter(ws, "one", 1)
    want(ws, horizons=(1,))
    [item] = rank(ws, as_of=2, now=at(9))  # issue 2 is published after `now`
    assert item.gain == 0.0


def test_the_mission_streams_the_view_is_built_from_include_existing_arms(world):
    publish(world, arm(id="w/adm/old", start=0), 1, {("A", 0): 1.0}, at(1))
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world)
    [item] = rank(world)
    assert item.gain == pytest.approx(2 * math.log(2))


def test_items_sort_by_priority_descending_then_id(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world, "cheap", spec=arm(id="w/adm/s1"), cost=1.0)
    want(world, "dear", spec=arm(id="w/adm/s2"), cost=4.0)
    want(world, "z-unsupported", spec=arm(id="w/adm/s3", variable="vaccinate_fraction"))
    want(world, "a-unsupported", spec=arm(id="w/adm/s4", variable="vaccinate_fraction"))
    assert [i.item for i in rank(world)] == ["cheap", "dear", "a-unsupported", "z-unsupported"]


def test_the_ranking_is_deterministic(world):
    for i in range(4):
        supporter(world, f"p{i}", i)
    want(world, "a")
    want(world, "b", spec=arm(id="w/adm/s2"))
    assert rank(world) == rank(world)


def test_the_mission_isolation_floor_applies(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world)
    with pytest.raises(MissionError):
        rank(world, mission=make_mission(required_isolation=Isolation.CONTAINER), isolation=Isolation.PROCESS)


def test_ranking_runs_under_process_isolation(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world)
    [item] = rank(world, mission=make_mission(required_isolation=Isolation.PROCESS), isolation=Isolation.PROCESS)
    assert item.gain == pytest.approx(2 * math.log(2))


# --- claims ---


def standing(claim, *pairs) -> ClaimStanding:
    return ClaimStanding(claim=claim, statement="s", pairs=tuple(pairs), verdict=Verdict.INSUFFICIENT)


def pair(claim, asserts, denies, delta) -> PairStanding:
    return PairStanding(
        claim=claim, asserts=asserts, denies=denies, delta_nats=delta, n_targets=3, verdict=Verdict.INSUFFICIENT
    )


def school_mission(weight=3.0):
    return make_mission(claims=(Claim(id="school", statement="s", scope=TargetFilter(), weight=weight),))


def test_targeted_gain_uses_the_pairs_two_program_weights(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    want(world, cost=2.0)
    claims = [standing("school", pair("school", h_yes, h_no, delta=4.0))]  # tau = 2
    [item] = rank(world, mission=school_mission(3.0), claims=claims)
    per_target = entropy2(float(expit(2.0)))
    assert item.targeted == {"school": pytest.approx(2 * per_target)}
    assert item.gain == pytest.approx(2 * math.log(2))
    assert item.priority == pytest.approx((item.gain + 3.0 * 2 * per_target) / 2.0)


def test_a_pair_that_favors_denial_weighs_the_other_way(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    want(world)
    asserted = rank(world, mission=school_mission(), claims=[standing("school", pair("school", h_yes, h_no, 4.0))])
    denied = rank(world, mission=school_mission(), claims=[standing("school", pair("school", h_yes, h_no, -4.0))])
    assert denied[0].targeted["school"] == pytest.approx(asserted[0].targeted["school"])  # entropy is symmetric


def test_a_pair_with_no_evidence_is_the_fair_coin(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    want(world)
    [item] = rank(world, mission=school_mission(), claims=[standing("school", pair("school", h_yes, h_no, 0.0))])
    assert item.targeted["school"] == pytest.approx(2 * math.log(2))


def test_a_huge_delta_does_not_overflow(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    want(world)
    claims = [standing("school", pair("school", h_yes, h_no, -1e6))]
    [item] = rank(world, mission=school_mission(), claims=claims)
    assert item.targeted["school"] == pytest.approx(0.0, abs=1e-12)


def test_targeted_sums_over_the_ok_pairs_of_a_claim(world):
    a1, d1 = supporter(world, "a1", 0), supporter(world, "d1", 10)
    a2, d2 = supporter(world, "a2", 20), supporter(world, "d2", 30)
    want(world, horizons=(1,))
    claims = [standing("school", pair("school", a1, d1, 0.0), pair("school", a2, d2, 0.0))]
    [item] = rank(world, mission=school_mission(), claims=claims)
    assert item.targeted["school"] == pytest.approx(2 * math.log(2))


def test_only_pairs_with_both_members_ok_count(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    h_flat = frozen(world, "flat", point_code(5))  # does not support the intervention
    h_bad = frozen(world, "bad", RAISES, interface=(SCHOOLS,))
    want(world, horizons=(1,))
    claims = [
        standing("school", pair("school", h_yes, h_no, 0.0), pair("school", h_yes, h_flat, 0.0)),
        standing("flat-only", pair("flat-only", h_yes, h_flat, 0.0)),
        standing("failed-only", pair("failed-only", h_bad, h_no, 0.0)),
        standing("empty"),
    ]
    [item] = rank(world, mission=school_mission(), claims=claims)
    assert set(item.targeted) == {"school"}
    assert item.targeted["school"] == pytest.approx(math.log(2))  # the (yes, flat) pair adds nothing


def test_a_claim_without_a_mission_weight_adds_no_priority(world):
    h_yes, h_no = supporter(world, "yes", 0), supporter(world, "no", 10)
    want(world)
    claims = [standing("unlisted", pair("unlisted", h_yes, h_no, 0.0))]
    [item] = rank(world, claims=claims)
    assert item.targeted["unlisted"] == pytest.approx(2 * math.log(2))
    assert item.priority == pytest.approx(item.gain)


def test_claims_of_unranked_pairs_leave_the_item_untouched(world):
    supporter(world, "lo", 0)
    supporter(world, "hi", 10)
    want(world)
    claims = [standing("school", pair("school", "sha256:aa", "sha256:bb", 1.0))]
    [item] = rank(world, mission=school_mission(), claims=claims)
    assert item.targeted == {} and item.priority == pytest.approx(item.gain)


# --- choose ---


def ranked_items(n=3) -> list[RankedItem]:
    return [
        RankedItem(item=str(i), supporting=(), failed=(), gain=0.0, targeted={}, priority=float(-i), cost=1.0)
        for i in range(n)
    ]


def test_choose_honors_the_reserve():
    items = ranked_items()
    assert choose(items, 0.0, np.random.default_rng(0)).item == "0"
    assert {choose(items, 1.0, np.random.default_rng(s)).item for s in range(20)} == {"0", "1", "2"}


def test_choose_rejects_an_empty_list():
    with pytest.raises(ValueError):
        choose([], 0.5, np.random.default_rng(0))


def test_choose_draws_once_when_it_takes_the_first():
    used, fresh = np.random.default_rng(5), np.random.default_rng(5)
    choose(ranked_items(), 0.0, used)
    fresh.random()
    assert used.random() == fresh.random()


def test_choose_draws_a_uniform_when_it_takes_the_reserve_branch():
    items = ranked_items()
    used, fresh = np.random.default_rng(5), np.random.default_rng(5)
    got = choose(items, 1.0, used)
    fresh.random()
    expected = items[int(fresh.integers(len(items)))]
    assert got == expected and used.random() == fresh.random()


def test_choose_takes_the_reserve_branch_with_the_stated_probability():
    items = ranked_items(4)
    rng = np.random.default_rng(1)
    firsts = sum(choose(items, 0.4, rng).item == "0" for _ in range(4000))
    # first with probability 0.6 + 0.4 / 4
    assert firsts / 4000 == pytest.approx(0.7, abs=0.03)


def test_choose_with_one_item_returns_it():
    [only] = ranked_items(1)
    assert choose([only], 1.0, np.random.default_rng(0)) == only


# --- save_ranking / load_latest_ranking ---


def ranking(as_of=2, mission="m", n=2) -> Ranking:
    return Ranking(mission=mission, as_of=as_of, items=tuple(ranked_items(n)))


def test_a_saved_ranking_round_trips(ws):
    r = Ranking(
        mission="m",
        as_of=2,
        items=(
            RankedItem(
                item="a", supporting=("sha256:x",), failed=("sha256:y",), gain=0.5, targeted={"c": 0.25},
                priority=0.75, cost=2.0,
            ),
        ),
    )
    save_ranking(ws, r)
    assert (ws.scores / "m" / "wanted" / "00002.json").is_file()
    assert load_latest_ranking(ws, "m") == r


def test_load_latest_ranking_takes_the_highest_as_of(ws):
    for as_of in (3, 12, 7):
        save_ranking(ws, ranking(as_of=as_of))
    latest = load_latest_ranking(ws, "m")
    assert latest is not None and latest.as_of == 12


def test_load_latest_ranking_is_none_without_rankings(ws):
    assert load_latest_ranking(ws, "m") is None
    save_ranking(ws, ranking(mission="other"))
    assert load_latest_ranking(ws, "m") is None


def test_files_that_are_not_rankings_are_ignored(ws):
    directory = ws.scores / "m" / "wanted"
    directory.mkdir(parents=True)
    for name in ("notes.txt", "3.json", "abc.json", "00007.json.bak"):
        (directory / name).write_text("not a ranking", encoding="utf-8")
    assert load_latest_ranking(ws, "m") is None
    save_ranking(ws, ranking(as_of=2))
    latest = load_latest_ranking(ws, "m")
    assert latest is not None and latest.as_of == 2


def test_a_ranking_is_write_once(ws):
    save_ranking(ws, ranking())
    with pytest.raises(WriteOnceError):
        save_ranking(ws, ranking(n=1))
    assert load_latest_ranking(ws, "m") == ranking()


def test_a_ranking_file_must_hold_the_ranking_its_name_claims(ws):
    save_ranking(ws, ranking(as_of=2))
    (ws.scores / "m" / "wanted" / "00002.json").rename(ws.scores / "m" / "wanted" / "00009.json")
    with pytest.raises(MissionError):
        load_latest_ranking(ws, "m")


@pytest.mark.parametrize("name", ["", "..", ".", "a/b", "../x"])
def test_mission_names_cannot_leave_the_scores_directory(ws, name):
    with pytest.raises(MissionError):
        save_ranking(ws, ranking(mission=name))
    with pytest.raises(MissionError):
        load_latest_ranking(ws, name)


def test_rankings_do_not_disturb_the_prospective_record(ws):
    target = Target(stream=STREAM, jurisdiction="A", reference_week=1, horizon=0, resolution_lag=2)
    record = PredictionRecord(
        mission="m", program="sha256:" + "ab" * 32, target=target, pmf=Pmf.point(1), scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )
    store = RecordStore(ws)
    store.write("m", STREAM, 1, record.program, [record])
    save_ranking(ws, ranking())
    assert store.all("m") == [record]
