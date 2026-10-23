import pytest
from helpers import CONST, at, count_spec, make_mission, rt, write_program

from scienceme.claims import (
    ClaimStanding,
    PairStanding,
    Verdict,
    claim_standings,
    find_pair_sets,
    find_pairs,
    pair_standing,
    summarize,
)
from scienceme.manifest import PairDecl, Tag, closure_hash, load_manifest
from scienceme.mission import Claim
from scienceme.model import TargetFilter
from scienceme.registry import Freeze, Registry, RegistryError
from scienceme.scoring import Resolution
from scienceme.workspace import append_jsonl

SPECS = {"w/adm": count_spec()}


def test_delta_counts_shared_in_scope_targets_only():
    claim = Claim(id="school", statement="s", scope=TargetFilter(jurisdictions=("A",)))
    ks = [
        rt(1, 2, {"a": 0.0, "d": -3.1}),
        rt(2, 3, {"a": 0.0, "d": -3.1}),
        rt(3, 4, {"a": 0.0, "d": -50.0}, j="B"),
        rt(4, 5, {"a": 0.0}),
    ]
    p = pair_standing(claim, "a", "d", ks, {"w/adm": count_spec(jurisdictions=("A", "B"))}, tau=2.0, threshold=3.0)
    assert (p.delta_nats, p.n_targets, p.verdict) == (pytest.approx(6.2), 2, Verdict.SUPPORTS)
    assert (p.claim, p.asserts, p.denies) == ("school", "a", "d")


@pytest.mark.parametrize(
    "delta,verdict",
    [
        (6.2, Verdict.SUPPORTS),
        (6.0, Verdict.SUPPORTS),
        (-6.2, Verdict.CONTRADICTS),
        (-6.0, Verdict.CONTRADICTS),
        (5.8, Verdict.INSUFFICIENT),
        (-5.8, Verdict.INSUFFICIENT),
        (0.0, Verdict.INSUFFICIENT),
    ],
)
def test_thresholds(delta, verdict):
    claim = Claim(id="school", statement="s", scope=TargetFilter())
    p = pair_standing(claim, "a", "d", [rt(1, 2, {"a": 0.0, "d": -delta})], SPECS, tau=2.0, threshold=3.0)
    assert (p.delta_nats, p.verdict) == (pytest.approx(delta), verdict)


def test_no_shared_targets_is_insufficient_with_zero_delta():
    claim = Claim(id="school", statement="s", scope=TargetFilter())
    p = pair_standing(claim, "a", "d", [rt(1, 2, {"a": 0.0}), rt(2, 3, {"d": 0.0})], SPECS, tau=2.0, threshold=3.0)
    assert (p.delta_nats, p.n_targets, p.verdict) == (0.0, 0, Verdict.INSUFFICIENT)


def test_scope_filters_by_stream_role_and_horizon():
    claim = Claim(id="c", statement="s", scope=TargetFilter(roles=("admissions",), horizons=(1,)))
    ks = [rt(1, 3, {"a": 0.0, "d": -4.0}, h=1), rt(2, 4, {"a": 0.0, "d": -40.0}, h=0)]
    p = pair_standing(claim, "a", "d", ks, SPECS, tau=2.0, threshold=3.0)
    assert (p.delta_nats, p.n_targets) == (pytest.approx(4.0), 1)
    other_role = Claim(id="c", statement="s", scope=TargetFilter(roles=("ed-visits",)))
    assert pair_standing(other_role, "a", "d", ks, SPECS, tau=2.0, threshold=3.0).n_targets == 0


def test_summarize():
    s, c, i = (
        PairStanding(claim="x", asserts="a", denies="d", delta_nats=0, n_targets=1, verdict=v)
        for v in (Verdict.SUPPORTS, Verdict.CONTRADICTS, Verdict.INSUFFICIENT)
    )
    assert summarize([s, i]) == Verdict.SUPPORTS and summarize([s, c]) == Verdict.MIXED
    assert summarize([i]) == summarize([]) == Verdict.INSUFFICIENT
    assert summarize([c, i, c]) == Verdict.CONTRADICTS
    assert summarize([s, s]) == Verdict.SUPPORTS
    assert summarize([s, c, i]) == Verdict.MIXED


