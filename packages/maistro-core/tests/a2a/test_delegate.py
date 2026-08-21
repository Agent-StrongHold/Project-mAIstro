"""Tests for `maistro.a2a.delegate` — task delegation, modes, and status tracking."""

from __future__ import annotations

import itertools

import pytest

from maistro.a2a.delegate import A2ADelegator, DelegationMode, TaskStatus, can_transition


def test_register_agent_capability_records_targets() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder", "reviewer"])
    task_id = delegator.delegate_task(
        "planner", "do x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.to_agent == "coder"


def test_delegate_task_none_mode_with_to_agent_raises() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    with pytest.raises(ValueError, match="Cannot specify to_agent with delegation_mode=NONE"):
        delegator.delegate_task("planner", "x", "coder", delegation_mode=DelegationMode.NONE)


def test_delegate_task_no_capabilities_raises() -> None:
    delegator = A2ADelegator()
    with pytest.raises(ValueError, match="Agent planner has no delegation capabilities"):
        delegator.delegate_task("planner", "x", None, delegation_mode=DelegationMode.ALLOW_ALL)


def test_delegate_task_to_agent_not_in_capabilities_raises() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    with pytest.raises(ValueError, match=r"Agent planner cannot delegate to reviewer"):
        delegator.delegate_task(
            "planner", "x", "reviewer", delegation_mode=DelegationMode.ALLOW_LIST
        )


def test_delegate_task_auto_select_allow_all_picks_first_capability() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder", "reviewer"])
    task_id = delegator.delegate_task(
        "planner", "x", None, delegation_mode=DelegationMode.ALLOW_ALL
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.to_agent == "coder"


def test_delegate_task_auto_select_allow_list_uses_priority_tier() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder", "reviewer"])
    delegator.register_agent_capability("coder", ["P1"])
    delegator.register_agent_capability("reviewer", ["P0"])
    task_id = delegator.delegate_task(
        "planner", "x", None, delegation_mode=DelegationMode.ALLOW_LIST
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.to_agent == "reviewer"


def test_select_from_priority_falls_back_to_first_agent_when_no_tier_matches() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder", "reviewer"])
    task_id = delegator.delegate_task(
        "planner", "x", None, delegation_mode=DelegationMode.ALLOW_LIST
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.to_agent == "coder"


def test_delegate_task_unknown_mode_defaults_to_first_capability() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder", "reviewer"])
    task_id = delegator.delegate_task("planner", "x", None, delegation_mode=DelegationMode.NONE)
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.to_agent == "coder"


def test_delegate_task_sets_queued_status_and_metadata_fields() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "implement x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.QUEUED
    assert task.from_agent == "planner"
    assert task.task == "implement x"
    assert task.assigned_at is None
    assert task.completed_at is None
    assert task.result is None
    assert task.error is None
    assert task.delegation_mode == DelegationMode.ALLOW_LIST


def test_get_task_status_unknown_task_returns_none() -> None:
    delegator = A2ADelegator()
    assert delegator.get_task_status("nonexistent") is None


def test_update_task_status_running_to_completed_sets_completed_at() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    delegator.update_task_status(task_id, TaskStatus.RUNNING)
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.completed_at is None

    delegator.update_task_status(task_id, TaskStatus.COMPLETED, result="done")
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.COMPLETED
    assert task.result == "done"
    assert task.completed_at is not None
    assert task.error is None


def test_update_task_status_failed_sets_completed_at_and_error() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    delegator.update_task_status(task_id, TaskStatus.FAILED, error="boom")
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.FAILED
    assert task.error == "boom"
    assert task.completed_at is not None


def test_update_task_status_cancelled_sets_completed_at_and_error() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    delegator.update_task_status(task_id, TaskStatus.CANCELLED, error="abandoned")
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.CANCELLED
    assert task.error == "abandoned"
    assert task.completed_at is not None


def test_update_task_status_queued_to_assigned_does_not_set_completed_at() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    delegator.update_task_status(task_id, TaskStatus.ASSIGNED)
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.ASSIGNED
    assert task.completed_at is None


def test_update_task_status_unknown_task_raises() -> None:
    delegator = A2ADelegator()
    with pytest.raises(ValueError, match="Task not found: nope"):
        delegator.update_task_status("nope", TaskStatus.COMPLETED)


def test_update_task_status_rejects_invalid_transition() -> None:
    delegator = A2ADelegator()
    delegator.register_agent_capability("planner", ["coder"])
    task_id = delegator.delegate_task(
        "planner", "x", "coder", delegation_mode=DelegationMode.ALLOW_LIST
    )
    delegator.update_task_status(task_id, TaskStatus.RUNNING)
    delegator.update_task_status(task_id, TaskStatus.COMPLETED, result="done")
    with pytest.raises(ValueError, match="Invalid task status transition"):
        delegator.update_task_status(task_id, TaskStatus.QUEUED)
    task = delegator.get_task_status(task_id)
    assert task is not None
    assert task.status == TaskStatus.COMPLETED


# Independently re-derived expected transitions for A2A's 6-value TaskStatus
# (distinct from tasks/status.py's 8-value enum). QUEUED can jump straight to
# RUNNING (auto-started, no separate assignment step) per the existing
# test_update_task_status_running_to_completed_sets_completed_at above, or go
# through ASSIGNED first. COMPLETED/FAILED/CANCELLED are terminal.
EXPECTED_A2A_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.QUEUED: frozenset(
        {TaskStatus.ASSIGNED, TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}
    ),
    TaskStatus.ASSIGNED: frozenset({TaskStatus.RUNNING, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED}),
    TaskStatus.COMPLETED: frozenset(),
    TaskStatus.FAILED: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

_ALL_A2A_PAIRS = list(itertools.product(TaskStatus, TaskStatus))


@pytest.mark.parametrize(
    "current,target",
    _ALL_A2A_PAIRS,
    ids=[f"{c.value}->{t.value}" for c, t in _ALL_A2A_PAIRS],
)
def test_a2a_transition_matrix(current: TaskStatus, target: TaskStatus) -> None:
    expected = target in EXPECTED_A2A_TRANSITIONS[current]
    assert can_transition(current, target) is expected


class TestA2ATerminalStatesAreAbsorbing:
    @pytest.mark.parametrize(
        "terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
    )
    def test_no_outgoing_transitions(self, terminal: TaskStatus) -> None:
        for target in TaskStatus:
            assert can_transition(terminal, target) is False

    @pytest.mark.parametrize(
        "terminal", [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]
    )
    def test_terminal_cannot_self_transition(self, terminal: TaskStatus) -> None:
        assert can_transition(terminal, terminal) is False


class TestA2ANoSelfTransitions:
    @pytest.mark.parametrize("status", list(TaskStatus))
    def test_no_status_can_self_transition(self, status: TaskStatus) -> None:
        assert can_transition(status, status) is False
