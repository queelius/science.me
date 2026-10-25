import math
import shutil
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from helpers import CONST, at, count_spec, make_mission, publish, write_program
from pydantic import ValidationError

import scienceme.cli
from scienceme.archive import ArchiveError
from scienceme.cli import build_parser, main
from scienceme.gain import load_latest_ranking
from scienceme.manifest import ClosureError, InterfaceVar, PairError, Tag
from scienceme.mission import Candidate, Claim, Mission, MissionError, WantedItem, append_wanted, save_mission
from scienceme.model import Intervention, Isolation, Target, TargetFilter, Timing
from scienceme.predict import OriginReport
from scienceme.readback import Readback, ReadbackError
from scienceme.record import RecordError, RecordStore
from scienceme.registry import Freeze, Registry, RegistryError, Withdrawal
from scienceme.worker import WorkerError
from scienceme.workspace import WriteOnceError

ORIGINAL_NOW = scienceme.cli._now
STREAM = "w/adm"
SCHOOLS = InterfaceVar(variable="schools_closed", timing=Timing.START_OF_WEEK, alters=("transmission",))
SCHOOL = Claim(id="school", statement="Closing schools lowers admissions.", scope=TargetFilter())
NONE = ("--isolation", "none")


def point_code(value: int) -> str:
    return f"from scienceme.pmf import Pmf\ndef predict(ctx, target):\n    return Pmf.point({value})\n"


@pytest.fixture(autouse=True)
def clock(monkeypatch):
    """The CLI's wall clock, fixed at `at(0)`; a test moves it by assigning `clock.now`."""
    c = SimpleNamespace(now=at(0))
    monkeypatch.setattr(scienceme.cli, "_now", lambda: c.now)
    return c


@pytest.fixture
def cli(ws, capsys):
    """Run `main` against the workspace; returns (exit code, stdout, stderr)."""

    def run(*args):
        code = main(["--root", str(ws.root), *args])
        out, err = capsys.readouterr()
        return code, out, err

    return run


def publish_issues(ws, issues=range(1, 6)) -> None:
    """Publish each issue of `w/adm` (jurisdiction A) at `at(issue)`, every week so far showing 5."""
    spec = count_spec(jurisdictions=("A",), support_max=99)
    for issue in issues:
        publish(ws, spec, issue, {("A", w): 5.0 for w in range(issue)}, at(issue))


def one_line(text: str) -> bool:
    return len(text.strip().splitlines()) == 1


def append(path, text: str) -> None:
    """Append `text` to the file at `path`, closing it."""
    with path.open("a", encoding="utf-8") as f:
        f.write(text)


# --- parsing and exit codes ---


def test_unknown_subcommand_is_a_usage_error(cli):
    code, out, err = cli("frobnicate")
    assert (code, out) == (2, "")
    assert "frobnicate" in err


def test_no_subcommand_is_a_usage_error(cli):
    assert cli()[0] == 2


def test_missing_required_arguments_are_usage_errors(cli):
    assert cli("freeze")[0] == 2
    assert cli("withdraw", "p")[0] == 2  # --reason is required
    assert cli("predict", "--mission", "m")[0] == 2  # needs --issue or --all
    assert cli("predict", "--mission", "m", "--issue", "1", "--all")[0] == 2  # not both
    assert cli("predict", "--mission", "m", "--issue", "one")[0] == 2
    assert cli("rank-wanted")[0] == 2
    assert cli("readback-packet", "p")[0] == 2


def test_help_exits_zero(cli):
    code, out, _ = cli("--help")
    assert code == 0 and "freeze" in out


def test_a_root_that_is_not_a_directory_is_a_usage_error(tmp_path, capsys):
    assert main(["--root", str(tmp_path / "nowhere"), "check"]) == 2
    assert "nowhere" in capsys.readouterr().err


def test_root_defaults_to_the_current_directory(ws, monkeypatch, capsys):
    monkeypatch.chdir(ws.root)
    assert main(["check"]) == 0
    assert capsys.readouterr().out.strip() == "ok"


