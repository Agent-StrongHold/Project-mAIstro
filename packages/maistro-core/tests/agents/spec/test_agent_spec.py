"""Coverage for maistro.agents.spec.agent_spec (was 0%).

Exercises AgentSpec/AgentOutput defaults, with_defaults() role-derived
fill-in (and its "don't overwrite explicit values" guarantee), and
mark_error()/mark_complete() duration + recoverability computation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from maistro.agents.spec.agent_spec import (
    DEFAULT_TOOLS,
    RECOVERABLE_ERRORS,
    AgentOutput,
    AgentRole,
    AgentSpec,
    ErrorType,
    Lane,
)


def _spec(**overrides) -> AgentSpec:
    defaults = {
        "role": AgentRole.CODER,
        "task_id": "task-1",
        "subtask_id": "sub-1",
        "description": "do the thing",
    }
    defaults.update(overrides)
    return AgentSpec(**defaults)


# ─── AgentSpec defaults ──────────────────────────────────────────────────────


def test_agent_spec_generates_unique_agent_id_with_expected_prefix() -> None:
    spec = _spec()
    assert spec.agent_id.startswith("agent-")
    # uuid4().hex[:8] -> 8 hex chars after the prefix.
    suffix = spec.agent_id.removeprefix("agent-")
    assert len(suffix) == 8
    int(suffix, 16)  # must be valid hex


def test_agent_spec_ids_are_unique_across_instances() -> None:
    a, b = _spec(), _spec()
    assert a.agent_id != b.agent_id


def test_agent_spec_default_field_values() -> None:
    spec = _spec()
    assert spec.parent_agent_id is None
    assert spec.tenant_id == "default"
    assert spec.attempt == 1
    assert spec.context == {}
    assert spec.upstream_outputs == {}
    assert spec.tier == 2
    assert spec.model_override is None
    assert spec.temperature is None
    assert spec.max_tokens is None
    assert spec.prompt_name is None
    assert spec.prompt_label == "production"
    assert spec.prompt_variables == {}
    assert spec.recipe_name is None
    assert spec.result_type is None
    assert spec.tools_allowed == []
    assert spec.write_scopes == []
    assert spec.lane == Lane.BACKGROUND
    assert spec.langfuse_trace_id is None
    assert spec.langfuse_parent_span_id is None


def test_agent_spec_requires_role_task_id_subtask_id_description() -> None:
    with pytest.raises(ValidationError):
        AgentSpec()


def test_agent_spec_mutable_defaults_are_independent_per_instance() -> None:
    a = _spec()
    b = _spec()
    a.context["k"] = "v"
    assert b.context == {}


# ─── with_defaults() ─────────────────────────────────────────────────────────


def test_with_defaults_fills_tools_allowed_from_role() -> None:
    spec = _spec(role=AgentRole.CODER).with_defaults()
    assert spec.tools_allowed == DEFAULT_TOOLS[AgentRole.CODER]
    assert spec.tools_allowed == [
        "file_ops.read",
        "file_ops.write",
        "file_ops.list",
        "shell.run",
    ]


def test_with_defaults_fills_prompt_name_from_role() -> None:
    spec = _spec(role=AgentRole.PLANNER).with_defaults()
    assert spec.prompt_name == "planner.decompose"


def test_with_defaults_role_with_no_prompt_mapping_leaves_prompt_name_none() -> None:
    # INTENT_ROUTER and CONVERSATION/ARTIFACT have no entry in _PROMPT_NAME_MAP.
    spec = _spec(role=AgentRole.INTENT_ROUTER).with_defaults()
    assert spec.prompt_name is None
    assert spec.tools_allowed == []


def test_with_defaults_does_not_overwrite_explicit_tools_allowed() -> None:
    spec = _spec(role=AgentRole.CODER, tools_allowed=["custom.tool"]).with_defaults()
    assert spec.tools_allowed == ["custom.tool"]


def test_with_defaults_does_not_overwrite_explicit_prompt_name() -> None:
    spec = _spec(role=AgentRole.CODER, prompt_name="custom.prompt").with_defaults()
    assert spec.prompt_name == "custom.prompt"


def test_with_defaults_returns_self_for_chaining() -> None:
    spec = _spec()
    result = spec.with_defaults()
    assert result is spec


def test_with_defaults_unknown_role_default_tools_empty_list() -> None:
    # DEFAULT_TOOLS.get(role, []) handles a role with no DEFAULT_TOOLS entry;
    # every current AgentRole has an entry, so this exercises the dict literal
    # for VALIDATOR explicitly as a representative role.
    spec = _spec(role=AgentRole.VALIDATOR).with_defaults()
    assert spec.tools_allowed == ["file_ops.read", "file_ops.list", "shell.run_read_only"]


# ─── AgentOutput ─────────────────────────────────────────────────────────────


def _output(**overrides) -> AgentOutput:
    defaults = {
        "agent_id": "agent-abc12345",
        "role": AgentRole.CODER,
        "task_id": "task-1",
        "subtask_id": "sub-1",
    }
    defaults.update(overrides)
    return AgentOutput(**defaults)


def test_agent_output_defaults() -> None:
    out = _output()
    assert out.attempt == 1
    assert out.success is True
    assert out.output == ""
    assert out.output_parsed is None
    assert out.error is None
    assert out.error_type is None
    assert out.recoverable is True
    assert out.escalation_reason is None
    assert out.variant_used is None
    assert out.model_used is None
    assert out.tier_used is None
    assert out.tokens_used == {}
    assert out.completed_at is None
    assert out.duration_ms == 0.0
    assert out.langfuse_span_id is None
    assert isinstance(out.started_at, datetime)
    assert out.started_at.tzinfo is not None


def test_mark_complete_sets_completed_at_and_duration() -> None:
    out = _output(started_at=datetime.now(UTC) - timedelta(milliseconds=50))
    out.mark_complete()
    assert out.completed_at is not None
    assert out.duration_ms >= 50.0


def test_mark_complete_with_zero_elapsed_time_gives_nonnegative_duration() -> None:
    now = datetime.now(UTC)
    out = _output(started_at=now)
    out.completed_at = now
    out.mark_complete()
    assert out.duration_ms >= 0.0


def test_mark_error_recoverable_error_type() -> None:
    out = _output()
    out.mark_error("boom", ErrorType.TIMEOUT)

    assert out.success is False
    assert out.error == "boom"
    assert out.error_type == ErrorType.TIMEOUT
    assert out.recoverable is True
    assert out.escalation_reason is None
    assert out.completed_at is not None


def test_mark_error_nonrecoverable_error_type() -> None:
    out = _output()
    out.mark_error("breach", ErrorType.SAFETY_VIOLATION, escalation_reason="policy")

    assert out.recoverable is False
    assert out.escalation_reason == "policy"
    assert out.error_type == ErrorType.SAFETY_VIOLATION


@pytest.mark.parametrize(
    "error_type",
    [ErrorType.TIMEOUT, ErrorType.PARSE_FAILURE, ErrorType.MODEL_ERROR, ErrorType.LOW_SCORE],
)
def test_mark_error_all_recoverable_types_match_recoverable_errors_set(error_type) -> None:
    out = _output()
    out.mark_error("e", error_type)
    assert out.recoverable is True
    assert error_type in RECOVERABLE_ERRORS


@pytest.mark.parametrize(
    "error_type",
    [ErrorType.SAFETY_VIOLATION, ErrorType.TOOL_VIOLATION, ErrorType.DEPENDENCY_FAILED],
)
def test_mark_error_all_nonrecoverable_types_excluded_from_recoverable_errors_set(
    error_type,
) -> None:
    out = _output()
    out.mark_error("e", error_type)
    assert out.recoverable is False
    assert error_type not in RECOVERABLE_ERRORS


def test_mark_error_calls_mark_complete_and_sets_duration() -> None:
    out = _output(started_at=datetime.now(UTC) - timedelta(milliseconds=10))
    out.mark_error("e", ErrorType.TIMEOUT)
    assert out.duration_ms >= 10.0
    assert out.completed_at is not None


# ─── Enum sanity (string values feed YAML/JSON wire format) ────────────────


def test_lane_string_values() -> None:
    assert Lane.LIVE.value == "live-chat"
    assert Lane.BACKGROUND.value == "background-task"


def test_agent_role_string_values_complete() -> None:
    expected = {
        "planner",
        "coder",
        "reviewer",
        "scout",
        "architect",
        "extractor",
        "validator",
        "intent_router",
        "artifact",
        "conversation",
    }
    assert {role.value for role in AgentRole} == expected


def test_error_type_string_values_complete() -> None:
    expected = {
        "timeout",
        "parse_failure",
        "model_error",
        "low_score",
        "safety_violation",
        "tool_violation",
        "dependency_failed",
    }
    assert {e.value for e in ErrorType} == expected


def test_recoverable_errors_is_frozenset_of_exactly_four() -> None:
    assert isinstance(RECOVERABLE_ERRORS, frozenset)
    assert len(RECOVERABLE_ERRORS) == 4


def test_default_tools_covers_every_role() -> None:
    assert set(DEFAULT_TOOLS.keys()) == set(AgentRole)


def test_default_tools_intent_router_and_conversation_are_empty() -> None:
    assert DEFAULT_TOOLS[AgentRole.INTENT_ROUTER] == []
    assert DEFAULT_TOOLS[AgentRole.CONVERSATION] == []


def test_agent_id_default_factory_uses_uuid4_hex(monkeypatch) -> None:
    fixed = uuid.UUID("12345678-1234-5678-1234-567812345678")
    monkeypatch.setattr(uuid, "uuid4", lambda: fixed)
    spec = _spec()
    assert spec.agent_id == "agent-12345678"
