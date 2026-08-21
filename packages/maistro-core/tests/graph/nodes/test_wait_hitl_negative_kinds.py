"""Phase 1c: tests for the wait/HITL/negative-signal node kinds.

Pause/resume semantics are tested by inspecting the NodeResult envelope —
the runtime piece that persists the pause + later re-invokes the node is
exercised separately (next commit in this phase).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from maistro.graph.nodes import NodeContext, get_node, list_kinds


def _ctx(**overrides: Any) -> NodeContext:
    base = {
        "run_id": "r1",
        "dag_id": "d1",
        "node_id": "n1",
        "user_id": "u1",
        "project_id": "p1",
    }
    base.update(overrides)
    return NodeContext(**base)


# --- human.ask_question ---------------------------------------------------


async def test_ask_question_first_reach_pauses_with_metadata() -> None:
    Node = get_node("human.ask_question")
    result = await Node().run(
        {
            "question": "Approve the rollout to canary?",
            "response_kind": "yes_no",
            "timeout_seconds": 3600,
            "context_markdown": "## Risk profile\nLow.",
        },
        _ctx(node_id="approve-canary"),
    )
    assert result.success is True
    assert result.status == "paused"
    assert result.resume_at is not None
    assert result.metadata["paused_reason"] == "awaiting_human_answer"
    assert result.metadata["question"] == "Approve the rollout to canary?"
    assert result.metadata["response_kind"] == "yes_no"
    assert result.metadata["context_markdown"].startswith("## Risk")


async def test_ask_question_resume_with_user_answer_completes() -> None:
    Node = get_node("human.ask_question")
    ctx = _ctx(node_id="approve-canary")
    ctx.metadata["hitl_answers"] = {
        "approve-canary": {"answer": True, "answered_at": "2026-05-22T10:00:00Z"}
    }
    result = await Node().run({"question": "Approve?", "response_kind": "yes_no"}, ctx)
    assert result.success is True
    assert result.status == "completed"
    assert result.output.answer is True
    assert result.output.answered_at == "2026-05-22T10:00:00Z"
    assert result.output.timed_out is False


# --- human.approve_draft --------------------------------------------------


async def test_approve_draft_first_reach_pauses_with_draft_payload() -> None:
    Node = get_node("human.approve_draft")
    draft = {"summary": "Audit lockfile", "project": "PROJ"}
    result = await Node().run(
        {"draft": draft, "draft_kind": "jira_ticket", "title": "Create Audit Story"},
        _ctx(node_id="approve-jira-draft"),
    )
    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "awaiting_human_approval"
    assert result.metadata["draft"] == draft
    assert result.metadata["draft_kind"] == "jira_ticket"
    assert result.metadata["title"] == "Create Audit Story"


async def test_approve_draft_resume_with_verdict_modified() -> None:
    Node = get_node("human.approve_draft")
    ctx = _ctx(node_id="approve-jira-draft")
    ctx.metadata["hitl_answers"] = {
        "approve-jira-draft": {
            "verdict": "modified",
            "modified_draft": {"summary": "Audit lockfile (Q3)", "project": "PROJ"},
            "reviewer_note": "Add Q3 scope",
        }
    }
    result = await Node().run({"draft": {"summary": "x"}, "draft_kind": "jira_ticket"}, ctx)
    assert result.status == "completed"
    assert result.output.verdict == "modified"
    assert result.output.modified_draft is not None
    assert result.output.modified_draft["summary"] == "Audit lockfile (Q3)"
    assert result.output.reviewer_note == "Add Q3 scope"


# --- jira.wait_for_subtasks -----------------------------------------------


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, payload: dict[str, Any], status_code: int = 200
) -> None:
    class _Resp:
        status_code = 200

        def json(self) -> Any:
            return payload

    _Resp.status_code = status_code

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def get(self, *args: Any, **kwargs: Any) -> _Resp:
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


async def test_wait_for_subtasks_short_circuits_when_no_subtasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(monkeypatch, {"fields": {"subtasks": []}})
    Node = get_node("jira.wait_for_subtasks")
    result = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "PROJ-100",
            "pat": "pat",
            "flavor": "server",
            "target_statuses": ["Done"],
        },
        _ctx(),
    )
    assert result.status == "completed"
    assert result.output.all_match is True
    assert result.output.subtask_keys == []
    assert result.output.timed_out is False


async def test_wait_for_subtasks_all_done_returns_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(
        monkeypatch,
        {
            "fields": {
                "subtasks": [
                    {"key": "PROJ-101", "fields": {"status": {"name": "Done"}}},
                    {"key": "PROJ-102", "fields": {"status": {"name": "Closed"}}},
                ]
            }
        },
    )
    Node = get_node("jira.wait_for_subtasks")
    result = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "PROJ-100",
            "pat": "pat",
            "flavor": "server",
            "target_statuses": ["Done", "Closed"],
        },
        _ctx(),
    )
    assert result.status == "completed"
    assert result.output.all_match is True
    assert sorted(result.output.subtask_keys) == ["PROJ-101", "PROJ-102"]


async def test_wait_for_subtasks_some_open_pauses_for_poll_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(
        monkeypatch,
        {
            "fields": {
                "subtasks": [
                    {"key": "PROJ-101", "fields": {"status": {"name": "Done"}}},
                    {"key": "PROJ-102", "fields": {"status": {"name": "In Progress"}}},
                ]
            }
        },
    )
    Node = get_node("jira.wait_for_subtasks")
    result = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "PROJ-100",
            "pat": "pat",
            "target_statuses": ["Done"],
            "poll_interval_seconds": 60,
        },
        _ctx(),
    )
    assert result.status == "paused"
    assert result.metadata["paused_reason"] == "waiting_on_jira_subtasks"
    assert result.metadata["current_statuses"]["PROJ-101"] == "Done"
    assert result.metadata["current_statuses"]["PROJ-102"] == "In Progress"


async def test_wait_for_subtasks_timeout_returns_timed_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_httpx(
        monkeypatch,
        {"fields": {"subtasks": [{"key": "PROJ-101", "fields": {"status": {"name": "Open"}}}]}},
    )
    Node = get_node("jira.wait_for_subtasks")
    # Simulate "we started waiting an hour ago" with a 60-second timeout.
    ctx = _ctx()
    from datetime import UTC, datetime, timedelta

    one_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    ctx.metadata[f"wait_first_seen:{ctx.node_id}"] = one_hour_ago
    result = await Node().run(
        {
            "base_url": "https://jira.example.com",
            "parent_key": "PROJ-100",
            "pat": "pat",
            "target_statuses": ["Done"],
            "timeout_seconds": 60,
        },
        ctx,
    )
    assert result.status == "completed"  # node returned successfully — outcome is "timed out"
    assert result.output.timed_out is True
    assert result.output.all_match is False


# --- compliance.block (negative_signal) -----------------------------------


async def test_compliance_block_writes_penalty_to_blackboard() -> None:
    from maistro.graph.types import GraphBlackboard

    bb = GraphBlackboard(task_objective="x", workspace="")
    ctx = NodeContext(run_id="r1", dag_id="d1", node_id="block-1", blackboard=bb)
    Node = get_node("compliance.block")
    result = await Node().run(
        {
            "rule_id": "pii.email_in_summary",
            "severity": 3.0,
            "reason": "Draft summary contains a customer email address",
            "evidence": {"matched": "alice@example.com"},
        },
        ctx,
    )
    assert result.success
    assert result.output.rule_id == "pii.email_in_summary"
    assert result.output.severity == 3.0
    assert result.output.halt_run is False
    penalties = bb.metadata["penalties"]
    assert len(penalties) == 1
    p = penalties[0]
    assert p["rule_id"] == "pii.email_in_summary"
    assert p["severity"] == 3.0
    assert p["evidence"] == {"matched": "alice@example.com"}
    # No halt requested
    assert "halt_requested" not in bb.metadata


async def test_compliance_block_with_halt_sets_halt_flag() -> None:
    from maistro.graph.types import GraphBlackboard

    bb = GraphBlackboard(task_objective="x", workspace="")
    ctx = NodeContext(run_id="r1", dag_id="d1", node_id="block-1", blackboard=bb)
    Node = get_node("compliance.block")
    await Node().run(
        {
            "rule_id": "policy.export_controlled",
            "severity": 10.0,
            "halt_run": True,
            "reason": "ITAR",
        },
        ctx,
    )
    assert bb.metadata.get("halt_requested") is True
    assert bb.metadata.get("halt_reason") == "ITAR"


# --- Registry presence ----------------------------------------------------


def test_phase1c_kinds_registered() -> None:
    kinds = set(list_kinds())
    expected = {
        "human.ask_question",
        "human.approve_draft",
        "jira.wait_for_subtasks",
        "compliance.block",
    }
    missing = expected - kinds
    assert not missing, f"missing kinds: {missing}"


def test_full_catalog_has_eleven_kinds_after_phases_1a_1b_1c() -> None:
    # 7 sync (Phase 1b) + 4 async/special (Phase 1c) = 11 + 3 test fixtures
    # registered by test_base_contract = 14. We assert ≥ 11 production kinds.
    production_kinds = [k for k in list_kinds() if not k.startswith("test.")]
    assert len(production_kinds) >= 11
