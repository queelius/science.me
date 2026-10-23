import pytest
from helpers import at, count_spec, covariate_spec, publish

from scienceme.archive import Archive, ArchiveError, ArchiveView
from scienceme.model import Capture, Intervention, ModelError, Row, Target, Vintage


def test_view_respects_issue_and_publication_time(ws):
    s = count_spec(jurisdictions=("A",))
    for i in (1, 2, 3):
        publish(ws, s, i, {("A", i - 1): 10.0 * i}, at(i))
    a = Archive(ws)
    assert [v.issue for v in a.view(["w/adm"], as_of=2, published_by=at(3)).history("w/adm")] == [1, 2]
    assert [v.issue for v in a.view(["w/adm"], as_of=3, published_by=at(2)).history("w/adm")] == [1, 2]


def test_view_boundaries_are_inclusive_and_exact(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 2, {("A", 0): 1.0}, at(5))
    a = Archive(ws)
    assert len(a.view(["w/adm"], as_of=2, published_by=at(5)).history("w/adm")) == 1
    assert a.view(["w/adm"], as_of=1, published_by=at(5)).history("w/adm") == ()
    assert a.view(["w/adm"], as_of=2, published_by=at(4.999)).history("w/adm") == ()


def test_view_requires_both_conditions_for_out_of_order_publication(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 2, {("A", 0): 2.0}, at(9))  # issue 2 was published late
    publish(ws, s, 3, {("A", 0): 3.0}, at(3))
    v = Archive(ws).view(["w/adm"], as_of=3, published_by=at(5))
    assert [x.issue for x in v.history("w/adm")] == [3]
    assert v.series("w/adm", "A") == [(0, 3.0)]


def test_view_requires_aware_published_by(ws):
    publish(ws, count_spec(), 1, {("A", 0): 1.0}, at(1))
    with pytest.raises(ArchiveError, match="timezone-aware"):
        Archive(ws).view(["w/adm"], 1, at(1).replace(tzinfo=None))


def test_view_of_unknown_stream_refused(ws):
    with pytest.raises(ArchiveError, match="unknown stream"):
        Archive(ws).view(["w/none"], 1, at(1))


def test_series_uses_the_latest_vintage(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 2, {("A", 0): 5.0, ("A", 1): 3.0}, at(2))
    publish(ws, s, 3, {("A", 0): 6.0, ("A", 1): 8.0, ("A", 2): 1.0}, at(3))
    assert Archive(ws).view(["w/adm"], 3, at(9)).series("w/adm", "A") == [(0, 6.0), (1, 8.0), (2, 1.0)]


def test_series_and_latest_select_one_jurisdiction_sorted_by_week(ws):
    s = count_spec()
    publish(ws, s, 4, {("A", 2): 1.0, ("B", 0): 9.0, ("A", 0): 3.0, ("A", 1): 2.0}, at(4))
    v = Archive(ws).view(["w/adm"], 4, at(9))
    assert v.series("w/adm", "A") == [(0, 3.0), (1, 2.0), (2, 1.0)]
    assert v.series("w/adm", "B") == [(0, 9.0)]
    assert v.series("w/adm", "nowhere") == []
    assert {(r.jurisdiction, r.week) for r in v.latest("w/adm")} == {("A", 0), ("A", 1), ("A", 2), ("B", 0)}


def test_stream_without_vintages_gives_empty_results_but_a_spec(ws):
    s = count_spec()
    Archive(ws).create_stream(s)
    v = Archive(ws).view(["w/adm"], 5, at(9))
    assert v.history("w/adm") == () and v.latest("w/adm") == () and v.series("w/adm", "A") == []
    assert v.spec("w/adm") == s
    assert v.history("w/other") == ()


def test_view_spec_of_unknown_stream_refused(ws):
    publish(ws, count_spec(), 1, {("A", 0): 1.0}, at(1))
    with pytest.raises(ArchiveError, match="unknown stream"):
        Archive(ws).view(["w/adm"], 1, at(9)).spec("w/none")


def test_find_returns_the_base_stream_not_an_arm(ws):
    base = count_spec()
    arm = count_spec(
        id="w/adm~c",
        parent="w/adm",
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=4),
    )
    other_world = count_spec(id="v/adm", world="v")
    for s in (arm, base, other_world, covariate_spec()):
        Archive(ws).create_stream(s)
    v = Archive(ws).view(["w/adm~c", "w/adm", "v/adm", "w/x"], 1, at(9))
    assert v.find("w", "admissions") == base
    assert v.find("v", "admissions") == other_world
    assert v.find("w", "covariate-x") == covariate_spec()
    assert v.find("w", "ed-visits") is None
    assert Archive(ws).view(["w/adm~c"], 1, at(9)).find("w", "admissions") is None