def test_verdict_values():
    assert [v.value for v in Verdict] == ["supports", "contradicts", "insufficient evidence", "mixed"]


def _freeze_pair(ws, a="a", d="d", claim="school", from_side="d", start=0):
    """Freeze program `a` (asserts `claim`) and `d` (denies it); `from_side` declares the pair.  Returns (ha, hd)."""
    first, second = (a, d) if from_side == "d" else (d, a)
    stance = {a: Tag.ASSERTS, d: Tag.DENIES}
    registry = Registry(ws)
    write_program(ws, first, CONST + f"#{first}\n", tags={claim: stance[first]})
    h_first = registry.freeze(first, at(start)).closure_hash
    write_program(
        ws,
        second,
        CONST + f"#{second}\n",
        tags={claim: stance[second]},
        pairs=(PairDecl(claim=claim, partner=h_first),),
    )
    h_second = registry.freeze(second, at(start + 1)).closure_hash
    return (h_first, h_second) if from_side == "d" else (h_second, h_first)


@pytest.mark.parametrize("from_side", ["d", "a"])
def test_find_pairs_orients_by_tags_whichever_side_declares(ws, from_side):
    ha, hd = _freeze_pair(ws, from_side=from_side)
    assert find_pairs(ws, "school") == [(ha, hd)]


def test_find_pairs_is_empty_without_pairs_or_registry_entries(ws):
    assert find_pairs(ws, "school") == []
    write_program(ws, "p", CONST, tags={"school": Tag.ASSERTS})
    Registry(ws).freeze("p", at(0))
    assert find_pairs(ws, "school") == []


def test_find_pairs_only_for_the_claim(ws):
    ha, hd = _freeze_pair(ws, claim="school")
    assert find_pairs(ws, "school") == [(ha, hd)]
    assert find_pairs(ws, "covariate-x") == []


def test_find_pairs_deduplicates_repeated_declarations(ws):
    registry = Registry(ws)
    write_program(ws, "a", CONST + "#a\n", tags={"school": Tag.ASSERTS})
    ha = registry.freeze("a", at(0)).closure_hash
    decl = PairDecl(claim="school", partner=ha)
    write_program(ws, "d", CONST + "#d\n", tags={"school": Tag.DENIES}, pairs=(decl, decl))
    hd = registry.freeze("d", at(1)).closure_hash
    assert find_pairs(ws, "school") == [(ha, hd)]


def test_find_pairs_lists_every_distinct_pair_sorted(ws):
    pairs = [_freeze_pair(ws, a=f"a{i}", d=f"d{i}", start=2 * i) for i in range(3)]
    # one asserting program with two denying partners: (a0, d0) already exists, add (a0, e)
    registry = Registry(ws)
    ha0 = pairs[0][0]
    write_program(
        ws, "e", CONST + "#e\n", tags={"school": Tag.DENIES}, pairs=(PairDecl(claim="school", partner=ha0),)
    )
    he = registry.freeze("e", at(10)).closure_hash
    found = find_pairs(ws, "school")
    assert found == sorted(found)
    assert set(found) == {*pairs, (ha0, he)}
    assert len(found) == 4


def test_find_pairs_reads_pairs_from_withdrawn_programs_too(ws):
    ha, hd = _freeze_pair(ws)
    Registry(ws).withdraw(hd, at(5), "test")
    assert find_pairs(ws, "school") == [(ha, hd)]


def _rewrite_manifest(ws, name, **update):
    program_dir = ws.programs / name
    edited = load_manifest(program_dir).model_copy(update=update)
    (program_dir / "program.json").write_text(edited.model_dump_json(), encoding="utf-8")


@pytest.mark.parametrize(
    "name,update",
    [
        ("d", {"tags": {"school": Tag.ASSERTS}}),  # the declarer's stance flipped: the pair would reverse
        ("d", {"pairs": ()}),  # the declaration removed: the pair would vanish
        ("a", {"tags": {"school": Tag.DENIES}}),  # the partner's manifest edited
        ("p", {"author_lineage": "someone else"}),  # an unrelated frozen program: its manifest is read too
    ],
)
def test_find_pairs_refuses_a_manifest_edited_after_freeze(ws, name, update):
    _freeze_pair(ws)
    write_program(ws, "p", CONST + "#p\n")
    Registry(ws).freeze("p", at(5))
    assert len(find_pairs(ws, "school")) == 1
    _rewrite_manifest(ws, name, **update)
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        find_pairs(ws, "school")