def test_isolation_choices_are_the_isolation_values_and_default_is_container():
    parser = build_parser()
    assert parser.parse_args(["predict", "--mission", "m", "--all"]).isolation is Isolation.CONTAINER
    assert parser.parse_args(["rank-wanted", "--mission", "m"]).isolation is Isolation.CONTAINER
    for isolation in Isolation:
        args = parser.parse_args(["predict", "--mission", "m", "--all", "--isolation", isolation.value])
        assert args.isolation is isolation


def test_a_bad_isolation_is_a_usage_error(cli):
    assert cli("predict", "--mission", "m", "--all", "--isolation", "vm")[0] == 2


def test_now_is_timezone_aware_utc():
    before = datetime.now(UTC)
    now = ORIGINAL_NOW()
    assert before <= now <= datetime.now(UTC) + timedelta(seconds=1)
    assert now.utcoffset() == timedelta(0)


# --- domain errors print one line and exit 1 ---


def with_multiline_message() -> ValidationError:
    try:
        Mission.model_validate({"name": 1})
    except ValidationError as e:
        return e
    raise AssertionError("an incomplete mission validated")


DOMAIN_ERRORS = [
    RegistryError("registry says no"),
    ArchiveError("archive says no"),
    MissionError("mission says no"),
    PairError("pair says no"),
    ClosureError("closure says no"),
    RecordError("record says no"),
    ReadbackError("readback says no"),
    WriteOnceError("refusing to overwrite x"),
    WorkerError("worker says no"),
    FileNotFoundError("missing file"),
]


@pytest.mark.parametrize("error", DOMAIN_ERRORS, ids=lambda e: type(e).__name__)
def test_domain_errors_print_one_line_and_exit_1(cli, monkeypatch, error):
    def fail(ws):
        raise error

    monkeypatch.setattr(scienceme.cli, "write_all", fail)
    code, out, err = cli("standings")
    assert (code, out) == (1, "")
    assert one_line(err) and "Traceback" not in err and str(error) in err


def test_a_multi_line_message_is_collapsed_to_one_line(cli, monkeypatch):
    def fail(ws):
        raise RegistryError("first line\nsecond line\n  third line")

    monkeypatch.setattr(scienceme.cli, "write_all", fail)
    code, _, err = cli("standings")
    assert code == 1 and err.strip().endswith("first line second line third line")


def test_a_validation_error_names_the_offending_fields(cli, monkeypatch):
    def fail(ws):
        raise with_multiline_message()

    monkeypatch.setattr(scienceme.cli, "write_all", fail)
    _, _, err = cli("standings")
    assert one_line(err) and "name" in err and "captain" in err


def test_a_bug_is_not_swallowed(cli, monkeypatch):
    def fail(ws):
        raise ZeroDivisionError("bug")

    monkeypatch.setattr(scienceme.cli, "write_all", fail)
    with pytest.raises(ZeroDivisionError):
        cli("standings")


# --- freeze ---


def test_freeze_records_the_program_at_the_clock(ws, cli, clock):
    write_program(ws, "p", CONST)
    clock.now = at(3)
    code, out, err = cli("freeze", "p")
    assert (code, err) == (0, "")
    record = Registry(ws).by_name("p")
    assert isinstance(record, Freeze) and record.frozen_at == at(3)
    assert "p" in out and record.closure_hash in out


def test_freeze_is_idempotent_for_unchanged_content(ws, cli, clock):
    write_program(ws, "p", CONST)
    assert cli("freeze", "p")[0] == 0
    clock.now = at(9)
    assert cli("freeze", "p")[0] == 0
    assert Registry(ws).by_name("p").frozen_at == at(0)
    assert len(Registry(ws).entries()) == 1


def test_freezing_a_missing_program_is_a_domain_error(cli):
    code, out, err = cli("freeze", "ghost")
    assert (code, out) == (1, "")
    assert one_line(err) and "ghost" in err


