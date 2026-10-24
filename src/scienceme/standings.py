"""Standings: the generated, committed account of which programs the evidence favors.

`compute` turns one mission's record into a `Standings`; `render` formats a list of them as Markdown;
`write_all` writes `standings.json` and `STANDINGS.md` at the workspace root, and `check_all` says whether
those files are what `write_all` would write now.  A stale file fails the check, so everything here is a pure
function of the workspace: no wall-clock, and every ordering is explicit.

The forecast records are a cache kept outside git (spec 4.7): `scienceme predict --all` rebuilds them from
the registry and the archive, forecast for forecast.  The record only grows, so both functions refuse a
checkout whose record holds fewer forecasts for a program than the committed `standings.json` counts
(`IncompleteRecordError`), rather than writing or passing standings over a partial cache.

A stream's *awake* programs are the ones with any record on it (a forecast or an unscored run) that were
never withdrawn.  Advantages come from one mixture run over the whole mission, so a program carries the same
advantage in every table; its weight is the softmax of that advantage over the programs awake on the stream.
Coverage and `n_predicted` are the program's across the mission, as for claims.

Every float in a `Standings` is rounded to 12 significant digits as it is built (`_quantized`).  The weights,
advantages and log scores come from numpy's exp and log, which can differ in the last bit between CPU
families; the rounding keeps that noise out of the committed files, so `check_all` can stay an exact byte
comparison.  Decisions taken from a float (the regime flag, the top set) use the rounded value.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import TypeAdapter

from scienceme.archive import Archive
from scienceme.calibration import Calibration, calibration
from scienceme.claims import ClaimStanding, claim_standings
from scienceme.gain import Ranking, load_latest_ranking
from scienceme.manifest import program_files
from scienceme.mission import Mission, list_missions, load_mission, mission_streams
from scienceme.model import Frozen, StreamKind, StreamSpec
from scienceme.readback import ReadbackFlag, load_readback
from scienceme.readback import flags as readback_flags
from scienceme.record import RecordError
from scienceme.registry import Freeze, Registry, RegistryError, Withdrawal
from scienceme.scoring import Resolution, ResolvedTarget, resolve
from scienceme.weights import Advantages, normalized_weights, regime_tv, run_mixture
from scienceme.worker import scorer_hash
from scienceme.workspace import Workspace

JSON_FILE = "standings.json"
MARKDOWN_FILE = "STANDINGS.md"
# The indicators look at the fewest programs holding this share of the cumulative weight.
_TOP_MASS = 0.9
_WANTED_SHOWN = 10
_ENCODING = "utf-8"
_SIGNIFICANT_DIGITS = 12
_SHORTFALLS_SHOWN = 3


class IncompleteRecordError(RecordError):
    """This checkout's forecast record holds fewer forecasts for a program than the committed standings count."""


class ProgramStanding(Frozen):
    """One program on one stream.

    `program` is the closure hash.  Weights are over the programs awake on the stream; advantages are the
    mission's (nats over the mixture).  `n_predicted` and `coverage = predicted / (predicted + unscored)` count
    the program's records across the mission.  `length_bytes` is the size of every file in its closure and
    `flags` are the read-back flags, sorted by value.
    """

    program: str
    name: str
    lineage: str
    w_cumulative: float
    w_current: float
    advantage_cumulative: float
    advantage_current: float
    n_predicted: int
    coverage: float
    length_bytes: int
    calibration: Calibration
    flags: tuple[ReadbackFlag, ...]


class StreamStanding(Frozen):
    """One COUNT stream: its awake programs (best cumulative weight first), the mixture's record on it, and the regime flag.

    `regime_tv` is the total variation between the cumulative and current weights; `regime_flag` says it
    exceeds the mission's threshold.  `n_resolved` and `n_pending` count targets, resolved and still pending;
    `n_withdrawn` counts the withdrawn programs with records on the stream, which are not shown.
    """

    stream: str
    programs: tuple[ProgramStanding, ...]
    regime_tv: float
    regime_flag: bool
    mixture_calibration: Calibration
    mixture_log_score: float
    n_resolved: int
    n_pending: int
    n_withdrawn: int


class Indicators(Frozen):
    """Health of the field on the mission's first base COUNT stream, over its top set of programs by cumulative weight.

    Zero when the stream has no programs.  `lineage_entropy` is in nats.
    """

    interface_weight_share: float
    readback_clean_share: float
    lineage_entropy: float


