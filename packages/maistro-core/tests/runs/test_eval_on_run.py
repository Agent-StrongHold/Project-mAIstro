"""Eval scores live on the Run that produced the artifact (M7-A3, #792).

Scoring a design artifact is part of the same execution that produced it, so
the score is `RunEvalScore` evidence on the canonical spine — naming the
NodeRun and Attempt whose work it scored and the exact Goal and Rubric
revisions applied — never a sidecar job and never a second execution identity.
Every store claim here runs against all three backends through the shared
`spine` fixture, because "Run evidence" that only one store persists is three
separate beliefs, not one contract.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.graph import Graph, Node
from maistro.runs.eval import eval_summary, open_re_eval_attempt
from maistro.runs.model import (
    AttemptStatus,
    EvalJudge,
    EvalMethod,
    RunEvalScore,
)
from maistro.runs.store import (
    ActiveAttemptExists,
    AttemptNotFound,
    NodeRunNotFound,
    RunIntegrityError,
    RunNotFound,
)

GOAL_ID = "goal-homestead"
GOAL_REVISION = 4
RUBRIC_ID = "rubric-homestead"
RUBRIC_REVISION = 2
DIMENSIONS = ("contrast", "palette")


def _graph(workspace: str, project_id: str) -> Graph:
    return Graph(
        workspace_id=workspace,
        project_id=project_id,
        name="Design graph",
        nodes=[Node(node_id="node-1", node_type="agent")],
    )


async def _produce(spine: Any) -> tuple[Any, Any, Any, Any]:
    """A Run that produced one node of work, with the Attempt that did it.

    Returns (store, run, node_run, completed_attempt) — the physical evidence a
    score records. The NodeRun itself stays open, exactly as it is after an
    Attempt completes but before the graph moves on.
    """
    store, workspace, project_id = spine
    run = await store.create_run(_graph(workspace, project_id))
    node_run = await store.create_node_run(run.run_id, node_id="node-1")
    attempt = await store.create_attempt(node_run.node_run_id)
    await store.transition_attempt(attempt.attempt_id, AttemptStatus.RUNNING)
    attempt = await store.transition_attempt(
        attempt.attempt_id, AttemptStatus.COMPLETED, result={"artifact": "brief-v1"}
    )
    return store, run, node_run, attempt


def _score(
    *,
    store_run_id: str,
    node_run_id: str,
    attempt_id: str,
    dimension: str,
    raw_score: float,
    passed: bool,
    eval_id: str | None = None,
) -> RunEvalScore:
    return RunEvalScore(
        eval_id=eval_id or f"eval-{dimension}-{raw_score}",
        run_id=store_run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        goal_id=GOAL_ID,
        goal_revision=GOAL_REVISION,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_id=dimension,
        raw_score=raw_score,
        passed=passed,
        method=EvalMethod.DETERMINISTIC,
        evidence_pointers=[f"attempt:{attempt_id}/evidence/{dimension}"],
        detail={"threshold": 0.7},
    )


async def test_a_planted_failing_dimension_is_durable_run_evidence(spine: Any) -> None:
    """Scoring a failing dimension appends a record onto the producing Run."""
    store, run, node_run, attempt = await _produce(spine)
    failing = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=0.2,
        passed=False,
    )
    recorded = await store.record_eval_score(failing)

    by_id = await store.get_eval_score(failing.eval_id)
    assert by_id is not None
    # The record that comes back is the store's copy: same identity, same verdict.
    assert recorded.eval_id == by_id.eval_id == failing.eval_id
    assert by_id.passed is False
    assert by_id.raw_score == pytest.approx(0.2)

    listed = await store.list_eval_scores(run.run_id)
    assert [score.eval_id for score in listed] == [failing.eval_id]
    # The record names the whole spine it scores — Run, NodeRun, Attempt...
    assert by_id.run_id == run.run_id
    assert by_id.node_run_id == node_run.node_run_id
    assert by_id.attempt_id == attempt.attempt_id
    # ...and the exact Goal and Rubric revisions that were applied.
    assert by_id.goal_id == GOAL_ID
    assert by_id.goal_revision == GOAL_REVISION
    assert by_id.rubric_id == RUBRIC_ID
    assert by_id.rubric_revision == RUBRIC_REVISION
    assert by_id.method is EvalMethod.DETERMINISTIC
    assert by_id.evidence_pointers == [f"attempt:{attempt.attempt_id}/evidence/contrast"]


async def test_a_passing_and_a_failing_dimension_coexist_on_one_run(spine: Any) -> None:
    store, run, node_run, attempt = await _produce(spine)
    for dimension, raw_score, passed in (
        ("contrast", 0.2, False),
        ("palette", 0.9, True),
    ):
        await store.record_eval_score(
            _score(
                store_run_id=run.run_id,
                node_run_id=node_run.node_run_id,
                attempt_id=attempt.attempt_id,
                dimension=dimension,
                raw_score=raw_score,
                passed=passed,
            )
        )

    listed = await store.list_eval_scores(run.run_id)
    assert {score.dimension_id for score in listed} == set(DIMENSIONS)
    assert {score.passed for score in listed} == {True, False}

    summary = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=DIMENSIONS,
    )
    assert summary.complete is True
    # Coexist does not mean pass: one failing dimension fails the Run's eval,
    # without hiding the passing one.
    assert summary.passed is False
    assert summary.failed_dimensions == ("contrast",)
    assert set(summary.latest_by_dimension) == set(DIMENSIONS)


async def test_a_reeval_scores_under_a_new_attempt_and_the_failed_record_stays_queryable(
    spine: Any,
) -> None:
    store, run, node_run, attempt = await _produce(spine)
    failing = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=0.2,
        passed=False,
    )
    await store.record_eval_score(failing)

    # The retry is a new Attempt on the same NodeRun of the same Run/Graph —
    # not a new anonymous generation, not a rewrite of the failed one.
    retry = await open_re_eval_attempt(store, run.run_id, node_run.node_run_id)
    assert retry.attempt_id != attempt.attempt_id
    assert retry.node_run_id == node_run.node_run_id
    assert retry.ordinal == attempt.ordinal + 1

    passing = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=retry.attempt_id,
        dimension="contrast",
        raw_score=0.9,
        passed=True,
    )
    await store.record_eval_score(passing)

    # The failed record is append-only evidence: still there, still failing.
    failed_record = await store.get_eval_score(failing.eval_id)
    assert failed_record is not None
    assert failed_record.passed is False
    assert failed_record.attempt_id == attempt.attempt_id

    summary = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=("contrast",),
    )
    # The latest record supersedes without deleting the earlier one.
    assert summary.complete is True
    assert summary.passed is True
    assert summary.latest_by_dimension["contrast"].eval_id == passing.eval_id
    assert len(summary.records) == 2
    assert {record.eval_id for record in summary.records} == {
        failing.eval_id,
        passing.eval_id,
    }


async def test_a_reeval_waits_for_the_prior_attempt_and_stays_on_its_own_run(
    spine: Any,
) -> None:
    """A retry opens only where the spine allows one: same Run, no live Attempt."""
    store, run, node_run, _attempt = await _produce(spine)

    other = await store.create_run(_graph(*spine[1:]))
    other_node_run = await store.create_node_run(other.run_id, node_id="node-1")
    with pytest.raises(NodeRunNotFound):
        await open_re_eval_attempt(store, run.run_id, other_node_run.node_run_id)

    with pytest.raises(RunNotFound):
        await open_re_eval_attempt(store, "run-that-never-was", node_run.node_run_id)

    # A live Attempt on the NodeRun is work in flight; the retry waits for it.
    live = await store.create_attempt(node_run.node_run_id)
    with pytest.raises(ActiveAttemptExists):
        await open_re_eval_attempt(store, run.run_id, node_run.node_run_id)
    await store.transition_attempt(live.attempt_id, AttemptStatus.RUNNING)
    await store.transition_attempt(live.attempt_id, AttemptStatus.YIELDED)
    retry = await open_re_eval_attempt(store, run.run_id, node_run.node_run_id)
    assert retry.ordinal == live.ordinal + 1


async def test_eval_complete_is_a_property_of_persisted_records_not_of_intentions(
    spine: Any,
) -> None:
    """Nothing off the Run's durable evidence can make a Run read eval-complete."""
    store, run, node_run, attempt = await _produce(spine)

    unscored = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=DIMENSIONS,
    )
    assert unscored.complete is False
    assert unscored.passed is False
    assert unscored.missing_dimensions == DIMENSIONS

    # The sidecar shape the contract forbids: a score held on the artifact's
    # own state — a DesignProject field, a CreativeBrief dict, UI state — is
    # invisible to the Run. Only persisted Run evidence answers.
    sidecar_state: dict[str, RunEvalScore] = {}
    sidecar_state["contrast"] = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=1.0,
        passed=True,
    )
    assert sidecar_state["contrast"].passed is True
    still_unscored = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=DIMENSIONS,
    )
    assert still_unscored.complete is False

    # Persisting one of the two dimensions completes exactly one.
    await store.record_eval_score(sidecar_state.pop("contrast"))
    half = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=DIMENSIONS,
    )
    assert half.complete is False
    assert half.missing_dimensions == ("palette",)

    # A different Rubric revision does not answer for this one: the record
    # names the revision it scored, and the summary asks for a specific one.
    await store.record_eval_score(
        _score(
            store_run_id=run.run_id,
            node_run_id=node_run.node_run_id,
            attempt_id=attempt.attempt_id,
            dimension="palette",
            raw_score=0.8,
            passed=True,
        )
    )
    prior_rubric = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION + 1,
        dimension_ids=DIMENSIONS,
    )
    assert prior_rubric.complete is False

    complete = await eval_summary(
        store,
        run.run_id,
        rubric_id=RUBRIC_ID,
        rubric_revision=RUBRIC_REVISION,
        dimension_ids=DIMENSIONS,
    )
    assert complete.complete is True
    assert complete.passed is True
    assert complete.missing_dimensions == ()


