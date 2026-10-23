import pytest
from helpers import count_spec, covariate_spec, make_mission
from pydantic import TypeAdapter, ValidationError

from scienceme.mission import (
    Candidate,
    Claim,
    MissionError,
    WantedItem,
    append_wanted,
    load_mission,
    load_wanted,
    mission_streams,
    save_mission,
)
from scienceme.model import Intervention, Target, TargetFilter
from scienceme.workspace import read_jsonl


def arm_spec(id="w/adm~a", **kw):
    kw.setdefault("intervention", Intervention(variable="schools_closed", value=1.0, start_week=3))
    return count_spec(id=id, parent="w/adm", **kw)


def wanted_item(id="a", arm=None, **kw) -> WantedItem:
    arm = arm or arm_spec()
    return WantedItem(
        id=id,
        proposed_by="test",
        candidate=Candidate(
            stream=arm,
            targets=(Target(stream=arm.id, jurisdiction="A", reference_week=3, horizon=0),),
        ),
        **kw,
    )


def test_targets_for_a_base_stream():
    assert make_mission().targets(count_spec(), 4) == [
        Target(stream="w/adm", jurisdiction=j, reference_week=4, horizon=h, resolution_lag=2)
        for j in ("A", "B")
        for h in (0, 1)
    ]


def test_targets_enumerate_horizons_ascending_without_duplicates():
    got = make_mission(horizons=(2, 0, 2)).targets(count_spec(jurisdictions=("B", "A")), 4)
    assert [(t.jurisdiction, t.horizon) for t in got] == [("B", 0), ("B", 2), ("A", 0), ("A", 2)]


def test_arm_targets_start_at_first_issue_and_intervention_start():
    arm = count_spec(
        id="w/adm~close",
        jurisdictions=("A",),
        parent="w/adm",
        first_issue=6,
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=7, end_week=9),
    )
    m = make_mission()
    assert m.targets(arm, 5) == []
    assert [t.target_week for t in m.targets(arm, 6)] == [7]


def test_targets_are_limited_to_the_mission_issue_window():
    m = make_mission(first_issue=3, last_issue=5)
    assert m.targets(count_spec(), 2) == []
    assert m.targets(count_spec(), 3) != []
    assert m.targets(count_spec(), 5) != []
    assert m.targets(count_spec(), 6) == []
    assert m.targets(count_spec(first_issue=5), 4) == []


def test_covariate_streams_have_no_targets():
    assert make_mission().targets(covariate_spec(), 4) == []


def test_resolution_issue_and_lag_validation():
    assert make_mission().targets(count_spec(), 4)[1].resolution_issue == 7
    with pytest.raises(ValidationError):
        make_mission(resolution_lag=0)


@pytest.mark.parametrize(
    "field, value",
    [
        ("epsilon", 0.0),
        ("epsilon", 1.0),
        ("tau", 0.0),
        ("tau", -1.0),
        ("half_life_weeks", 0.0),
        ("half_life_weeks", float("inf")),
        ("half_life_weeks", float("nan")),
    ],
)
def test_parameter_validation(field, value):
    with pytest.raises(ValidationError):
        make_mission(**{field: value})


def test_mission_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        make_mission(unknown=1)


def test_mission_streams_include_arms_of_base_streams():
    arm = arm_spec()
    other = count_spec(id="v/adm", world="v")
    got = mission_streams(make_mission(streams=("w/adm", "w/x")), [arm, other, count_spec(), covariate_spec()])
    assert [s.id for s in got] == ["w/adm", "w/adm~a", "w/x"]


def test_mission_and_wanted_round_trip(ws):
    save_mission(ws, make_mission())
    assert load_mission(ws, "m") == make_mission()
    item = wanted_item()
    append_wanted(ws, "m", item)
    assert load_wanted(ws, "m") == [item]
    with pytest.raises(MissionError):
        append_wanted(ws, "m", item)


def test_mission_round_trip_keeps_claims_and_enums(ws):
    claim = Claim(id="school", statement="closing schools lowers admissions", scope=TargetFilter(roles=("admissions",)), weight=0.5)
    m = make_mission(claims=(claim,))
    save_mission(ws, m)
    assert load_mission(ws, "m") == m
    assert (ws.missions / "m" / "mission.json").exists()


def test_save_mission_replaces_the_captains_file(ws):
    save_mission(ws, make_mission())
    save_mission(ws, make_mission(epoch=2, tau=3.0))
    assert load_mission(ws, "m").epoch == 2
    assert load_mission(ws, "m").tau == 3.0


def test_load_mission_of_an_unknown_name_raises(ws):
    with pytest.raises(FileNotFoundError):
        load_mission(ws, "nope")


def test_wanted_list_is_empty_before_any_append(ws):
    assert load_wanted(ws, "m") == []


def test_wanted_list_is_append_only_in_order(ws):
    first, second = wanted_item("a"), wanted_item("b", arm_spec("w/adm~b"))
    append_wanted(ws, "m", first)
    append_wanted(ws, "m", second)
    assert [w.id for w in load_wanted(ws, "m")] == ["a", "b"]
    with pytest.raises(MissionError):
        append_wanted(ws, "m", wanted_item("a", arm_spec("w/adm~c")))
    assert len(read_jsonl(ws.missions / "m" / "wanted.jsonl", TypeAdapter(WantedItem))) == 2


def test_wanted_lists_are_per_mission(ws):
    append_wanted(ws, "m", wanted_item())
    assert load_wanted(ws, "other") == []
    append_wanted(ws, "other", wanted_item())


def test_wanted_item_defaults():
    item = wanted_item()
    assert (item.cost, item.fulfiller) == (1.0, "custodian")


def test_wanted_item_cost_must_be_a_positive_finite_number():
    assert wanted_item(cost=0.25).cost == 0.25
    for cost in (0.0, -1.0, float("inf"), float("nan")):
        with pytest.raises(ValidationError):
            wanted_item(cost=cost)


def test_candidate_must_be_an_arm_with_targets_on_its_stream():
    with pytest.raises(ValidationError):
        Candidate(stream=count_spec(), targets=())
    arm = arm_spec()
    with pytest.raises(ValidationError):
        Candidate(stream=arm, targets=(Target(stream="w/adm", jurisdiction="A", reference_week=3, horizon=0),))
