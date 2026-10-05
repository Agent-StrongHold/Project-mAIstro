"""Coverage for memory/learnings/gauntlet.py and its promoter wiring (M4-B2,
plus the M4-B5 outcome-evidence gauntlet and anti-pattern capture, #121).

The property under test: local success alone cannot create shared
institutional knowledge. A learning proposed for collective reuse must
survive independent evaluation — trials in contexts other than the one that
produced it, of frozen candidate content, executed as canonical Runs — before
it promotes, and a rejected candidate keeps its evidence while the repertoire
stays closed to it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest

from maistro.agents.context_builder import _render_learnings_block
from maistro.graph import Graph, Node
from maistro.memory.learnings.gauntlet import (
    GAUNTLET_TRIAL_PURPOSE,
    ChainedGauntlet,
    EvaluationRecord,
    GauntletCandidate,
    IndependentTrialsGauntlet,
    OutcomeEvidenceGauntlet,
    TrialResult,
    evidence_of,
    freeze_candidate,
    learning_content_hash,
)
from maistro.memory.learnings.lifecycle import effectiveness
from maistro.memory.learnings.promoter import LearningPromoter
from maistro.memory.learnings.store import InMemoryLearningStore
from maistro.memory.types import Learning
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore, RunExecutionService, RunStatus
from maistro.runtime import PythonExecutionRuntime
from maistro.types.memory import (
    ANTI_PATTERN_CONFIDENCE_FLOOR,
    EpistemicType,
    LearningStage,
)

PRODUCER_RUN = "run-producer-1"


def make_learning(**kwargs: Any) -> Learning:
    defaults: dict[str, Any] = {
        "category": "tooling",
        "trigger_keys": ["deploy"],
        "learning": "snapshot the workspace before deploying",
        "tool_name": "bash",
        "run_id": PRODUCER_RUN,
        "hit_count": 10,
        "success_after_use": 4,
        "failure_after_use": 0,
    }
    defaults.update(kwargs)
    return Learning(**defaults)


def passing_trials(
    content_hash: str, *, regimes: tuple[str, ...] = ("tooling", "bash")
) -> EvaluationRecord:
    """A record the Gauntlet accepts: distinct canonical Runs, held-out trials,
    multiple contexts, every regime applicable, all successful."""
    contexts = ("ctx-held-out-a", "ctx-held-out-b", "ctx-c")
    return EvaluationRecord(
        evaluator="trial-evaluator",
        evaluator_version="1.4.2",
        content_hash=content_hash,
        trials=tuple(
            TrialResult(
                context_id=contexts[i % len(contexts)],
                regime=regimes[i % len(regimes)],
                run_id=f"run-eval-{i + 1}",
                success=True,
                held_out=i < 2,
            )
            for i in range(3)
        ),
    )


class ScriptedEvaluator:
    """Returns a canned record; remembers the candidate it was handed."""

    def __init__(
        self,
        record_factory: Callable[[GauntletCandidate], EvaluationRecord],
        *,
        name: str = "trial-evaluator",
        version: str = "1.4.2",
    ) -> None:
        self.name = name
        self.version = version
        self._factory = record_factory
        self.candidates: list[GauntletCandidate] = []

    async def evaluate(self, candidate: GauntletCandidate) -> EvaluationRecord:
        self.candidates.append(candidate)
        return self._factory(candidate)


def passing_evaluator(**kwargs: Any) -> ScriptedEvaluator:
    return ScriptedEvaluator(lambda candidate: passing_trials(candidate.content_hash, **kwargs))


class TrialRunStore:
    """Minimal canonical Run store: resolves only the trials registered on it."""

    def __init__(self) -> None:
        self.runs: dict[str, Any] = {}

    async def get_run(self, run_id: str, *, principal_id: str | None = None) -> Any:
        return self.runs.get(run_id)

    def register(
        self,
        run_id: str,
        *,
        content_hash: str,
        context_id: str,
        held_out: bool = False,
        status: Any = RunStatus.COMPLETED,
        provenance: dict[str, Any] | None = None,
    ) -> None:
        base = {
            "purpose": GAUNTLET_TRIAL_PURPOSE,
            "gauntlet_candidate_content_hash": content_hash,
            "trial_context_id": context_id,
            "held_out": held_out,
        }
        self.runs[run_id] = SimpleNamespace(
            status=status, provenance={**base, **(provenance or {})}
        )


class StoreRegisteringEvaluator:
    """Wraps a scripted evaluator; registers every returned trial as a
    completed canonical Run whose provenance binds it to the candidate."""

    def __init__(
        self,
        inner: Any,
        store: TrialRunStore,
        *,
        provenance_overrides: dict[str, Any] | None = None,
    ) -> None:
        self._inner = inner
        self._store = store
        self._overrides = provenance_overrides or {}
        self.name = inner.name
        self.version = inner.version

    async def evaluate(self, candidate: GauntletCandidate) -> EvaluationRecord:
        record = await self._inner.evaluate(candidate)
        for trial in record.trials:
            self._store.register(
                trial.run_id,
                content_hash=candidate.content_hash,
                context_id=trial.context_id,
                held_out=trial.held_out,
                provenance=self._overrides,
            )
        return record


def gauntlet(evaluator: Any, **kwargs: Any) -> IndependentTrialsGauntlet:
    """A gate whose evaluator's trials resolve to real, completed, bound Runs."""
    store = TrialRunStore()
    return IndependentTrialsGauntlet(
        StoreRegisteringEvaluator(evaluator, store), run_store=store, **kwargs
    )