async def test_an_eval_record_cannot_dangle_off_the_spine(spine: Any) -> None:
    """Run, NodeRun, Attempt must be one connected triple, or the store refuses."""
    store, run, node_run, attempt = await _produce(spine)
    other_run = await store.create_run(_graph(*spine[1:]))
    other_node_run = await store.create_node_run(other_run.run_id, node_id="node-1")
    other_attempt = await store.create_attempt(other_node_run.node_run_id)

    def _named(**overrides: Any) -> RunEvalScore:
        fields = {
            "store_run_id": run.run_id,
            "node_run_id": node_run.node_run_id,
            "attempt_id": attempt.attempt_id,
            "dimension": "contrast",
            "raw_score": 0.5,
            "passed": True,
        }
        fields.update(overrides)
        return _score(**fields)

    # A NodeRun from a different Run is not this Run's evidence.
    with pytest.raises(RunIntegrityError, match="belongs to Run"):
        await store.record_eval_score(
            _named(node_run_id=other_node_run.node_run_id, attempt_id=other_attempt.attempt_id)
        )
    # An Attempt from a different NodeRun did not produce this artifact.
    with pytest.raises(RunIntegrityError, match="belongs to NodeRun"):
        await store.record_eval_score(_named(attempt_id=other_attempt.attempt_id))
    with pytest.raises(RunNotFound):
        await store.record_eval_score(_named(store_run_id="run-that-never-was"))
    with pytest.raises(NodeRunNotFound):
        await store.record_eval_score(_named(node_run_id="nr-that-never-was"))
    with pytest.raises(AttemptNotFound):
        await store.record_eval_score(_named(attempt_id="attempt-that-never-was"))

    # None of the refusals left anything behind.
    assert await store.list_eval_scores(run.run_id) == []