def test_freezing_edited_content_under_the_same_name_is_refused(ws, cli):
    d = write_program(ws, "p", CONST)
    assert cli("freeze", "p")[0] == 0
    (d / "program.py").write_text(CONST + "# edited\n")
    code, _, err = cli("freeze", "p")
    assert code == 1 and one_line(err) and "already frozen" in err


def test_freezing_a_program_with_an_unfrozen_import_is_refused(ws, cli):
    write_program(ws, "lib", CONST, library=True)
    write_program(ws, "user", CONST, imports={"lib": "sha256:" + "0" * 64})
    code, _, err = cli("freeze", "user")
    assert code == 1 and one_line(err) and "not frozen" in err
    assert Registry(ws).by_name("user") is None


# --- withdraw ---


def test_withdraw_looks_the_program_up_by_name(ws, cli, clock):
    write_program(ws, "p", CONST)
    cli("freeze", "p")
    clock.now = at(5)
    code, out, err = cli("withdraw", "p", "--reason", "superseded by q")
    assert (code, err) == (0, "")
    freeze, withdrawal = Registry(ws).entries()
    assert isinstance(withdrawal, Withdrawal)
    assert withdrawal.closure_hash == freeze.closure_hash
    assert (withdrawal.at, withdrawal.reason) == (at(5), "superseded by q")
    assert "p" in out
    assert not Registry(ws).active(freeze.closure_hash, at(6))


def test_withdrawing_an_unknown_name_is_a_domain_error(ws, cli):
    write_program(ws, "p", CONST)  # on disk but never frozen
    code, out, err = cli("withdraw", "p", "--reason", "x")
    assert (code, out) == (1, "")
    assert one_line(err) and "'p'" in err and "not frozen" in err
    assert Registry(ws).entries() == []


# --- predict ---


@pytest.fixture
def forecasting(ws):
    """Mission `m` over `w/adm` with issues 1..5 published at at(1..5) and program `p` frozen at at(0)."""
    publish_issues(ws)
    save_mission(ws, make_mission())
    write_program(ws, "p", CONST)
    Registry(ws).freeze("p", at(0))
    return ws


def records(ws):
    return RecordStore(ws).all("m")


def test_predict_issue_records_that_week_only(forecasting, cli):
    code, out, err = cli("predict", "--mission", "m", "--issue", "3", *NONE)
    assert (code, err) == (0, "")
    assert {r.target.reference_week for r in records(forecasting)} == {3}
    assert len(records(forecasting)) == 2  # horizons 0 and 1, one jurisdiction
    assert out.strip().splitlines() == [f"run week=3 stream={STREAM} program=p targets=2"]


def test_predict_all_runs_every_published_week(forecasting, cli):
    code, out, err = cli("predict", "--mission", "m", "--all", *NONE)
    assert (code, err) == (0, "")
    assert {r.target.reference_week for r in records(forecasting)} == {1, 2, 3, 4, 5}
    assert [line.split()[1] for line in out.strip().splitlines()] == [f"week={w}" for w in range(1, 6)]


def test_predict_reports_each_skip_on_a_rerun(forecasting, cli):
    cli("predict", "--mission", "m", "--issue", "3", *NONE)
    code, out, _ = cli("predict", "--mission", "m", "--issue", "3", *NONE)
    assert code == 0
    assert out.strip().splitlines() == [f"skip week=3 stream={STREAM} program=p reason=already-recorded"]
    assert len(records(forecasting)) == 2  # nothing rewritten


def test_predict_reports_programs_edited_after_freezing(forecasting, cli):
    (forecasting.programs / "p" / "program.py").write_text(CONST + "# tampered\n")
    code, out, _ = cli("predict", "--mission", "m", "--issue", "3", *NONE)
    assert code == 0
    assert out.strip().splitlines() == [f"skip week=3 stream={STREAM} program=p reason=modified-after-freeze"]
    assert records(forecasting) == []


def test_predict_records_carry_the_clock_and_isolation(forecasting, cli, clock):
    clock.now = at(40)
    cli("predict", "--mission", "m", "--issue", "2", *NONE)
    assert {(r.recorded_at, r.isolation) for r in records(forecasting)} == {(at(40), Isolation.NONE)}


