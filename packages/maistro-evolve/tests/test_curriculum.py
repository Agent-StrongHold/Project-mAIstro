"""SPEC-282: self-generated curriculum behind protected validity gates.

M4-D (#24): proposer/solver-generated challenges are admitted only when every
host-owned gate — well-formedness, reference solvability, independent-solver
solvability, baseline discrimination — affirms with executed evidence, and the
resulting practice signal can never enter external-evaluation scoring
(fitness hard gate / weighted score / harness registration).
"""

from __future__ import annotations

import pytest

from maistro_evolve.curriculum import (
    CURRICULUM_PROVENANCE,
    GATE_BASELINE_FAILS,
    GATE_REFERENCE_SOLVES,
    GATE_SOLVER_SOLVES,
    GATE_WELL_FORMED,
    GATES,
    RESERVED_BENCHMARK_PREFIX,
    AdmissionDecision,
    ChallengeDraft,
    Curriculum,
    CurriculumItem,
    GateOutcome,
    generate_curriculum,
    validate_challenge,
)

# SPEC-282's behavioral contract (ADR-032): every test here exercises the
# fail-closed admission behavior the spec declares as its contract kind.
pytestmark = [pytest.mark.contract("behavioral")]


def _draft(
    *,
    expected: str = "4",
    verify=None,
    reference_solution: str | None = "4",
    statement: str = "What is 2+2?",
    acceptance: str = "the answer is 4",
) -> ChallengeDraft:
    if verify is None:
        verify = lambda a: a.strip() == expected  # noqa: E731 — test-local checker
    return ChallengeDraft(
        statement=statement,
        acceptance=acceptance,
        verify=verify,
        reference_solution=reference_solution,
    )


async def _solver(draft: ChallengeDraft) -> str:
    return "4"


_DRAFT_KEYS = ("expected", "verify", "reference_solution", "statement", "acceptance")


def _run(**kwargs):
    """validate_challenge with the fully-satisfying default inputs."""
    draft_kwargs = {k: kwargs.pop(k) for k in _DRAFT_KEYS if k in kwargs}
    kwargs.setdefault("solver", _solver)
    kwargs.setdefault("baseline_answer", "")
    return validate_challenge(_draft(**draft_kwargs), **kwargs)


