import json

import pytest
from pydantic import TypeAdapter, ValidationError

from helpers import at, count_spec, covariate_spec
from scienceme.model import (
    Capture,
    Frozen,
    Intervention,
    Isolation,
    ModelError,
    Row,
    StreamKind,
    StreamSpec,
    Target,
    TargetFilter,
    Timing,
    Vintage,
    validate_vintage,
)
from scienceme.workspace import (
    Workspace,
    WriteOnceError,
    append_jsonl,
    read_jsonl,
    read_model,
    write_new,
)


def test_target_week():
    assert Target(stream="w/adm", jurisdiction="A", reference_week=10, horizon=3).target_week == 13


def test_resolution_issue_follows_the_lag():
    t = Target(stream="w/adm", jurisdiction="A", reference_week=10, horizon=3)
    assert t.resolution_lag == 1 and t.resolution_issue == 14
    assert t.model_copy(update={"resolution_lag": 4}).resolution_issue == 17


@pytest.mark.parametrize("bad", [{"horizon": -1}, {"resolution_lag": 0}, {"resolution_lag": -2}])
def test_target_rejects_bad_horizon_or_lag(bad):
    with pytest.raises(ValidationError):
        Target(stream="w/adm", jurisdiction="A", reference_week=1, **{"horizon": 0, **bad})


def test_filter_none_matches_and_fields_restrict():
    t, spec = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=0), count_spec()
    assert TargetFilter().matches(t, spec)
    assert not TargetFilter(jurisdictions=("B",)).matches(t, spec)
    assert TargetFilter(roles=("admissions",), horizons=(0,)).matches(t, spec)


def test_filter_each_field_restricts_independently():
    t, spec = Target(stream="w/adm", jurisdiction="A", reference_week=1, horizon=2), count_spec()
    assert TargetFilter(streams=("w/adm",)).matches(t, spec)
    assert not TargetFilter(streams=("w/other",)).matches(t, spec)
    assert not TargetFilter(roles=("ed-visits",)).matches(t, spec)
    assert not TargetFilter(horizons=(0, 1)).matches(t, spec)
    assert TargetFilter(streams=("w/adm",), roles=("admissions",), jurisdictions=("A", "B"), horizons=(2,)).matches(t, spec)
    assert not TargetFilter(streams=("w/adm",), roles=("admissions",), jurisdictions=("A",), horizons=(3,)).matches(t, spec)


def test_count_vintage_validation():
    spec = count_spec(jurisdictions=("A",), support_max=100)
    validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(Row(jurisdiction="A", week=4, value=7.0),)))
    for bad in (Row(jurisdiction="A", week=5, value=7.0), Row(jurisdiction="A", week=4, value=101.0),
                Row(jurisdiction="A", week=4, value=2.5), Row(jurisdiction="B", week=4, value=1.0)):
        with pytest.raises(ModelError):
            validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(bad,)))


def test_count_vintage_bounds_are_inclusive_and_reject_negatives():
    spec = count_spec(jurisdictions=("A",), support_max=100)
    for ok in (0.0, 100.0):
        validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(Row(jurisdiction="A", week=4, value=ok),)))
    with pytest.raises(ModelError):
        validate_vintage(spec, Vintage(stream="w/adm", issue=5, rows=(Row(jurisdiction="A", week=4, value=-1.0),)))


def test_vintage_must_match_the_spec_stream():
    with pytest.raises(ModelError):
        validate_vintage(count_spec(), Vintage(stream="w/other", issue=5, rows=()))


def test_vintage_rejects_duplicate_jurisdiction_week():
    rows = (Row(jurisdiction="A", week=3, value=1.0), Row(jurisdiction="A", week=3, value=2.0))
    with pytest.raises(ModelError):
        validate_vintage(count_spec(), Vintage(stream="w/adm", issue=5, rows=rows))
    # The same week in two jurisdictions is fine.
    rows = (Row(jurisdiction="A", week=3, value=1.0), Row(jurisdiction="B", week=3, value=2.0))
    validate_vintage(count_spec(), Vintage(stream="w/adm", issue=5, rows=rows))