async def test_eval_records_are_append_only(spine: Any) -> None:
    store, run, node_run, attempt = await _produce(spine)
    first = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=0.2,
        passed=False,
    )
    await store.record_eval_score(first)

    # Same eval_id is a duplicate identity, not a rewrite: refused outright.
    with pytest.raises(RunIntegrityError, match="already recorded"):
        await store.record_eval_score(first)
    assert len(await store.list_eval_scores(run.run_id)) == 1

    # A superseding score is a new record; the failed one is untouched.
    second = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=0.9,
        passed=True,
    )
    await store.record_eval_score(second)
    listed = await store.list_eval_scores(run.run_id)
    assert [score.eval_id for score in listed] == [first.eval_id, second.eval_id]
    assert listed[0].passed is False
    assert listed[1].passed is True


async def test_deleting_the_run_takes_its_eval_evidence_with_it(spine: Any) -> None:
    """Eval evidence is spine-attached: it dies with the Run, never before it."""
    store, run, node_run, attempt = await _produce(spine)
    score = _score(
        store_run_id=run.run_id,
        node_run_id=node_run.node_run_id,
        attempt_id=attempt.attempt_id,
        dimension="contrast",
        raw_score=0.2,
        passed=False,
    )
    await store.record_eval_score(score)

    assert await store.delete_run(run.run_id, force=True) is True
    assert await store.get_eval_score(score.eval_id) is None
    with pytest.raises(RunNotFound):
        await store.list_eval_scores(run.run_id)


