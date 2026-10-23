"""#891 (M8-A11): the Z3/SMT experiment over the schedule fire decision.

The issue asks one representative constraint-heavy decision to be encoded
directly in Z3, interrogated with satisfiability and counterexample
questions, and compared against the current procedural logic. The target is
`maistro.scheduling.engine.evaluate`'s decision core; the encoding and the
bounded closed-loop model live in `_z3_fire_contract.py`, and the experiment
record with the measured evidence and the disposition is
`docs/testing/z3-smt-decisions-evidence.md`.

The cells here are *the whole bounded grid*, not samples: the solver is asked
whether any contract-satisfying decision on the entire space differs from
what production chose. That completeness claim is what the existing sampled
and Hypothesis tests (`test_engine.py`) cannot make.
"""

from __future__ import annotations

import time
import tomllib
from datetime import timedelta
from pathlib import Path

import pytest
import z3

from maistro.scheduling.engine import SkipReason, enumeration_start, evaluate
from maistro.scheduling.model import OverlapPolicy, Schedule

from ._z3_fire_contract import (
    NOON,
    BufferedStarvationModel,
    Cell,
    FireContractModel,
    iter_cells,
    production_decision,
)

#: Generous structural ceiling for a whole grid walk. Measured runs land far
#: below it; this only fails on a runaway encode, never on ordinary variance.
GRID_WALL_CLOCK_CAP_S = 120.0

_REPO_ROOT = Path(__file__).resolve().parents[4]

#: Normalized distribution names of the solver. A requirement with one of
#: these names in a shipped manifest (`packages/*`, `extensions/*`) is
#: production drift wherever it is declared — a package manifest has no
#: test tree of its own that could justify it, and a dynamic
#: `importlib.import_module` load would slip past the source scan unnoticed.
_SOLVER_NAMES = frozenset({"z3", "z3-solver"})


def _requirements_of(node: object) -> list[object]:
    """Flatten a requirements declaration: a list of requirement strings, or
    a `dependency-groups` / `optional-dependencies` mapping of such lists."""
    if isinstance(node, dict):
        return [req for group in node.values() for req in _requirements_of(group)]
    if isinstance(node, list):
        return list(node)
    return []


def _requirement_names(manifest: dict[str, object]) -> list[str]:
    """Every requirement name the manifest declares, in any group.

    Covers the production list (`[project] dependencies`), every
    `optional-dependencies` group, and every PEP 735 `dependency-groups`
    group. Unparsable TOML raises — a manifest the guard cannot read must
    fail the scan, not silently pass it.
    """
    project = manifest.get("project")
    declared: list[object] = []
    if isinstance(project, dict):
        declared.extend(_requirements_of(project.get("dependencies")))
        declared.extend(_requirements_of(project.get("optional-dependencies")))
    declared.extend(_requirements_of(manifest.get("dependency-groups")))
    names: list[str] = []
    for dep in declared:
        name = str(dep)
        # Requirement strings may carry extras/markers/version specifiers;
        # the distribution name is everything before the first of those.
        for sep in (";", "[", "==", ">", "<", "~", "!", "="):
            name = name.split(sep)[0]
        names.append(name.strip().lower())
    return names


def test_production_conforms_to_the_contract_on_the_whole_bounded_grid() -> None:
    """Every cell: production's decision satisfies the SMT contract, and the
    design-independent invariants hold on the raw evaluation."""
    started = time.monotonic()
    for cell in iter_cells():
        decision, evaluation = production_decision(cell)

        # Design-independent contract, checked on the raw production output
        # without trusting the encoding: accounting, the per-policy promises,
        # the cap.
        accounted = sorted(
            [f.scheduled_for for f in evaluation.fires]
            + [s.scheduled_for for s in evaluation.skipped]
        )
        due = [NOON - timedelta(minutes=cell.due - i) for i in range(1, cell.due + 1)]
        assert accounted == due, f"cell {cell}: every due occurrence accounted exactly once"
        if cell.remaining is not None:
            assert len(evaluation.fires) <= cell.remaining, f"cell {cell}: cap respected"
        if cell.policy is OverlapPolicy.SKIP and cell.active_run:
            assert evaluation.fires == (), f"cell {cell}: SKIP never fires over an active Run"
        if cell.policy is OverlapPolicy.BUFFER_ONE:
            buffered = [s for s in evaluation.skipped if s.reason is SkipReason.BUFFERED]
            assert len(buffered) <= 1, f"cell {cell}: at most one queued occurrence"
            if cell.active_run:
                assert evaluation.fires == (), f"cell {cell}: buffer never runs alongside"
        if evaluation.cancel_active_run:
            assert cell.policy is OverlapPolicy.CANCEL_OTHER, f"cell {cell}: cancel is latest-wins"
            assert cell.active_run and evaluation.fires

        # The SMT contract agrees that this decision is one of its own.
        model = FireContractModel(cell)
        assert model.conforms(decision) == z3.sat, f"cell {cell}: production violates contract"
    elapsed = time.monotonic() - started
    assert elapsed < GRID_WALL_CLOCK_CAP_S, f"grid walk took {elapsed:.1f}s"