class TestProtectedGates:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_all_gates_affirm_admits(self):
        """AC-1: a challenge satisfying every gate is admitted."""
        decision = await _run()
        assert decision.admitted
        assert [o.gate for o in decision.outcomes] == list(GATES)
        assert all(o.executed and o.passed for o in decision.outcomes)

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_missing_solver_never_admits(self):
        """AC-1: no independent solver is a refusal, not a bypass."""
        decision = await _run(solver=None)
        assert not decision.admitted
        outcome = decision.outcome(GATE_SOLVER_SOLVES)
        assert outcome is not None and not outcome.executed and not outcome.passed

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_missing_baseline_never_admits(self):
        """AC-1: no baseline answer leaves degeneracy unverifiable — refused."""
        decision = await _run(baseline_answer=None)
        assert not decision.admitted
        outcome = decision.outcome(GATE_BASELINE_FAILS)
        assert outcome is not None and not outcome.executed

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_missing_reference_solution_never_admits(self):
        """AC-1: without a reference solution, solvability is unverifiable."""
        decision = await validate_challenge(
            _draft(reference_solution=None), solver=_solver, baseline_answer=""
        )
        assert not decision.admitted
        outcome = decision.outcome(GATE_REFERENCE_SOLVES)
        assert outcome is not None and not outcome.executed

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-2")
    async def test_unsatisfiable_challenge_rejected_by_its_own_reference(self):
        """AC-2: a draft whose reference solution fails its own verifier is refused."""
        decision = await validate_challenge(
            _draft(reference_solution="five"), solver=_solver, baseline_answer=""
        )
        assert not decision.admitted
        outcome = decision.outcome(GATE_REFERENCE_SOLVES)
        assert outcome is not None and outcome.executed and not outcome.passed

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-3")
    async def test_independent_solver_must_solve_it(self):
        """AC-3: a solver whose answer fails the verifier blocks admission."""

        async def wrong_solver(draft: ChallengeDraft) -> str:
            return "5"

        decision = await _run(solver=wrong_solver)
        assert not decision.admitted
        outcome = decision.outcome(GATE_SOLVER_SOLVES)
        assert outcome is not None and outcome.executed and not outcome.passed

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-3")
    async def test_sync_solver_is_supported(self):
        """AC-3: the solver seam accepts a plain (non-async) callable too."""
        decision = await _run(solver=lambda d: "4")
        assert decision.admitted

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-4")
    async def test_vacuous_verifier_rejected_by_baseline_discrimination(self):
        """AC-4: a verifier that passes anything fails the baseline gate alone."""
        decision = await _run(verify=lambda a: True)
        # Every other gate affirms — the discrimination gate is what rejects.
        for gate in (GATE_WELL_FORMED, GATE_REFERENCE_SOLVES, GATE_SOLVER_SOLVES):
            outcome = decision.outcome(gate)
            assert outcome is not None and outcome.executed and outcome.passed
        assert not decision.admitted
        baseline = decision.outcome(GATE_BASELINE_FAILS)
        assert baseline is not None and baseline.executed and not baseline.passed
        assert "degenerate" in baseline.detail

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_solver_crash_is_a_refusal_not_an_error(self):
        """AC-5: an exception in the solver seam fails closed with the reason."""

        async def exploding_solver(draft: ChallengeDraft) -> str:
            raise RuntimeError("solver down")

        decision = await _run(solver=exploding_solver)
        assert not decision.admitted
        outcome = decision.outcome(GATE_SOLVER_SOLVES)
        assert outcome is not None
        assert not outcome.executed and not outcome.passed
        assert "solver down" in outcome.detail

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_verifier_crash_cannot_admit(self):
        """AC-5: a verifier that raises yields no verdict — never an admission."""

        def exploding_verifier(answer: str) -> bool:
            raise TypeError("bad verifier")

        decision = await _run(verify=exploding_verifier)
        assert not decision.admitted
        assert not decision.outcome(GATE_REFERENCE_SOLVES).executed  # type: ignore[union-attr]
        assert not decision.outcome(GATE_SOLVER_SOLVES).executed  # type: ignore[union-attr]
        assert not decision.outcome(GATE_BASELINE_FAILS).executed  # type: ignore[union-attr]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_malformed_draft_fails_well_formed_gate(self):
        """AC-5: empty statement/acceptance is refused before anything runs."""
        decision = await validate_challenge(
            ChallengeDraft(statement="  ", acceptance="", verify=lambda a: True),
            solver=_solver,
            baseline_answer="",
        )
        assert not decision.admitted
        well_formed = decision.outcome(GATE_WELL_FORMED)
        assert well_formed is not None and not well_formed.passed
        assert "statement is empty" in well_formed.detail

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_non_string_solver_answer_is_refused(self):
        """AC-5: a solver returning a non-str has produced no gradeable answer."""

        async def weird_solver(draft: ChallengeDraft) -> str:
            return 42  # type: ignore[return-value]

        decision = await _run(solver=weird_solver)
        assert not decision.admitted
        outcome = decision.outcome(GATE_SOLVER_SOLVES)
        assert outcome is not None and not outcome.executed
        assert "not a str" in outcome.detail

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_non_callable_verifier_fails_well_formed(self):
        """AC-5: a draft without a callable checker has nothing to gate on."""
        decision = await validate_challenge(
            _draft(verify="not a callable"),  # type: ignore[arg-type]
            solver=_solver,
            baseline_answer="",
        )
        assert not decision.admitted
        well_formed = decision.outcome(GATE_WELL_FORMED)
        assert well_formed is not None and not well_formed.passed
        assert "not a callable checker" in well_formed.detail


class TestCurriculumStore:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_only_admitted_items_enter_the_store(self):
        """AC-1: the store grows only through all-gates-passed decisions."""
        curriculum = Curriculum()
        await curriculum.submit(_draft(), solver=_solver, baseline_answer="")
        await curriculum.submit(
            _draft(verify=lambda a: True),  # degenerate
            solver=_solver,
            baseline_answer="",
        )
        assert curriculum.summary() == {"admitted": 1, "rejected": 1}
        assert len(curriculum.items) == 1
        assert len(curriculum.rejected) == 1

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-6")
    async def test_item_provenance_is_pinned(self):
        """AC-6: admitted items always report the self-generated provenance."""
        curriculum = Curriculum()
        await curriculum.submit(_draft(), solver=_solver, baseline_answer="")
        assert curriculum.items[0].provenance == CURRICULUM_PROVENANCE

    @pytest.mark.ac("SPEC-282/AC-6")
    def test_item_cannot_be_rebranded_as_external(self):
        """AC-6: constructing an item under another provenance label raises."""
        draft = _draft()
        with pytest.raises(ValueError, match="provenance"):
            CurriculumItem(id="x", draft=draft, provenance="external-ifeval")

    @pytest.mark.ac("SPEC-282/AC-6")
    def test_reserved_namespace_constant_shape(self):
        """AC-6/AC-7: the reserved prefix is the exact contract fitness keys off."""
        assert RESERVED_BENCHMARK_PREFIX == "self_generated/"
        assert CURRICULUM_PROVENANCE == "self-generated"