def test_claim_standings_refuses_a_manifest_edited_after_freeze(ws):
    ha, hd = _freeze_pair(ws)
    res = _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)])
    assert claim_standings(ws, _mission(SCHOOL), res, SPECS)[0].verdict is Verdict.SUPPORTS
    _rewrite_manifest(ws, "d", tags={"school": Tag.ASSERTS})
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        claim_standings(ws, _mission(SCHOOL), res, SPECS)


def test_find_pairs_refuses_a_declaration_with_no_stance(ws):
    # Only reachable if a registry entry was written around `freeze`; the pair cannot be oriented.
    ha, _ = _freeze_pair(ws)
    d = write_program(ws, "u", CONST + "#u\n", pairs=(PairDecl(claim="school", partner=ha),))
    append_jsonl(ws.registry, Freeze(name="u", closure_hash=closure_hash(d), frozen_at=at(9)))
    with pytest.raises(RegistryError, match="school"):
        find_pairs(ws, "school")


def _resolution(ha, hd, scores, predicted=None, unscored=None):
    """A Resolution with one jurisdiction-A target per (a, d) log_p pair in `scores`.

    `predicted` and `unscored` default to every score predicted and none unscored (full coverage).
    """
    resolved = tuple(rt(i + 1, i + 2, {ha: a, hd: d}) for i, (a, d) in enumerate(scores))
    n = len(scores)
    return Resolution(
        resolved=resolved,
        pending=0,
        predicted={ha: n, hd: n} if predicted is None else predicted,
        unscored={ha: 0, hd: 0} if unscored is None else unscored,
    )


def _mission(*claims, **kw):
    return make_mission(claims=claims, tau=2.0, claim_threshold_nats=3.0, coverage_min=0.8, **kw)


SCHOOL = Claim(id="school", statement="Closing schools lowers admissions.", scope=TargetFilter())


def test_claim_standing_supports_from_a_frozen_pair(ws):
    ha, hd = _freeze_pair(ws)
    standings = claim_standings(ws, _mission(SCHOOL), _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)]), SPECS)
    assert len(standings) == 1
    s = standings[0]
    assert (s.claim, s.statement, s.verdict) == ("school", SCHOOL.statement, Verdict.SUPPORTS)
    assert len(s.pairs) == 1
    p = s.pairs[0]
    assert (p.claim, p.asserts, p.denies, p.n_targets) == ("school", ha, hd, 2)
    assert p.delta_nats == pytest.approx(8.0) and p.verdict is Verdict.SUPPORTS


def test_claim_standing_uses_mission_tau_and_threshold(ws):
    ha, hd = _freeze_pair(ws)
    res = _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)])
    assert claim_standings(ws, _mission(SCHOOL), res, SPECS)[0].verdict is Verdict.SUPPORTS
    strict = make_mission(claims=(SCHOOL,), tau=4.0, claim_threshold_nats=3.0, coverage_min=0.8)
    assert claim_standings(ws, strict, res, SPECS)[0].verdict is Verdict.INSUFFICIENT
    flipped = _resolution(ha, hd, [(-4.0, 0.0), (-4.0, 0.0)])
    assert claim_standings(ws, _mission(SCHOOL), flipped, SPECS)[0].verdict is Verdict.CONTRADICTS


def test_low_coverage_pair_is_excluded(ws):
    ha, hd = _freeze_pair(ws)
    res = _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)], predicted={ha: 1, hd: 10}, unscored={ha: 9, hd: 0})
    s = claim_standings(ws, _mission(SCHOOL), res, SPECS)[0]
    assert (s.pairs, s.verdict) == ((), Verdict.INSUFFICIENT)


def test_coverage_exactly_at_the_minimum_is_kept(ws):
    ha, hd = _freeze_pair(ws)
    res = _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)], predicted={ha: 8, hd: 10}, unscored={ha: 2, hd: 0})
    s = claim_standings(ws, _mission(SCHOOL), res, SPECS)[0]
    assert len(s.pairs) == 1 and s.verdict is Verdict.SUPPORTS


