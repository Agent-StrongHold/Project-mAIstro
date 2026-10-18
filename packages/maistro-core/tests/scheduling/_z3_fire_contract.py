"""Z3/SMT encoding of the schedule fire/skip contract (#891, M8-A11 research).

M8-A11 asks whether direct SMT modeling clarifies a constraint-heavy MAIstro
decision or merely duplicates its procedural logic. This module is the bounded
experiment for one representative target: the pure fire/skip decision core of
`maistro.scheduling.engine.evaluate` — overlap policy x active-run x
max_runs exhaustion, the combination the overlap-policy docstrings promise
semantics for.

Two models live here:

`FireContractModel` encodes one evaluation cell's contract as SMT constraints
over decision variables (which due occurrence fires, with which skip reason,
whether the in-flight run is cancelled, whether the evaluation reports
exhaustion). The rules are transcribed from the *documented* semantics — the
`OverlapPolicy` docstrings, the `SkipReason.BUFFERED` contract, the
exhaustion rule on `ScheduleEvaluation.exhausted` — not from the code paths.
The queries compare the production function against that contract over the
whole bounded cell grid:

- `conforms`: production's concrete decision satisfies the contract (sat);
- `unique_beyond`: no *other* contract-satisfying decision exists (unsat) —
  a completeness claim over the entire bounded space, which sampled property
  tests cannot make;
- mutation flags (`mutate=`) deliberately drift the encoding so the teeth of
  the differential can be measured;
- `impossible_fire_core` asks the solver to explain a requested fire that the
  contract forbids, via an unsat core.

`BufferedStarvationModel` is a closed-loop unrolling of the BUFFER_ONE policy
over T ticks — arrivals, the single held occurrence carried across
evaluations, run lengths, and the max_runs budget — answering the issue's
"can scheduler constraints produce starvation under a bounded model" question
for every run length inside the bound at once.

Bounded-space note (an experimental finding, not an assumption): occurrences
older than the catch-up horizon sit behind `enumeration_start` and are
*neither fired nor skipped* — `evaluate` never emits `OUTSIDE_CATCHUP` on
this path, so the per-cell space has no stale axis; the horizon semantics are
pinned directly by a test instead.

This is research machinery: it lives in the test tree, imports z3 (a
dev-only dependency), and must never be referenced from `packages/*/src`.
The conformance test module scans for that. The evidence record and
disposition are `docs/testing/z3-smt-decisions-evidence.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import product

import z3

from maistro.scheduling.engine import ScheduleEvaluation, SkipReason, evaluate
from maistro.scheduling.model import OverlapPolicy, Schedule

__all__ = [
    "NOON",
    "QUERY_TIMEOUT_MS",
    "BufferedStarvationModel",
    "Cell",
    "Decision",
    "FireContractModel",
    "iter_cells",
    "production_decision",
]

NOON = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)

#: Per-query solver timeout. A structural bound against a runaway encode, not
#: a performance claim — measured times land orders of magnitude below it.
QUERY_TIMEOUT_MS = 10_000

POLICY_SKIP: z3.ExprRef
POLICY_ALLOW: z3.ExprRef
POLICY_CANCEL_OTHER: z3.ExprRef
POLICY_BUFFER_ONE: z3.ExprRef
_POLICY_SORT, (POLICY_SKIP, POLICY_ALLOW, POLICY_CANCEL_OTHER, POLICY_BUFFER_ONE) = z3.EnumSort(
    "OverlapPolicy", ["skip", "allow", "cancel_other", "buffer_one"]
)

REASON_NONE: z3.ExprRef
REASON_OVERLAP: z3.ExprRef
REASON_EXHAUSTED: z3.ExprRef
REASON_BUFFERED: z3.ExprRef
_REASON_SORT, (REASON_NONE, REASON_OVERLAP, REASON_EXHAUSTED, REASON_BUFFERED) = z3.EnumSort(
    "SkipReason", ["none", "overlap", "exhausted", "buffered"]
)

_Z3_POLICY = {
    OverlapPolicy.SKIP: POLICY_SKIP,
    OverlapPolicy.ALLOW: POLICY_ALLOW,
    OverlapPolicy.CANCEL_OTHER: POLICY_CANCEL_OTHER,
    OverlapPolicy.BUFFER_ONE: POLICY_BUFFER_ONE,
}
_Z3_REASON = {
    "none": REASON_NONE,
    "overlap": REASON_OVERLAP,
    "exhausted": REASON_EXHAUSTED,
    "buffered": REASON_BUFFERED,
}


@dataclass(frozen=True)
class Cell:
    """One bounded decision cell: the inputs one `evaluate` call decides on.

    `due` per-minute occurrences are due at NOON and enumerated by the
    catch-up walk (a wide catch-up window covers them all, so every due
    occurrence reaches the decision core — see the module note on the
    horizon). `remaining` is `Schedule.runs_remaining` (None = unbounded). A
    cell with `remaining == 0` never reaches the decision core — the schedule
    is already exhausted and `evaluate` short-circuits — so the contract grid
    excludes it and a dedicated test pins the short-circuit itself.
    """

    policy: OverlapPolicy
    active_run: bool
    due: int
    remaining: int | None = None


@dataclass(frozen=True)
class Decision:
    """The concrete decision for one cell: ascending fired indices, the skip
    reason per due index, the cancellation request, the exhaustion flag."""

    fires: tuple[int, ...]
    reasons: tuple[str, ...]
    cancel_active_run: bool
    exhausted: bool


def iter_cells() -> list[Cell]:
    """The whole bounded grid the experiment certifies.

    due 0..5, every policy, both active-run states, and every budget from 1
    past the largest due count plus the unbounded budget.
    """
    cells: list[Cell] = []
    budgets: list[int | None] = [None, *range(1, 7)]
    for due, policy, active, remaining in product(
        range(0, 6), list(OverlapPolicy), [False, True], budgets
    ):
        cells.append(Cell(policy=policy, active_run=active, due=due, remaining=remaining))
    return cells


def production_decision(cell: Cell) -> tuple[Decision, ScheduleEvaluation]:
    """Run the production decision core on a real Schedule shaped as `cell`.

    The per-minute cron makes occurrence identity boring on purpose:
    moment_i = NOON - (due - i) minutes for i = 1..due, so the newest due
    occurrence sits exactly at NOON. `last_fired_at` precedes all of them and
    the catch-up window covers the whole range, so the walk enumerates all
    `due` occurrences and none are truncated.
    """
    schedule = Schedule(
        workspace_id="w1",
        project_id="p1",
        name="z3-grid",
        cron="* * * * *",
        graph_template_id="tpl",
        created_at=NOON - timedelta(days=30),
        last_fired_at=NOON - timedelta(minutes=cell.due),
        catchup_window_seconds=3600.0,
        overlap_policy=cell.policy,
        **(
            {}
            if cell.remaining is None
            else {"max_runs": cell.remaining + cell.due, "runs_so_far": cell.due}
        ),
    )
    evaluation = evaluate(schedule, now=NOON, active_run=cell.active_run)

    moments = [NOON - timedelta(minutes=cell.due - i) for i in range(1, cell.due + 1)]
    moment_index = {m: i for i, m in enumerate(moments)}
    fires = tuple(sorted(moment_index[f.scheduled_for] for f in evaluation.fires))

    reason_by_moment: dict[datetime, str] = {}
    for skipped in evaluation.skipped:
        assert skipped.reason is not SkipReason.TRUNCATED, "bounded grid must not truncate"
        assert skipped.reason is not SkipReason.OUTSIDE_CATCHUP, "wide window: nothing is stale"
        reason_by_moment[skipped.scheduled_for] = skipped.reason.value
    reasons = tuple(reason_by_moment.get(m, "none") for m in moments)

    decision = Decision(
        fires=fires,
        reasons=reasons,
        cancel_active_run=evaluation.cancel_active_run,
        exhausted=evaluation.exhausted,
    )
    assert all(r in _Z3_REASON for r in reasons)
    return decision, evaluation


class FireContractModel:
    """The documented fire/skip contract for one cell, as SMT constraints.

    `mutate` deliberately drifts the encoding to measure the differential's
    sensitivity: `"skip_as_allow"` encodes a SKIP cell with the ALLOW rule,
    `"no_cap"` drops the max_runs cap. Each mutation must turn some cell's
    uniqueness query satisfiable — that is the teeth guard.
    """

    def __init__(self, cell: Cell, mutate: str | None = None) -> None:
        self.cell = cell
        self.mutate = mutate
        n = cell.due
        self.fire = [z3.Bool(f"fire_{i}") for i in range(n)]
        self.reason = [z3.Const(f"reason_{i}", _REASON_SORT) for i in range(n)]
        self.cancel = z3.Bool("cancel_active_run")
        self.exhausted_flag = z3.Bool("exhausted_flag")
        self.labels: list[tuple[str, z3.ExprRef]] = []
        self._encoded = False

    # -- encoding ---------------------------------------------------------

    def _add(self, label: str, constraint: z3.ExprRef | bool) -> None:
        self.labels.append((label, constraint))

    def _prefix_rule(self, to_fire: int, reason_tail: z3.ExprRef) -> None:
        """The earliest `to_fire` occurrences fire; the rest get `reason_tail`.

        The shared shape of every policy's decision: fire a prefix of the due
        vector, explain the remainder with one reason.
        """
        for i in range(self.cell.due):
            if i < to_fire:
                self._add("policy", self.fire[i])
                self._add("policy", self.reason[i] == REASON_NONE)
            else:
                self._add("policy", z3.Not(self.fire[i]))
                self._add("policy", self.reason[i] == reason_tail)

    def _encode(self) -> None:
        if self._encoded:
            return
        self._encoded = True
        cell, n = self.cell, self.cell.due

        # Accounting: an occurrence either fires or carries exactly one reason.
        for i in range(n):
            self._add("accounting", self.fire[i] == (self.reason[i] == REASON_NONE))

        self.capped = cell.remaining is not None and self.mutate != "no_cap"

        if n == 0:
            # Nothing due: nothing fires, nothing cancels, nothing exhausts.
            self._add("policy", z3.Not(self.cancel))
            self._add("policy", z3.Not(self.exhausted_flag))
            return

        policy = _Z3_POLICY[cell.policy]
        if self.mutate == "skip_as_allow" and cell.policy is OverlapPolicy.SKIP:
            policy = POLICY_ALLOW

        {
            POLICY_ALLOW: self._encode_allow,
            POLICY_SKIP: self._encode_skip,
            POLICY_CANCEL_OTHER: self._encode_cancel_other,
            POLICY_BUFFER_ONE: self._encode_buffer_one,
        }[policy]()
        self._encode_exhaustion(policy is POLICY_ALLOW)

    def _encode_allow(self) -> None:
        """The whole due vector wants to fire, the budget allowing; the
        refused tail is named exhaustion."""
        remaining, n = self.cell.remaining, self.cell.due
        if self.capped:
            assert remaining is not None
            self._prefix_rule(min(n, remaining), REASON_EXHAUSTED)
        else:
            self._prefix_rule(n, REASON_NONE)
        self._add("policy", z3.Not(self.cancel))

    def _encode_skip(self) -> None:
        """An in-flight Run is kept: nothing fires. Idle, the first
        occurrence fires and itself becomes the in-flight Run, so later
        occurrences in the same batch overlap it."""
        if self.cell.active_run:
            self._prefix_rule(0, REASON_OVERLAP)
        else:
            self._prefix_rule(1, REASON_OVERLAP)
        self._add("policy", z3.Not(self.cancel))

    def _encode_cancel_other(self) -> None:
        """Only the newest occurrence matters when the rule is latest-wins."""
        n = self.cell.due
        for i in range(n):
            newest = i == n - 1
            self._add("policy", self.fire[i] == z3.BoolVal(newest))
            self._add(
                "policy",
                self.reason[i] == (REASON_NONE if newest else REASON_OVERLAP),
            )
        self._add("policy", self.cancel == z3.BoolVal(self.cell.active_run))

    def _encode_buffer_one(self) -> None:
        """At most one queued occurrence, held until the active Run finishes;
        everything older than the held one is dropped."""
        n = self.cell.due
        self._add("policy", z3.Not(self.cancel))
        if self.cell.active_run:
            # Nothing fires; the newest occurrence is the one held, older
            # arrivals are dropped as overlap. (With a single due occurrence
            # the hold *is* the whole decision.)
            for i in range(n - 1):
                self._add("policy", z3.Not(self.fire[i]))
                self._add("policy", self.reason[i] == REASON_OVERLAP)
            self._add("policy", self.reason[n - 1] == REASON_BUFFERED)
        else:
            # Idle: the first occurrence fires and becomes the in-flight Run;
            # the newest stays queued; arrivals between them are dropped as
            # overlap.
            self._add("policy", self.fire[0])
            self._add("policy", self.reason[0] == REASON_NONE)
            for i in range(1, n - 1):
                self._add("policy", z3.Not(self.fire[i]))
                self._add("policy", self.reason[i] == REASON_OVERLAP)
            if n >= 2:
                self._add("policy", z3.Not(self.fire[n - 1]))
                self._add("policy", self.reason[n - 1] == REASON_BUFFERED)

    def _encode_exhaustion(self, is_allow: bool) -> None:
        """max_runs: the cap applies to the fires the policy produced, oldest
        first, and refusals are named. Only ALLOW can produce more fires than
        any reachable budget — every other policy fires at most one occurrence
        and the zero-budget schedule short-circuits before the core — so
        `exhausted` refusals encode exactly on ALLOW tails."""
        cell, n, remaining = self.cell, self.cell.due, self.cell.remaining
        to_fire = {
            OverlapPolicy.ALLOW: n,
            OverlapPolicy.SKIP: 0 if cell.active_run else 1,
            OverlapPolicy.CANCEL_OTHER: 1,
            OverlapPolicy.BUFFER_ONE: 0 if cell.active_run else 1,
        }[
            OverlapPolicy.SKIP
            if self.mutate == "skip_as_allow" and cell.policy is OverlapPolicy.SKIP
            else cell.policy
        ]
        if self.capped:
            assert remaining is not None
            fires_allowed = z3.Sum([z3.If(f, 1, 0) for f in self.fire])
            self._add("exhaustion", fires_allowed <= remaining)
            for i in range(n):
                refused = is_allow and i >= remaining
                self._add(
                    "exhaustion",
                    (self.reason[i] == REASON_EXHAUSTED) == z3.BoolVal(refused),
                )
            self._add(
                "exhaustion",
                self.exhausted_flag == z3.BoolVal(remaining <= to_fire),
            )
        else:
            for i in range(n):
                self._add("exhaustion", z3.Not(self.reason[i] == REASON_EXHAUSTED))
            self._add("exhaustion", z3.Not(self.exhausted_flag))

    # -- queries ----------------------------------------------------------

    def _decision_equals(self, decision: Decision) -> z3.ExprRef | bool:
        equalities: list[z3.ExprRef | bool] = [
            self.cancel == decision.cancel_active_run,
            self.exhausted_flag == decision.exhausted,
        ]
        for i in range(self.cell.due):
            equalities.append(self.fire[i] == (i in decision.fires))
            equalities.append(self.reason[i] == _Z3_REASON[decision.reasons[i]])
        return z3.And(*equalities)

    def _solver_with(self, *extra: z3.ExprRef | bool) -> z3.Solver:
        """A solver carrying the whole contract plus `extra`."""
        self._encode()
        solver = z3.Solver()
        solver.set("timeout", QUERY_TIMEOUT_MS)
        for _label, constraint in self.labels:
            solver.add(constraint)
        for constraint in extra:
            solver.add(constraint)
        return solver

    def conforms(self, decision: Decision) -> z3.CheckSatResult:
        """sat iff production's decision satisfies the contract."""
        return self._solver_with(self._decision_equals(decision)).check()

    def unique_beyond(self, decision: Decision) -> z3.CheckSatResult:
        """sat iff some *other* contract-satisfying decision exists.

        Expected unsat everywhere: the procedural implementation is then the
        unique function satisfying the documented contract on the whole
        bounded cell grid. A sat result is a divergence to investigate.
        """
        return self._solver_with(z3.Not(self._decision_equals(decision))).check()

    def divergent_witness(self, decision: Decision) -> dict[str, object] | None:
        """A concrete contract-satisfying decision that differs from `decision`."""
        solver = self._solver_with(z3.Not(self._decision_equals(decision)))
        if solver.check() != z3.sat:
            return None
        model = solver.model()
        return {
            "fires": [i for i, f in enumerate(self.fire) if z3.is_true(model.eval(f, True))],
            "reasons": [str(model.eval(r, True)) for r in self.reason],
            "cancel_active_run": z3.is_true(model.eval(self.cancel, True)),
            "exhausted": z3.is_true(model.eval(self.exhausted_flag, True)),
        }

    def tracked_solver(self, *extra: z3.ExprRef | bool) -> tuple[z3.Solver, dict[str, str]]:
        """A solver with every contract constraint tracked under a unique name.

        z3 refuses a repeated tracking name, and the encoding asserts many
        constraints per rule family, so each assertion gets a suffixed name
        and `family` maps every name back to its family — an unsat core read
        through it names rule families, not individual constraints.
        """
        self._encode()
        solver = z3.Solver()
        solver.set("timeout", QUERY_TIMEOUT_MS)
        family: dict[str, str] = {}
        counts: dict[str, int] = {}
        for label, constraint in self.labels:
            k = counts.get(label, 0)
            counts[label] = k + 1
            name = label if k == 0 else f"{label}#{k}"
            solver.assert_and_track(constraint, name)
            family[name] = label
        for constraint in extra:
            solver.add(constraint)
        return solver, family

    def impossible_fire_core(self, index: int) -> tuple[z3.CheckSatResult, list[str]]:
        """Ask the solver to explain why occurrence `index` cannot fire.

        The request is asserted against the *tracked* contract constraints so
        an unsat result yields a core: the named rule families that block the
        fire. That is the explainability question — can the solver say *why*
        a requested decision is impossible, and does the explanation name the
        same cause the procedural reason codes name?
        """
        solver, family = self.tracked_solver()
        solver.assert_and_track(self.fire[index], "request")
        result = solver.check()
        if result != z3.unsat:
            return result, []
        families = {family.get(str(name), str(name)) for name in solver.unsat_core()}
        return result, sorted(families)