def test_production_is_the_unique_contract_decision_on_the_whole_bounded_grid() -> None:
    """Every cell: no *other* contract-satisfying decision exists.

    This is the completeness claim sampled tests cannot make: the procedural
    implementation is the unique function satisfying the documented contract
    everywhere in the bounded space. A satisfiable difference would be a
    divergence between the written semantics and the code.
    """
    started = time.monotonic()
    for cell in iter_cells():
        decision, _ = production_decision(cell)
        model = FireContractModel(cell)
        result = model.unique_beyond(decision)
        assert result == z3.unsat, (
            f"cell {cell}: production decision is not the unique contract "
            f"decision; witness {model.divergent_witness(decision)}"
        )
    elapsed = time.monotonic() - started
    assert elapsed < GRID_WALL_CLOCK_CAP_S, f"uniqueness walk took {elapsed:.1f}s"


def test_a_drifted_spec_is_detected_the_encoding_has_teeth() -> None:
    """Deliberately wrong encodings must be caught, or the differential is
    vacuous. Mutating SKIP to the ALLOW rule (and dropping the cap) must make
    the uniqueness query satisfiable with a witness that differs from
    production."""
    active_skip = Cell(policy=OverlapPolicy.SKIP, active_run=True, due=3, remaining=None)
    decision, _ = production_decision(active_skip)
    assert decision.fires == ()  # production: SKIP over an active Run fires nothing
    mutated = FireContractModel(active_skip, mutate="skip_as_allow")
    assert mutated.unique_beyond(decision) == z3.sat
    witness = mutated.divergent_witness(decision)
    assert witness is not None and witness["fires"] == [0, 1, 2]

    capped_allow = Cell(policy=OverlapPolicy.ALLOW, active_run=False, due=4, remaining=1)
    decision, _ = production_decision(capped_allow)
    assert len(decision.fires) == 1  # production: the cap holds
    uncapped = FireContractModel(capped_allow, mutate="no_cap")
    assert uncapped.unique_beyond(decision) == z3.sat
    witness = uncapped.divergent_witness(decision)
    assert witness is not None and len(witness["fires"]) == 4


def test_unsat_cores_explain_why_a_requested_fire_is_impossible() -> None:
    """The issue's explainability question: a requested decision the contract
    forbids is refused, and the unsat core names the rule family that blocks
    it — the same cause the procedural reason codes report."""
    # SKIP over an active Run: the overlap rule is the blocker.
    cell = Cell(policy=OverlapPolicy.SKIP, active_run=True, due=3, remaining=None)
    result, core = FireContractModel(cell).impossible_fire_core(index=2)
    assert result == z3.unsat
    assert "policy" in core and "request" in core

    # BUFFER_ONE over an active Run: the same hold rule.
    cell = Cell(policy=OverlapPolicy.BUFFER_ONE, active_run=True, due=2, remaining=None)
    result, core = FireContractModel(cell).impossible_fire_core(index=0)
    assert result == z3.unsat
    assert "policy" in core and "request" in core

    # ALLOW with a spent budget: the exhaustion flag is forced, and asking
    # for a non-exhausted evaluation is impossible.
    cell = Cell(policy=OverlapPolicy.ALLOW, active_run=False, due=4, remaining=1)
    model = FireContractModel(cell)
    solver, family = model.tracked_solver()
    solver.assert_and_track(z3.Not(model.exhausted_flag), "request_not_exhausted")
    assert solver.check() == z3.unsat
    core_families = {family.get(str(c), str(c)) for c in solver.unsat_core()}
    assert "exhaustion" in core_families and "request_not_exhausted" in core_families


@pytest.mark.parametrize("budget", [1, 2, 3])
def test_the_bounded_buffer_loop_never_starves_a_budgeted_occurrence(budget: int) -> None:
    """The issue's starvation question, as a bounded closed loop: under
    BUFFER_ONE, no run length inside the bound leaves an occurrence held
    forever while fire budget remains — the moment the Run ends, the next
    idle evaluation fires it."""
    model = BufferedStarvationModel(budget=budget)
    assert model.no_starvation_while_budget_remains() == z3.unsat
    assert model.drains_after_run_ends() == z3.unsat
    assert model.respects_budget() == z3.unsat