def test_predict_with_nothing_to_do_says_so(ws, cli):
    save_mission(ws, make_mission())
    code, out, _ = cli("predict", "--mission", "m", "--all", *NONE)
    assert code == 0 and one_line(out) and "nothing" in out


def test_predict_below_the_missions_isolation_floor_is_a_domain_error(forecasting, cli):
    save_mission(forecasting, make_mission(required_isolation=Isolation.CONTAINER))
    code, out, err = cli("predict", "--mission", "m", "--issue", "3", *NONE)
    assert (code, out) == (1, "")
    assert one_line(err) and "container" in err
    assert records(forecasting) == []


def test_predict_for_an_unknown_mission_is_a_domain_error(ws, cli):
    code, out, err = cli("predict", "--mission", "ghost", "--all", *NONE)
    assert (code, out) == (1, "")
    assert one_line(err) and "ghost" in err


def test_predict_passes_the_chosen_isolation_and_the_clock(forecasting, cli, clock, monkeypatch):
    seen = {}

    def fake(ws, mission, week, isolation, now):
        seen.update(week=week, isolation=isolation, now=now)
        return OriginReport(mission=mission.name, reference_week=week, ran=(), skipped=())

    monkeypatch.setattr(scienceme.cli, "run_origin", fake)
    clock.now = at(8)
    assert cli("predict", "--mission", "m", "--issue", "4", "--isolation", "process")[0] == 0
    assert seen == dict(week=4, isolation=Isolation.PROCESS, now=at(8))
    seen.clear()
    cli("predict", "--mission", "m", "--issue", "4")
    assert seen["isolation"] is Isolation.CONTAINER


def test_a_worker_failure_is_a_domain_error(forecasting, cli, monkeypatch):
    def fail(*args):
        raise WorkerError("docker is not running")

    monkeypatch.setattr(scienceme.cli, "run_origin", fail)
    code, _, err = cli("predict", "--mission", "m", "--issue", "3")
    assert code == 1 and one_line(err) and "docker is not running" in err


# --- rank-wanted ---


def arm_spec(id="w/adm/s1", start=5):
    return count_spec(
        id=id,
        jurisdictions=("A",),
        parent=STREAM,
        intervention=Intervention(variable="schools_closed", value=1.0, start_week=start),
    )


def want(ws, item_id, cost=1.0, mission="m") -> WantedItem:
    spec = arm_spec(id=f"w/adm/{item_id}")
    targets = tuple(
        Target(stream=spec.id, jurisdiction="A", reference_week=3, horizon=h, resolution_lag=2) for h in (2, 3)
    )
    item = WantedItem(id=item_id, proposed_by="test", candidate=Candidate(stream=spec, targets=targets), cost=cost)
    append_wanted(ws, mission, item)
    return item


@pytest.fixture
def ranking(ws, clock):
    """Mission `m` with issues 1..3 published, two disjoint-forecasting programs that support `schools_closed`
    (frozen at at(0)), and wanted items `a` (cost 1) and `b` (cost 4), both starting after issue 3.  The clock
    reads at(10)."""
    clock.now = at(10)
    publish_issues(ws, range(1, 4))
    save_mission(ws, make_mission())
    for name, value in (("five", 5), ("nine", 9)):
        write_program(ws, name, point_code(value), interface=(SCHOOLS,))
        Registry(ws).freeze(name, at(0))
    want(ws, "a")
    want(ws, "b", cost=4.0)
    return ws


def test_rank_wanted_saves_the_ranking_and_prints_a_line_per_item(ranking, cli):
    code, out, err = cli("rank-wanted", "--mission", "m", *NONE)
    assert (code, err) == (0, "")
    saved = load_latest_ranking(ranking, "m")
    assert saved is not None and saved.as_of == 3 and [r.item for r in saved.items] == ["a", "b"]
    lines = out.strip().splitlines()
    assert len(lines) == 2
    for line, item in zip(lines, saved.items):
        assert line == f"{item.item} priority={item.priority:.6g} gain={item.gain:.6g}"
    # nothing has resolved, so the two programs weigh the same and disjoint forecasts carry one bit per target
    assert saved.items[0].gain == pytest.approx(2 * math.log(2))
    assert saved.items[0].priority > saved.items[1].priority  # same gain, a quarter of the cost