class Standings(Frozen):
    """Where a mission stands as of issue `as_of`.

    `program_names` maps the closure hash of every program mentioned here (in the streams, the claims'
    pairs and the ranking) to its name, since the claims and the ranking carry hashes.
    """

    mission: str
    epoch: int
    as_of: int
    scorer: str
    streams: tuple[StreamStanding, ...]
    claims: tuple[ClaimStanding, ...]
    ranking: Ranking | None
    indicators: Indicators
    program_names: dict[str, str]


_STANDINGS_LIST = TypeAdapter(list[Standings])


def _round[T](value: T) -> T:
    """`value` with every float in it (at any depth of dicts, lists and tuples) rounded to 12 significant digits.

    Integers, booleans, strings and None are untouched, and rounding twice changes nothing more.
    """
    match value:
        case float():
            return float(f"{value:.{_SIGNIFICANT_DIGITS}g}")
        case dict():
            return {k: _round(v) for k, v in value.items()}
        case list() | tuple():
            return type(value)(_round(v) for v in value)
        case _:
            return value


def _quantized[M: Frozen](model: M) -> M:
    """`model` with every float in it rounded by `_round`."""
    return type(model).model_validate(_round(model.model_dump()))


@dataclass(frozen=True)
class _Facts:
    """What the registry and the program directory say about a frozen program, whatever the stream."""

    name: str
    lineage: str
    has_interface: bool
    length_bytes: int
    flags: tuple[ReadbackFlag, ...]


def _facts(registry: Registry, program: str, name: str) -> _Facts:
    """Facts about the frozen `program`.  RegistryError when any member of its closure changed since its freeze."""
    members = registry.closure(program)
    for member in members:
        registry.verify(member)
    manifest = registry.manifest(program)
    length = 0
    for member in members:
        directory = registry.program_dir(member)
        length += sum((directory / rel).stat().st_size for rel in program_files(directory))
    raised = readback_flags(manifest, load_readback(registry.program_dir(program)))
    return _Facts(
        name=name,
        lineage=manifest.author_lineage,
        has_interface=bool(manifest.interface),
        length_bytes=length,
        flags=tuple(sorted(raised, key=lambda f: f.value)),
    )


def _order(program: ProgramStanding) -> tuple[float, str]:
    """Best cumulative weight first, then by name."""
    return (-program.w_cumulative, program.name)


def _count_streams(mission: Mission, specs: Sequence[StreamSpec]) -> list[StreamSpec]:
    """The mission's COUNT streams and their arms, sorted by id."""
    return [s for s in mission_streams(mission, specs) if s.kind is StreamKind.COUNT]


def _program_standing(
    p: str,
    facts: _Facts,
    resolution: Resolution,
    adv: Advantages,
    resolved: Sequence[ResolvedTarget],
    w_cum: Mapping[str, float],
    w_cur: Mapping[str, float],
) -> ProgramStanding:
    predicted, unscored = resolution.predicted[p], resolution.unscored[p]
    return _quantized(
        ProgramStanding(
            program=p,
            name=facts.name,
            lineage=facts.lineage,
            w_cumulative=w_cum[p],
            w_current=w_cur[p],
            advantage_cumulative=adv.cumulative.get(p, 0.0),
            advantage_current=adv.current.get(p, 0.0),
            n_predicted=predicted,
            coverage=predicted / (predicted + unscored),
            length_bytes=facts.length_bytes,
            calibration=calibration([k.scores[p] for k in resolved if p in k.scores]),
            flags=facts.flags,
        )
    )


def _stream_standing(
    mission: Mission,
    stream: str,
    resolution: Resolution,
    adv: Advantages,
    awake: Sequence[str],
    n_withdrawn: int,
    facts: Mapping[str, _Facts],
) -> StreamStanding:
    w_cum = normalized_weights(adv.cumulative, awake, mission.tau)
    w_cur = normalized_weights(adv.current, awake, mission.tau)
    resolved = [k for k in resolution.resolved if k.target.stream == stream]
    mixture = [step.score for step in adv.steps if step.target.stream == stream]
    programs = sorted(
        (_program_standing(p, facts[p], resolution, adv, resolved, w_cum, w_cur) for p in awake), key=_order
    )
    tv = _round(regime_tv(w_cum, w_cur))
    return _quantized(
        StreamStanding(
            stream=stream,
            programs=tuple(programs),
            regime_tv=tv,
            regime_flag=tv > mission.regime_flag_tv,
            mixture_calibration=calibration(mixture),
            mixture_log_score=sum((score.log_p for score in mixture), 0.0),
            n_resolved=len(resolved),
            n_pending=resolution.pending_targets_by_stream.get(stream, 0),
            n_withdrawn=n_withdrawn,
        )
    )


