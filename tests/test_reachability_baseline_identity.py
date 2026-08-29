"""The reachability baseline is written in the graph's own module identities.

SPEC-082926-f1c3. The baseline stored report labels while the walk produced
scoped identities, and `check_ac_state_impl._is_reachable` — which grades the
`reachable` rung — looks an *identity* up in it. Absence reads as reachable, so
forty genuinely-unreachable modules would have graded as reachable the moment a
criterion anchored to one of them, which SPEC-082926-c2d7 made the correct thing
to do.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REACHABILITY = ROOT / "scripts" / "check-reachability.py"
AC_STATE = ROOT / "scripts" / "check_ac_state_impl.py"
BASELINE = ROOT / "quality" / "reachability-baseline.json"
DISPOSITIONS = ROOT / "quality" / "reachability-dispositions.json"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def check():
    return _load("check_reachability_identity", REACHABILITY)


@pytest.fixture(scope="module")
def ac_state():
    return _load("check_ac_state_impl", AC_STATE)


@pytest.fixture(scope="module")
def universe(check) -> set[str]:
    mods, _ = check._reachability(
        check.ROOT, check.FLAT_APPS, check.STATIC_ROOTS, check.DYNAMIC_ROOTS
    )
    return set(mods)


@pytest.fixture(scope="module")
def baseline() -> set[str]:
    return set(json.loads(BASELINE.read_text())["unreachable"])


# --- AC-1: every entry is an identity the walk produces ---


@pytest.mark.ac("SPEC-082926-f1c3/AC-1")
def test_every_baseline_entry_resolves_to_a_module_identity(baseline, universe):
    """The property the whole spec is about, asserted on the committed file.

    Not `unknown_baseline_entries(...) == []` — that would assert the gate
    agrees with itself. This asks the module universe directly.
    """
    strays = sorted(baseline - universe)
    assert strays == [], f"{len(strays)} baseline entries name no module: {strays[:5]}"


@pytest.mark.ac("SPEC-082926-f1c3/AC-1")
def test_the_baseline_holds_scoped_identities_and_none_of_their_labels(baseline, check):
    """Both halves. Holding identities is not the same as holding no labels:
    the file could carry both spellings of one module and satisfy the first."""
    flat = {entry for entry in baseline if entry.startswith("@flat/")}
    tooling = {entry for entry in baseline if entry.startswith("@tool/")}
    assert flat, "flat-app modules are in the graph and some are unreachable"
    assert tooling, "repo tooling is in the graph (#249) and some is unreachable"

    labels = {check.display_name(entry) for entry in flat | tooling}
    assert not (labels & baseline), sorted(labels & baseline)


@pytest.mark.ac("SPEC-082926-f1c3/AC-1")
def test_the_dispositions_ledger_names_the_same_identities(baseline):
    """The ledger must stay 1:1 with the baseline, so it moved with it. A
    rewrite of one file alone would have failed the dispositions gate, but
    passing that gate is also satisfied by rewriting *neither*."""
    ledger = json.loads(DISPOSITIONS.read_text())
    modules = {module for group in ledger["groups"] for module in group["modules"]}
    assert modules == baseline


# --- AC-2: an entry the walk cannot resolve fails the gate ---


def _run_gate(check, monkeypatch, tmp_path, entries: list[str]) -> int:
    """The gate's exit code against a stand-in baseline."""
    stand_in = tmp_path / "baseline.json"
    stand_in.write_text(json.dumps({"unreachable": entries}))
    monkeypatch.setattr(check, "BASELINE", stand_in)
    return check.main()


@pytest.mark.ac("SPEC-082926-f1c3/AC-2")
def test_an_entry_written_as_a_report_label_fails_with_the_identity_named(
    check, universe, baseline, tmp_path, monkeypatch, capsys
):
    """The exact fault this fixes: the label of a module that really is
    baselined. The gate must both reject it and say what to write instead."""
    labelled = sorted(entry for entry in baseline if check.display_name(entry) != entry)
    assert labelled, "some baselined module must have a label distinct from its identity"
    victim = labelled[0]
    label = check.display_name(victim)
    assert label not in universe, "the label must not itself be an identity"

    entries = [*sorted(baseline - {victim}), label]
    code = _run_gate(check, monkeypatch, tmp_path, entries)
    out = capsys.readouterr().out

    assert code == 1
    assert "name NO module the graph knows" in out
    assert label in out
    assert f"rename to {victim!r}" in out


@pytest.mark.ac("SPEC-082926-f1c3/AC-2")
def test_an_entry_naming_nothing_at_all_is_told_to_go(
    check, baseline, tmp_path, monkeypatch, capsys
):
    """A phantom takes the opposite fix from a mis-spelling, so it gets the
    opposite instruction. Telling someone to rename a module that does not
    exist is advice they cannot follow."""
    phantom = "maistro.nonexistent_module"
    code = _run_gate(check, monkeypatch, tmp_path, [*sorted(baseline), phantom])
    out = capsys.readouterr().out

    assert code == 1
    assert phantom in out
    assert "no such module — delete it" in out
    assert "rename to" not in out