class TestGenerateCurriculum:
    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_no_proposer_is_an_error_not_a_fabrication(self):
        """AC-5: no proposer callback raises — a curriculum is never fabricated."""
        with pytest.raises(ValueError, match="proposer"):
            await generate_curriculum(None, solver=_solver, baseline_answer="")

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_proposer_crash_skips_round_and_is_recorded(self):
        """AC-5: one broken proposal must not kill the batch nor admit anything."""
        calls = {"n": 0}

        def flaky_proposer() -> ChallengeDraft:
            calls["n"] += 1
            if calls["n"] == 2:
                raise RuntimeError("proposer blew up")
            return _draft()

        curriculum = await generate_curriculum(
            flaky_proposer, solver=_solver, baseline_answer="", rounds=3
        )
        assert curriculum.summary() == {"admitted": 2, "rejected": 0}
        assert len(curriculum.proposer_errors) == 1
        assert "proposer blew up" in curriculum.proposer_errors[0]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_async_proposer_is_awaited(self):
        """AC-5: the proposer seam accepts an async callback (the LLM case)."""

        async def async_proposer() -> ChallengeDraft:
            return _draft()

        curriculum = await generate_curriculum(
            async_proposer, solver=_solver, baseline_answer="", rounds=1
        )
        assert curriculum.summary() == {"admitted": 1, "rejected": 0}

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_non_draft_proposer_value_is_recorded_not_crashed(self):
        """AC-5: a proposer returning garbage produces no decision — recorded
        as a proposer error, never admitted, batch survives."""

        def garbage_proposer():
            return "just trust me"

        curriculum = await generate_curriculum(
            garbage_proposer, solver=_solver, baseline_answer="", rounds=2
        )
        assert curriculum.summary() == {"admitted": 0, "rejected": 0}
        assert len(curriculum.proposer_errors) == 2
        assert "not a ChallengeDraft" in curriculum.proposer_errors[0]

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-5")
    async def test_non_positive_rounds_is_refused(self):
        """AC-5: rounds < 1 asks for a curriculum from nothing — refused."""
        with pytest.raises(ValueError, match="rounds"):
            await generate_curriculum(
                lambda: _draft(), solver=_solver, baseline_answer="", rounds=0
            )

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_submit_refuses_non_draft_values(self):
        """AC-1: submit demands a ChallengeDraft — a blob has no gates to run."""
        curriculum = Curriculum()
        with pytest.raises(TypeError, match="ChallengeDraft"):
            await curriculum.submit("just trust me", solver=_solver, baseline_answer="")  # type: ignore[arg-type]
        assert curriculum.summary() == {"admitted": 0, "rejected": 0}

    @pytest.mark.asyncio
    @pytest.mark.ac("SPEC-282/AC-1")
    async def test_rejections_are_counted_not_stored(self):
        """AC-1: a batch of degenerate proposals yields an empty curriculum."""

        def degenerate_proposer() -> ChallengeDraft:
            return _draft(verify=lambda a: True)

        curriculum = await generate_curriculum(
            degenerate_proposer, solver=_solver, baseline_answer="", rounds=2
        )
        assert curriculum.summary() == {"admitted": 0, "rejected": 2}
        assert curriculum.items == ()


class TestAdmissionDecisionShape:
    @pytest.mark.ac("SPEC-282/AC-1")
    def test_empty_outcomes_is_never_admitted(self):
        """AC-1: a decision with no gate outcomes cannot admit (fail closed)."""
        decision = AdmissionDecision(draft=_draft(), outcomes=())
        assert not decision.admitted

    @pytest.mark.ac("SPEC-282/AC-1")
    def test_partial_outcomes_is_never_admitted(self):
        """AC-1: fewer outcomes than protected gates is not admission."""
        decision = AdmissionDecision(
            draft=_draft(),
            outcomes=(GateOutcome(gate=GATE_WELL_FORMED, executed=True, passed=True),),
        )
        assert not decision.admitted

    @pytest.mark.ac("SPEC-282/AC-1")
    def test_outcome_lookup_for_unknown_gate_is_none(self):
        """AC-1: asking a decision about a gate it never ran reports None."""
        decision = AdmissionDecision(draft=_draft(), outcomes=())
        assert decision.outcome(GATE_WELL_FORMED) is None