def test_empty_vintage_is_valid():
    validate_vintage(count_spec(), Vintage(stream="w/adm", issue=0, rows=()))


def test_covariate_rows_may_lead_the_issue():
    validate_vintage(covariate_spec(jurisdictions=("A",)), Vintage(stream="w/x", issue=5, rows=(Row(jurisdiction="A", week=8, value=-0.3),)))


def test_covariate_rows_still_check_jurisdictions_and_duplicates():
    spec = covariate_spec(jurisdictions=("A",))
    with pytest.raises(ModelError):
        validate_vintage(spec, Vintage(stream="w/x", issue=5, rows=(Row(jurisdiction="B", week=8, value=0.0),)))
    dup = (Row(jurisdiction="A", week=8, value=0.0), Row(jurisdiction="A", week=8, value=0.1))
    with pytest.raises(ModelError):
        validate_vintage(spec, Vintage(stream="w/x", issue=5, rows=dup))


def test_count_spec_needs_support_max_and_arm_needs_parent():
    with pytest.raises(ValidationError):
        count_spec(support_max=None)
    with pytest.raises(ValidationError):
        count_spec(intervention=Intervention(variable="schools_closed", value=1.0, start_week=3))


def test_count_spec_rejects_negative_support_max_but_allows_zero():
    with pytest.raises(ValidationError):
        count_spec(support_max=-1)
    assert count_spec(support_max=0).support_max == 0


def test_arm_with_parent_and_covariate_without_support_max_are_valid():
    arm = count_spec(id="w/adm~a", parent="w/adm", intervention=Intervention(variable="schools_closed", value=1.0, start_week=3))
    assert arm.parent == "w/adm" and arm.intervention.start_week == 3
    cov = covariate_spec()
    assert cov.kind is StreamKind.COVARIATE and cov.support_max is None


@pytest.mark.parametrize("good", ["w/adm", "w/adm~a", "a.b/c-d/e~1", "x"])
def test_stream_id_accepts_path_segments(good):
    assert count_spec(id=good).id == good


@pytest.mark.parametrize("bad", ["", "W/adm", "w//adm", "/w", "w/", "w adm", "w/adm_x", "w/ad\nm", "../x", "w/..", "w/./x", "..."])
def test_stream_id_rejects_non_paths(bad):
    with pytest.raises(ValidationError):
        count_spec(id=bad)


def test_intervention_activity_window_and_jurisdictions():
    everywhere = Intervention(variable="schools_closed", value=1.0, start_week=3)
    assert not everywhere.active(2, "A")
    assert everywhere.active(3, "A") and everywhere.active(500, "Z")
    window = Intervention(variable="schools_closed", value=1.0, start_week=3, end_week=5, jurisdictions=("A",))
    assert [window.active(w, "A") for w in (2, 3, 4, 5, 6)] == [False, True, True, True, False]
    assert not window.active(4, "B")
    assert window.timing is Timing.START_OF_WEEK


def test_frozen_forbids_extras_and_mutation():
    class Thing(Frozen):
        a: int

    t = Thing(a=1)
    with pytest.raises(ValidationError):
        Thing(a=1, b=2)
    with pytest.raises(ValidationError):
        t.a = 2


def test_models_are_frozen_and_compare_by_value():
    row = Row(jurisdiction="A", week=0, value=1.0)
    with pytest.raises(ValidationError):
        row.value = 2.0
    assert row == Row(jurisdiction="A", week=0, value=1.0)


@pytest.mark.parametrize("v", [float("nan"), float("inf"), float("-inf")])
def test_row_values_must_be_finite(v):
    with pytest.raises(ValidationError):
        Row(jurisdiction="A", week=0, value=v)


def test_capture_hash_is_content_hash():
    v = Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=3.0),))
    a, b = Capture.make(v, at(0), "test"), Capture.make(v, at(5), "test")
    assert a.sha256 == b.sha256 and a.sha256.startswith("sha256:")
    with pytest.raises(ValidationError):
        Capture(vintage=v, published_at=at(0), source="test", sha256="sha256:" + "0" * 64)


