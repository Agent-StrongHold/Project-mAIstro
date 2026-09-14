"""Adversarial tests for the canonical governed tool seam (#57)."""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.invocation import InvocationStatus
from maistro.tools.contracts import (
    GovernedToolExecutor,
    PredictionMismatch,
    ToolArgumentError,
    ToolContract,
    ToolContractRegistry,
    ToolInvocationContext,
    ToolNotAuthorized,
    ToolRegistration,
    ToolReversibility,
    UnknownToolSchema,
    canonical_digest,
    validate_tool_arguments,
)

_CONTEXT = ToolInvocationContext(
    workspace_id="ws-1",
    project_id="project-1",
    run_id="run-1",
    node_run_id="node-run-1",
    attempt_id="attempt-1",
)


def _binding() -> Binding:
    return Binding(
        binding_id="tool-binding-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="ticketing",
        provider_name="ticket-provider",
    )


def _registry(*, observed: Any = None) -> ToolContractRegistry:
    registry = ToolContractRegistry()
    registry.register(
        ToolContract(
            name="create_ticket",
            schema={
                "type": "object",
                "properties": {"title": {"type": "string"}},
                "required": ["title"],
                "additionalProperties": False,
            },
            capability="ticketing",
            provider_name="ticket-provider",
            high_impact=True,
            policy_version="tickets-v3",
            pre_state=lambda _args: {"ticket_count": 0},
            expected_post_state=lambda _args: {"ticket_count": 1},
            observed_post_state=lambda _result: observed,
        ),
        ToolRegistration(
            name="create_ticket",
            reversibility=ToolReversibility.REVERSIBLE,
            compensator="delete_ticket",
        ),
    )
    return registry


@pytest.mark.asyncio
async def test_governed_tool_persists_expected_evidence_on_canonical_invocation() -> None:
    effects = new_effect_context()
    await effects.bindings.put(_binding())
    registry = _registry(observed={"ticket_count": 1})
    calls: list[tuple[str, dict[str, Any]]] = []

    async def backend(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"id": "ticket-1"}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return _binding()

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=registry,
        binding_for=binding_for,
        backend=backend,
    )

    result = await executor.execute(
        "create_ticket",
        {"title": "exact title"},
        context=_CONTEXT,
        authorized_tools=frozenset({"create_ticket"}),
    )

    assert result == {"id": "ticket-1"}
    assert calls == [("create_ticket", {"title": "exact title"})]
    rows = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="tool-binding-1",
        effect_key="tool:create_ticket:" + canonical_digest({"title": "exact title"}),
    )
    assert len(rows) == 1
    invocation = rows[0]
    assert invocation.status is InvocationStatus.COMPLETED
    assert invocation.expected_effect is not None
    assert invocation.expected_effect.invocation_id == invocation.invocation_id
    assert invocation.expected_effect.materialized_arguments == {"title": "exact title"}
    assert invocation.expected_effect.matched is True
    events = await effects.event_store.list_stream("workspace:ws-1")
    assert [event.type for event in events] == [
        "capability.invocation.policy_decision",
        "capability.invocation.completed",
    ]
    assert events[1].invocation_id == invocation.invocation_id


@pytest.mark.asyncio
async def test_prediction_mismatch_is_durable_evidence_and_not_success() -> None:
    effects = new_effect_context()
    await effects.bindings.put(_binding())
    registry = _registry(observed={"ticket_count": 2})

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        return {"id": "ticket-1"}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return _binding()

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=registry,
        binding_for=binding_for,
        backend=backend,
    )
    with pytest.raises(PredictionMismatch):
        await executor.execute(
            "create_ticket",
            {"title": "mismatch"},
            context=_CONTEXT,
            authorized_tools=frozenset({"create_ticket"}),
        )

    events = await effects.event_store.list_stream("workspace:ws-1")
    mismatch = [event for event in events if event.type.endswith("expected_effect_mismatch")]
    assert len(mismatch) == 1
    assert mismatch[0].invocation_id
    assert mismatch[0].payload["policy_version"] == "tickets-v3"

    rows = await effects.invocation_store.list_effect(
        run_id="run-1",
        node_run_id="node-run-1",
        binding_id="tool-binding-1",
        effect_key="tool:create_ticket:" + canonical_digest({"title": "mismatch"}),
    )
    assert rows[0].expected_effect is not None
    assert rows[0].expected_effect.matched is False
    unchanged = await effects.invocations.record_expected_effect_observation(
        rows[0].invocation_id, {"ticket_count": 1}
    )
    assert unchanged.expected_effect is not None
    assert unchanged.expected_effect.matched is False


@pytest.mark.asyncio
async def test_agent_allowlist_and_unknown_schema_fail_before_backend() -> None:
    effects = new_effect_context()
    await effects.bindings.put(_binding())
    registry = _registry()
    called = False

    async def backend(_name: str, _arguments: dict[str, Any]) -> None:
        nonlocal called
        called = True

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return _binding()

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=registry,
        binding_for=binding_for,
        backend=backend,
    )
    with pytest.raises(ToolNotAuthorized):
        await executor.execute(
            "create_ticket",
            {"title": "no"},
            context=_CONTEXT,
            authorized_tools=frozenset(),
        )
    with pytest.raises(UnknownToolSchema):
        await executor.execute(
            "model_selected_unknown",
            {},
            context=_CONTEXT,
            authorized_tools=frozenset({"model_selected_unknown"}),
        )
    assert called is False


def test_schema_validation_rejects_command_text_and_extra_fields() -> None:
    schema = {
        "type": "object",
        "properties": {"argv": {"type": "array", "items": {"type": "string"}}},
        "required": ["argv"],
        "additionalProperties": False,
    }
    validate_tool_arguments(schema, {"argv": ["git", "status"]})
    with pytest.raises(ToolArgumentError):
        validate_tool_arguments(schema, {"cmd": "git status"})
    with pytest.raises(ToolArgumentError):
        validate_tool_arguments(schema, {"argv": ["git"], "cmd": "status"})
