"""The `scienceme` command line: how an agent loop or CI drives the platform.

Every command works on one workspace (`--root`, default the current directory).  Exit codes: 0 for success,
1 for a domain error, a failed `check` or stale standings, and 2 for a usage error.  A domain error prints one
line to stderr and never a traceback; anything else is a bug and propagates.

This is the only library module that reads the wall clock (`_now`): everything below it takes `now`.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from scienceme.archive import Archive, ArchiveError
from scienceme.claims import claim_standings
from scienceme.gain import Ranking, load_latest_ranking, rank_wanted, save_ranking
from scienceme.manifest import ClosureError, PairError, load_manifest
from scienceme.mission import Mission, MissionError, list_missions, load_mission, load_wanted
from scienceme.model import Isolation
from scienceme.predict import OriginReport, run_all, run_origin
from scienceme.readback import ReadbackError, packet
from scienceme.record import RecordError
from scienceme.registry import Freeze, Registry, RegistryError
from scienceme.scoring import resolve
from scienceme.standings import JSON_FILE, MARKDOWN_FILE, check_all, published_as_of, write_all
from scienceme.weights import run_mixture
from scienceme.worker import WorkerError
from scienceme.workspace import Workspace, WriteOnceError

Handler = Callable[[Workspace, argparse.Namespace], int]

# What a command reports as a one-line error.  No common base class, so they are listed.
_DOMAIN_ERRORS = (
    RegistryError,
    ArchiveError,
    MissionError,
    PairError,
    ClosureError,
    RecordError,
    ReadbackError,
    WriteOnceError,
    WorkerError,
    ValidationError,
    FileNotFoundError,
)


def _now() -> datetime:
    """The wall clock, as an aware UTC datetime: the one place the platform reads it."""
    return datetime.now(UTC)


def _describe(error: Exception) -> str:
    """`error` on one line.  A pydantic error is listed field by field."""
    if isinstance(error, ValidationError):
        fields = "; ".join(f"{'.'.join(map(str, e['loc'])) or '(document)'}: {e['msg']}" for e in error.errors())
        text = f"{error.title}: {fields}"
    else:
        text = str(error)
    return " ".join(text.split()) or type(error).__name__


def _fail(message: str) -> int:
    """Print `message` as an error on stderr and return the domain-error exit code."""
    print(f"scienceme: error: {message}", file=sys.stderr)
    return 1


# --- lookups ---


def _mission(ws: Workspace, name: str) -> Mission:
    """The mission `name`; MissionError when the workspace has none."""
    try:
        return load_mission(ws, name)
    except FileNotFoundError:
        raise MissionError(f"no mission {name!r} in {ws.missions}") from None


def _frozen(registry: Registry, name: str) -> Freeze:
    """The freeze recorded under `name`; RegistryError when there is none."""
    freeze = registry.by_name(name)
    if freeze is None:
        raise RegistryError(f"{name!r} is not frozen")
    return freeze


# --- commands ---


def _freeze(ws: Workspace, args: argparse.Namespace) -> int:
    record = Registry(ws).freeze(args.name, _now())
    print(f"frozen {record.name} {record.closure_hash} at {record.frozen_at.isoformat()}")
    return 0


def _withdraw(ws: Workspace, args: argparse.Namespace) -> int:
    registry = Registry(ws)
    freeze = _frozen(registry, args.name)
    record = registry.withdraw(freeze.closure_hash, _now(), args.reason)
    print(f"withdrew {freeze.name} {freeze.closure_hash} at {record.at.isoformat()}")
    return 0


def _origin_lines(reports: Sequence[OriginReport], names: dict[str, str]) -> Iterator[str]:
    """One line per run and per skip, programs by name."""
    for report in reports:
        week = report.reference_week
        for run in report.ran:
            yield f"run week={week} stream={run.stream} program={names[run.program]} targets={run.n_targets}"
        for skip in report.skipped:
            yield f"skip week={week} stream={skip.stream} program={names[skip.program]} reason={skip.reason}"


def _predict(ws: Workspace, args: argparse.Namespace) -> int:
    mission = _mission(ws, args.mission)
    now = _now()
    if args.all:
        reports = run_all(ws, mission, args.isolation, now)
    else:
        reports = [run_origin(ws, mission, args.issue, args.isolation, now)]
    names = {h: f.name for h, f in Registry(ws).freezes().items()}
    lines = list(_origin_lines(reports, names))
    print("\n".join(lines) if lines else f"nothing to predict for mission {mission.name!r}")
    return 0


def _rank_wanted(ws: Workspace, args: argparse.Namespace) -> int:
    mission = _mission(ws, args.mission)
    archive = Archive(ws)
    specs = archive.specs()
    as_of = published_as_of(archive, mission, specs)
    if as_of is None:
        print(f"nothing is published for mission {mission.name!r}; nothing to rank")
        return 0
    latest = load_latest_ranking(ws, mission.name)
    if latest is not None and latest.as_of == as_of:  # fail before running every program, not after
        raise WriteOnceError(f"refusing to overwrite the ranking of mission {mission.name!r} at issue {as_of}")
    resolution = resolve(ws, mission, as_of)
    advantages = run_mixture(resolution.resolved, mission.tau, mission.half_life_weeks, as_of)
    claims = claim_standings(ws, mission, resolution, {s.id: s for s in specs})
    items = rank_wanted(ws, mission, as_of, _now(), args.isolation, advantages, claims)
    save_ranking(ws, Ranking(mission=mission.name, as_of=as_of, items=tuple(items)))
    if not items:
        print(f"no open wanted items for mission {mission.name!r}")
    for item in items:
        print(f"{item.item} priority={item.priority:.6g} gain={item.gain:.6g}")
    return 0


def _standings(ws: Workspace, args: argparse.Namespace) -> int:
    if not args.check:
        write_all(ws)
        print(f"wrote {JSON_FILE} and {MARKDOWN_FILE}")
        return 0
    if check_all(ws):
        print("standings are current")
        return 0
    return _fail(f"standings are stale: run `scienceme standings` to regenerate {JSON_FILE} and {MARKDOWN_FILE}")


def _readback_packet(ws: Workspace, args: argparse.Namespace) -> int:
    mission = _mission(ws, args.mission)
    freeze = _frozen(Registry(ws), args.name)
    print(packet(ws, freeze.closure_hash, mission.claims))
    return 0


def _problems(ws: Workspace) -> Iterator[str]:
    """One line per thing wrong with the workspace's programs, registry and missions."""
    if ws.programs.is_dir():
        for directory in sorted(d for d in ws.programs.iterdir() if d.is_dir()):
            try:
                load_manifest(directory)
            except (OSError, ValueError) as e:
                yield f"programs/{directory.name}: {_describe(e)}"
    registry = Registry(ws)
    try:
        frozen = list(registry.freezes())
    except (OSError, ValueError) as e:
        yield f"registry: {_describe(e)}"
        frozen = []
    for closure_hash in frozen:
        try:
            registry.verify(closure_hash)
        except RegistryError as e:
            yield _describe(e)
    for name in list_missions(ws):
        try:
            load_mission(ws, name)
        except (OSError, ValueError) as e:
            yield f"missions/{name}: {_describe(e)}"
        try:
            load_wanted(ws, name)
        except (OSError, ValueError) as e:
            yield f"missions/{name}/wanted.jsonl: {_describe(e)}"