@pytest.mark.ac("SPEC-082926-f1c3/AC-2")
def test_an_unresolvable_entry_is_not_also_reported_as_newly_reachable(
    check, baseline, tmp_path, monkeypatch, capsys
):
    """One fault, one report. An unresolvable entry is absent from the
    unreachable set by construction, so the naive `baseline - unreachable`
    would also call it newly reachable and send the reader to prune what
    needs respelling."""
    code = _run_gate(
        check, monkeypatch, tmp_path, [*sorted(baseline), "maistro.nonexistent_module"]
    )
    out = capsys.readouterr().out

    assert code == 1
    assert "newly REACHABLE" not in out
    assert "must shrink" not in out


@pytest.mark.ac("SPEC-082926-f1c3/AC-2")
def test_the_committed_baseline_passes_the_gate_it_now_carries(check, baseline, universe, capsys):
    """A gate nothing currently satisfies would be reverted on the next merge.

    Both levels, because they can disagree: the predicate can be clean while
    `main` still returns 1 through a branch that reads the set a second time.
    """
    assert check.unknown_baseline_entries(baseline, universe) == []
    assert check.main() == 0
    assert "name NO module" not in capsys.readouterr().out


@pytest.mark.ac("SPEC-082926-f1c3/AC-3")
def test_a_newly_unreachable_module_is_still_reported_by_its_label(
    check, baseline, tmp_path, monkeypatch, capsys
):
    """Storage moved to identities; the report did not.

    `scripts/mutation_ratchet.py` is findable where `mutation_ratchet` is one
    grep away from the wrong thing — the reason `_display_name` exists. The
    identity comes with it, so the baseline line can be written from the
    failure without consulting the spec.
    """
    labelled = sorted(entry for entry in baseline if check.display_name(entry) != entry)
    assert labelled, "some baselined module must have a label distinct from its identity"
    victim = labelled[0]

    code = _run_gate(check, monkeypatch, tmp_path, sorted(baseline - {victim}))
    out = capsys.readouterr().out

    assert code == 1
    assert "NEWLY UNREACHABLE" in out
    assert check.display_name(victim) in out
    assert victim in out


# --- AC-3: the rewrite moves no verdict ---


@pytest.mark.ac("SPEC-082926-f1c3/AC-3")
def test_the_baseline_is_exactly_the_unreachable_set(check, baseline):
    """Equality, not containment. The ratchet requires the baseline to shrink
    when a module becomes reachable, so a superset is slack and a subset is a
    failure — and the rewrite must have preserved the set exactly."""
    unreachable, _ = check.unreachable_modules()
    assert set(unreachable) == baseline


@pytest.mark.ac("SPEC-082926-f1c3/AC-3")
def test_the_convergence_census_still_attributes_every_unreachable_module():
    """The census subtracts the baseline from the module set, both in label
    form. Storing identities without translating on read would have emptied
    the unreachable share ADR-082526-aef8 derives — silently, since an empty
    intersection is a valid census."""
    matrix = _load("check_convergence_matrix", ROOT / "scripts" / "check-convergence-matrix.py")
    labels = matrix.unreachable_modules()
    modules = set(matrix.production_modules())

    assert labels <= modules, sorted(labels - modules)
    assert len(labels) == len(json.loads(BASELINE.read_text())["unreachable"])


# --- AC-4: the rung this exists for ---


@pytest.mark.ac("SPEC-082926-f1c3/AC-4")
@pytest.mark.parametrize("prefix", ["@flat/", "@tool/"])
def test_a_criterion_anchored_to_a_baselined_scoped_module_reports_passing(
    ac_state, baseline, prefix
):
    """The defect, stated as the grade it produced.

    Both scoped shapes, because they arrived by different routes — flat-app
    modules lose their app scope, tooling modules become file paths — and a
    fix that handled one would look complete.
    """
    candidates = sorted(entry for entry in baseline if entry.startswith(prefix))
    assert candidates, f"no baselined module has a {prefix} identity"
    anchored = candidates[0]

    criterion = ac_state.Criterion(
        ac_id="AC-1", covered_by=["tests/test_x.py"], passing=True, module=anchored
    )
    assert criterion.rung(baseline) == "passing"


@pytest.mark.ac("SPEC-082926-f1c3/AC-4")
def test_every_baselined_module_grades_below_reachable(ac_state, baseline):
    """All 187, not a sample. The forty that were stored as labels are the
    ones this fixes, and singling them out would leave the assertion passing
    if a later edit re-introduced a stray somewhere else."""
    graded = {
        entry: ac_state.Criterion(
            ac_id="AC-1", covered_by=["tests/test_x.py"], passing=True, module=entry
        ).rung(baseline)
        for entry in baseline
    }
    wrong = {entry: rung for entry, rung in graded.items() if rung != "passing"}
    assert wrong == {}


@pytest.mark.ac("SPEC-082926-f1c3/AC-4")
def test_a_reachable_module_still_grades_reachable(ac_state, baseline, universe):
    """The control. A change that graded *everything* `passing` would satisfy
    the assertion above and destroy the rung."""
    reachable = sorted(universe - baseline)
    assert reachable, "most of the tree is reachable"

    criterion = ac_state.Criterion(
        ac_id="AC-1", covered_by=["tests/test_x.py"], passing=True, module=reachable[0]
    )
    assert criterion.rung(baseline) == "reachable"
