import shutil

import pytest
from helpers import CONST, at, write_program

from scienceme.manifest import PairDecl, Tag, closure_hash
from scienceme.registry import Freeze, Registry, RegistryError, Withdrawal
from scienceme.workspace import append_jsonl


def test_freeze_records_hash_and_time(ws):
    d = write_program(ws, "p", CONST)
    f = Registry(ws).freeze("p", at(0))
    assert (f.name, f.closure_hash, f.frozen_at) == ("p", closure_hash(d), at(0))


def test_refreeze_same_content_is_idempotent_and_changed_content_refused(ws):
    d = write_program(ws, "p", CONST)
    r = Registry(ws)
    f = r.freeze("p", at(0))
    assert r.freeze("p", at(1)) == f
    (d / "program.py").write_text(CONST + "# edit\n")
    with pytest.raises(RegistryError, match="new name"):
        r.freeze("p", at(2))
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(f.closure_hash)


def test_unknown_import_refused(ws):
    write_program(ws, "p", CONST, imports={"core": "sha256:" + "d" * 64})
    with pytest.raises(RegistryError):
        Registry(ws).freeze("p", at(0))


def test_active_window_is_strict(ws):
    write_program(ws, "p", CONST)
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    assert not r.active(h, at(0)) and r.active(h, at(1))
    r.withdraw(h, at(5), "test")
    assert r.active(h, at(5)) and not r.active(h, at(6))


def test_pair_partner_must_be_frozen_and_matched(ws):
    write_program(ws, "a", CONST, tags={"school": Tag.ASSERTS})
    r = Registry(ws)
    ha = r.freeze("a", at(0)).closure_hash
    write_program(ws, "d", CONST + "#d\n", tags={"school": Tag.DENIES}, pairs=(PairDecl(claim="school", partner=ha),))
    r.freeze("d", at(1))
    write_program(ws, "bad", CONST + "#b\n", tags={"school": Tag.ASSERTS}, pairs=(PairDecl(claim="school", partner=ha),))
    with pytest.raises(RegistryError):
        r.freeze("bad", at(2))


def test_registry_is_append_only(ws):
    write_program(ws, "p", CONST)
    write_program(ws, "q", CONST + "#q\n")
    r = Registry(ws)
    r.freeze("p", at(0))
    first = ws.registry.read_text()
    r.freeze("q", at(1))
    assert ws.registry.read_text().startswith(first)


def test_closure_lists_imports_first(ws):
    write_program(ws, "core", "def level():\n    return 3\n", library=True)
    r = Registry(ws)
    hc = r.freeze("core", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"core": hc})
    hp = r.freeze("p", at(1)).closure_hash
    assert r.closure(hp) == [hc, hp]


# --- beyond the brief ---


def test_entries_empty_before_any_freeze(ws):
    r = Registry(ws)
    assert r.entries() == [] and r.freezes() == {} and r.by_name("p") is None


def test_entries_round_trip_freezes_and_withdrawals_in_order(ws):
    write_program(ws, "p", CONST)
    r = Registry(ws)
    f = r.freeze("p", at(0))
    w = r.withdraw(f.closure_hash, at(3), "superseded")
    assert r.entries() == [f, w]
    assert isinstance(f, Freeze) and isinstance(w, Withdrawal)
    assert (w.closure_hash, w.at, w.reason) == (f.closure_hash, at(3), "superseded")
    assert r.freezes() == {f.closure_hash: f}
    assert r.by_name("p") == f


def test_program_dir_and_manifest_by_hash(ws):
    d = write_program(ws, "p", CONST, tags={"school": Tag.ASSERTS})
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    assert r.program_dir(h) == d
    assert r.manifest(h).tags == {"school": Tag.ASSERTS}


def test_unfrozen_hash_is_refused_everywhere(ws):
    r = Registry(ws)
    h = "sha256:" + "e" * 64
    assert not r.active(h, at(10))
    for call in (
        lambda: r.program_dir(h),
        lambda: r.manifest(h),
        lambda: r.verify(h),
        lambda: r.closure(h),
        lambda: r.withdraw(h, at(0), "nope"),
    ):
        with pytest.raises(RegistryError, match="not frozen"):
            call()


def test_withdrawal_does_not_unfreeze(ws):
    write_program(ws, "p", CONST)
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    r.withdraw(h, at(2), "test")
    assert h in r.freezes()
    assert r.freeze("p", at(9)).closure_hash == h
    assert len(r.entries()) == 2