def test_view_round_trips_through_json(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 1, {("A", 0): 1.0}, at(1))
    publish(ws, s, 2, {("A", 0): 1.0, ("A", 1): 4.0}, at(2))
    v = Archive(ws).view(["w/adm"], 2, at(9))
    assert ArchiveView.model_validate_json(v.model_dump_json()) == v
    with pytest.raises(ValueError):
        v.as_of = 3


def test_realized_reads_the_resolution_vintage(ws):
    s = count_spec(jurisdictions=("A",))
    t = Target(stream="w/adm", jurisdiction="A", reference_week=2, horizon=1, resolution_lag=2)
    a = Archive(ws)
    publish(ws, s, 4, {("A", 3): 4.0}, at(4))
    assert a.realized(t) is None
    publish(ws, s, 5, {("A", 3): 9.0}, at(5))
    assert a.realized(t) == 9
    assert type(a.realized(t)) is int


def test_realized_is_none_when_the_resolution_vintage_lacks_the_week(ws):
    s = count_spec()
    t = Target(stream="w/adm", jurisdiction="A", reference_week=2, horizon=1, resolution_lag=1)
    publish(ws, s, 4, {("A", 2): 4.0, ("B", 3): 7.0}, at(4))
    a = Archive(ws)
    assert a.realized(t) is None  # no (A, 3) row
    assert a.realized(t.model_copy(update={"jurisdiction": "B"})) == 7
    assert a.realized(t.model_copy(update={"stream": "w/none"})) is None


def test_realized_refuses_a_non_integer_value(ws):
    publish(ws, covariate_spec(), 3, {("A", 1): 0.5}, at(3))
    t = Target(stream="w/x", jurisdiction="A", reference_week=0, horizon=1, resolution_lag=2)
    with pytest.raises(ArchiveError, match="not an integer"):
        Archive(ws).realized(t)


def test_duplicate_issue_and_unknown_stream_refused(ws):
    s = count_spec(jurisdictions=("A",))
    c = publish(ws, s, 1, {("A", 0): 1.0}, at(1))
    with pytest.raises(ArchiveError):
        Archive(ws).add(c)
    with pytest.raises(ArchiveError):
        Archive(ws).add(Capture.make(Vintage(stream="w/none", issue=1, rows=()), at(1), "t"))


def test_duplicate_issue_message_and_original_is_untouched(ws):
    s = count_spec(jurisdictions=("A",))
    c = publish(ws, s, 1, {("A", 0): 1.0}, at(1))
    other = Capture.make(Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=2.0),)), at(2), "t")
    with pytest.raises(ArchiveError, match="issue already captured; source corrections are a tier 2 feature"):
        Archive(ws).add(other)
    v = Archive(ws).view(["w/adm"], 1, at(9))
    assert v.history("w/adm") == (c.vintage,)
    assert Archive(ws).published_at("w/adm", 1) == at(1)


def test_malformed_vintage_refused_and_nothing_written(ws):
    a = Archive(ws)
    a.create_stream(count_spec(jurisdictions=("A",)))
    bad = Capture.make(Vintage(stream="w/adm", issue=1, rows=(Row(jurisdiction="A", week=0, value=1.5),)), at(1), "t")
    with pytest.raises(ModelError):
        a.add(bad)
    assert a.issues("w/adm") == []


def test_stream_ids_that_escape_the_archive_are_refused(ws):
    a = Archive(ws)
    for bad in ("../x", "w/../x", "/etc", "w//adm", "", "."):
        with pytest.raises(ArchiveError, match="invalid stream id"):
            a.spec(bad)
    with pytest.raises(ArchiveError, match="invalid stream id"):
        a.add(Capture.make(Vintage(stream="../x", issue=1, rows=()), at(1), "t"))


def test_create_stream_conflict(ws):
    a = Archive(ws)
    a.create_stream(count_spec())
    a.create_stream(count_spec())
    with pytest.raises(ArchiveError):
        a.create_stream(count_spec(support_max=5))
    assert a.spec("w/adm") == count_spec()


