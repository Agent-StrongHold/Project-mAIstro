"""Behavioral tests for the Builders 2.0 orchestrator state machine.

Covers: stage-transition validation, completion gates, retry counting,
result application (status mapping, artifact merge, idempotency), and
dump/load round-tripping.
"""

from __future__ import annotations

import pytest

from maistro.builders.contracts import (
    ArtifactRef,
    RunResult,
    RunStatus,
    StageEvent,
    WorkerName,
)
from maistro.builders.orchestrator import BuildersOrchestrator, RunState


def _new_run(orch: BuildersOrchestrator, run_id: str = "run-1") -> RunState:
    return orch.create_run(
        run_id=run_id,
        repo="acme/widget",
        issue_number=42,
        branch="feat/widget",
        workspace_ref="ws-abc",
    )


# ---------------------------------------------------------------------------
# create_run
# ---------------------------------------------------------------------------


def test_create_run_initial_state() -> None:
    orch = BuildersOrchestrator()
    run = _new_run(orch)

    assert run.run_id == "run-1"
    assert run.current_stage == "queued"
    assert run.current_worker is WorkerName.FRANK
    assert run.status is RunStatus.QUEUED
    assert run.runtime_version == "v1"  # only ready version registered by default


def test_create_run_emits_run_created_event() -> None:
    orch = BuildersOrchestrator()
    run = _new_run(orch)

    assert len(run.events) == 1
    event = run.events[0]
    assert event.event == "run_created"
    assert event.actor == "system"
    assert event.stage == "queued"
    assert "#42" in event.message


def test_create_run_is_retrievable() -> None:
    orch = BuildersOrchestrator()
    run = _new_run(orch)
    assert orch.get_run("run-1") is run


# ---------------------------------------------------------------------------
# advance_stage — transition validation
# ---------------------------------------------------------------------------


def test_advance_stage_valid_transition() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    run = orch.advance_stage("run-1", "issue_analyzed")

    assert run.current_stage == "issue_analyzed"
    assert run.status is RunStatus.RUNNING
    assert run.events[-1].event == "stage_advanced"


def test_advance_stage_invalid_transition_rejected() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    # queued may only go to issue_analyzed.
    with pytest.raises(ValueError, match="invalid stage transition"):
        orch.advance_stage("run-1", "completed")


def test_advance_stage_to_terminal_states_sets_status() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed")
    run = orch.advance_stage("run-1", "blocked")

    assert run.current_stage == "blocked"
    assert run.status is RunStatus.BLOCKED
    # blocked is terminal — no further transitions allowed.
    with pytest.raises(ValueError, match="invalid stage transition"):
        orch.advance_stage("run-1", "issue_analyzed")


def test_advance_stage_to_failed_sets_failed_status() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed")
    orch.advance_stage("run-1", "acceptance_defined")
    orch.advance_stage("run-1", "tests_written")
    orch.advance_stage("run-1", "implementation_started")
    run = orch.advance_stage("run-1", "failed")

    assert run.current_stage == "failed"
    assert run.status is RunStatus.FAILED


def test_advance_stage_changes_worker_when_requested() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    run = orch.advance_stage("run-1", "issue_analyzed", next_worker=WorkerName.MASON)
    assert run.current_worker is WorkerName.MASON


def test_advance_stage_full_happy_path_to_completed() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    sequence = [
        "issue_analyzed",
        "acceptance_defined",
        "tests_written",
        "implementation_started",
        "implementation_ready",
        "quality_checks_passed",
        "completed",
    ]
    for stage in sequence:
        orch.advance_stage("run-1", stage)
    run = orch.get_run("run-1")
    assert run.current_stage == "completed"
    assert run.status is RunStatus.PASSED


# ---------------------------------------------------------------------------
# completion gates
# ---------------------------------------------------------------------------


def _drive_to_quality_checks(orch: BuildersOrchestrator) -> None:
    for stage in (
        "issue_analyzed",
        "acceptance_defined",
        "tests_written",
        "implementation_started",
        "implementation_ready",
        "quality_checks_passed",
    ):
        orch.advance_stage("run-1", stage)


def test_can_complete_requires_quality_checks_stage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed")
    # Not at quality_checks_passed yet.
    assert (
        orch.can_complete("run-1", ci_passed=True, coverage_pct=99.0, quality_passed=True) is False
    )


def test_can_complete_all_gates_satisfied() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    assert (
        orch.can_complete("run-1", ci_passed=True, coverage_pct=85.0, quality_passed=True) is True
    )