def _top_set(programs: Sequence[ProgramStanding]) -> list[ProgramStanding]:
    """The fewest programs, by cumulative weight, whose weights reach `_TOP_MASS`."""
    top: list[ProgramStanding] = []
    mass = 0.0
    for program in sorted(programs, key=_order):
        top.append(program)
        mass += program.w_cumulative
        if mass >= _TOP_MASS or math.isclose(mass, _TOP_MASS):
            break
    return top


def _indicators(programs: Sequence[ProgramStanding], facts: Mapping[str, _Facts]) -> Indicators:
    """The indicators over the top set of `programs`; all zero when there are none."""
    top = _top_set(programs)
    if not top:
        return Indicators(interface_weight_share=0.0, readback_clean_share=0.0, lineage_entropy=0.0)
    mass = sum(p.w_cumulative for p in top)
    by_lineage: defaultdict[str, float] = defaultdict(float)
    for p in top:
        by_lineage[p.lineage] += p.w_cumulative
    shares = [by_lineage[lineage] / mass for lineage in sorted(by_lineage)]
    return _quantized(
        Indicators(
            interface_weight_share=sum(p.w_cumulative for p in top if facts[p.program].has_interface) / mass,
            readback_clean_share=sum(1 for p in top if not p.flags) / len(top),
            lineage_entropy=sum(-q * math.log(q) for q in shares if q > 0),
        )
    )


def _first_base_stream(mission: Mission, specs: Sequence[StreamSpec]) -> str | None:
    """The first stream the mission names that is a COUNT stream without an intervention."""
    by_id = {s.id: s for s in specs}
    for stream in mission.streams:
        spec = by_id.get(stream)
        if spec is not None and spec.kind is StreamKind.COUNT and spec.intervention is None:
            return stream
    return None


def _ranking_programs(ranking: Ranking | None) -> set[str]:
    """Every closure hash a ranking mentions."""
    if ranking is None:
        return set()
    return {h for item in ranking.items for h in (*item.supporting, *item.failed)}


def _freeze(freezes: Mapping[str, Freeze], program: str) -> Freeze:
    """The freeze of `program`; RegistryError when it is not frozen."""
    try:
        return freezes[program]
    except KeyError:
        raise RegistryError(f"{program} is not frozen") from None


def _withdrawn(registry: Registry) -> set[str]:
    """The closure hashes of every withdrawn program."""
    return {e.closure_hash for e in registry.entries() if isinstance(e, Withdrawal)}


def compute(ws: Workspace, mission: Mission, as_of: int) -> Standings:
    """The standings of `mission` as of issue `as_of`.

    RegistryError when a program was edited after it was frozen (the claims read every frozen manifest, and
    each program shown is verified), or when a program with records or in a pair or ranking is not frozen.
    """
    archive, registry = Archive(ws), Registry(ws)
    specs = archive.specs()
    resolution = resolve(ws, mission, as_of)
    adv = run_mixture(resolution.resolved, mission.tau, mission.half_life_weeks, as_of)
    claims = claim_standings(ws, mission, resolution, {s.id: s for s in specs})
    ranking = load_latest_ranking(ws, mission.name)
    freezes = registry.freezes()
    withdrawn = _withdrawn(registry)

    facts: dict[str, _Facts] = {}
    streams = []
    for spec in _count_streams(mission, specs):
        recorded = resolution.programs_by_stream.get(spec.id, ())
        awake = [p for p in recorded if p not in withdrawn]
        for p in awake:
            if p not in facts:
                facts[p] = _facts(registry, p, _freeze(freezes, p).name)
        streams.append(_stream_standing(mission, spec.id, resolution, adv, awake, len(recorded) - len(awake), facts))

    base = _first_base_stream(mission, specs)
    base_programs = next((s.programs for s in streams if s.stream == base), ())
    mentioned = (
        set(facts)
        | {h for c in claims for pair in c.pairs for h in (pair.asserts, pair.denies)}
        | _ranking_programs(ranking)
    )
    return _quantized(
        Standings(
            mission=mission.name,
            epoch=mission.epoch,
            as_of=as_of,
            scorer=scorer_hash(),
            streams=tuple(streams),
            claims=tuple(claims),
            ranking=ranking,
            indicators=_indicators(base_programs, facts),
            program_names={h: _freeze(freezes, h).name for h in sorted(mentioned)},
        )
    )


