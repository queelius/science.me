import pytest
from helpers import CONST, PER_TARGET, at, count_spec, covariate_spec, make_mission, publish, write_program

import scienceme.predict
from scienceme.manifest import InterfaceVar
from scienceme.model import Intervention, Isolation, Target, TargetFilter, Timing
from scienceme.mission import MissionError
from scienceme.pmf import Pmf
from scienceme.predict import OriginReport, Run, Skip, SkipReason, run_all, run_origin
from scienceme.record import PredictionRecord, RecordError, RecordStore, UnscoredRecord
from scienceme.registry import Registry
from scienceme.worker import WorkerError, scorer_hash
from scienceme.worker_entry import program_dirname
from scienceme.workspace import WriteOnceError

STREAM = "w/adm"

# A program that forecasts how many vintages of its target's stream it can see.
VIEW_LEN = "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(len(ctx.view.history(target.stream)))\n"


def frozen(ws, name, code=CONST, when=at(0), **fields) -> str:
    """Write and freeze program `name` at `when`; return its closure hash."""
    write_program(ws, name, code, **fields)
    return Registry(ws).freeze(name, when).closure_hash


def tgt(jurisdiction="A", week=1, horizon=0, stream=STREAM) -> Target:
    return Target(stream=stream, jurisdiction=jurisdiction, reference_week=week, horizon=horizon, resolution_lag=2)