async def test_scoring_a_run_that_does_not_exist_is_refused(spine: Any) -> None:
    store, _workspace, _project_id = spine
    with pytest.raises(RunNotFound):
        await store.record_eval_score(
            _score(
                store_run_id="run-that-never-was",
                node_run_id="nr-that-never-was",
                attempt_id="attempt-that-never-was",
                dimension="contrast",
                raw_score=0.5,
                passed=True,
            )
        )


def test_the_judge_names_whatever_scored_when_it_is_not_deterministic() -> None:
    """A model- or human-scored record is auditable only if it names its judge."""

    def _model_score(method: EvalMethod, judge: EvalJudge | None) -> RunEvalScore:
        return RunEvalScore(
            run_id="run-1",
            node_run_id="nr-1",
            attempt_id="a-1",
            goal_id=GOAL_ID,
            goal_revision=1,
            rubric_id=RUBRIC_ID,
            rubric_revision=1,
            dimension_id="contrast",
            raw_score=0.8,
            passed=True,
            method=method,
            judge=judge,
        )

    # Deterministic scoring is in-process: naming a judge contradicts it.
    with pytest.raises(ValueError, match="cannot name a judge"):
        _model_score(
            EvalMethod.DETERMINISTIC,
            EvalJudge(kind=EvalMethod.MODEL_JUDGE, identity="gpt-judge"),
        )
    # A model verdict without the model's identity cannot be audited.
    with pytest.raises(ValueError, match="must name its judge"):
        _model_score(EvalMethod.MODEL_JUDGE, None)
    # The judge's kind must agree with the method that recorded the score.
    with pytest.raises(ValueError, match="kind must match"):
        _model_score(
            EvalMethod.MODEL_JUDGE,
            EvalJudge(kind=EvalMethod.HUMAN, identity="reviewer-7"),
        )
    # Human scoring waits on the HITL fence and records who answered.
    human = _model_score(
        EvalMethod.HUMAN,
        EvalJudge(kind=EvalMethod.HUMAN, identity="reviewer-7"),
    )
    assert human.judge is not None
    assert human.judge.identity == "reviewer-7"


async def test_a_summary_over_no_dimensions_is_a_question_that_means_nothing(
    spine: Any,
) -> None:
    """Completeness over an empty dimension set would vacuously read complete."""
    store, run, _node_run, _attempt = await _produce(spine)
    with pytest.raises(ValueError, match="must not be empty"):
        await eval_summary(
            store,
            run.run_id,
            rubric_id=RUBRIC_ID,
            rubric_revision=RUBRIC_REVISION,
            dimension_ids=(),
        )


async def test_a_summary_cannot_ask_twice_for_the_same_dimension(spine: Any) -> None:
    """A duplicated dimension would silently answer one record for two asks."""
    store, run, _node_run, _attempt = await _produce(spine)
    with pytest.raises(ValueError, match="must not contain duplicates"):
        await eval_summary(
            store,
            run.run_id,
            rubric_id=RUBRIC_ID,
            rubric_revision=RUBRIC_REVISION,
            dimension_ids=("contrast", "contrast"),
        )