# --- rendering ---


def _fmt(x: float, places: int) -> str:
    """`x` to `places` decimals, never as a negative zero."""
    text = f"{x:.{places}f}"
    return text.lstrip("-") if float(text) == 0 else text


def _opt(x: float | None, places: int = 2) -> str:
    return "n/a" if x is None else _fmt(x, places)


def _cell(text: str) -> str:
    """`text` safe inside a table cell: one line, no bare pipes."""
    return " ".join(text.splitlines()).replace("|", "\\|")


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    lines.extend("| " + " | ".join(_cell(c) for c in row) + " |" for row in rows)
    return "\n".join(lines)


def _stream_block(stream: StreamStanding) -> list[str]:
    heading = f"### Stream {stream.stream}"
    if not stream.programs:
        return [heading, "No active programs." if stream.n_withdrawn else "No forecasts yet."]
    regime = "regime shift flagged" if stream.regime_flag else "stable"
    summary = (
        f"Resolved {stream.n_resolved}, pending {stream.n_pending}. "
        f"Mixture log score {_fmt(stream.mixture_log_score, 2)} nats, "
        f"90% coverage {_opt(stream.mixture_calibration.coverage_90)}. "
        f"Regime TV {_fmt(stream.regime_tv, 3)}: {regime}."
    )
    rows = [
        [
            p.name,
            _fmt(p.w_cumulative, 3),
            _fmt(p.w_current, 3),
            _fmt(p.advantage_cumulative, 2),
            str(p.n_predicted),
            _fmt(p.coverage, 2),
            _opt(p.calibration.coverage_90),
            ", ".join(f.value for f in p.flags) or "-",
        ]
        for p in sorted(stream.programs, key=_order)
    ]
    header = ["program", "w cum", "w cur", "advantage", "n", "coverage", "cov90", "flags"]
    return [heading, summary, _table(header, rows)]


def _claims_block(s: Standings) -> list[str]:
    if not s.claims:
        return ["### Claims", "No claims."]
    rows = []
    for claim in s.claims:
        head = [claim.claim, claim.statement, claim.verdict.value]
        if not claim.pairs:
            rows.append([*head, "-", "-", "-", "-", "-"])
        for i, pair in enumerate(claim.pairs):
            rows.append(
                [
                    *(head if i == 0 else ["", "", ""]),
                    s.program_names[pair.asserts],
                    s.program_names[pair.denies],
                    _fmt(pair.delta_nats, 2),
                    str(pair.n_targets),
                    pair.verdict.value,
                ]
            )
    header = ["claim", "statement", "verdict", "asserts", "denies", "delta (nats)", "targets", "pair verdict"]
    return ["### Claims", _table(header, rows)]


def _names(s: Standings, programs: Sequence[str]) -> str:
    """The names of `programs` (closure hashes), comma-separated; "-" for none."""
    return ", ".join(s.program_names[h] for h in programs) or "-"


def _wanted_block(s: Standings) -> list[str]:
    heading = f"### Wanted (top {_WANTED_SHOWN})"
    if s.ranking is None:
        return [heading, "No wanted ranking yet."]
    if not s.ranking.items:
        return [heading, f"No open wanted items as of week {s.ranking.as_of}."]
    rows = [
        [
            str(rank),
            item.item,
            _fmt(item.priority, 2),
            _fmt(item.gain, 2),
            _fmt(item.cost, 2),
            _names(s, item.supporting),
            _names(s, item.failed),
        ]
        for rank, item in enumerate(s.ranking.items[:_WANTED_SHOWN], start=1)
    ]
    header = ["rank", "item", "priority", "gain (nats)", "cost", "supporting", "failed"]
    return [heading, f"Ranked as of week {s.ranking.as_of}.", _table(header, rows)]


def _indicators_block(indicators: Indicators) -> list[str]:
    basis = "On the mission's first base count stream, over the programs holding 90% of the cumulative weight."
    bullets = [
        f"- Interface weight share: {_fmt(indicators.interface_weight_share, 3)}",
        f"- Read-back clean share: {_fmt(indicators.readback_clean_share, 2)}",
        f"- Lineage entropy: {_fmt(indicators.lineage_entropy, 2)} nats",
    ]
    return ["### Indicators", basis, "\n".join(bullets)]