def test_either_member_below_coverage_excludes_the_pair(ws):
    ha, hd = _freeze_pair(ws)
    res = _resolution(ha, hd, [(0.0, -4.0)], predicted={ha: 10, hd: 1}, unscored={ha: 0, hd: 9})
    assert claim_standings(ws, _mission(SCHOOL), res, SPECS)[0].pairs == ()


def test_program_absent_from_the_resolution_has_zero_coverage(ws):
    ha, hd = _freeze_pair(ws)
    res = Resolution(resolved=(), pending=0, predicted={ha: 5}, unscored={ha: 0})
    s = claim_standings(ws, _mission(SCHOOL), res, SPECS)[0]
    assert (s.pairs, s.verdict) == ((), Verdict.INSUFFICIENT)


def test_claim_without_pairs_is_insufficient(ws):
    res = Resolution(resolved=(), pending=0, predicted={}, unscored={})
    s = claim_standings(ws, _mission(SCHOOL), res, SPECS)[0]
    assert (s.claim, s.pairs, s.verdict) == ("school", (), Verdict.INSUFFICIENT)


def test_withdrawn_programs_still_count(ws):
    ha, hd = _freeze_pair(ws)
    registry = Registry(ws)
    registry.withdraw(ha, at(5), "test")
    registry.withdraw(hd, at(5), "test")
    s = claim_standings(ws, _mission(SCHOOL), _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)]), SPECS)[0]
    assert s.verdict is Verdict.SUPPORTS and len(s.pairs) == 1


def test_one_standing_per_claim_in_mission_order(ws):
    ha, hd = _freeze_pair(ws)
    other = Claim(id="covariate-x", statement="x", scope=TargetFilter())
    mission = _mission(other, SCHOOL)
    standings = claim_standings(ws, mission, _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)]), SPECS)
    assert [s.claim for s in standings] == ["covariate-x", "school"]
    assert [s.verdict for s in standings] == [Verdict.INSUFFICIENT, Verdict.SUPPORTS]
    assert claim_standings(ws, make_mission(), _resolution(ha, hd, []), SPECS) == []


def test_pairs_that_disagree_make_the_claim_mixed(ws):
    a1, d1 = _freeze_pair(ws, a="a1", d="d1", start=0)
    a2, d2 = _freeze_pair(ws, a="a2", d="d2", start=2)
    resolved = (
        rt(1, 2, {a1: 0.0, d1: -8.0, a2: -8.0, d2: 0.0}),
        rt(2, 3, {a1: 0.0, d1: -8.0, a2: -8.0, d2: 0.0}),
    )
    programs = (a1, d1, a2, d2)
    res = Resolution(
        resolved=resolved, pending=0, predicted={h: 2 for h in programs}, unscored={h: 0 for h in programs}
    )
    s = claim_standings(ws, _mission(SCHOOL), res, SPECS)[0]
    assert s.verdict is Verdict.MIXED
    assert {p.verdict for p in s.pairs} == {Verdict.SUPPORTS, Verdict.CONTRADICTS}
    assert [(p.asserts, p.denies) for p in s.pairs] == sorted((p.asserts, p.denies) for p in s.pairs)


def test_standing_uses_the_claim_scope(ws):
    ha, hd = _freeze_pair(ws)
    scoped = Claim(id="school", statement="s", scope=TargetFilter(jurisdictions=("A",)))
    resolved = (rt(1, 2, {ha: 0.0, hd: -4.0}), rt(2, 3, {ha: -90.0, hd: 0.0}, j="B"))
    res = Resolution(resolved=resolved, pending=0, predicted={ha: 2, hd: 2}, unscored={ha: 0, hd: 0})
    s = claim_standings(ws, _mission(scoped), res, {"w/adm": count_spec(jurisdictions=("A", "B"))})[0]
    assert s.pairs[0].n_targets == 1 and s.pairs[0].delta_nats == pytest.approx(4.0)


def test_standings_round_trip_through_json(ws):
    ha, hd = _freeze_pair(ws)
    s = claim_standings(ws, _mission(SCHOOL), _resolution(ha, hd, [(0.0, -4.0), (0.0, -4.0)]), SPECS)[0]
    assert ClaimStanding.model_validate_json(s.model_dump_json()) == s