def test_rank_wanted_weights_by_the_resolved_record(ranking, cli):
    cli("predict", "--mission", "m", "--all", *NONE)
    assert cli("rank-wanted", "--mission", "m", *NONE)[0] == 0
    saved = load_latest_ranking(ranking, "m")
    assert saved.as_of == 3 and saved.items[0].gain > 0
    # "five" has been right and "nine" wrong, so the mixture leans on one program and the gain is below ln 2
    assert saved.items[0].gain < math.log(2)


def test_rank_wanted_is_write_once_per_issue(ranking, cli, monkeypatch):
    assert cli("rank-wanted", "--mission", "m", *NONE)[0] == 0

    def must_not_run(*args):
        raise AssertionError("the programs ran although the ranking cannot be saved")

    with monkeypatch.context() as m:
        m.setattr(scienceme.cli, "rank_wanted", must_not_run)  # refused before the expensive part
        code, out, err = cli("rank-wanted", "--mission", "m", *NONE)
    assert (code, out) == (1, "")
    assert one_line(err) and "overwrite" in err
    publish_issues(ranking, [4])
    assert cli("rank-wanted", "--mission", "m", *NONE)[0] == 0
    assert load_latest_ranking(ranking, "m").as_of == 4


def test_rank_wanted_with_nothing_published_saves_nothing(ws, cli):
    save_mission(ws, make_mission())
    code, out, err = cli("rank-wanted", "--mission", "m", *NONE)
    assert (code, err) == (0, "")
    assert one_line(out) and "nothing" in out
    assert load_latest_ranking(ws, "m") is None


def test_rank_wanted_with_no_open_items_saves_an_empty_ranking(ws, cli):
    publish_issues(ws, range(1, 4))
    save_mission(ws, make_mission())
    code, out, _ = cli("rank-wanted", "--mission", "m", *NONE)
    assert code == 0 and one_line(out) and "no open" in out
    assert load_latest_ranking(ws, "m").items == ()


@pytest.mark.parametrize(("now_hours", "late_supports"), [(10, False), (30, True)])
def test_rank_wanted_uses_the_clock_for_who_is_active(ranking, cli, clock, now_hours, late_supports):
    write_program(ranking, "late", point_code(1), interface=(SCHOOLS,))
    late = Registry(ranking).freeze("late", at(20)).closure_hash
    clock.now = at(now_hours)
    assert cli("rank-wanted", "--mission", "m", *NONE)[0] == 0
    (first, *_) = load_latest_ranking(ranking, "m").items
    assert (late in first.supporting) is late_supports


def test_rank_wanted_below_the_isolation_floor_is_a_domain_error(ranking, cli):
    save_mission(ranking, make_mission(required_isolation=Isolation.PROCESS))
    code, _, err = cli("rank-wanted", "--mission", "m", *NONE)
    assert code == 1 and one_line(err) and "process" in err
    assert load_latest_ranking(ranking, "m") is None


def test_rank_wanted_for_an_unknown_mission_is_a_domain_error(ws, cli):
    code, _, err = cli("rank-wanted", "--mission", "ghost", *NONE)
    assert code == 1 and one_line(err) and "ghost" in err


# --- standings ---


def test_standings_check_is_stale_until_standings_writes_the_files(ws, cli):
    publish_issues(ws, range(1, 4))
    save_mission(ws, make_mission())
    code, out, err = cli("standings", "--check")
    assert (code, out) == (1, "")
    assert one_line(err) and "stale" in err
    assert cli("standings")[0] == 0
    assert (ws.root / "standings.json").is_file() and (ws.root / "STANDINGS.md").is_file()
    code, out, err = cli("standings", "--check")
    assert (code, err) == (0, "") and one_line(out)