def _check(ws: Workspace, args: argparse.Namespace) -> int:
    problems = list(_problems(ws))
    print("\n".join(problems) if problems else "ok")
    return 1 if problems else 0


# --- parsing ---


def _isolation(text: str) -> Isolation:
    """An `Isolation` by its value; the error lists the valid ones."""
    try:
        return Isolation(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not one of {', '.join(Isolation)}") from None


def _add_isolation(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--isolation",
        type=_isolation,
        default=Isolation.CONTAINER,
        metavar="{" + ",".join(Isolation) + "}",
        help="how strongly to isolate programs (default: container)",
    )


def build_parser() -> argparse.ArgumentParser:
    """The argument parser: a global `--root` and one subcommand per command."""
    parser = argparse.ArgumentParser(prog="scienceme", description="Drive a scienceme workspace.")
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="the workspace directory (default: the current directory)"
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, handler: Handler, summary: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=summary, description=summary)
        sub.set_defaults(handler=handler)
        return sub

    freeze = command("freeze", _freeze, "freeze programs/NAME in the registry")
    freeze.add_argument("name", metavar="NAME")

    withdraw = command("withdraw", _withdraw, "end a frozen program's eligibility, keeping its freeze")
    withdraw.add_argument("name", metavar="NAME")
    withdraw.add_argument("--reason", required=True, metavar="TEXT")

    predict = command("predict", _predict, "run the eligible programs on a reference week (or on every published week)")
    predict.add_argument("--mission", required=True, metavar="M")
    which = predict.add_mutually_exclusive_group(required=True)
    which.add_argument("--issue", type=int, metavar="N", help="the reference week to run")
    which.add_argument("--all", action="store_true", help="every week from the first issue to the latest published")
    _add_isolation(predict)

    rank = command("rank-wanted", _rank_wanted, "rank the wanted list by expected information gain and save it")
    rank.add_argument("--mission", required=True, metavar="M")
    _add_isolation(rank)

    standings = command("standings", _standings, "write standings.json and STANDINGS.md")
    standings.add_argument("--check", action="store_true", help="exit 1 if the files are not what would be written")

    readback = command("readback-packet", _readback_packet, "print the blind read-back packet of a frozen program")
    readback.add_argument("name", metavar="NAME")
    readback.add_argument("--mission", required=True, metavar="M")

    command("check", _check, "check that every program, mission and wanted list loads and every freeze verifies")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line `argv` (default `sys.argv[1:]`) and return its exit code."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
        if not args.root.is_dir():
            parser.error(f"--root {args.root} is not a directory")
    except SystemExit as e:  # argparse exits for a usage error (2) and for --help (0)
        return int(e.code or 0)
    try:
        return args.handler(Workspace(args.root), args)
    except _DOMAIN_ERRORS as e:
        return _fail(_describe(e))