# ---------------------------------------------------------------------------
# Frozen candidate content
# ---------------------------------------------------------------------------


async def test_candidate_is_frozen_content_with_a_content_hash() -> None:
    learning = make_learning()
    candidate = freeze_candidate(learning)

    assert candidate.learning_id == (learning.id or 0)
    assert candidate.learning == learning.learning
    assert candidate.trigger_keys == ("deploy",)
    assert candidate.producer_run_id == PRODUCER_RUN
    # Applicability is the regimes the candidate itself declares.
    assert candidate.applicability == ("tooling", "bash")
    assert candidate.content_hash == learning_content_hash(
        learning.learning,
        learning.trigger_keys,
        tool_name=learning.tool_name,
        category=learning.category,
        source_query=learning.source_query,
    )


async def test_content_hash_moves_when_any_frozen_content_moves() -> None:
    base = learning_content_hash("text", ["a"], tool_name="t", category="c")
    assert base != learning_content_hash("other", ["a"], tool_name="t", category="c")
    assert base != learning_content_hash("text", ["b"], tool_name="t", category="c")
    assert base != learning_content_hash("text", ["a"], tool_name="u", category="c")
    assert base != learning_content_hash("text", ["a"], tool_name="t", category="d")


async def test_gauntlet_hands_the_evaluator_only_the_frozen_candidate() -> None:
    evaluator = passing_evaluator()
    gauntlet_ = gauntlet(evaluator)
    await gauntlet_.evaluate(make_learning())

    assert len(evaluator.candidates) == 1
    handed = evaluator.candidates[0]
    assert isinstance(handed, GauntletCandidate)
    assert handed.producer_run_id == PRODUCER_RUN
    # The producer's hit_count — its enthusiasm about itself — is not part of
    # what the evaluator may see.
    assert not hasattr(handed, "hit_count")


# ---------------------------------------------------------------------------
# The verdict records the exact evaluation provenance
# ---------------------------------------------------------------------------


async def test_verdict_names_exact_runs_evaluator_and_content_hash() -> None:
    verdict = await gauntlet(passing_evaluator()).evaluate(make_learning())

    assert verdict.ok
    assert verdict.evaluation_run_ids == ("run-eval-1", "run-eval-2", "run-eval-3")
    assert verdict.evaluator_name == "trial-evaluator"
    assert verdict.evaluator_version == "1.4.2"
    assert verdict.content_hash == freeze_candidate(make_learning()).content_hash


# ---------------------------------------------------------------------------
# Local success alone is not institutional knowledge
# ---------------------------------------------------------------------------


async def test_high_local_success_without_evaluation_does_not_promote() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning())
    # The evaluator rejects: not one independent trial has run yet.
    evaluator = ScriptedEvaluator(
        lambda candidate: EvaluationRecord(
            evaluator="trial-evaluator",
            evaluator_version="1.4.2",
            content_hash=candidate.content_hash,
            trials=(),
        )
    )
    promoter = LearningPromoter(store, threshold=5, gauntlet=gauntlet(evaluator))

    promoted = await promoter.check_and_promote()

    assert promoted == []
    all_rows = await store.list_all()
    assert all_rows[0].status == "active"


async def test_threshold_crossing_with_passing_evaluation_promotes() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning())
    promoter = LearningPromoter(store, threshold=5, gauntlet=gauntlet(passing_evaluator()))

    promoted = await promoter.check_and_promote()

    assert [p.learning for p in promoted] == ["snapshot the workspace before deploying"]
    assert (await store.get_promoted())[0].status == "promoted"


async def test_low_hit_count_is_not_even_a_candidate() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning(hit_count=1))
    evaluator = passing_evaluator()
    promoter = LearningPromoter(store, threshold=5, gauntlet=gauntlet(evaluator))

    promoted = await promoter.check_and_promote()

    assert promoted == []
    assert evaluator.candidates == []  # never evaluated: not a candidate


# ---------------------------------------------------------------------------
# The evaluation set is independent of the producing evidence
# ---------------------------------------------------------------------------


async def test_evaluation_set_may_not_include_the_producing_run() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        # Trial 3 re-runs the very Run that produced the learning.
        trials = list(base.trials)
        trials[2] = TrialResult(
            context_id="ctx-c", regime="bash", run_id=PRODUCER_RUN, success=True
        )
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "independence" in verdict.failed_checks


async def test_evaluation_requires_a_held_out_trial() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        trials = [
            TrialResult(
                context_id=t.context_id,
                regime=t.regime,
                run_id=t.run_id,
                success=t.success,
                held_out=False,
            )
            for t in base.trials
        ]
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "held_out" in verdict.failed_checks


# ---------------------------------------------------------------------------
# Multi-context / multi-regime / held-out trials
# ---------------------------------------------------------------------------


async def test_trials_must_span_multiple_contexts() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        trials = [
            TrialResult(
                context_id="ctx-only",
                regime=t.regime,
                run_id=t.run_id,
                success=t.success,
                held_out=t.held_out,
            )
            for t in base.trials
        ]
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "contexts" in verdict.failed_checks


async def test_trials_must_span_the_required_regimes() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        return passing_trials(candidate.content_hash, regimes=("bash", "bash", "bash"))

    verdict = await gauntlet(ScriptedEvaluator(record), min_regimes=2).evaluate(make_learning())

    assert not verdict.ok
    assert "regimes" in verdict.failed_checks


async def test_trials_outside_the_candidate_applicability_prove_nothing() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        return passing_trials(candidate.content_hash, regimes=("cooking", "bash", "bash"))

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "applicability" in verdict.failed_checks