def test_standings_go_stale_when_the_record_changes(ws, cli):
    publish_issues(ws, range(1, 4))
    save_mission(ws, make_mission())
    cli("standings")
    publish_issues(ws, [4])
    assert cli("standings", "--check")[0] == 1
    assert cli("standings")[0] == 0
    assert cli("standings", "--check")[0] == 0


def test_standings_without_missions_still_writes_files(ws, cli):
    assert cli("standings")[0] == 0
    assert "No mission has published data" in (ws.root / "STANDINGS.md").read_text()
    assert cli("standings", "--check")[0] == 0


def test_the_forecast_record_is_a_cache_that_predict_rebuilds(forecasting, cli):
    cli("predict", "--mission", "m", "--all", *NONE)
    assert cli("standings")[0] == 0
    shutil.rmtree(forecasting.scores)  # a fresh checkout: the forecasts are not in git
    forecasting.scores.mkdir()
    for args in (("standings",), ("standings", "--check")):
        code, out, err = cli(*args)
        assert (code, out) == (1, "")
        assert one_line(err) and "incomplete" in err and "predict --all" in err
    cli("predict", "--mission", "m", "--all", *NONE)
    assert cli("standings", "--check")[0] == 0  # rebuilt forecast for forecast


def test_standings_refuses_a_program_edited_after_freezing(forecasting, cli):
    cli("predict", "--mission", "m", "--all", *NONE)
    (forecasting.programs / "p" / "program.py").write_text(CONST + "# tampered\n")
    code, out, err = cli("standings")
    assert (code, out) == (1, "")
    assert one_line(err) and "modified-after-freeze" in err


# --- readback-packet ---


def test_readback_packet_prints_the_blind_packet(ws, cli):
    write_program(ws, "p", CONST + "# CODE-MARKER\n", tags={"school": Tag.ASSERTS}, interface=(SCHOOLS,))
    Registry(ws).freeze("p", at(0))
    save_mission(ws, make_mission(claims=(SCHOOL,)))
    code, out, err = cli("readback-packet", "p", "--mission", "m")
    assert (code, err) == (0, "")
    assert "CODE-MARKER" in out and SCHOOL.statement in out
    assert '"tags"' not in out and "schools_closed" not in out


def test_readback_packet_for_an_unknown_program_is_a_domain_error(ws, cli):
    save_mission(ws, make_mission())
    code, out, err = cli("readback-packet", "ghost", "--mission", "m")
    assert (code, out) == (1, "")
    assert one_line(err) and "ghost" in err


def test_readback_packet_for_an_unknown_mission_is_a_domain_error(ws, cli):
    write_program(ws, "p", CONST)
    Registry(ws).freeze("p", at(0))
    code, _, err = cli("readback-packet", "p", "--mission", "ghost")
    assert code == 1 and one_line(err) and "ghost" in err


def test_readback_packet_refuses_a_modified_program(ws, cli):
    d = write_program(ws, "p", CONST)
    Registry(ws).freeze("p", at(0))
    save_mission(ws, make_mission())
    (d / "program.py").write_text(CONST + "# tampered\n")
    code, out, err = cli("readback-packet", "p", "--mission", "m")
    assert (code, out) == (1, "")
    assert one_line(err) and "modified-after-freeze" in err


# --- check ---


@pytest.fixture
def clean(ws):
    """A frozen program, a mission, and a wanted list, all valid."""
    write_program(ws, "p", CONST, interface=(SCHOOLS,))
    Registry(ws).freeze("p", at(0))
    publish_issues(ws, range(1, 4))
    save_mission(ws, make_mission())
    want(ws, "a")
    return ws


def test_check_of_an_empty_workspace_is_ok(cli):
    assert cli("check") == (0, "ok\n", "")


def test_check_of_a_directory_with_no_workspace_layout_is_ok(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "check"]) == 0
    assert capsys.readouterr().out == "ok\n"


def test_check_of_a_clean_workspace_is_ok(clean, cli):
    assert cli("check") == (0, "ok\n", "")