# --- claim families: which pairs count for which claim (R11) ---

CX, CXF, SCH = "covariate-x", "covariate-x-flat", "school"


def _stances(cx: Tag, school: Tag) -> dict[str, Tag]:
    return {CX: cx, CXF: cx, SCH: school}


def _freeze_seir_family(ws) -> dict[str, str]:
    """The seed library's four stances with its pairs, plus `conf`: x0s0's stances paired with x1s1 over all three
    claims, a declaration that R9 accepts although the pair differs in two mechanisms.  Returns name -> hash."""
    registry = Registry(ws)
    h: dict[str, str] = {}

    def freeze(name, cx, school, pairs=(), when=0):
        decls = tuple(PairDecl(claim=c, partner=h[p]) for p, claims in pairs for c in claims)
        write_program(ws, name, CONST + f"#{name}\n", tags=_stances(cx, school), pairs=decls)
        h[name] = registry.freeze(name, at(when)).closure_hash

    A, D = Tag.ASSERTS, Tag.DENIES
    freeze("x1s1", A, A)
    freeze("x1s0", A, D, [("x1s1", (SCH,))], 1)
    freeze("x0s1", D, A, [("x1s1", (CX, CXF))], 2)
    freeze("x0s0", D, D, [("x1s0", (CX, CXF)), ("x0s1", (SCH,))], 3)
    freeze("conf", D, D, [("x1s1", (CX, CXF, SCH))], 4)
    return h


def _family_resolution(h: dict[str, str]) -> Resolution:
    """Every program predicted every target: full coverage, and x1s1 scores best."""
    resolved = tuple(rt(i + 1, i + 2, {p: (0.0 if n == "x1s1" else -4.0) for n, p in h.items()}) for i in range(2))
    full = {p: 2 for p in h.values()}
    return Resolution(resolved=resolved, pending=0, predicted=full, unscored={p: 0 for p in h.values()})


def _pairs_by_claim(ws, mission, h) -> dict[str, set[tuple[str, str]]]:
    names = {p: n for n, p in h.items()}
    standings = claim_standings(ws, mission, _family_resolution(h), SPECS)
    return {s.claim: {(names[p.asserts], names[p.denies]) for p in s.pairs} for s in standings}


def test_find_pair_sets_carries_each_pairs_declared_claims(ws):
    h = _freeze_seir_family(ws)
    names = {p: n for n, p in h.items()}
    found = {(names[a], names[d]): claims for a, d, claims in find_pair_sets(ws, SCH)}
    assert found == {
        ("x1s1", "x1s0"): frozenset({SCH}),
        ("x0s1", "x0s0"): frozenset({SCH}),
        ("x1s1", "conf"): frozenset({CX, CXF, SCH}),
    }
    assert find_pairs(ws, SCH) == sorted((a, d) for a, d, _ in find_pair_sets(ws, SCH))


def test_a_pair_counts_only_for_claims_its_declared_set_stays_within(ws):
    h = _freeze_seir_family(ws)
    family = (
        Claim(id=CX, statement="x", scope=TargetFilter()),
        Claim(id=CXF, statement="x where flat", scope=TargetFilter(), refines=CX),
        Claim(id=SCH, statement="s", scope=TargetFilter()),
    )
    by_claim = _pairs_by_claim(ws, _mission(*family), h)
    x_pairs = {("x1s1", "x0s1"), ("x1s0", "x0s0")}
    assert by_claim[CX] == x_pairs  # {cx, cxf}: cxf refines cx
    assert by_claim[CXF] == x_pairs  # {cx, cxf}: cx is the claim cxf refines
    assert by_claim[SCH] == {("x1s1", "x1s0"), ("x0s1", "x0s0")}  # conf also differs in the covariate: excluded


def test_without_refines_a_pair_over_two_claims_counts_for_neither(ws):
    h = _freeze_seir_family(ws)
    unrelated = tuple(Claim(id=c, statement=c, scope=TargetFilter()) for c in (CX, CXF, SCH))
    by_claim = _pairs_by_claim(ws, _mission(*unrelated), h)
    assert by_claim[CX] == by_claim[CXF] == set()
    assert by_claim[SCH] == {("x1s1", "x1s0"), ("x0s1", "x0s0")}
