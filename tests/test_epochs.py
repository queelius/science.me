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


def test_rebuilt_forecasts_use_the_origin_epochs_targets(ws) -> None:
    from scienceme.predict import run_origin  # noqa: PLC0415

    save_mission(ws, make_mission(horizons=(0,)))
    mission = begin_epoch(ws, "m", {"horizons": [0, 1], "resolution_lag": 1}, 6, "r", 5)
    publish(ws, count_spec(jurisdictions=("A",)), 1, {("A", 0): 3.0}, at(1))
    write_program(ws, "p", CONST)
    Registry(ws).freeze("p", at(0))
    run_origin(ws, mission, 1, Isolation.NONE, at(7))
    assert [(r.target.horizon, r.target.resolution_lag) for r in RecordStore(ws).all("m")] == [(0, 2)]


@pytest.mark.parametrize("streams", [(), ("w/x",)])
def test_saved_streams_cannot_be_dropped(ws, streams) -> None:
    save_mission(ws, make_mission())
    with pytest.raises(MissionError, match="w/adm.*a stream once scored stays scored"):
        save_mission(ws, make_mission(streams=streams))
    assert load_mission(ws, "m").streams == (STREAM,)
    assert len(load_epochs(ws, "m")) == 1


@pytest.mark.parametrize("defect", ["missing", "extra", "invalid"])
def test_every_epoch_snapshot_is_complete_and_valid(ws, defect) -> None:
    from scienceme.mission import under  # noqa: PLC0415

    save_mission(ws, make_mission())
    begin_epoch(ws, "m", {"tau": 3.0}, 6, "r", 5)
    path = ws.missions / "m" / "epochs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    for row in rows:
        if defect == "missing":
            del row["conventions"]["epsilon"]
        elif defect == "extra":
            row["conventions"]["captain"] = "intruder"
        else:
            row["conventions"]["tau"] = -1
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))
    problems = epoch_problems(ws, "m")
    assert len(problems) == 2
    assert "epoch 1" in problems[0] and "epoch 2" in problems[1]
    for epoch in load_epochs(ws, "m"):
        with pytest.raises(MissionError if defect != "invalid" else ValueError):
            under(load_mission(ws, "m"), epoch)


@pytest.mark.parametrize("retry", [True, False])
def test_an_interrupted_epoch_must_be_retried_exactly(ws, monkeypatch, retry) -> None:
    import scienceme.mission as missions  # noqa: PLC0415

    save_mission(ws, make_mission())

    def interrupted(*args):
        raise OSError("interrupted")

    with monkeypatch.context() as patch:
        patch.setattr(missions, "_write", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            begin_epoch(ws, "m", {"epsilon": 0.05}, 6, "r", 5)
    assert len(load_epochs(ws, "m")) == 2
    assert load_mission(ws, "m").epoch == 1
    if retry:
        mission = begin_epoch(ws, "m", {"epsilon": 0.05}, 6, "r", 8)
        assert (mission.epoch, mission.epsilon) == (2, 0.05)
        assert load_mission(ws, "m") == mission
        assert len(load_epochs(ws, "m")) == 2
        following = begin_epoch(ws, "m", {"tau": 3.0}, 10, "next", 9)
        assert (following.epoch, following.epsilon, following.tau) == (3, 0.05, 3.0)
    else:
        with pytest.raises(MissionError, match="retry the interrupted change"):
            begin_epoch(ws, "m", {"tau": 3.0}, 10, "next", 9)
        assert len(load_epochs(ws, "m")) == 2
        assert load_mission(ws, "m").epoch == 1


@pytest.mark.parametrize("weeks, expected", [([5], [5, None]), ([0, 3, 5, 6, 9], [5, 9]), ([0], [0, None])])
def test_rankings_belong_to_the_epoch_at_their_as_of(ws, scored, weeks, expected) -> None:
    from scienceme.gain import Ranking, save_ranking  # noqa: PLC0415

    save_mission(ws, make_mission())
    begin_epoch(ws, "m", {"tau": 3.0}, 6, "r", 5)
    for week in weeks:
        save_ranking(ws, Ranking(mission="m", as_of=week, items=()))
    standings = compute_all(ws)
    assert [s.ranking.as_of if s.ranking is not None else None for s in standings] == expected


@pytest.mark.parametrize("week, expected", [(0, 1), (5, 1), (6, 2), (9, 2)])
def test_epoch_at_selects_the_origin_window(ws, week, expected) -> None:
    from scienceme.mission import epoch_at  # noqa: PLC0415

    save_mission(ws, make_mission())
    begin_epoch(ws, "m", {"tau": 3.0}, 6, "r", 5)
    assert epoch_at(ws, "m", week).epoch == expected


def test_epoch_at_without_a_record_uses_the_saved_mission(ws) -> None:
    from scienceme.mission import epoch_at  # noqa: PLC0415

    mission = make_mission()
    save_mission(ws, mission)
    (ws.missions / "m" / "epochs.jsonl").unlink()
    assert epoch_at(ws, "m", 0) == mission


@pytest.mark.parametrize("changes, start, reason", [
    ({"epsilon": 0.05}, 7, "r"),
    ({"epsilon": 0.05}, 6, "different"),
    ({"epsilon": 0.06}, 6, "r"),
    ({"epsilon": 2.0}, 6, "r"),
    ({}, 6, "r"),
    ({"streams": []}, 6, "r"),
])
def test_an_interrupted_change_refuses_a_different_retry(ws, changes, start, reason) -> None:
    save_mission(ws, make_mission())
    path = ws.missions / "m" / "mission.json"
    saved = path.read_text()
    begin_epoch(ws, "m", {"epsilon": 0.05}, 6, "r", 5)
    path.write_text(saved)
    with pytest.raises(MissionError, match="retry the interrupted change"):
        begin_epoch(ws, "m", changes, start, reason, 5)
    assert path.read_text() == saved
    assert len(load_epochs(ws, "m")) == 2


def test_a_disagreement_with_epoch_one_refuses_a_transition(ws) -> None:
    save_mission(ws, make_mission())
    path = ws.missions / "m" / "mission.json"
    path.write_text(make_mission(epsilon=0.2).model_dump_json())
    with pytest.raises(MissionError, match="retry the interrupted change"):
        begin_epoch(ws, "m", {"tau": 3.0}, 6, "r", 5)


@pytest.mark.parametrize("changes", [{"horizons": (0,), "tau": 2.0}, {"epsilon": "0.05"}])
def test_retry_accepts_the_original_changes_with_unchanged_fields(ws, changes) -> None:
    save_mission(ws, make_mission())
    path = ws.missions / "m" / "mission.json"
    saved = path.read_text()
    following = begin_epoch(ws, "m", changes, 6, "r", 5)
    path.write_text(saved)
    assert begin_epoch(ws, "m", changes, 6, "r", 5) == following
    assert len(load_epochs(ws, "m")) == 2