def prediction(program, target, mission="m") -> PredictionRecord:
    return PredictionRecord(
        mission=mission, program=program, target=target, pmf=Pmf.point(1), scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def unscored(program, target, mission="m") -> UnscoredRecord:
    return UnscoredRecord(
        mission=mission, program=program, target=target, reason="boom", scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(3),
    )


def arm_spec(id="w/adm/s1", variable="schools_closed", **kw):
    return count_spec(
        id=id,
        jurisdictions=("A",),
        parent=STREAM,
        intervention=Intervention(variable=variable, value=1.0, start_week=0),
        **kw,
    )


SCHOOLS = InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",))


# --- eligibility (spec 4.2) ---


def test_frozen_after_publication_is_ineligible(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    write_program(ws, "late", CONST)
    Registry(ws).freeze("late", at(2))
    assert run_origin(ws, make_mission(), 1, Isolation.NONE, at(3)).ran == ()


def test_frozen_after_publication_is_not_even_reported_skipped(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    frozen(ws, "late", when=at(2))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == () and report.skipped == ()
    assert RecordStore(ws).all("m") == []


def test_frozen_at_the_instant_of_publication_is_ineligible(ws):
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    frozen(ws, "instant", when=at(1))
    assert run_origin(ws, make_mission(), 1, Isolation.NONE, at(3)).ran == ()


def test_frozen_before_publication_is_recorded(ws):
    write_program(ws, "early", CONST)
    h = Registry(ws).freeze("early", at(0)).closure_hash
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    rep = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert rep.ran == (Run(stream="w/adm", program=h, n_targets=2),)
    assert {r.kind for r in RecordStore(ws).all("m")} == {"prediction"}


def test_a_program_withdrawn_before_publication_is_ineligible(ws):
    h = frozen(ws, "early")
    Registry(ws).withdraw(h, at(0.5), "retired")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == () and report.skipped == ()


def test_eligibility_is_decided_per_stream_publication_time(ws):
    # `late` froze between the two streams' publications: eligible for the later stream only
    early = frozen(ws, "early")
    late = frozen(ws, "late", CONST + "# late\n", when=at(1.5))
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, count_spec(id="w/adm2", jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(2))
    report = run_origin(ws, make_mission(streams=(STREAM, "w/adm2")), 1, Isolation.NONE, at(3))
    assert [(r.stream, r.program) for r in report.ran] == sorted([(STREAM, early), ("w/adm2", early), ("w/adm2", late)])


def test_libraries_are_not_candidates(ws):
    frozen(ws, "core", "X = 1\n", library=True)
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == () and report.skipped == ()


def test_a_stream_without_a_vintage_at_the_week_is_skipped_silently(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 2, Isolation.NONE, at(3))
    assert report == OriginReport(mission="m", reference_week=2, ran=(), skipped=())


# --- what is written ---


def test_records_are_stamped_and_cover_every_target(ws):
    h = frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A", "B")), 1, {("A", 0): 3.0, ("B", 0): 4.0}, at(1))
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    records = RecordStore(ws).all("m")
    assert [r.target for r in records] == [
        tgt("A", horizon=0), tgt("A", horizon=1), tgt("B", horizon=0), tgt("B", horizon=1)
    ]
    for r in records:
        assert isinstance(r, PredictionRecord)
        assert (r.mission, r.program, r.pmf) == ("m", h, Pmf.point(7))
        assert (r.scorer, r.isolation, r.recorded_at) == (scorer_hash(), Isolation.NONE, at(3))


def test_the_record_stamps_the_isolation_it_ran_under(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    mission = make_mission(required_isolation=Isolation.PROCESS)
    report = run_origin(ws, mission, 1, Isolation.PROCESS, at(3))
    assert len(report.ran) == 1
    assert {r.isolation for r in RecordStore(ws).all("m")} == {Isolation.PROCESS}


def test_a_run_outside_a_container_records_no_runtime_image(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert {r.image for r in RecordStore(ws).all("m")} == {None}


def test_scorer_hash_is_computed_once_per_origin(ws, monkeypatch):
    frozen(ws, "a")
    frozen(ws, "b", CONST + "# b\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    calls = []
    monkeypatch.setattr(scienceme.predict, "scorer_hash", lambda: calls.append(1) or "sha256:once")
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert calls == [1]
    assert {r.scorer for r in RecordStore(ws).all("m")} == {"sha256:once"}


def test_failures_are_recorded_unscored(ws):
    h = frozen(ws, "flaky", PER_TARGET)
    publish(ws, count_spec(jurisdictions=("A", "B")), 1, {("A", 0): 3.0, ("B", 0): 4.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == (Run(stream=STREAM, program=h, n_targets=4),)
    by_target = {r.target: r for r in RecordStore(ws).all("m")}
    assert len(by_target) == 4
    for target, record in by_target.items():
        if target.jurisdiction == "B":
            assert isinstance(record, UnscoredRecord)
            assert "boom" in record.reason
        else:
            assert isinstance(record, PredictionRecord)
            assert record.pmf == Pmf.point(target.horizon)


def test_a_program_that_outlives_the_mission_timeout_is_recorded_unscored(ws):
    frozen(ws, "slow", "import time\ndef predict(ctx, target):\n    time.sleep(60)\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    mission = make_mission(required_isolation=Isolation.PROCESS, run_timeout_s=1)
    report = run_origin(ws, mission, 1, Isolation.PROCESS, at(3))
    assert report.ran[0].n_targets == 2
    assert {(r.kind, r.reason) for r in RecordStore(ws).all("m")} == {("unscored", "timeout")}


def test_the_view_excludes_later_vintages(ws):
    frozen(ws, "counter", VIEW_LEN)
    spec = count_spec(jurisdictions=("A",))
    publish(ws, spec, 1, {("A", 0): 3.0}, at(1))
    publish(ws, spec, 2, {("A", 0): 3.0, ("A", 1): 4.0}, at(2))
    publish(ws, spec, 3, {("A", 0): 3.0, ("A", 1): 4.0, ("A", 2): 5.0}, at(3))
    run_origin(ws, make_mission(), 2, Isolation.NONE, at(4))
    records = RecordStore(ws).all("m")
    assert len(records) == 2
    assert {r.pmf for r in records} == {Pmf.point(2)}


def test_the_view_excludes_vintages_published_after_the_streams_cutoff(ws):
    # the covariate's issue 1 appeared after the count stream's: at the count stream's cutoff it was not yet public
    frozen(ws, "covariate-counter", "from scienceme.sdk import Pmf\ndef predict(ctx, target):\n    return Pmf.point(len(ctx.view.history('w/x')))\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, covariate_spec(), 1, {("A", 0): 0.5}, at(2))
    mission = make_mission(streams=(STREAM, "w/x"))
    run_origin(ws, mission, 1, Isolation.NONE, at(4))
    assert {r.pmf for r in RecordStore(ws).all("m")} == {Pmf.point(0)}


def test_covariate_streams_are_not_forecast(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, covariate_spec(), 1, {("A", 0): 0.5}, at(1))
    report = run_origin(ws, make_mission(streams=(STREAM, "w/x")), 1, Isolation.NONE, at(3))
    assert [r.stream for r in report.ran] == [STREAM]


# --- idempotence and skips ---


def test_rerun_is_idempotent(ws):
    h = frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    before = RecordStore(ws).all("m")
    again = run_origin(ws, make_mission(), 1, Isolation.NONE, at(9))
    assert again.ran == ()
    assert again.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.ALREADY_RECORDED),)
    assert RecordStore(ws).all("m") == before


def test_a_rerun_after_a_new_freeze_writes_only_the_missing_file(ws):
    first = frozen(ws, "first")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    second = frozen(ws, "second", CONST + "# second\n", when=at(0.5))
    again = run_origin(ws, make_mission(), 1, Isolation.NONE, at(4))
    assert [r.program for r in again.ran] == [second]
    assert [s.program for s in again.skipped] == [first]
    assert {r.program for r in RecordStore(ws).all("m")} == {first, second}


def test_unsupported_arm_gets_no_record(ws):
    h = frozen(ws, "plain")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, arm_spec(), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == (Run(stream=STREAM, program=h, n_targets=2),)
    assert report.skipped == (Skip(stream="w/adm/s1", program=h, reason=SkipReason.UNSUPPORTED_INTERVENTION),)
    store = RecordStore(ws)
    assert store.has("m", STREAM, 1, h)
    assert not store.has("m", "w/adm/s1", 1, h)
    assert not store.path("m", "w/adm/s1", 1, h).exists()


def test_a_program_with_the_interface_runs_on_the_arm(ws):
    h = frozen(ws, "causal", interface=(SCHOOLS,))
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, arm_spec(), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == (
        Run(stream=STREAM, program=h, n_targets=2),
        Run(stream="w/adm/s1", program=h, n_targets=2),
    )
    assert report.skipped == ()


def test_a_program_without_in_scope_targets_is_skipped(ws):
    h = frozen(ws, "elsewhere", scope=TargetFilter(jurisdictions=("Z",)))
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == ()
    assert report.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.OUT_OF_SCOPE),)
    assert RecordStore(ws).all("m") == []


def test_a_program_is_run_only_on_its_in_scope_targets(ws):
    h = frozen(ws, "just-a", scope=TargetFilter(jurisdictions=("A",)))
    publish(ws, count_spec(jurisdictions=("A", "B")), 1, {("A", 0): 3.0, ("B", 0): 4.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == (Run(stream=STREAM, program=h, n_targets=2),)
    assert {r.target.jurisdiction for r in RecordStore(ws).all("m")} == {"A"}


def test_modified_program_is_skipped(ws):
    h = frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    (ws.programs / "early" / "program.py").write_text(CONST + "# edited after the freeze\n")
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == ()
    assert report.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.MODIFIED_AFTER_FREEZE),)
    assert not RecordStore(ws).path("m", STREAM, 1, h).exists()
    assert RecordStore(ws).all("m") == []


def test_modification_is_reported_before_an_unsupported_intervention(ws):
    h = frozen(ws, "plain")
    publish(ws, arm_spec(), 1, {("A", 0): 3.0}, at(1))
    (ws.programs / "plain" / "program.py").write_text("edited\n")
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.skipped == (Skip(stream="w/adm/s1", program=h, reason=SkipReason.MODIFIED_AFTER_FREEZE),)


def test_an_existing_record_is_reported_before_a_later_modification(ws):
    h = frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    (ws.programs / "early" / "program.py").write_text("edited\n")
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(4))
    assert report.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.ALREADY_RECORDED),)
    assert len(RecordStore(ws).all("m")) == 2  # the old records are untouched


def test_a_program_whose_manifest_vanished_is_skipped_as_modified(ws):
    h = frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    (ws.programs / "early" / "program.json").unlink()
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.MODIFIED_AFTER_FREEZE),)


def test_a_program_whose_import_was_modified_is_skipped(ws):
    core = frozen(ws, "core", "X = 1\n", library=True)
    h = frozen(ws, "uses-core", CONST, imports={"core": core})
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    (ws.programs / "core" / "program.py").write_text("X = 2\n")
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert report.ran == ()
    assert report.skipped == (Skip(stream=STREAM, program=h, reason=SkipReason.MODIFIED_AFTER_FREEZE),)
    assert RecordStore(ws).all("m") == []


def test_one_modified_program_does_not_stop_the_others(ws):
    broken = frozen(ws, "broken")
    fine = frozen(ws, "fine", CONST + "# fine\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    (ws.programs / "broken" / "program.py").write_text("edited\n")
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert [r.program for r in report.ran] == [fine]
    assert [(s.program, s.reason) for s in report.skipped] == [(broken, SkipReason.MODIFIED_AFTER_FREEZE)]


def test_programs_and_streams_run_in_a_deterministic_order(ws):
    for name in ("p3", "p1", "p2"):
        frozen(ws, name, CONST + f"# {name}\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    publish(ws, arm_spec("w/adm/b"), 1, {("A", 0): 3.0}, at(1))
    publish(ws, arm_spec("w/adm/a"), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    keys = [(r.stream, r.program) for r in report.ran]
    assert keys == sorted(keys)
    assert len(keys) == 3
    skips = [(s.stream, s.program) for s in report.skipped]
    assert skips == sorted(skips)
    assert len(skips) == 6


# --- isolation and infrastructure failure ---


def test_weaker_isolation_refused(ws):
    with pytest.raises(MissionError):
        run_origin(ws, make_mission(required_isolation=Isolation.PROCESS), 1, Isolation.NONE, at(3))


def test_stronger_isolation_than_required_is_accepted(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    report = run_origin(ws, make_mission(required_isolation=Isolation.NONE), 1, Isolation.PROCESS, at(3))
    assert len(report.ran) == 1


def test_a_worker_error_propagates_and_a_rerun_fills_the_rest(ws, monkeypatch):
    for name in ("p1", "p2", "p3"):
        frozen(ws, name, CONST + f"# {name}\n")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    real = scienceme.predict.run_order
    calls = []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise WorkerError("docker is down")
        return real(*args, **kwargs)

    monkeypatch.setattr(scienceme.predict, "run_order", flaky)
    with pytest.raises(WorkerError):
        run_origin(ws, make_mission(), 1, Isolation.NONE, at(3))
    assert len({r.program for r in RecordStore(ws).all("m")}) == 1  # the first program's records stay

    monkeypatch.setattr(scienceme.predict, "run_order", real)
    again = run_origin(ws, make_mission(), 1, Isolation.NONE, at(4))
    assert len(again.ran) == 2
    assert [s.reason for s in again.skipped] == [SkipReason.ALREADY_RECORDED]
    assert len({r.program for r in RecordStore(ws).all("m")}) == 3


# --- run_all ---


def test_run_all_covers_each_week_with_a_published_issue(ws):
    h = frozen(ws, "early")
    spec = count_spec(jurisdictions=("A",))
    for issue in (1, 2, 3):
        publish(ws, spec, issue, {("A", w): 1.0 for w in range(issue)}, at(issue))
    reports = run_all(ws, make_mission(), Isolation.NONE, at(9))
    assert [r.reference_week for r in reports] == [1, 2, 3]
    assert all(r.ran == (Run(stream=STREAM, program=h, n_targets=2),) for r in reports)
    assert {r.target.reference_week for r in RecordStore(ws).all("m")} == {1, 2, 3}


def test_run_all_stops_at_the_missions_last_issue(ws):
    frozen(ws, "early")
    spec = count_spec(jurisdictions=("A",))
    for issue in (1, 2, 3):
        publish(ws, spec, issue, {("A", 0): 1.0}, at(issue))
    reports = run_all(ws, make_mission(last_issue=2), Isolation.NONE, at(9))
    assert [r.reference_week for r in reports] == [1, 2]


def test_run_all_starts_at_the_missions_first_issue(ws):
    frozen(ws, "early")
    spec = count_spec(jurisdictions=("A",))
    for issue in (1, 2, 3):
        publish(ws, spec, issue, {("A", 0): 1.0}, at(issue))
    reports = run_all(ws, make_mission(first_issue=2), Isolation.NONE, at(9))
    assert [r.reference_week for r in reports] == [2, 3]


def test_run_all_with_nothing_published_runs_nothing(ws):
    assert run_all(ws, make_mission(), Isolation.NONE, at(9)) == []


def test_run_all_refuses_weaker_isolation(ws):
    with pytest.raises(MissionError):
        run_all(ws, make_mission(required_isolation=Isolation.CONTAINER), Isolation.PROCESS, at(9))


def test_run_all_is_idempotent(ws):
    frozen(ws, "early")
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 1.0}, at(1))
    run_all(ws, make_mission(), Isolation.NONE, at(9))
    before = RecordStore(ws).all("m")
    again = run_all(ws, make_mission(), Isolation.NONE, at(10))
    assert all(r.ran == () for r in again)
    assert RecordStore(ws).all("m") == before


# --- RecordStore ---


def test_record_path_layout(ws):
    h = "sha256:" + "ab" * 32
    path = RecordStore(ws).path("m", "w/adm", 7, h)
    assert path == ws.scores / "m" / "w" / "adm" / "00007" / (program_dirname(h) + ".json")


@pytest.mark.parametrize(
    "mission, stream",
    [("", "w/adm"), ("m/x", "w/adm"), ("..", "w/adm"), ("m", "../adm"), ("m", "w//adm"), ("m", "/w"), ("m", "")],
)
def test_record_path_refuses_ids_that_could_escape(ws, mission, stream):
    with pytest.raises(RecordError):
        RecordStore(ws).path(mission, stream, 1, "sha256:" + "ab" * 32)


def test_record_path_refuses_a_malformed_program_hash(ws):
    with pytest.raises(ValueError):
        RecordStore(ws).path("m", STREAM, 1, "not-a-hash")


def test_record_store_round_trips_both_kinds(ws):
    h = "sha256:" + "ab" * 32
    store = RecordStore(ws)
    records = [prediction(h, tgt("A")), unscored(h, tgt("B"))]
    assert not store.has("m", STREAM, 1, h)
    store.write("m", STREAM, 1, h, records)
    assert store.has("m", STREAM, 1, h)
    assert store.all("m") == records


def test_record_store_is_write_once(ws):
    h = "sha256:" + "ab" * 32
    store = RecordStore(ws)
    store.write("m", STREAM, 1, h, [prediction(h, tgt("A"))])
    with pytest.raises(WriteOnceError):
        store.write("m", STREAM, 1, h, [prediction(h, tgt("B"))])
    assert [r.target.jurisdiction for r in store.all("m")] == ["A"]


def test_record_store_all_is_scoped_to_one_mission_and_ordered(ws):
    h1, h2 = "sha256:" + "ab" * 32, "sha256:" + "cd" * 32
    store = RecordStore(ws)
    store.write("m", STREAM, 2, h1, [prediction(h1, tgt("A", week=2))])
    store.write("m", STREAM, 1, h2, [prediction(h2, tgt("A", week=1))])
    store.write("m", STREAM, 1, h1, [prediction(h1, tgt("A", week=1))])
    store.write("other", STREAM, 1, h1, [prediction(h1, tgt("A"), mission="other")])
    assert [(r.target.reference_week, r.program) for r in store.all("m")] == [(1, h1), (1, h2), (2, h1)]
    assert [r.mission for r in store.all("other")] == ["other"]
    assert store.all("nobody") == []


@pytest.mark.parametrize(
    "records",
    [
        [],
        [prediction("sha256:" + "cd" * 32, tgt())],  # another program
        [prediction("sha256:" + "ab" * 32, tgt(), mission="other")],  # another mission
        [prediction("sha256:" + "ab" * 32, tgt(week=2))],  # another reference week
        [prediction("sha256:" + "ab" * 32, tgt(stream="w/other"))],  # another stream
        [prediction("sha256:" + "ab" * 32, tgt()), unscored("sha256:" + "ab" * 32, tgt())],  # a target twice
    ],
)
def test_record_store_refuses_records_that_do_not_belong_in_the_file(ws, records):
    store = RecordStore(ws)
    with pytest.raises(RecordError):
        store.write("m", STREAM, 1, "sha256:" + "ab" * 32, records)
    assert not store.has("m", STREAM, 1, "sha256:" + "ab" * 32)
