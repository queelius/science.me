"""Mission epochs: a change of scoring convention is a new epoch, and a new epoch never re-scores the old record."""

import json

import pytest
from helpers import CONST, at, count_spec, make_mission, publish, write_program

from scienceme.mission import (
    Epoch,
    MissionError,
    begin_epoch,
    convention_fields,
    conventions,
    epoch_problems,
    load_epochs,
    load_mission,
    save_mission,
)
from scienceme.model import Isolation, Target
from scienceme.pmf import Pmf
from scienceme.record import PredictionRecord, RecordStore
from scienceme.registry import Registry
from scienceme.standings import compute_all, write_all

STREAM = "w/adm"


def test_the_conventions_are_the_fields_that_decide_a_score() -> None:
    assert convention_fields() == (
        "horizons", "resolution_lag", "epsilon", "tau", "half_life_weeks", "coverage_min",
        "claim_threshold_nats", "regime_flag_tv", "claims",
    )


def test_the_first_save_records_epoch_one(ws) -> None:
    mission = make_mission()
    save_mission(ws, mission)
    assert load_epochs(ws, "m") == [
        Epoch(epoch=1, starts_at=mission.first_issue, reason="the mission's first conventions", conventions=conventions(mission))
    ]


def test_an_operational_change_is_saved_in_the_same_epoch(ws) -> None:
    save_mission(ws, make_mission())
    save_mission(ws, make_mission(streams=(STREAM, "w/x"), exploration_reserve=0.1, last_issue=12))
    assert len(load_epochs(ws, "m")) == 1 and load_mission(ws, "m").streams == (STREAM, "w/x")


@pytest.mark.parametrize("change", [{"epsilon": 0.05}, {"tau": 9.0}, {"horizons": (0,)}, {"epoch": 2}])
def test_saving_a_changed_convention_is_refused(ws, change) -> None:
    save_mission(ws, make_mission())
    with pytest.raises(MissionError, match="new epoch"):
        save_mission(ws, make_mission(**change))
    assert load_mission(ws, "m") == make_mission()


def test_a_first_save_must_be_epoch_one(ws) -> None:
    with pytest.raises(MissionError, match="epoch 1"):
        save_mission(ws, make_mission(epoch=3))


def test_begin_epoch_records_the_change_with_its_reason_and_start(ws) -> None:
    save_mission(ws, make_mission())
    mission = begin_epoch(ws, "m", {"epsilon": 0.05}, starts_at=6, reason="the floor was too low", published=5)
    assert (mission.epoch, mission.epsilon) == (2, 0.05)
    assert load_mission(ws, "m") == mission
    first, second = load_epochs(ws, "m")
    assert (second.epoch, second.starts_at, second.reason) == (2, 6, "the floor was too low")
    assert second.conventions == conventions(mission) and first.conventions["epsilon"] == 0.01
    assert epoch_problems(ws, "m") == []


@pytest.mark.parametrize(
    ("changes", "starts_at", "match"),
    [
        ({"streams": ("w/other",)}, 6, "not a scoring convention"),
        ({"epsilon": 0.01}, 6, "change no convention"),
        ({"epsilon": 0.05}, 5, "after issue 5"),
        ({"epsilon": 0.05}, 1, "after issue 5"),
        ({"epsilon": 2.0}, 6, "epsilon"),
    ],
)
def test_begin_epoch_refuses(ws, changes, starts_at, match) -> None:
    save_mission(ws, make_mission())
    with pytest.raises((MissionError, ValueError), match=match):
        begin_epoch(ws, "m", changes, starts_at=starts_at, reason="r", published=5)
    assert len(load_epochs(ws, "m")) == 1 and load_mission(ws, "m") == make_mission()


def test_epochs_start_in_order(ws) -> None:
    save_mission(ws, make_mission(first_issue=1))
    begin_epoch(ws, "m", {"epsilon": 0.05}, starts_at=8, reason="r", published=None)
    with pytest.raises(MissionError, match="after epoch 2"):
        begin_epoch(ws, "m", {"tau": 3.0}, starts_at=8, reason="r", published=None)


def test_a_hand_edited_convention_is_a_problem(ws) -> None:
    save_mission(ws, make_mission())
    path = ws.missions / "m" / "mission.json"
    edited = json.loads(path.read_text()) | {"epsilon": 0.2}
    path.write_text(json.dumps(edited))
    (problem,) = epoch_problems(ws, "m")
    assert "epsilon" in problem and "new-epoch" in problem


def test_a_mission_without_an_epoch_record_is_a_problem(ws) -> None:
    save_mission(ws, make_mission())
    (ws.missions / "m" / "epochs.jsonl").unlink()
    assert epoch_problems(ws, "m") == ["missions/m: no epochs.jsonl; save the mission once to record epoch 1"]


# --- standings per epoch ---


def forecast(program: str, week: int, value: int) -> PredictionRecord:
    target = Target(stream=STREAM, jurisdiction="A", reference_week=week, horizon=0, resolution_lag=2)
    return PredictionRecord(
        mission="m", program=program, target=target, pmf=Pmf.point(value), scorer="sha256:s",
        isolation=Isolation.NONE, recorded_at=at(week),
    )


@pytest.fixture
def scored(ws):
    """Issues 1..12 published, a program forecasting origins 1..10 exactly right, as of issue 12."""
    spec = count_spec(id=STREAM, jurisdictions=("A",), support_max=99)
    for issue in range(1, 13):
        publish(ws, spec, issue, {("A", w): 5.0 for w in range(issue)}, at(issue))
    write_program(ws, "p", CONST)
    program = Registry(ws).freeze("p", at(0)).closure_hash
    for week in range(1, 11):
        RecordStore(ws).write("m", STREAM, week, program, [forecast(program, week, 5)])
    return program


