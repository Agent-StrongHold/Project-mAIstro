"""Self-generated curriculum: proposer/solver challenges behind protected validity gates.

Implements the M4-D intent (#24, initiative #450): a proposer may generate
practice challenges and a solver may attempt them, but a generated challenge is
admitted to the curriculum **only** behind independent, host-owned
solvability/validity checks — and the resulting practice signal can never
displace external evaluation.

Why the gates are shaped the way they are (DR-Zero proposer/solver
co-evolution, filtered through this repo's protected-evaluator/quarantine
principles):

* **Self-certification is the failure mode.** A proposer that also owns the
  verdict can emit unsatisfiable, trivial, or self-grading challenges. So the
  gates below are *host-owned* functions in this module — the proposer's draft
  carries a mechanical ``verify`` callable, but nothing in the draft can mark
  itself admitted, and no single gate can admit on its own.
* **Each gate kills one degenerate proposer strategy:**

  ============================  ==============================================
  Gate                          Rejects a challenge that is...
  ============================  ==============================================
  ``well_formed``               empty, undescribed, or carries no verifier
  ``reference_solves``          unsatisfiable (its own reference solution fails)
  ``solver_solves``             unsolvable in practice (an independent solver
                                distinct from the proposer cannot solve it)
  ``baseline_fails``            vacuous (a trivial baseline passes the verifier)
  ============================  ==============================================

* **Fail closed, like quarantine (#347).** A gate that cannot produce a
  verdict — missing input, raised exception — is recorded as *not executed and
  not passed*. Admission requires every gate executed *and* passed; an absent
  gate input is a refusal, never a bypass. "The challenge was rejected" and
  "the challenge could not be checked" stay different facts, both of which are
  refusals.
* **Provenance is pinned.** Every admitted item reports
  ``CURRICULUM_PROVENANCE`` and refuses any other label, so curriculum
  practice cannot be rebranded as external evidence downstream.
* **Never replaces external evaluation.** Curriculum practice scores live
  under the reserved ``RESERVED_BENCHMARK_PREFIX`` namespace. ``fitness``
  refuses those keys at the hard gate and excludes them from the weighted eval
  score, and ``EvalHarness`` refuses to register a benchmark under the
  reserved namespace (SPEC-282): a genome must still earn its fitness on
  external benchmarks, and a genome scored *only* on self-generated challenges
  cannot breed.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from inspect import isawaitable
from typing import Any

__all__ = [
    "CURRICULUM_PROVENANCE",
    "GATE_BASELINE_FAILS",
    "GATE_REFERENCE_SOLVES",
    "GATE_SOLVER_SOLVES",
    "GATE_WELL_FORMED",
    "RESERVED_BENCHMARK_PREFIX",
    "AdmissionDecision",
    "ChallengeDraft",
    "Curriculum",
    "CurriculumItem",
    "GateOutcome",
    "generate_curriculum",
    "validate_challenge",
]

#: Pinned provenance of every admitted curriculum item. Practice signal is
#: always *labelled* self-generated; an item claiming another provenance is a
#: tamper attempt and raises at construction.
CURRICULUM_PROVENANCE = "self-generated"

#: Reserved benchmark namespace for curriculum practice scores. Anything under
#: this prefix is not external evaluation: ``fitness`` hard-gate-fails and
#: skips it, and ``EvalHarness.register_benchmark`` refuses it outright
#: (SPEC-282 AC-7/AC-8). Never shorten it to a bare prefix check on ``"self"``
#: — the namespace, not the adjective, is the contract.
RESERVED_BENCHMARK_PREFIX = "self_generated/"

GATE_WELL_FORMED = "well_formed"
GATE_REFERENCE_SOLVES = "reference_solves"
GATE_SOLVER_SOLVES = "solver_solves"
GATE_BASELINE_FAILS = "baseline_fails"

#: The protected gate set, in execution order. Admission requires *all* of
#: them; a caller cannot weaken the set without replacing this module.
GATES: tuple[str, ...] = (
    GATE_WELL_FORMED,
    GATE_REFERENCE_SOLVES,
    GATE_SOLVER_SOLVES,
    GATE_BASELINE_FAILS,
)


@dataclass(frozen=True)
class ChallengeDraft:
    """One proposed challenge, exactly as the proposer produced it.

    ``verify`` is the mechanical acceptance check. It is carried on the draft
    but it is *not* trusted: the gates below execute it against inputs the
    proposer did not choose (an independent solver's answer, a trivial
    baseline, the draft's own reference solution), which is what turns a
    claim into a check.
    """

    statement: str
    acceptance: str
    verify: Checker
    reference_solution: str | None = None
    proposer: str = "unattributed"


#: Mechanical verifier shipped with a draft: maps an answer to "solved".
#: Deliberately a plain callable, not a network call — a verifier that needs a
#: model to grade is not an independent check, it is a second opinion.
Checker = Callable[[str], bool]

#: Proposer callback: returns one fresh draft per call, or raises.
ProposeFn = Callable[[], Awaitable[ChallengeDraft]]

#: Independent solver callback: returns the solver's answer for a draft.
#: Deliberately a *separate* seam from the proposer — the same actor playing
#: both roles is the self-certification this module exists to prevent.
SolverFn = Callable[[ChallengeDraft], Awaitable[str]]


@dataclass(frozen=True)
class GateOutcome:
    """One protected gate's verdict on one draft.

    ``executed`` means the gate produced a definite verdict; a missing input
    or a raised exception leaves ``executed=False``. ``passed`` is True only
    for affirmative evidence. Admission needs ``executed and passed`` from
    every gate, so *both* refusal kinds — "checked and failed" and "could not
    be checked" — fail closed while staying distinguishable in ``detail``.
    """

    gate: str
    executed: bool
    passed: bool
    detail: str = ""


@dataclass(frozen=True)
class AdmissionDecision:
    """Outcome of running the protected gate set against one draft."""

    draft: ChallengeDraft
    outcomes: tuple[GateOutcome, ...] = field(default=())

    @property
    def admitted(self) -> bool:
        """True iff every protected gate executed and passed — all or nothing."""
        return len(self.outcomes) == len(GATES) and all(
            o.executed and o.passed for o in self.outcomes
        )

    def outcome(self, gate: str) -> GateOutcome | None:
        for o in self.outcomes:
            if o.gate == gate:
                return o
        return None


def _check_well_formed(draft: ChallengeDraft) -> GateOutcome:
    problems: list[str] = []
    if not isinstance(draft.statement, str) or not draft.statement.strip():
        problems.append("statement is empty")
    if not isinstance(draft.acceptance, str) or not draft.acceptance.strip():
        problems.append("acceptance criteria are empty")
    if not callable(draft.verify):
        problems.append("verify is not a callable checker")
    return GateOutcome(
        gate=GATE_WELL_FORMED,
        executed=True,
        passed=not problems,
        detail="; ".join(problems),
    )


async def validate_challenge(
    draft: ChallengeDraft,
    *,
    solver: SolverFn | None,
    baseline_answer: str | None,
) -> AdmissionDecision:
    """Run the protected gate set against ``draft``. Fails closed throughout.

    ``solver`` must be an independent solver seam and ``baseline_answer`` a
    trivial non-answer; either being ``None`` (or any gate raising) is a
    refusal recorded in the decision, never an admission.
    """
    outcomes: list[GateOutcome] = [_check_well_formed(draft)]

    # reference_solves — the draft's own reference solution must satisfy its
    # own verifier. Kills unsatisfiable challenges.
    if draft.reference_solution is None:
        outcomes.append(
            GateOutcome(
                gate=GATE_REFERENCE_SOLVES,
                executed=False,
                passed=False,
                detail="no reference solution — solvability unverifiable",
            )
        )
    else:
        outcomes.append(
            await _run_check(
                GATE_REFERENCE_SOLVES,
                lambda: _verify_solved(draft, draft.reference_solution or ""),
                expect=True,
                failure_detail="reference solution does not satisfy the verifier",
            )
        )

    # solver_solves — an independent solver must solve it. Kills challenges
    # that are unsatisfiable in practice, not just on paper.
    if solver is None:
        outcomes.append(
            GateOutcome(
                gate=GATE_SOLVER_SOLVES,
                executed=False,
                passed=False,
                detail="no independent solver — admission refused",
            )
        )
    else:
        outcomes.append(await _run_solver_gate(draft, solver))

    # baseline_fails — a trivial baseline must NOT solve it. Kills vacuous
    # verifiers that would grade any output as correct.
    if baseline_answer is None:
        outcomes.append(
            GateOutcome(
                gate=GATE_BASELINE_FAILS,
                executed=False,
                passed=False,
                detail="no baseline answer — degeneracy unverifiable",
            )
        )
    else:
        outcomes.append(
            await _run_check(
                GATE_BASELINE_FAILS,
                lambda: _verify_solved(draft, baseline_answer),
                expect=False,
                failure_detail=("trivial baseline passes the verifier — challenge is degenerate"),
            )
        )

    return AdmissionDecision(draft=draft, outcomes=tuple(outcomes))


async def _run_solver_gate(draft: ChallengeDraft, solver: SolverFn) -> GateOutcome:
    try:
        answer: Any = solver(draft)
        if isawaitable(answer):
            answer = await answer
        if not isinstance(answer, str):
            return GateOutcome(
                gate=GATE_SOLVER_SOLVES,
                executed=False,
                passed=False,
                detail=f"solver returned {type(answer).__name__}, not a str answer",
            )
    except Exception as exc:
        return GateOutcome(
            gate=GATE_SOLVER_SOLVES,
            executed=False,
            passed=False,
            detail=f"solver failed: {type(exc).__name__}: {exc}",
        )
    return await _run_check(
        GATE_SOLVER_SOLVES,
        lambda: _verify_solved(draft, answer),
        expect=True,
        failure_detail="independent solver's answer does not satisfy the verifier",
    )


async def _run_check(
    gate: str,
    check: Callable[[], bool],
    *,
    expect: bool,
    failure_detail: str,
) -> GateOutcome:
    """Run one verifier probe; a crash is a refusal, never a pass."""
    try:
        verdict = bool(check())
    except Exception as exc:
        return GateOutcome(
            gate=gate,
            executed=False,
            passed=False,
            detail=f"verifier raised {type(exc).__name__}: {exc}",
        )
    return GateOutcome(
        gate=gate,
        executed=True,
        passed=verdict == expect,
        detail="" if verdict == expect else failure_detail,
    )


def _verify_solved(draft: ChallengeDraft, answer: str) -> bool:
    return bool(draft.verify(answer))


@dataclass(frozen=True)
class CurriculumItem:
    """An admitted challenge. Provenance is pinned at construction."""

    id: str
    draft: ChallengeDraft
    provenance: str = CURRICULUM_PROVENANCE

    def __post_init__(self) -> None:
        if self.provenance != CURRICULUM_PROVENANCE:
            raise ValueError(
                f"a curriculum item always reports provenance "
                f"{CURRICULUM_PROVENANCE!r}; got {self.provenance!r} — practice "
                "signal cannot be rebranded as external evaluation evidence "
                "(SPEC-282 AC-6)"
            )


class Curriculum:
    """The admitted-only store of self-generated challenges.

    The only way in is :meth:`submit`, and it admits solely on an affirmative
    all-gates-passed decision — there is no constructor bypass and no direct
    item insertion, so an unvalidated challenge has no path into the store.
    """

    def __init__(self) -> None:
        self._items: list[CurriculumItem] = []
        self._rejected: list[AdmissionDecision] = []
        # Drafts the proposer failed to produce at all (exception, or a
        # non-draft value). Recorded so a broken proposer is visible in the
        # batch summary instead of silently shrinking the round count.
        self.proposer_errors: list[str] = []

    @property
    def items(self) -> tuple[CurriculumItem, ...]:
        return tuple(self._items)

    @property
    def rejected(self) -> tuple[AdmissionDecision, ...]:
        return tuple(self._rejected)

    async def submit(
        self,
        draft: ChallengeDraft,
        *,
        solver: SolverFn | None,
        baseline_answer: str | None,
    ) -> AdmissionDecision:
        """Validate ``draft`` through the protected gates; store it iff admitted."""
        if not isinstance(draft, ChallengeDraft):
            raise TypeError(
                f"submit requires a ChallengeDraft, got {type(draft).__name__} — "
                "an untyped blob has no gates to run"
            )
        decision = await validate_challenge(draft, solver=solver, baseline_answer=baseline_answer)
        if decision.admitted:
            self._items.append(CurriculumItem(id=uuid.uuid4().hex, draft=draft))
        else:
            self._rejected.append(decision)
        return decision

    def summary(self) -> dict[str, int]:
        # Read through the public accessors so the store's own reporting and
        # any caller's inspection agree on one definition of each count.
        return {"admitted": len(self.items), "rejected": len(self.rejected)}


async def generate_curriculum(
    propose: ProposeFn | None,
    *,
    solver: SolverFn,
    baseline_answer: str,
    rounds: int = 1,
) -> Curriculum:
    """Propose up to ``rounds`` drafts and gate each through :meth:`Curriculum.submit`.

    A proposer crash is recorded in ``curriculum.proposer_errors`` and skips
    that round — it is not a challenge, so it produces no decision and can
    never admit anything.
    """
    if propose is None:
        raise ValueError(
            "generate_curriculum requires a proposer callback; there is no "
            "fabrication fallback — a curriculum nobody actually proposed is "
            "not a curriculum (same posture as benchmarks with llm_call=None)"
        )
    if rounds < 1:
        raise ValueError("rounds must be >= 1")

    curriculum = Curriculum()
    for _ in range(rounds):
        try:
            # `Any`-typed seam, exactly like the solver gate: the callback may be
            # sync or async, and mypy must not pin the variable to Awaitable.
            proposed: Any = propose()
            if isawaitable(proposed):
                proposed = await proposed
            draft = proposed
        except Exception as exc:
            curriculum.proposer_errors.append(f"{type(exc).__name__}: {exc}")
            continue
        if not isinstance(draft, ChallengeDraft):
            # Same containment posture as a raise: garbage that isn't a draft
            # produces no decision and can never admit anything.
            curriculum.proposer_errors.append(
                f"proposer returned {type(draft).__name__}, not a ChallengeDraft"
            )
            continue
        await curriculum.submit(draft, solver=solver, baseline_answer=baseline_answer)
    return curriculum