async def test_min_success_rate_rejects_a_majority_failing_candidate() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        trials = [
            TrialResult(
                context_id=t.context_id,
                regime=t.regime,
                run_id=t.run_id,
                success=i == 0,  # 1/3
                held_out=t.held_out,
            )
            for i, t in enumerate(base.trials)
        ]
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "success_rate" in verdict.failed_checks


# ---------------------------------------------------------------------------
# Failure retains evidence; the collective stays closed
# ---------------------------------------------------------------------------


async def test_rejected_candidate_keeps_its_evidence_and_stays_local() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning())
    promoter = LearningPromoter(
        store,
        threshold=5,
        gauntlet=gauntlet(
            ScriptedEvaluator(
                lambda candidate: EvaluationRecord(
                    evaluator="trial-evaluator",
                    evaluator_version="1.4.2",
                    content_hash=candidate.content_hash,
                    trials=(),
                )
            )
        ),
    )

    promoted = await promoter.check_and_promote()

    assert promoted == []
    row = (await store.list_all())[0]
    # Retained: the row, its status, its outcome evidence, its producer.
    assert row.status == "active"
    assert row.learning == "snapshot the workspace before deploying"
    assert row.hit_count == 10
    assert row.success_after_use == 4
    assert row.failure_after_use == 0
    assert row.run_id == PRODUCER_RUN
    # Blocked: no collective visibility, no validation provenance minted.
    assert await store.get_promoted() == []
    assert row.validated_by == ""
    assert row.validation_run_ids == []
    # Still local: unchanged scope axes.
    assert row.category == "tooling" and row.tool_name == "bash"


class RaisingThenRecordingEvaluator(ScriptedEvaluator):
    """Raises for the first candidate it sees; otherwise returns passing trials."""

    def __init__(self) -> None:
        super().__init__(lambda candidate: passing_trials(candidate.content_hash))
        self.raised: list[str] = []

    async def evaluate(self, candidate: GauntletCandidate) -> EvaluationRecord:
        if not self.raised:
            self.raised.append(candidate.content_hash)
            raise RuntimeError("transient trial Run failure")
        return await super().evaluate(candidate)


async def test_evaluator_failure_is_contained_per_candidate() -> None:
    """An evaluator that raises must not abort the pass or poison the caller.

    The raising candidate stays active for a controlled retry; later
    candidates are still considered and promoted in the same pass.
    """
    store = InMemoryLearningStore()
    await store.store(make_learning(trigger_keys=["deploy"]))
    await store.store(make_learning(trigger_keys=["lint"], learning="run the linter"))
    evaluator = RaisingThenRecordingEvaluator()
    promoter = LearningPromoter(store, threshold=5, gauntlet=gauntlet(evaluator))

    promoted = await promoter.check_and_promote()

    # The failure hit exactly one candidate; the other still promoted.
    assert len(evaluator.raised) == 1
    assert [p.learning for p in promoted] == ["run the linter"]
    rows = {row.learning: row for row in await store.list_all()}
    assert rows["snapshot the workspace before deploying"].status == "active"
    assert rows["run the linter"].status == "promoted"


async def test_store_promotion_seam_is_per_candidate_and_scoped() -> None:
    store = InMemoryLearningStore()
    learning = make_learning()
    await store.store(learning)
    other_org = make_learning(org_id="org-b")
    await store.store(other_org)
    promoted_id = await store.store(make_learning(status="promoted"))

    promoted = await store.promote_learning(
        learning.id or 0,
        validated_by="independent-trials",
        evaluator_version="1.4.2",
        validated_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        validation_run_ids=("run-eval-1",),
        validation_content_hash="deadbeef",
    )
    # Cross-org id and already-promoted id are not ours to touch.
    assert await store.promote_learning(other_org.id or 0, org_id="org-a") is None
    assert await store.promote_learning(promoted_id, org_id="") is None
    assert await store.promote_learning(9999) is None

    assert promoted is not None
    assert promoted.status == "promoted"
    assert promoted.validated_by == "independent-trials"
    assert promoted.validated_evaluator_version == "1.4.2"
    assert promoted.validated_at == datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    assert promoted.validation_run_ids == ["run-eval-1"]
    assert promoted.validation_content_hash == "deadbeef"
    # The other org's row was untouched by the whole affair.
    assert other_org.status == "active"


# ---------------------------------------------------------------------------
# Verdicts bind to frozen content and canonical Runs
# ---------------------------------------------------------------------------


async def test_a_verdict_cannot_be_spent_on_different_content() -> None:
    def record(candidate: GauntletCandidate) -> EvaluationRecord:
        # The evaluator judged content that no longer matches the candidate.
        return passing_trials("hash-of-some-other-content")

    verdict = await gauntlet(ScriptedEvaluator(record)).evaluate(make_learning())

    assert not verdict.ok
    assert "frozen_content" in verdict.failed_checks
    # The verdict still names the hash it was judging against, so the drift is
    # auditable from the rejection alone.
    assert verdict.content_hash == freeze_candidate(make_learning()).content_hash