def test_capture_hash_tracks_content_and_survives_a_json_round_trip():
    v1 = Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=3.0),))
    v2 = Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=4.0),))
    c1 = Capture.make(v1, at(0), "test")
    assert c1.sha256 != Capture.make(v2, at(0), "test").sha256
    assert len(c1.sha256) == len("sha256:") + 64
    assert Capture.model_validate_json(c1.model_dump_json()) == c1


def test_capture_requires_an_aware_timestamp():
    v = Vintage(stream="w/adm", issue=1, rows=())
    with pytest.raises(ValidationError):
        Capture.make(v, at(0).replace(tzinfo=None), "test")


def test_isolation_order():
    assert Isolation.CONTAINER.at_least(Isolation.PROCESS) and not Isolation.NONE.at_least(Isolation.PROCESS)


def test_isolation_total_order_is_none_process_container():
    order = [Isolation.NONE, Isolation.PROCESS, Isolation.CONTAINER]
    for i, a in enumerate(order):
        for j, b in enumerate(order):
            assert a.at_least(b) == (i >= j)
    assert [i.value for i in order] == ["none", "process", "container"]


def test_workspace_create_makes_the_layout(tmp_path):
    ws = Workspace.create(tmp_path / "new" / "root")
    for d in (ws.programs, ws.missions, ws.archive, ws.scores, ws.registry.parent):
        assert d.is_dir()
    assert ws.programs == ws.root / "programs" and ws.missions == ws.root / "missions"
    assert ws.archive == ws.root / "archive" and ws.scores == ws.root / "scores"
    assert ws.registry == ws.root / "registry" / "freezes.jsonl"
    assert not ws.registry.exists()
    assert Workspace.create(ws.root) == ws


def test_write_new_refuses_overwrite(ws):
    path = ws.root / "x.json"
    write_new(path, Row(jurisdiction="A", week=0, value=1.0))
    with pytest.raises(WriteOnceError):
        write_new(path, Row(jurisdiction="A", week=0, value=2.0))


def test_write_once_error_is_a_file_exists_error_and_keeps_the_original(ws):
    path = ws.root / "x.json"
    write_new(path, Row(jurisdiction="A", week=0, value=1.0))
    with pytest.raises(FileExistsError):
        write_new(path, Row(jurisdiction="A", week=0, value=2.0))
    assert read_model(path, Row).value == 1.0


def test_write_new_creates_parents_and_round_trips(ws):
    path = ws.root / "a" / "b" / "c.json"
    row = Row(jurisdiction="A", week=2, value=3.5)
    write_new(path, row)
    assert read_model(path, Row) == row
    assert json.loads(path.read_text()) == {"jurisdiction": "A", "week": 2, "value": 3.5}


def test_read_model_validates(ws):
    path = ws.root / "bad.json"
    path.write_text('{"jurisdiction": "A", "week": 2}')
    with pytest.raises(ValidationError):
        read_model(path, Row)


def test_jsonl_append_and_read_in_order(ws):
    adapter = TypeAdapter(Row)
    path = ws.registry
    assert read_jsonl(path, adapter) == []
    rows = [Row(jurisdiction="A", week=i, value=float(i)) for i in range(3)]
    for r in rows[:2]:
        append_jsonl(path, r)
    assert read_jsonl(path, adapter) == rows[:2]
    append_jsonl(path, rows[2])
    assert read_jsonl(path, adapter) == rows
    assert len(path.read_text().splitlines()) == 3


def test_jsonl_creates_parents_and_reads_back_a_union(tmp_path):
    path = tmp_path / "deep" / "dir" / "log.jsonl"
    v = Vintage(stream="w/adm", issue=1, rows=())
    r = Row(jurisdiction="A", week=0, value=1.0)
    append_jsonl(path, v)
    append_jsonl(path, r)
    assert read_jsonl(path, TypeAdapter(Vintage | Row)) == [v, r]


def test_streamspec_json_round_trip():
    spec = count_spec(id="w/adm~a", parent="w/adm", first_issue=2, fulfills="a",
                      intervention=Intervention(variable="schools_closed", value=1.0, start_week=3, end_week=6, jurisdictions=("A",)))
    assert StreamSpec.model_validate_json(spec.model_dump_json()) == spec
