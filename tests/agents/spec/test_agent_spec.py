"""Tests for AgentSpec + AgentOutput envelopes (ADR-004)."""

from __future__ import annotations

from maistro.agents.spec.agent_spec import (
    DEFAULT_TOOLS,
    RECOVERABLE_ERRORS,
    AgentOutput,
    AgentRole,
    AgentSpec,
    ErrorType,
    Lane,
)


def _minimal_spec(**kwargs) -> AgentSpec:
    defaults = {
        "role": AgentRole.CODER,
        "task_id": "task-1",
        "subtask_id": "sub-1",
        "description": "Write a function",
    }
    defaults.update(kwargs)
    return AgentSpec(**defaults)


class TestAgentSpec:
    def test_agent_id_auto_generated(self) -> None:
        spec = _minimal_spec()
        assert spec.agent_id.startswith("agent-")
        assert len(spec.agent_id) > 6

    def test_agent_id_unique(self) -> None:
        a = _minimal_spec()
        b = _minimal_spec()
        assert a.agent_id != b.agent_id

    def test_defaults_fills_tools_allowed(self) -> None:
        spec = _minimal_spec(role=AgentRole.CODER)
        spec = spec.with_defaults()
        assert "file_ops.write" in spec.tools_allowed

    def test_defaults_does_not_overwrite_explicit_tools(self) -> None:
        spec = _minimal_spec(tools_allowed=["custom.tool"])
        spec = spec.with_defaults()
        assert spec.tools_allowed == ["custom.tool"]

    def test_defaults_fills_prompt_name(self) -> None:
        spec = _minimal_spec(role=AgentRole.PLANNER)
        spec = spec.with_defaults()
        assert spec.prompt_name == "planner.decompose"

    def test_defaults_coder_prompt_name(self) -> None:
        spec = _minimal_spec(role=AgentRole.CODER)
        spec = spec.with_defaults()
        assert spec.prompt_name == "coder.generate"

    def test_defaults_does_not_overwrite_prompt_name(self) -> None:
        spec = _minimal_spec(prompt_name="my.custom.prompt")
        spec = spec.with_defaults()
        assert spec.prompt_name == "my.custom.prompt"

    def test_default_lane_is_background(self) -> None:
        spec = _minimal_spec()
        assert spec.lane == Lane.BACKGROUND

    def test_json_roundtrip(self) -> None:
        spec = _minimal_spec(role=AgentRole.SCOUT)
        data = spec.model_dump_json()
        restored = AgentSpec.model_validate_json(data)
        assert restored.role == spec.role
        assert restored.task_id == spec.task_id

    def test_all_roles_have_default_tools(self) -> None:
        for role in AgentRole:
            assert role in DEFAULT_TOOLS


class TestAgentOutput:
    def _make_output(self) -> AgentOutput:
        return AgentOutput(
            agent_id="agent-abc123",
            role=AgentRole.CODER,
            task_id="task-1",
            subtask_id="sub-1",
        )

    def test_mark_complete_sets_duration(self) -> None:
        out = self._make_output()
        out.mark_complete()
        assert out.completed_at is not None
        assert out.duration_ms >= 0.0

    def test_mark_error_recoverable(self) -> None:
        out = self._make_output()
        out.mark_error("timeout occurred", ErrorType.TIMEOUT)
        assert out.success is False
        assert out.error_type == ErrorType.TIMEOUT
        assert out.recoverable is True
        assert out.completed_at is not None

    def test_mark_error_non_recoverable(self) -> None:
        out = self._make_output()
        out.mark_error("policy violation", ErrorType.SAFETY_VIOLATION)
        assert out.recoverable is False

    def test_mark_error_non_recoverable_tool_violation(self) -> None:
        out = self._make_output()
        out.mark_error("tool blocked", ErrorType.TOOL_VIOLATION)
        assert out.recoverable is False

    def test_mark_error_with_escalation_reason(self) -> None:
        out = self._make_output()
        out.mark_error("low score", ErrorType.LOW_SCORE, escalation_reason="score=4.2")
        assert out.escalation_reason == "score=4.2"
        assert out.recoverable is True

    def test_default_success_is_true(self) -> None:
        out = self._make_output()
        assert out.success is True


class TestRecoverableErrors:
    def test_recoverable_errors_contents(self) -> None:
        assert ErrorType.TIMEOUT in RECOVERABLE_ERRORS
        assert ErrorType.PARSE_FAILURE in RECOVERABLE_ERRORS
        assert ErrorType.MODEL_ERROR in RECOVERABLE_ERRORS
        assert ErrorType.LOW_SCORE in RECOVERABLE_ERRORS

    def test_non_recoverable_not_in_set(self) -> None:
        assert ErrorType.SAFETY_VIOLATION not in RECOVERABLE_ERRORS
        assert ErrorType.TOOL_VIOLATION not in RECOVERABLE_ERRORS
        assert ErrorType.DEPENDENCY_FAILED not in RECOVERABLE_ERRORS