def test_check_catches_a_frozen_program_edited_afterwards(clean, cli):
    (clean.programs / "p" / "program.py").write_text(CONST + "# tampered\n")
    code, out, err = cli("check")
    assert code == 1
    lines = out.strip().splitlines()
    assert len(lines) == 1 and "p was frozen as" in lines[0] and "modified-after-freeze" in lines[0]
    assert err == ""


def test_check_catches_a_deleted_frozen_program(clean, cli):
    shutil.rmtree(clean.programs / "p")
    code, out, _ = cli("check")
    assert code == 1 and "p" in out


def test_check_reports_every_problem_on_its_own_line(clean, cli):
    (clean.programs / "p" / "program.py").write_text(CONST + "# tampered\n")
    (clean.programs / "broken").mkdir()
    (clean.programs / "broken" / "program.json").write_text("{not json")
    (clean.programs / "empty").mkdir()
    (clean.missions / "bad").mkdir()
    (clean.missions / "bad" / "mission.json").write_text('{"name": "bad"}')
    append(clean.missions / "m" / "wanted.jsonl", '{"id": "x"}\n')
    code, out, _ = cli("check")
    assert code == 1
    lines = out.strip().splitlines()
    assert len(lines) == 5
    text = "\n".join(lines)
    for fragment in (
        "modified-after-freeze",
        "programs/broken",
        "programs/empty",
        "missions/bad",
        "missions/m/wanted.jsonl",
    ):
        assert fragment in text
    assert len(set(lines)) == len(lines)


def test_check_flags_an_unparsable_wanted_list(clean, cli):
    append(clean.missions / "m" / "wanted.jsonl", "not json\n")
    code, out, _ = cli("check")
    assert code == 1 and one_line(out)
    assert out.startswith("missions/m/wanted.jsonl: ")


def test_check_flags_an_unreadable_mission_file(clean, cli):
    (clean.missions / "m" / "mission.json").write_text("{")
    code, out, _ = cli("check")
    assert code == 1 and one_line(out) and out.startswith("missions/m: ")


def test_check_flags_a_corrupt_registry_and_still_checks_the_rest(clean, cli):
    append(clean.registry, "garbage\n")
    (clean.missions / "m" / "mission.json").write_text("{")
    code, out, _ = cli("check")
    assert code == 1
    lines = out.strip().splitlines()
    assert len(lines) == 2 and any(line.startswith("registry: ") for line in lines)


def test_check_flags_an_invalid_readback(clean, cli):
    (clean.programs / "p" / "readback.json").write_text('{"not": "a readback"}')
    code, out, _ = cli("check")
    assert code == 1 and one_line(out)
    assert out.startswith("programs/p/readback.json: ") and "author_lineage" in out


def test_check_flags_an_unparsable_readback_of_an_unfrozen_program(clean, cli):
    write_program(clean, "draft", CONST)
    (clean.programs / "draft" / "readback.json").write_text("{")
    code, out, _ = cli("check")
    assert code == 1 and one_line(out) and out.startswith("programs/draft/readback.json: ")


def test_check_accepts_a_valid_readback(clean, cli):
    readback = Readback(
        author_lineage="openai/gpt",
        author_agent="codex",
        assumptions=(),
        inferred_tags={},
        inferred_interface=("schools_closed",),
        summary="",
    )
    (clean.programs / "p" / "readback.json").write_text(readback.model_dump_json())
    assert cli("check") == (0, "ok\n", "")


def test_check_ignores_files_among_the_programs(clean, cli):
    (clean.programs / ".gitkeep").write_text("")
    assert cli("check")[0] == 0


def test_rank_wanted_uses_only_current_epoch_evidence(ranking, cli):
    from scienceme.mission import begin_epoch  # noqa: PLC0415

    assert cli("predict", "--mission", "m", "--all", *NONE)[0] == 0
    begin_epoch(ranking, "m", {"epsilon": 0.3}, 4, "r", 3)
    assert cli("rank-wanted", "--mission", "m", *NONE)[0] == 0
    saved = load_latest_ranking(ranking, "m")
    assert saved.items[0].gain == pytest.approx(2 * math.log(2))