def test_withdrawal_applies_only_to_its_own_hash(ws):
    write_program(ws, "p", CONST)
    write_program(ws, "q", CONST + "#q\n")
    r = Registry(ws)
    hp = r.freeze("p", at(0)).closure_hash
    hq = r.freeze("q", at(0)).closure_hash
    r.withdraw(hp, at(1), "test")
    assert not r.active(hp, at(2)) and r.active(hq, at(2))


def test_verify_passes_for_unmodified_program(ws):
    write_program(ws, "p", CONST)
    r = Registry(ws)
    r.verify(r.freeze("p", at(0)).closure_hash)


def test_verify_ignores_readback_written_after_freezing(ws):
    d = write_program(ws, "p", CONST)
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    (d / "readback.json").write_text("{}")
    r.verify(h)


def test_verify_flags_missing_directory(ws):
    d = write_program(ws, "p", CONST)
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    for f in d.iterdir():
        f.unlink()
    d.rmdir()
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(h)


def test_verify_flags_symlink_added_after_freeze(ws, tmp_path):
    d = write_program(ws, "p", CONST)
    r = Registry(ws)
    h = r.freeze("p", at(0)).closure_hash
    (d / "link").symlink_to(tmp_path)
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(h)


def test_freeze_missing_program_refused(ws):
    with pytest.raises(RegistryError, match="ghost"):
        Registry(ws).freeze("ghost", at(0))


def test_freeze_malformed_manifest_refused(ws):
    d = write_program(ws, "p", CONST)
    (d / "program.json").write_text("{not json")
    with pytest.raises(RegistryError, match="program.json"):
        Registry(ws).freeze("p", at(0))


def test_freeze_lens_that_is_not_an_import_refused(ws):
    d = write_program(ws, "p", CONST)
    (d / "program.json").write_text('{"name": "p", "author_lineage": "test", "lens": "core"}')
    with pytest.raises(RegistryError, match="lens"):
        Registry(ws).freeze("p", at(0))


def test_freeze_name_must_match_manifest(ws):
    d = write_program(ws, "p", CONST)
    d.rename(ws.programs / "q")
    with pytest.raises(RegistryError, match="does not match"):
        Registry(ws).freeze("q", at(0))


@pytest.mark.parametrize("name", ["../p", "a/b", ".", "..", ""])
def test_freeze_name_must_be_one_directory(ws, name):
    with pytest.raises(RegistryError, match="directory name"):
        Registry(ws).freeze(name, at(0))


def test_freeze_symlink_in_program_refused(ws, tmp_path):
    d = write_program(ws, "p", CONST)
    (d / "link").symlink_to(tmp_path)
    with pytest.raises(RegistryError, match="symlink"):
        Registry(ws).freeze("p", at(0))
    assert Registry(ws).entries() == []


def test_failed_freeze_appends_nothing(ws):
    write_program(ws, "p", CONST, imports={"core": "sha256:" + "d" * 64})
    r = Registry(ws)
    with pytest.raises(RegistryError):
        r.freeze("p", at(0))
    assert not ws.registry.exists() or ws.registry.read_text() == ""


def test_same_hash_under_another_name_refused(ws):
    d = write_program(ws, "p", CONST)
    h = closure_hash(d)
    append_jsonl(ws.registry, Freeze(name="other", closure_hash=h, frozen_at=at(0)))
    with pytest.raises(RegistryError, match="other"):
        Registry(ws).freeze("p", at(1))


def test_asserting_program_may_declare_a_denying_partner(ws):
    write_program(ws, "d", CONST, tags={"school": Tag.DENIES})
    r = Registry(ws)
    hd = r.freeze("d", at(0)).closure_hash
    write_program(ws, "a", CONST + "#a\n", tags={"school": Tag.ASSERTS}, pairs=(PairDecl(claim="school", partner=hd),))
    assert r.freeze("a", at(1)).name == "a"


def test_pair_partner_not_frozen_refused(ws):
    write_program(ws, "d", CONST, pairs=(PairDecl(claim="school", partner="sha256:" + "a" * 64),), tags={"school": Tag.DENIES})
    with pytest.raises(RegistryError, match="not frozen"):
        Registry(ws).freeze("d", at(0))