def test_can_complete_blocked_by_low_coverage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    assert (
        orch.can_complete("run-1", ci_passed=True, coverage_pct=84.9, quality_passed=True) is False
    )


def test_can_complete_blocked_by_failed_ci() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    assert (
        orch.can_complete("run-1", ci_passed=False, coverage_pct=100.0, quality_passed=True)
        is False
    )


def test_can_complete_blocked_by_quality() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    assert (
        orch.can_complete("run-1", ci_passed=True, coverage_pct=100.0, quality_passed=False)
        is False
    )


def test_complete_run_if_ready_advances_when_gates_pass() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    run = orch.complete_run_if_ready(
        "run-1", ci_passed=True, coverage_pct=90.0, quality_passed=True
    )
    assert run.current_stage == "completed"
    assert run.status is RunStatus.PASSED


def test_complete_run_if_ready_raises_when_gates_fail() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    _drive_to_quality_checks(orch)
    with pytest.raises(ValueError, match="completion gates not satisfied"):
        orch.complete_run_if_ready("run-1", ci_passed=False, coverage_pct=90.0, quality_passed=True)
    # Run must NOT have advanced.
    assert orch.get_run("run-1").current_stage == "quality_checks_passed"


# ---------------------------------------------------------------------------
# schedule_retry — retry counting
# ---------------------------------------------------------------------------


def test_schedule_retry_counts_per_stage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed")

    orch.schedule_retry("run-1", reason="flaky")
    orch.schedule_retry("run-1", reason="flaky again")
    run = orch.get_run("run-1")

    assert run.retries["issue_analyzed"] == 2
    assert run.status is RunStatus.RUNNING
    assert run.events[-1].event == "retry_scheduled"
    assert run.events[-1].message == "flaky again"


def test_schedule_retry_is_keyed_by_current_stage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed")
    orch.schedule_retry("run-1", reason="r1")
    orch.advance_stage("run-1", "acceptance_defined")
    orch.schedule_retry("run-1", reason="r2")
    run = orch.get_run("run-1")
    assert run.retries == {"issue_analyzed": 1, "acceptance_defined": 1}


# ---------------------------------------------------------------------------
# build_request
# ---------------------------------------------------------------------------


def test_build_request_reflects_current_run_state() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    orch.advance_stage("run-1", "issue_analyzed", next_worker=WorkerName.MASON)
    req = orch.build_request("run-1")

    assert req.run_id == "run-1"
    assert req.stage == "issue_analyzed"
    assert req.worker is WorkerName.MASON
    assert req.repo == "acme/widget"
    assert req.issue_number == 42
    assert req.context["runtime_version"] == "v1"


# ---------------------------------------------------------------------------
# apply_result — status mapping + artifact merge
# ---------------------------------------------------------------------------


def test_apply_result_running_sets_running_and_advances() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.PASSED,
        summary="analyzed",
    )
    run = orch.apply_result(result, next_stage="issue_analyzed")
    assert run.current_stage == "issue_analyzed"
    assert run.status is RunStatus.RUNNING


def test_apply_result_failed_short_circuits_to_failed_stage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.FAILED,
        summary="boom",
    )
    run = orch.apply_result(result)
    assert run.status is RunStatus.FAILED
    assert run.current_stage == "failed"


def test_apply_result_blocked_short_circuits_to_blocked_stage() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.BLOCKED,
        summary="cannot proceed",
    )
    run = orch.apply_result(result)
    assert run.status is RunStatus.BLOCKED
    assert run.current_stage == "blocked"


def test_apply_result_merges_new_artifacts_without_duplicates() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    art = ArtifactRef(type="spec", path="runs/run-1/spec.json", producer="frank")
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.PASSED,
        summary="produced spec",
        artifacts=[art],
    )
    orch.apply_result(result)
    # Re-applying with the same artifact id must not duplicate it.
    result2 = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.PASSED,
        summary="produced spec again",
        artifacts=[art],
    )
    run = orch.apply_result(result2)
    matching = [a for a in run.artifacts if a.artifact_id == art.artifact_id]
    assert len(matching) == 1