async def test_every_trial_must_name_one_distinct_run() -> None:
    def empty_run_ids(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        trials = [
            TrialResult(
                context_id=t.context_id,
                regime=t.regime,
                run_id="",
                success=t.success,
                held_out=t.held_out,
            )
            for t in base.trials
        ]
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    def duplicate_run_ids(candidate: GauntletCandidate) -> EvaluationRecord:
        base = passing_trials(candidate.content_hash)
        trials = [
            TrialResult(
                context_id=t.context_id,
                regime=t.regime,
                run_id="run-eval-1",
                success=t.success,
                held_out=t.held_out,
            )
            for t in base.trials
        ]
        return EvaluationRecord(
            evaluator=base.evaluator,
            evaluator_version=base.evaluator_version,
            content_hash=base.content_hash,
            trials=tuple(trials),
        )

    empty = await gauntlet(ScriptedEvaluator(empty_run_ids)).evaluate(make_learning())
    duplicated = await gauntlet(ScriptedEvaluator(duplicate_run_ids)).evaluate(make_learning())

    assert "canonical_runs" in empty.failed_checks
    assert "canonical_runs" in duplicated.failed_checks


async def test_a_run_id_that_resolves_to_nothing_is_rejected() -> None:
    """Fabricated, mistyped, and deleted ids all fail the same way: the store
    has no such Run, and an audit trail that cannot be resolved is no trail."""
    # The evaluator names runs the store was never told about.
    store = TrialRunStore()
    verdict = await IndependentTrialsGauntlet(passing_evaluator(), run_store=store).evaluate(
        make_learning()
    )

    assert not verdict.ok
    assert "canonical_runs" in verdict.failed_checks


async def test_a_run_that_never_completed_cannot_validate() -> None:
    """A trial still running, failed, or cancelled proves nothing about the
    candidate — the record's `success` flag alone is not the spine's word."""
    learning = make_learning()
    content_hash = freeze_candidate(learning).content_hash
    record = passing_trials(content_hash)
    for status in (RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED):
        store = TrialRunStore()
        for trial in record.trials:
            store.register(
                trial.run_id,
                content_hash=content_hash,
                context_id=trial.context_id,
                held_out=trial.held_out,
                status=status,
            )
        gate = IndependentTrialsGauntlet(passing_evaluator(), run_store=store)
        verdict = await gate.evaluate(learning)

        assert not verdict.ok, status
        assert "run_outcome" in verdict.failed_checks, status


async def test_run_provenance_must_bind_to_this_candidate_and_context() -> None:
    """A real, completed Run from some other execution is not evidence here."""
    cases: tuple[dict[str, Any], ...] = (
        {"gauntlet_candidate_content_hash": "hash-of-some-other-candidate"},
        {"trial_context_id": "ctx-some-other-trial"},
        {"purpose": "some-other-purpose"},
        {"held_out": False},  # trials 1-2 report held_out=True
    )
    for overrides in cases:
        store = TrialRunStore()
        gate = IndependentTrialsGauntlet(
            StoreRegisteringEvaluator(passing_evaluator(), store, provenance_overrides=overrides),
            run_store=store,
        )
        verdict = await gate.evaluate(make_learning())

        assert not verdict.ok, overrides
        assert "run_provenance" in verdict.failed_checks, overrides


async def test_without_a_run_store_the_gate_fails_closed() -> None:
    """No store means no resolvable provenance, so nothing may promote."""
    verdict = await IndependentTrialsGauntlet(passing_evaluator()).evaluate(make_learning())

    assert not verdict.ok
    assert "canonical_runs" in verdict.failed_checks


async def test_unattributed_learning_cannot_be_validated() -> None:
    evaluator = passing_evaluator()
    verdict = await gauntlet(evaluator).evaluate(make_learning(run_id=""))

    assert not verdict.ok
    assert "producer" in verdict.failed_checks
    # The evaluator was still consulted — the producer check is a verdict
    # check, not a short-circuit — so the record of the attempt is complete.
    assert len(evaluator.candidates) == 1
    assert evaluator.candidates[0].producer_run_id == ""


# ---------------------------------------------------------------------------
# Chains
# ---------------------------------------------------------------------------


async def test_chained_gauntlet_requires_every_member_and_merges_provenance() -> None:
    evaluator = passing_evaluator()
    store = TrialRunStore()
    store_backed = StoreRegisteringEvaluator(evaluator, store)
    # Only three trials ran; demanding five makes this member fail.
    strict = IndependentTrialsGauntlet(store_backed, min_trials=5, name="strict", run_store=store)
    lenient = IndependentTrialsGauntlet(store_backed, name="lenient", run_store=store)

    chain = ChainedGauntlet(strict, lenient)
    rejected = await chain.evaluate(make_learning())
    assert not rejected.ok
    assert "min_trials" in rejected.failed_checks
    assert rejected.gauntlet == "gauntlet-chain"

    accepted = await ChainedGauntlet(lenient).evaluate(make_learning())
    assert accepted.ok
    assert accepted.evaluation_run_ids == ("run-eval-1", "run-eval-2", "run-eval-3")
    assert accepted.evaluator_version == "1.4.2"

    with pytest.raises(ValueError, match="at least one member"):
        ChainedGauntlet()


# ---------------------------------------------------------------------------
# Promoter integration: provenance lands on the promoted learning
# ---------------------------------------------------------------------------


async def test_promotion_links_exact_evaluation_runs_and_evaluator_version() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning())
    promoter = LearningPromoter(store, threshold=5, gauntlet=gauntlet(passing_evaluator()))

    promoted = await promoter.check_and_promote()

    assert len(promoted) == 1
    row = promoted[0]
    assert row.validated_by == "trial-evaluator"
    assert row.validated_evaluator_version == "1.4.2"
    assert row.validated_at is not None
    assert row.validation_run_ids == ["run-eval-1", "run-eval-2", "run-eval-3"]
    assert row.validation_content_hash == freeze_candidate(make_learning()).content_hash
    # The promoted read path — what system-prompt injection sees — carries the
    # same provenance.
    shared = (await store.get_promoted())[0]
    assert shared.validation_run_ids == row.validation_run_ids
    assert shared.validated_evaluator_version == row.validated_evaluator_version