def test_pair_requires_a_stance_on_the_claim(ws):
    write_program(ws, "a", CONST, tags={"school": Tag.ASSERTS})
    r = Registry(ws)
    ha = r.freeze("a", at(0)).closure_hash
    write_program(ws, "u", CONST + "#u\n", pairs=(PairDecl(claim="school", partner=ha),))
    with pytest.raises(RegistryError, match="school"):
        r.freeze("u", at(1))


def test_pair_that_differs_on_another_claim_refused_with_pair_error_chained(ws):
    write_program(ws, "a", CONST, tags={"school": Tag.ASSERTS, "x": Tag.ASSERTS})
    r = Registry(ws)
    ha = r.freeze("a", at(0)).closure_hash
    write_program(
        ws,
        "d",
        CONST + "#d\n",
        tags={"school": Tag.DENIES, "x": Tag.DENIES},
        pairs=(PairDecl(claim="school", partner=ha),),
    )
    with pytest.raises(RegistryError, match="differs on claim") as exc:
        r.freeze("d", at(1))
    assert exc.value.__cause__ is not None


def test_pair_partner_modified_after_freeze_refused(ws):
    da = write_program(ws, "a", CONST, tags={"school": Tag.ASSERTS})
    r = Registry(ws)
    ha = r.freeze("a", at(0)).closure_hash
    (da / "program.py").write_text(CONST + "# edit\n")
    write_program(ws, "d", CONST + "#d\n", tags={"school": Tag.DENIES}, pairs=(PairDecl(claim="school", partner=ha),))
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.freeze("d", at(1))


def test_closure_deduplicates_shared_imports_and_orders_depth_first(ws):
    r = Registry(ws)
    write_program(ws, "base", "X = 1\n", library=True)
    hb = r.freeze("base", at(0)).closure_hash
    write_program(ws, "left", "X = 2\n", library=True, imports={"base": hb})
    hl = r.freeze("left", at(1)).closure_hash
    write_program(ws, "right", "X = 3\n", library=True, imports={"base": hb})
    hr = r.freeze("right", at(2)).closure_hash
    write_program(ws, "top", CONST, imports={"left": hl, "right": hr})
    ht = r.freeze("top", at(3)).closure_hash
    assert r.closure(ht) == [hb, hl, hr, ht]
    assert r.closure(hb) == [hb]


# --- closure and manifest on a tampered registry (R8) ---


def test_closure_terminates_on_a_manifest_that_imports_itself(ws):
    r = Registry(ws)
    write_program(ws, "p", CONST)
    h = r.freeze("p", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"me": h})  # tampered after freezing: p now imports its own hash
    assert r.closure(h) == [h]
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(h)


def test_closure_terminates_on_an_import_cycle(ws):
    r = Registry(ws)
    write_program(ws, "a", "A = 1\n", library=True)
    ha = r.freeze("a", at(0)).closure_hash
    write_program(ws, "b", CONST, imports={"a": ha})
    hb = r.freeze("b", at(1)).closure_hash
    write_program(ws, "a", "A = 1\n", library=True, imports={"b": hb})  # tampered: a now imports b, which imports a
    assert r.closure(hb) == [ha, hb]
    with pytest.raises(RegistryError, match="modified-after-freeze"):
        r.verify(ha)


def test_closure_reports_a_missing_program_directory_as_a_registry_error(ws):
    r = Registry(ws)
    write_program(ws, "core", "X = 1\n", library=True)
    hc = r.freeze("core", at(0)).closure_hash
    write_program(ws, "p", CONST, imports={"core": hc})
    hp = r.freeze("p", at(1)).closure_hash
    shutil.rmtree(ws.programs / "core")
    with pytest.raises(RegistryError, match="program.json"):
        r.closure(hp)


@pytest.mark.parametrize("content", ["{not json", "", '{"name": "p"}', '{"name": "p", "author_lineage": "t", "bogus": 1}'])
def test_closure_reports_an_unreadable_manifest_as_a_registry_error(ws, content):
    r = Registry(ws)
    d = write_program(ws, "p", CONST)
    h = r.freeze("p", at(0)).closure_hash
    (d / "program.json").write_text(content)
    with pytest.raises(RegistryError, match="program.json"):
        r.closure(h)
    with pytest.raises(RegistryError, match="program.json"):
        r.manifest(h)