class BufferedStarvationModel:
    """BUFFER_ONE as a closed loop over T ticks — the starvation question.

    One occurrence arrives per tick. While a Run is in flight nothing fires
    and the newest occurrence is held (older arrivals are dropped, per the
    "at most one queued" rule). When idle, one occurrence fires — the oldest
    due, so the held one is never starved by newer arrivals. Firing starts a
    Run of symbolic length `run_length` ticks; `budget` bounds total fires
    (the max_runs rule). Every run length and interleaving inside the bound
    is explored symbolically, in one query per property.
    """

    TICKS = 4
    NEVER = 99  # a run length beyond the horizon: the Run never ends within it

    def __init__(self, budget: int) -> None:
        self.budget = budget
        self.run_length = z3.Int("run_length")
        self.buffer = [z3.Int(f"buffer_{t}") for t in range(self.TICKS + 1)]
        self.run_left = [z3.Int(f"run_left_{t}") for t in range(self.TICKS + 1)]
        self.spent = [z3.Int(f"spent_{t}") for t in range(self.TICKS + 1)]
        self.fire = [z3.Bool(f"fire_{t}") for t in range(self.TICKS)]

    def _solver_with(self, *extra: z3.ExprRef | bool) -> z3.Solver:
        solver = z3.Solver()
        solver.set("timeout", QUERY_TIMEOUT_MS)
        solver.add(self.run_length >= 1)
        solver.add(self.run_length <= self.NEVER)
        solver.add(self.buffer[0] == 0)
        solver.add(self.run_left[0] == self.run_length)
        solver.add(self.spent[0] == 0)
        for t in range(self.TICKS):
            idle = self.run_left[t] == 0
            budgeted = self.spent[t] < self.budget
            solver.add(self.fire[t] == z3.And(idle, budgeted))
            # Idle and within budget: fire the oldest due occurrence (the
            # held one when there is one); the newest arrival is then the one
            # held. In flight, or idle with the budget spent: hold the newest
            # arrival, drop older ones — the buffer never exceeds one and
            # never drains while the Run keeps going (or the budget is gone).
            solver.add(
                self.buffer[t + 1] == z3.If(self.fire[t], z3.If(self.buffer[t] >= 1, 1, 0), 1)
            )
            solver.add(self.spent[t + 1] == self.spent[t] + z3.If(self.fire[t], 1, 0))
            solver.add(
                self.run_left[t + 1]
                == z3.If(self.fire[t], self.run_length, z3.If(idle, 0, self.run_left[t] - 1))
            )
        for constraint in extra:
            solver.add(constraint)
        return solver

    def no_starvation_while_budget_remains(self) -> z3.CheckSatResult:
        """unsat iff every idle tick holding an occurrence fires within budget."""
        violations: list[z3.ExprRef | bool] = []
        for t in range(self.TICKS):
            violations.append(
                z3.And(
                    self.run_left[t] == 0,
                    self.buffer[t] >= 1,
                    self.spent[t] < self.budget,
                    z3.Not(self.fire[t]),
                )
            )
        return self._solver_with(z3.Or(*violations)).check()

    def drains_after_run_ends(self) -> z3.CheckSatResult:
        """unsat iff a run that ends within the horizon lets the buffer fire."""
        return self._solver_with(
            self.run_length <= 3,  # a real run: ends within the horizon
            z3.Not(z3.Or(*self.fire)),
        ).check()

    def respects_budget(self) -> z3.CheckSatResult:
        """unsat iff the loop never exceeds the fire budget."""
        return self._solver_with(self.spent[self.TICKS] > self.budget).check()

    def never_ending_run_holds(self) -> z3.CheckSatResult:
        """sat iff a Run that never ends keeps the buffer holding, unfired."""
        solver = self._solver_with(
            self.run_length == self.NEVER,
            *[self.fire[t] == z3.BoolVal(False) for t in range(self.TICKS)],
        )
        return solver.check()