async def test_gauntlet_takes_precedence_over_the_approval_gate() -> None:
    from maistro.memory.learnings.approval import LearningApprovalGate

    store = InMemoryLearningStore()
    await store.store(make_learning())
    gate = LearningApprovalGate()
    promoter = LearningPromoter(
        store,
        threshold=5,
        approval_gate=gate,
        gauntlet=gauntlet(
            ScriptedEvaluator(
                lambda candidate: EvaluationRecord(
                    evaluator="trial-evaluator",
                    evaluator_version="1.4.2",
                    content_hash=candidate.content_hash,
                    trials=(),
                )
            )
        ),
    )

    promoted = await promoter.check_and_promote()

    # The Gauntlet rejected, so nothing promotes — and the human queue is not
    # asked to re-litigate a question the evaluation already answered.
    assert promoted == []
    assert gate.get_pending() == []
    assert (await store.list_all())[0].status == "active"


async def test_legacy_path_without_gauntlet_is_unchanged() -> None:
    store = InMemoryLearningStore()
    await store.store(make_learning())
    promoter = LearningPromoter(store, threshold=5)

    promoted = await promoter.check_and_promote()

    assert [p.learning for p in promoted] == ["snapshot the workspace before deploying"]
    row = (await store.get_promoted())[0]
    # Legacy promotions carry no fabricated validation.
    assert row.validated_by == ""
    assert row.validation_run_ids == []


# ---------------------------------------------------------------------------
# The trials are canonical Runs, not invented identifiers
# ---------------------------------------------------------------------------


async def test_validating_trials_execute_as_real_canonical_runs() -> None:
    """The evaluator's trial Run ids resolve to Runs on the canonical spine.

    The Gauntlet contract says trial `run_id`s are canonical Run ids. This
    exercises the contract end to end: a `CanonicalTrialEvaluator` submits the
    trial through `RunExecutionService` — `Goal -> Graph -> Run -> NodeRun ->
    Attempt` — and the promoted learning names exactly those Runs, which the
    Run store can still produce on read.
    """
    project_store = InMemoryProjectScopeStore()
    root = await project_store.create_root("ws-gauntlet")
    project = await project_store.create(
        workspace_id="ws-gauntlet",
        parent_project_id=root.project_id,
        name="Gauntlet trials",
    )
    run_store = InMemoryRunStore(project_store=project_store)
    service = RunExecutionService(store=run_store, runtime=PythonExecutionRuntime())

    class CanonicalTrialEvaluator:
        """Evaluates a candidate by running one trial Run per context."""

        name = "canonical-trials"
        version = "0.3.0"

        def __init__(self, service: RunExecutionService, graph: Graph) -> None:
            self._service = service
            self._graph = graph

        async def evaluate(self, candidate: GauntletCandidate) -> EvaluationRecord:
            trials: list[TrialResult] = []
            for context_id in ("ctx-a", "ctx-b", "ctx-held-out"):
                run = await self._service.create_run(
                    self._graph,
                    actor_principal_id="principal-gauntlet",
                    provenance={
                        "purpose": "learning-gauntlet-trial",
                        "gauntlet_candidate_content_hash": candidate.content_hash,
                        "trial_context_id": context_id,
                        "trial_regime": "tooling",
                        "held_out": context_id == "ctx-held-out",
                    },
                )
                await self._service.execute_node(
                    run.run_id,
                    "node-1",
                    {"learning": candidate.learning, "context_id": context_id},
                    None,
                    executor=_trial_work(),
                )
                trials.append(
                    TrialResult(
                        context_id=context_id,
                        regime="tooling",
                        run_id=run.run_id,
                        success=True,
                        held_out=context_id == "ctx-held-out",
                    )
                )
            return EvaluationRecord(
                evaluator=self.name,
                evaluator_version=self.version,
                content_hash=candidate.content_hash,
                trials=tuple(trials),
            )

    graph = Graph(
        workspace_id="ws-gauntlet",
        project_id=project.project_id,
        name="Gauntlet trial",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )
    evaluator = CanonicalTrialEvaluator(service, graph)

    store = InMemoryLearningStore()
    await store.store(make_learning())
    promoter = LearningPromoter(
        store,
        threshold=5,
        gauntlet=IndependentTrialsGauntlet(evaluator, run_store=run_store),
    )
    promoted = await promoter.check_and_promote()

    assert len(promoted) == 1
    row = promoted[0]
    assert row.validated_by == "canonical-trials"
    assert row.validated_evaluator_version == "0.3.0"
    assert len(row.validation_run_ids) == 3
    # Every evaluation Run id is a real canonical Run, and the spine remembers
    # the trial it executed.
    for run_id in row.validation_run_ids:
        canonical = await run_store.get_run(run_id)
        assert canonical is not None
        assert canonical.provenance["purpose"] == "learning-gauntlet-trial"
        assert canonical.provenance["gauntlet_candidate_content_hash"] == (
            row.validation_content_hash
        )
    held_out_run = await run_store.get_run(row.validation_run_ids[2])
    assert held_out_run is not None
    assert held_out_run.provenance["held_out"] is True
    # And the Runs reached terminal success on the spine, not just on paper.
    for run_id in row.validation_run_ids:
        canonical = await run_store.get_run(run_id)
        assert canonical is not None
        assert canonical.status is RunStatus.COMPLETED


def _trial_work() -> Any:
    async def executor(_work: Any, _context: Any) -> str:
        return "trial ok"

    return executor