def test_a_new_epoch_never_re_scores_the_old_record(ws, scored) -> None:
    save_mission(ws, make_mission(last_issue=10))
    (before,) = compute_all(ws)
    begin_epoch(ws, "m", {"epsilon": 0.3}, starts_at=13, reason="r", published=12)
    old, new = compute_all(ws)
    assert old == before  # the first epoch, scored under its own conventions, over its own origins
    assert (old.epoch, new.epoch) == (1, 2)
    assert new.streams[0].programs == () and new.streams[0].n_resolved == 0  # nothing forecast since issue 13


def test_each_epoch_scores_only_its_own_origins_under_its_own_conventions(ws, scored) -> None:
    save_mission(ws, make_mission(last_issue=10))
    begin_epoch(ws, "m", {"epsilon": 0.3}, starts_at=6, reason="r", published=None)  # as if declared before issue 6
    old, new = compute_all(ws)
    assert (old.streams[0].n_resolved, new.streams[0].n_resolved) == (5, 5)  # origins 1..5 and 6..10
    log_score = {s.epoch: s.streams[0].mixture_log_score for s in (old, new)}
    assert log_score[1] > log_score[2]  # a point forecast loses more to a larger floor


def test_standings_list_every_epoch(ws, scored) -> None:
    save_mission(ws, make_mission(last_issue=10))
    begin_epoch(ws, "m", {"tau": 4.0}, starts_at=13, reason="r", published=12)
    write_all(ws)
    assert [s["epoch"] for s in json.loads((ws.root / "standings.json").read_text())] == [1, 2]
    assert "Epoch 1." in (ws.root / "STANDINGS.md").read_text() and "Epoch 2." in (ws.root / "STANDINGS.md").read_text()


# --- the command line ---


def test_new_epoch_from_the_command_line(ws, scored, capsys) -> None:
    from scienceme.cli import main  # noqa: PLC0415

    save_mission(ws, make_mission(last_issue=10))
    root = ["--root", str(ws.root)]
    assert main([*root, "new-epoch", "--mission", "m", "--changes", '{"epsilon": 0.05}', "--starts-at", "12", "--reason", "r"]) == 1
    assert "after issue 12" in capsys.readouterr().err
    assert main([*root, "new-epoch", "--mission", "m", "--changes", "[1]", "--starts-at", "13", "--reason", "r"]) == 1
    assert main([*root, "new-epoch", "--mission", "m", "--changes", '{"epsilon": 5}', "--starts-at", "13", "--reason", "r"]) == 1
    capsys.readouterr()
    assert main([*root, "new-epoch", "--mission", "m", "--changes", '{"epsilon": 0.05}', "--starts-at", "13", "--reason", "r"]) == 0
    assert "epoch 2" in capsys.readouterr().out
    assert main([*root, "check"]) == 0
    path = ws.missions / "m" / "mission.json"
    path.write_text(json.dumps(json.loads(path.read_text()) | {"tau": 1.0}))  # a captain's hand edit
    assert main([*root, "check"]) == 1
    assert "tau" in capsys.readouterr().out


def test_a_corrupt_epoch_record_is_one_problem(ws, capsys) -> None:
    from scienceme.cli import main  # noqa: PLC0415

    save_mission(ws, make_mission())
    with (ws.missions / "m" / "epochs.jsonl").open("a") as f:
        f.write("not json\n")
    assert main(["--root", str(ws.root), "check"]) == 1
    assert capsys.readouterr().out.startswith("missions/m/epochs.jsonl: ")


def test_misnumbered_or_misordered_epochs_are_problems(ws) -> None:
    save_mission(ws, make_mission())
    begin_epoch(ws, "m", {"tau": 3.0}, starts_at=5, reason="r", published=None)
    path = ws.missions / "m" / "epochs.jsonl"
    first, second = path.read_text().splitlines()
    path.write_text(first + "\n" + json.dumps(json.loads(second) | {"epoch": 3, "starts_at": 1}) + "\n")
    problems = epoch_problems(ws, "m")
    assert any("numbered" in p for p in problems) and any("increasing" in p for p in problems)


def test_begin_epoch_needs_an_epoch_record(ws) -> None:
    save_mission(ws, make_mission())
    (ws.missions / "m" / "epochs.jsonl").unlink()
    with pytest.raises(MissionError, match="no epoch record"):
        begin_epoch(ws, "m", {"tau": 3.0}, starts_at=5, reason="r", published=None)


def test_changes_that_are_not_json_are_refused(ws, capsys) -> None:
    from scienceme.cli import main  # noqa: PLC0415

    save_mission(ws, make_mission())
    assert main(["--root", str(ws.root), "new-epoch", "--mission", "m", "--changes", "{", "--starts-at", "5", "--reason", "r"]) == 1
    assert "not JSON" in capsys.readouterr().err


def test_a_mission_without_an_epoch_record_is_still_scored_as_it_stands(ws, scored) -> None:
    save_mission(ws, make_mission(last_issue=10))
    (ws.missions / "m" / "epochs.jsonl").unlink()  # until `scienceme check` gets it fixed
    (only,) = compute_all(ws)
    assert (only.epoch, only.streams[0].n_resolved) == (1, 10)