@pytest.mark.xfail(
    reason=(
        "DEFECT: apply_result dedup compares full StageEvent.model_dump(), which "
        "includes the per-call `timestamp` default. Two otherwise-identical results "
        "produce events with different timestamps, so the idempotency guard at "
        "orchestrator.py:170 never fires and a duplicate event is appended."
    ),
    strict=True,
)
def test_apply_result_is_idempotent_for_duplicate_result() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    result = RunResult(
        run_id="run-1",
        worker=WorkerName.FRANK,
        stage="queued",
        status=RunStatus.PASSED,
        summary="analyzed",
    )
    orch.apply_result(result)
    n_after_first = len(orch.get_run("run-1").events)
    orch.apply_result(result)
    n_after_dup = len(orch.get_run("run-1").events)
    assert n_after_dup == n_after_first


# ---------------------------------------------------------------------------
# runtime version selection
# ---------------------------------------------------------------------------


def test_select_runtime_version_prefers_highest_ready() -> None:
    orch = BuildersOrchestrator()
    orch.register_runtime_version("v2", state="ready")
    assert orch.select_runtime_version() == "v2"


def test_select_runtime_version_skips_non_ready() -> None:
    orch = BuildersOrchestrator()
    orch.register_runtime_version("v2", state="draining")
    assert orch.select_runtime_version() == "v1"


def test_select_runtime_version_raises_when_none_ready() -> None:
    orch = BuildersOrchestrator()
    orch.set_runtime_state("v1", "retired")
    with pytest.raises(ValueError, match="no ready runtime version"):
        orch.select_runtime_version()


def test_active_runs_for_version_counts_only_in_flight() -> None:
    orch = BuildersOrchestrator()
    orch.create_run(
        run_id="active",
        repo="r",
        issue_number=1,
        branch="b",
        workspace_ref="w",
        runtime_version="v1",
    )
    orch.advance_stage("active", "issue_analyzed")
    orch.create_run(
        run_id="done",
        repo="r",
        issue_number=2,
        branch="b",
        workspace_ref="w",
        runtime_version="v1",
    )
    done = orch.get_run("done")
    done.status = RunStatus.PASSED
    assert orch.active_runs_for_version("v1") == 1


# ---------------------------------------------------------------------------
# dump / load round-trip
# ---------------------------------------------------------------------------


def test_dump_load_round_trip_preserves_run_state() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    art = ArtifactRef(type="spec", path="runs/run-1/spec.json", producer="frank")
    orch.get_run("run-1").artifacts.append(art)
    orch.advance_stage("run-1", "issue_analyzed")
    orch.schedule_retry("run-1", reason="retry me")

    payload = orch.dump_runs()

    restored = BuildersOrchestrator()
    restored.load_runs(payload)
    original = orch.get_run("run-1")
    loaded = restored.get_run("run-1")

    assert loaded.run_id == original.run_id
    assert loaded.repo == original.repo
    assert loaded.issue_number == original.issue_number
    assert loaded.branch == original.branch
    assert loaded.workspace_ref == original.workspace_ref
    assert loaded.current_stage == original.current_stage
    assert loaded.current_worker == original.current_worker
    assert loaded.status == original.status
    assert loaded.runtime_version == original.runtime_version
    assert loaded.retries == original.retries
    assert [a.artifact_id for a in loaded.artifacts] == [a.artifact_id for a in original.artifacts]
    assert len(loaded.events) == len(original.events)


def test_dump_runs_serializes_events_as_json() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch)
    payload = orch.dump_runs()
    assert len(payload) == 1
    events = payload[0]["events"]
    assert isinstance(events, list)
    # mode="json" => timestamp serialized to a string, not a datetime.
    assert isinstance(events[0]["timestamp"], str)


def test_load_runs_replaces_existing_state() -> None:
    orch = BuildersOrchestrator()
    _new_run(orch, run_id="old")
    payload: list[dict[str, object]] = [
        {
            "run_id": "new",
            "repo": "r",
            "issue_number": 7,
            "branch": "b",
            "workspace_ref": "w",
            "current_stage": "queued",
            "current_worker": "frank",
            "status": "queued",
            "runtime_version": "v1",
            "artifacts": [],
            "events": [],
            "retries": {},
        }
    ]
    orch.load_runs(payload)
    assert orch.get_run("new").run_id == "new"
    with pytest.raises(KeyError):
        orch.get_run("old")


def test_stage_event_roundtrips_through_model_validate() -> None:
    # Guards the load path: events are reconstructed via model_validate.
    event = StageEvent(
        run_id="run-1",
        stage="queued",
        event="run_created",
        actor="system",
        message="hi",
    )
    rebuilt = StageEvent.model_validate(event.model_dump(mode="json"))
    assert rebuilt.run_id == event.run_id
    assert rebuilt.event == event.event