def test_streams_live_in_nested_directories_and_specs_finds_them_at_any_depth(ws):
    shallow = count_spec(id="adm", world="w")
    mid = count_spec(id="w/adm")
    deep = covariate_spec(id="w/deep/er/x")
    a = Archive(ws)
    for s in (mid, deep, shallow):
        a.create_stream(s)
    publish(ws, deep, 2, {("A", 0): 0.25}, at(2))
    assert (ws.archive / "w" / "adm" / "stream.json").is_file()
    assert (ws.archive / "w" / "deep" / "er" / "x" / "00002.json").is_file()
    assert [s.id for s in a.specs()] == ["adm", "w/adm", "w/deep/er/x"]
    assert a.specs() == [shallow, mid, deep]
    assert Archive(ws).specs() == a.specs()


def test_specs_of_an_empty_archive(ws):
    assert Archive(ws).specs() == []


def test_issues_and_published_at(ws):
    s = count_spec(jurisdictions=("A",))
    a = Archive(ws)
    assert a.issues("w/adm") == [] and a.published_at("w/adm", 3) is None
    for i in (10, 2, 3):
        publish(ws, s, i, {("A", 0): 1.0}, at(i))
    assert a.issues("w/adm") == [2, 3, 10]
    assert a.published_at("w/adm", 10) == at(10)
    assert a.published_at("w/adm", 4) is None
    assert (ws.archive / "w" / "adm" / "00010.json").is_file()


def test_stray_json_files_in_a_stream_directory_are_reported(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    stream_dir = ws.archive / "w" / "adm"
    (stream_dir / "notes.txt").write_text("not a capture")  # other file types are ignored
    assert Archive(ws).issues("w/adm") == [1]
    for stray in ("notes.json", "1.json", "1_0.json"):
        (stream_dir / stray).write_text("{}")
        with pytest.raises(ArchiveError, match="unexpected files"):
            Archive(ws).issues("w/adm")
        (stream_dir / stray).unlink()


def test_a_capture_filed_under_the_wrong_issue_is_refused(ws):
    s = count_spec(jurisdictions=("A",))
    publish(ws, s, 1, {("A", 0): 1.0}, at(1))
    stream_dir = ws.archive / "w" / "adm"
    (stream_dir / "00002.json").write_text((stream_dir / "00001.json").read_text())
    with pytest.raises(ArchiveError, match="holds issue 1"):
        Archive(ws).view(["w/adm"], 2, at(9))


def test_nested_streams_do_not_leak_into_the_parent_issue_list(ws):
    publish(ws, count_spec(id="w/adm", jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    publish(ws, count_spec(id="w/adm/sub", jurisdictions=("A",)), 2, {("A", 0): 1.0}, at(2))
    assert Archive(ws).issues("w/adm") == [1]
    assert Archive(ws).issues("w/adm/sub") == [2]


def test_candidate_aliases_parent_history(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    arm = count_spec(
        id="w/adm~c",
        jurisdictions=("A",),
        parent="w/adm",
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=4),
    )
    v = Archive(ws).view(["w/adm"], 1, at(9)).with_candidate(arm)
    assert v.history("w/adm~c") == v.history("w/adm") and v.spec("w/adm~c") == arm


def test_with_candidate_leaves_the_original_view_unchanged_and_serializes(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    arm = count_spec(
        id="w/adm~c",
        jurisdictions=("A",),
        parent="w/adm",
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=4),
    )
    base = Archive(ws).view(["w/adm"], 1, at(9))
    v = base.with_candidate(arm)
    assert "w/adm~c" not in base.specs and "w/adm~c" in v.specs
    assert v.series("w/adm~c", "A") == [(0, 1.0)]
    assert v.with_candidate(arm) == v  # the same candidate again changes nothing
    assert ArchiveView.model_validate_json(v.model_dump_json()) == v


def test_with_candidate_refuses_what_cannot_alias(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    v = Archive(ws).view(["w/adm"], 1, at(9))
    iv = Intervention(variable="schools_closed", value=1.0, start_week=4)
    with pytest.raises(ArchiveError, match="no parent"):
        v.with_candidate(count_spec(id="w/free", jurisdictions=("A",)))
    with pytest.raises(ArchiveError, match="parent"):
        v.with_candidate(count_spec(id="w/arm", parent="w/elsewhere", intervention=iv))
    with pytest.raises(ArchiveError, match="already in the view"):
        v.with_candidate(count_spec(id="w/adm", parent="w/adm", intervention=iv))