def test_starvation_queries_hold_occurrence_identity_not_just_a_count() -> None:
    """A 0/1 buffer count cannot tell draining the held occurrence from a
    fire that bypasses it and leaves it queued forever — both keep the count
    at 1. The ID-aware encoding distinguishes them: the faithful policy drains
    the held occurrence by ID (unsat violation), while the bypass drift that
    perpetually replaces it is flagged as starvation (sat witness)."""
    faithful = BufferedStarvationModel(budget=3)
    assert faithful.no_starvation_while_budget_remains() == z3.unsat
    assert faithful.drains_after_run_ends() == z3.unsat

    drift = BufferedStarvationModel(budget=3, mutate="bypass-held")
    assert drift.no_starvation_while_budget_remains() == z3.sat
    assert drift.drains_after_run_ends() == z3.sat


def test_a_never_ending_run_holds_the_buffer_by_design_not_starvation() -> None:
    """The one hold that never drains is the documented one: a Run that never
    ends. The solver produces the witness — the hold persists precisely while
    the run persists — distinguishing declared semantics from starvation."""
    model = BufferedStarvationModel(budget=3)
    assert model.never_ending_run_holds() == z3.sat


def test_an_exhausted_schedule_short_circuits_before_the_decision_core() -> None:
    """A zero remaining budget is decided at the schedule level: nothing is
    enumerated, nothing recorded, exhaustion reported — the grid excludes
    these cells, so the short-circuit is pinned directly."""
    schedule = Schedule(
        workspace_id="w1",
        project_id="p1",
        name="spent",
        cron="* * * * *",
        graph_template_id="tpl",
        created_at=NOON - timedelta(days=30),
        last_fired_at=NOON - timedelta(minutes=3),
        catchup_window_seconds=3600.0,
        max_runs=3,
        runs_so_far=3,
    )
    evaluation = evaluate(schedule, now=NOON, active_run=False)
    assert evaluation.fires == ()
    assert evaluation.skipped == ()
    assert evaluation.exhausted is True
    assert evaluation.next_due_at is None


def test_a_disabled_schedule_contracts_to_nothing() -> None:
    schedule = Schedule(
        workspace_id="w1",
        project_id="p1",
        name="off",
        cron="* * * * *",
        graph_template_id="tpl",
        created_at=NOON - timedelta(days=30),
        enabled=False,
    )
    evaluation = evaluate(schedule, now=NOON, active_run=True)
    assert evaluation.fires == ()
    assert evaluation.skipped == ()
    assert evaluation.next_due_at is None
    assert evaluation.exhausted is False


def test_occurrences_behind_the_catchup_horizon_are_out_of_scope_not_skipped() -> None:
    """An experimental finding pinned where it belongs: the walk starts at
    `enumeration_start` (never before the horizon), so occurrences older than
    the window are neither fired nor skipped — they are not considered, and
    the caller learns the range from `enumeration_start` (#1059). An SMT
    model that assumed an OUTSIDE_CATCHUP skip axis would encode semantics
    the engine does not have."""
    schedule = Schedule(
        workspace_id="w1",
        project_id="p1",
        name="stale",
        cron="* * * * *",
        graph_template_id="tpl",
        created_at=NOON - timedelta(days=30),
        last_fired_at=NOON - timedelta(minutes=5),
        catchup_window_seconds=150.0,
        overlap_policy=OverlapPolicy.ALLOW,
    )
    evaluation = evaluate(schedule, now=NOON)
    assert [f.scheduled_for.minute for f in evaluation.fires] == [58, 59, 0]
    assert evaluation.skipped == ()
    assert enumeration_start(schedule, now=NOON) == NOON - timedelta(seconds=150)


def test_z3_is_absent_from_production_sources() -> None:
    """The research non-goal: no solver runtime dependency in production.
    Two scans are the gate — any `z3` reference under `packages/*/src`, or
    any z3 requirement in a shipped package/extension manifest, fails here,
    so the dependency cannot drift into shipped code quietly (a dynamic
    import would evade the source scan; the manifest scan is what catches
    the dependency being declared without a static import at all)."""
    matches: list[str] = []
    for package_dir in sorted((_REPO_ROOT / "packages").glob("*/src")):
        for source in package_dir.rglob("*.py"):
            for lineno, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1):
                if "import z3" in line or "from z3" in line or line.lstrip().startswith("z3."):
                    matches.append(f"{source}:{lineno}: {line.strip()}")
    assert matches == []

    manifest_hits: list[str] = []
    for scope in ("packages", "extensions"):
        for manifest_path in sorted((_REPO_ROOT / scope).rglob("pyproject.toml")):
            manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
            for name in _requirement_names(manifest):
                if name in _SOLVER_NAMES:
                    manifest_hits.append(f"{manifest_path}: requires {name}")
    assert manifest_hits == []