# ---------------------------------------------------------------------------
# M4-B5 outcome-evidence Gauntlet and anti-pattern capture (develop #118/#121)
#
# The classes below came in with the M4-B5 integration (#1753): the lighter
# outcome-evidence validator, the promoter integration through the shared
# promotion seam, and #121's failure-knowledge capture and reuse. Adapted to
# the merged LearningGauntlet protocol: evaluate(learning) builds its own
# evidence projection.
# ---------------------------------------------------------------------------


class _StubForge:
    def __init__(self, result: dict[str, Any]) -> None:
        self._result = result
        self.calls: list[tuple[str, Learning]] = []

    async def mutate(self, skill_name: str, learning: Learning) -> dict[str, Any]:
        self.calls.append((skill_name, learning))
        return self._result


def _used_learning(**overrides: object) -> Learning:
    """A learning with good evidence: 4 successes out of 5 recorded outcomes."""
    kwargs: dict[str, object] = {
        "trigger_keys": ["deploy"],
        "learning": "snapshot first",
        "run_id": "run-1",
        "success_after_use": 4,
        "failure_after_use": 1,
    }
    kwargs.update(overrides)
    return Learning(**kwargs)  # type: ignore[arg-type]


@pytest.mark.contract("behavioral")
class TestEvidenceProjection:
    def test_evidence_counts_uses_not_hits(self) -> None:
        # hit_count is deliberately absent from the projection: recall
        # frequency says nothing about whether following the learning helped.
        lr = _used_learning(hit_count=999)
        ev = evidence_of(lr)
        assert ev.uses == 5
        assert ev.successes == 4
        assert ev.failures == 1
        assert ev.producer_run_id == "run-1"

    def test_unattributed_learning_names_no_producer(self) -> None:
        assert evidence_of(_used_learning(run_id="")).producer_run_id == ""


@pytest.mark.contract("behavioral")
class TestOutcomeEvidenceGauntlet:
    async def test_good_evidence_passes(self) -> None:
        lr = _used_learning()
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert verdict.ok
        assert verdict.gauntlet == "outcome-evidence"

    async def test_insufficient_uses_fail(self) -> None:
        lr = _used_learning(success_after_use=2, failure_after_use=0)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert not verdict.ok
        assert "min_uses" in verdict.failed_checks

    async def test_high_hits_with_failing_outcomes_fail(self) -> None:
        # The case hit-count promotion alone would wave through.
        lr = _used_learning(hit_count=50, success_after_use=1, failure_after_use=4)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert not verdict.ok
        assert "success_rate" in verdict.failed_checks

    async def test_contradictions_outweighing_reinforcements_fail(self) -> None:
        lr = _used_learning(contradiction_count=3, reinforcement_count=0)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert not verdict.ok
        assert "contradictions" in verdict.failed_checks

    async def test_decayed_confidence_fails(self) -> None:
        lr = _used_learning(confidence=0.1)
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert not verdict.ok
        assert "confidence" in verdict.failed_checks

    async def test_unattributed_producer_fails(self) -> None:
        # Nothing can be checked against an execution that is not named.
        lr = _used_learning(run_id="")
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert not verdict.ok
        assert "producer" in verdict.failed_checks

    async def test_producer_requirement_can_be_relaxed(self) -> None:
        lr = _used_learning(run_id="")
        gauntlet = OutcomeEvidenceGauntlet(require_producer=False)
        verdict = await gauntlet.evaluate(lr)
        assert verdict.ok


@pytest.mark.contract("behavioral")
class TestChainedGauntlet:
    async def test_all_members_must_pass(self) -> None:
        lr = _used_learning()
        strict = OutcomeEvidenceGauntlet(name="strict", min_uses=10)
        chain = ChainedGauntlet(OutcomeEvidenceGauntlet(), strict)
        verdict = await chain.evaluate(lr)
        assert not verdict.ok
        assert "strict" in verdict.reason

    async def test_passing_chain_reports_member_names(self) -> None:
        lr = _used_learning()
        chain = ChainedGauntlet(
            OutcomeEvidenceGauntlet(name="g1"),
            OutcomeEvidenceGauntlet(name="g2", min_uses=5),
        )
        verdict = await chain.evaluate(lr)
        assert verdict.ok
        assert verdict.gauntlet == "gauntlet-chain"

    def test_empty_chain_is_a_configuration_error(self) -> None:
        try:
            ChainedGauntlet()
        except ValueError as exc:
            assert "member" in str(exc)
        else:
            raise AssertionError("empty chain must raise")