def _mission_block(s: Standings) -> list[str]:
    blocks = [f"## Mission {s.mission}", f"Epoch {s.epoch}. As of week {s.as_of}. Scorer {s.scorer}."]
    for stream in s.streams:
        blocks.extend(_stream_block(stream))
    return [*blocks, *_claims_block(s), *_wanted_block(s), *_indicators_block(s.indicators)]


def render(all_standings: Sequence[Standings]) -> str:
    """The Markdown of `all_standings`, in the order given.  Deterministic: it holds no time, only the data."""
    blocks = ["# Standings", "Generated by `scienceme`. Do not edit by hand."]
    if not all_standings:
        blocks.append("No mission has published data.")
    for s in all_standings:
        blocks.extend(_mission_block(s))
    return "\n\n".join(blocks) + "\n"


# --- the generated files ---


def published_as_of(archive: Archive, mission: Mission, specs: Sequence[StreamSpec]) -> int | None:
    """The largest issue published on any of the mission's COUNT streams; None when nothing is."""
    return max((i for s in _count_streams(mission, specs) for i in archive.issues(s.id)), default=None)


def _all_standings(ws: Workspace) -> list[Standings]:
    """The standings of every mission with published data, in mission-name order."""
    archive = Archive(ws)
    specs = archive.specs()
    standings = []
    for mission in (load_mission(ws, name) for name in list_missions(ws)):
        as_of = published_as_of(archive, mission, specs)
        if as_of is not None:
            standings.append(compute(ws, mission, as_of))
    return standings


def _previous(ws: Workspace) -> list[Standings]:
    """The standings in the workspace's `standings.json`; none when it is missing or not a standings file."""
    try:
        return _STANDINGS_LIST.validate_json((ws.root / JSON_FILE).read_bytes())
    except (OSError, ValueError):
        return []


def _shortfalls(previous: Sequence[Standings], current: Sequence[Standings], withdrawn: set[str]) -> list[str]:
    """One line per program that `previous` counts more forecasts for than `current`, sorted.

    A program withdrawn since is no longer shown, so it is not compared.
    """
    have = {(s.mission, p.program): p.n_predicted for s in current for st in s.streams for p in st.programs}
    lines = {
        f"{s.mission}: {p.name} has {have.get((s.mission, p.program), 0)} of its {p.n_predicted} forecasts"
        for s in previous
        for st in s.streams
        for p in st.programs
        if p.program not in withdrawn and have.get((s.mission, p.program), 0) < p.n_predicted
    }
    return sorted(lines)


def _outputs(ws: Workspace) -> dict[str, bytes]:
    """The bytes of each generated file, by file name.

    IncompleteRecordError when they would count fewer forecasts for a program than the `standings.json` they
    replace: the record only grows, so the local cache of it is partial.
    """
    standings = _all_standings(ws)
    short = _shortfalls(_previous(ws), standings, _withdrawn(Registry(ws)))
    if short:
        shown = "; ".join(short[:_SHORTFALLS_SHOWN])
        more = f"; and {len(short) - _SHORTFALLS_SHOWN} more" if len(short) > _SHORTFALLS_SHOWN else ""
        raise IncompleteRecordError(
            f"the forecast record here is incomplete ({shown}{more}): rebuild it with `scienceme predict --all`"
        )
    return {
        JSON_FILE: _STANDINGS_LIST.dump_json(standings, indent=2) + b"\n",
        MARKDOWN_FILE: render(standings).encode(_ENCODING),
    }


def write_all(ws: Workspace) -> None:
    """Write `standings.json` and `STANDINGS.md` at the workspace root, replacing any earlier ones.

    IncompleteRecordError, writing nothing, when the local forecast record is partial (`_outputs`).
    """
    for name, data in _outputs(ws).items():
        (ws.root / name).write_bytes(data)


def check_all(ws: Workspace) -> bool:
    """True when both generated files exist and are byte-for-byte what `write_all` would write now.

    IncompleteRecordError when the local forecast record is partial, since then there is nothing to compare.
    """
    for name, data in _outputs(ws).items():
        path = ws.root / name
        if not path.is_file() or path.read_bytes() != data:
            return False
    return True