@pytest.mark.contract("behavioral")
class TestPromoterWithGauntlet:
    async def test_validated_learning_joins_repertoire(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()

        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE
        assert lr.status == "promoted"
        assert lr.validated_by == "outcome-evidence"
        assert lr.validated_at is not None
        # promoted-only readers see repertoire entries.
        assert [p.id for p in await store.get_promoted()] == [lr.id]

    async def test_rejected_learning_stays_local_and_active(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10, success_after_use=0, failure_after_use=1)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()

        assert promoted == []
        # ADR-103: a rejected candidate was never asserted as a claim, so it
        # stays on the bottom rung it was stored at -- local memory, not a
        # learning the collective may reuse.
        assert lr.stage is LearningStage.MEMORY
        assert lr.status == "active"
        assert lr.validated_by == ""
        assert await store.get_promoted() == []

    async def test_below_threshold_candidate_is_never_judged(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=2)
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        assert await promoter.check_and_promote() == []
        assert lr.stage is LearningStage.MEMORY

    async def test_gauntlet_gates_skill_mutation(self) -> None:
        store = InMemoryLearningStore()
        good = _used_learning(hit_count=10, tool_name="shell")
        bad = _used_learning(
            trigger_keys=["deploy", "verify"],
            learning="the other one",
            hit_count=10,
            tool_name="shell2",
            success_after_use=0,
            failure_after_use=5,
        )
        await store.store(good)
        await store.store(bad)

        forge = _StubForge({"status": "mutated", "old_hash": "a", "new_hash": "b"})
        promoter = LearningPromoter(
            store,
            threshold=5,
            skill_forge=forge,
            gauntlet=OutcomeEvidenceGauntlet(),
        )
        promoted = await promoter.check_and_promote()

        assert [p.id for p in promoted] == [good.id]
        assert [name for name, _ in forge.calls] == ["shell"]

    async def test_gauntlet_takes_precedence_over_approval_gate(self) -> None:
        # With a Gauntlet wired, a learning never waits in a human queue: the
        # machine validation decides, and the legacy gate path is not entered.
        # (The independent-trials twin of this posture is
        # test_gauntlet_takes_precedence_over_the_approval_gate above.)
        from maistro.memory.learnings.approval import LearningApprovalGate

        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10)
        await store.store(lr)

        promoter = LearningPromoter(
            store,
            threshold=5,
            approval_gate=LearningApprovalGate(),
            gauntlet=OutcomeEvidenceGauntlet(),
        )
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.status == "promoted"

    async def test_anti_pattern_failure_knowledge_is_promotable(self) -> None:
        # #121: failure knowledge follows the same validated road to the
        # repertoire as any other learning -- no separate door, none barred.
        store = InMemoryLearningStore()
        lr = _used_learning(
            epistemic_type=EpistemicType.ANTI_PATTERN,
            learning="never force-push to main",
            hit_count=10,
            success_after_use=5,
            failure_after_use=0,
            confidence=ANTI_PATTERN_CONFIDENCE_FLOOR,
        )
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5, gauntlet=OutcomeEvidenceGauntlet())
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN

    async def test_legacy_path_unchanged_without_gauntlet(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(hit_count=10, run_id="")
        await store.store(lr)

        promoter = LearningPromoter(store, threshold=5)
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.status == "promoted"


@pytest.mark.contract("behavioral")
class TestCaptureAntiPatterns:
    async def test_ineffective_learnings_become_anti_patterns(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(success_after_use=0, failure_after_use=4)
        await store.store(lr)

        promoter = LearningPromoter(store)
        captured = await promoter.capture_anti_patterns(min_uses=3)

        assert [c.id for c in captured] == [lr.id]
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN
        # Retained near-permanently: confidence lifted to the floor.
        assert lr.confidence == ANTI_PATTERN_CONFIDENCE_FLOOR
        # Reclassification is not validation: still local, still promotable.
        assert lr.status == "active"
        assert lr.stage is LearningStage.MEMORY

    async def test_effective_and_unmeasured_learnings_are_left_alone(self) -> None:
        store = InMemoryLearningStore()
        effective = _used_learning()  # 4/5 successes
        unmeasured = _used_learning(trigger_keys=["fresh"], learning="no outcomes yet")
        await store.store(effective)
        await store.store(unmeasured)

        captured = await LearningPromoter(store).capture_anti_patterns(min_uses=3)
        assert captured == []
        assert effective.epistemic_type is EpistemicType.EMPIRICAL
        assert unmeasured.epistemic_type is EpistemicType.EMPIRICAL

    async def test_org_scoping_and_double_capture(self) -> None:
        store = InMemoryLearningStore()
        org1 = _used_learning(org_id="org-1", success_after_use=0, failure_after_use=4)
        org2 = _used_learning(org_id="org-2", success_after_use=0, failure_after_use=4)
        await store.store(org1)
        await store.store(org2)

        promoter = LearningPromoter(store)
        captured = await promoter.capture_anti_patterns("org-1", min_uses=3)
        assert [c.id for c in captured] == [org1.id]
        assert org2.epistemic_type is EpistemicType.EMPIRICAL

        # Already-captured rows are not reprocessed.
        assert await promoter.capture_anti_patterns("org-1", min_uses=3) == []

    async def test_store_without_ineffective_read_yields_nothing(self) -> None:
        class NoIneffectiveStore:
            async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
                return []

        promoter = LearningPromoter(NoIneffectiveStore())  # type: ignore[arg-type]
        assert await promoter.capture_anti_patterns() == []

    async def test_captured_anti_pattern_can_then_be_validated(self) -> None:
        # The full #121 path: a captured anti-pattern with good later-Run
        # evidence joins the repertoire through the same Gauntlet.
        store = InMemoryLearningStore()
        lr = _used_learning(
            run_id="",
            success_after_use=0,
            failure_after_use=4,
        )
        await store.store(lr)
        promoter = LearningPromoter(store, gauntlet=OutcomeEvidenceGauntlet())

        await promoter.capture_anti_patterns(min_uses=3)
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN

        # Later Runs avoid the anti-pattern and succeed.
        lr.run_id = "run-42"
        lr.success_after_use = 4
        lr.failure_after_use = 0
        lr.hit_count = 10
        promoted = await promoter.check_and_promote()
        assert [p.id for p in promoted] == [lr.id]
        assert lr.stage is LearningStage.REPERTOIRE


@pytest.mark.contract("behavioral")
class TestAntiPatternKnowledgeReuse:
    """#121's reuse half: retrieval, contrary evidence, and the measured win.

    Capture alone would just be a rename. The acceptance this class pins:
    the retained knowledge is *surfaced* to later Runs as scoped advisory
    guidance (never unconditional policy), a later Run that disproves it can
    supersede it with the lineage kept, and the reason to bother is
    measurable -- the repeated-failure count before adoption versus the
    outcome evidence after it.
    """

    async def test_captured_anti_pattern_is_surfaced_as_scoped_advisory_guidance(
        self,
    ) -> None:
        store = InMemoryLearningStore()
        anti = _used_learning(
            trigger_keys=["force-push"],
            learning="never force-push to main",
            success_after_use=0,
            failure_after_use=4,
        )
        await store.store(anti)
        other_org = _used_learning(
            org_id="org-2",
            trigger_keys=["force-push"],
            learning="the other org's avoid rule",
            success_after_use=0,
            failure_after_use=4,
        )
        await store.store(other_org)
        await LearningPromoter(store).capture_anti_patterns(min_uses=3)
        assert anti.epistemic_type is EpistemicType.ANTI_PATTERN

        # Retrieval surfaces the anti-pattern for its own scope only: `org_id`
        # is the security boundary and binds exactly, so the other org's row
        # never crosses and this org's avoid rule is not visible without one.
        surfaced = await store.find_relevant("should I force-push to main?", org_id="")
        assert [s.id for s in surfaced] == [anti.id]
        # ...and org-2's read surfaces only org-2's own row: the boundary is
        # exact in both directions, so neither avoid rule crosses it.
        theirs = await store.find_relevant("should I force-push to main?", org_id="org-2")
        assert [s.id for s in theirs] == [other_org.id]

        # Rendered as one bounded advisory correction inside the closed
        # corrections block -- guidance for the Run to weigh, not a policy
        # statement appended to the system prompt unconditionally. The budget
        # can still drop it, and the block framing is what makes that a
        # demotion instead of a lie.
        block, kept_ids, added = _render_learnings_block(
            surfaced,
            block_type="matched",
            budget_chars=2000,
            use_rca_prefix=False,
        )
        assert added == 1
        assert kept_ids == [anti.id]
        assert block is not None
        assert block.startswith('<maistro:corrections type="matched">')
        assert block.rstrip().endswith("</maistro:corrections>")
        assert "never force-push to main" in block

        # After the Gauntlet commits it to the repertoire, the promoted read
        # surfaces it too -- still through the same advisory block.
        anti.hit_count = 10
        anti.success_after_use, anti.failure_after_use = 4, 0
        promoter = LearningPromoter(store, gauntlet=OutcomeEvidenceGauntlet())
        assert [p.id for p in await promoter.check_and_promote()] == [anti.id]
        promoted_block, _, promoted_added = _render_learnings_block(
            await store.get_promoted(org_id=""),
            block_type="promoted",
            budget_chars=2000,
            use_rca_prefix=True,
        )
        assert promoted_added == 1
        assert promoted_block is not None
        assert promoted_block.startswith('<maistro:corrections type="promoted">')

    async def test_contrary_evidence_supersedes_a_captured_anti_pattern(self) -> None:
        store = InMemoryLearningStore()
        anti = _used_learning(
            learning="never deploy on Fridays",
            success_after_use=0,
            failure_after_use=4,
        )
        await store.store(anti)
        await LearningPromoter(store).capture_anti_patterns(min_uses=3)
        assert anti.epistemic_type is EpistemicType.ANTI_PATTERN

        # A later Run disproves the rule. The replacement is stored first and
        # the old row retired second (so dedup cannot fold one into the
        # other), and the lineage is kept in both directions: institutional
        # knowledge is retained, not deleted.
        replacement = _used_learning(
            learning="Friday deploys are fine behind the release gate",
            run_id="run-9",
        )
        new_id = await store.supersede(anti.id or 0, replacement)

        assert anti.status == "superseded"
        assert anti.superseded_by == new_id
        survivor = await store.get(new_id)
        assert survivor is not None
        assert survivor.supersedes == anti.id
        # The retired row is no longer retrieved; the contrary knowledge is.
        surfaced = await store.find_relevant("deploy", org_id="")
        assert [s.id for s in surfaced] == [new_id]
        # And the superseded anti-pattern remains readable for the Runs that
        # ask what used to be believed.
        assert await store.get(anti.id or 0) is anti

    async def test_repeated_failures_measured_before_and_after_adoption(self) -> None:
        store = InMemoryLearningStore()
        lr = _used_learning(success_after_use=0, failure_after_use=4)
        await store.store(lr)

        # Before adoption: the redundant repeated failures are measurable --
        # four recorded outcomes, every one a failure -- and they are exactly
        # what the capture threshold reads.
        ineffective = await store.list_ineffective(min_uses=3)
        assert [i.id for i in ineffective] == [lr.id]
        assert effectiveness(lr) == -1.0
        await LearningPromoter(store).capture_anti_patterns(min_uses=3)
        assert lr.epistemic_type is EpistemicType.ANTI_PATTERN

        # After adoption, through the same public outcome path later Runs
        # drive: six recorded outcomes, all successes. The same counters that
        # measured the problem now measure the win -- the signed effectiveness
        # flips positive and the independent Gauntlet accepts the evidence.
        for _ in range(6):
            await store.mark_outcome([lr.id or 0], True)
        assert (lr.success_after_use, lr.failure_after_use) == (6, 4)
        assert effectiveness(lr) == 0.2
        verdict = await OutcomeEvidenceGauntlet().evaluate(lr)
        assert verdict.ok
        assert verdict.failed_checks == ()
