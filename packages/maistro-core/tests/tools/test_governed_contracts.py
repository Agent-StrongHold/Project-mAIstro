"""Adversarial tests for the canonical governed tool seam (#57)."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import aiosqlite
import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    binding_scope_policy,
    new_effect_context,
    new_sqlite_effect_context,
)
from maistro.capabilities.invocation import InvocationStatus
from maistro.events.envelope import EventEnvelope
from maistro.tools.approval.types import ApprovalDecision, Impact
from maistro.tools.contracts import (
    ExpectedEffectRequired,
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
    # The composition contract requires an explicit policy evaluator: a bare
    # context is an unavailable authority, not an implicit ALLOW (#846).
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
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
@pytest.mark.parametrize("pause_at", ["binding", "provider"])
async def test_caller_mutation_cannot_change_admitted_tool_arguments(pause_at: str) -> None:
    """Admission awaits cannot detach executed input from schema/prediction evidence."""
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(_binding())
    registry = _registry(observed={"ticket_count": 1})
    registry.require("create_ticket").schema["properties"]["labels"] = {
        "type": "array",
        "items": {"type": "string"},
    }
    original = {"title": "admitted title", "labels": ["admitted label"]}
    arguments = deepcopy(original)
    paused, resume = asyncio.Event(), asyncio.Event()
    calls: list[dict[str, Any]] = []

    async def pause(stage: str) -> None:
        if pause_at == stage:
            paused.set()
            await resume.wait()

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        await pause("binding")
        return _binding()

    async def backend(_name: str, received: dict[str, Any]) -> dict[str, Any]:
        await pause("provider")
        calls.append(deepcopy(received))
        return {"id": "ticket-1"}

    executor = GovernedToolExecutor(
        effects=effects, contracts=registry, binding_for=binding_for, backend=backend
    )
    task = asyncio.create_task(
        executor.execute(
            "create_ticket", arguments, context=_CONTEXT, authorized_tools={"create_ticket"}
        )
    )
    try:
        # Synchronize at a real async boundary, never with scheduling sleeps.
        await asyncio.wait_for(paused.wait(), timeout=10)
        arguments["title"] = 123  # Invalid after the schema check has already passed.
        arguments["labels"].append(456)  # A shallow copy is insufficient.
        resume.set()
        assert await task == {"id": "ticket-1"}
    finally:
        resume.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)

    assert calls == [original]
    rows = await effects.invocation_store.list_effect(
        run_id=_CONTEXT.run_id,
        node_run_id=_CONTEXT.node_run_id,
        binding_id=_binding().binding_id,
        effect_key="tool:create_ticket:" + canonical_digest(original),
    )
    assert len(rows) == 1
    invocation = rows[0]
    assert invocation.request["arguments"] == original
    evidence = invocation.expected_effect
    assert evidence is not None
    assert evidence.materialized_arguments == calls[0] == original
    assert evidence.arguments_digest == canonical_digest(calls[0])
    assert evidence.invocation_id == invocation.invocation_id
    assert evidence.matched is True


@pytest.mark.asyncio
async def test_prediction_mismatch_is_durable_evidence_and_not_success() -> None:
    # The composition contract requires an explicit policy evaluator: a bare
    # context is an unavailable authority, not an implicit ALLOW (#846).
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
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
@pytest.mark.parametrize("append_committed", [False, True])
async def test_mismatch_event_recovers_after_sqlite_reopen(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, append_committed: bool
) -> None:
    """Recover a lost append/ack without redispatch or duplicate mismatch events."""
    db_path = tmp_path / "tool-effects.db"
    calls: list[dict[str, Any]] = []
    arguments = {"title": "durable mismatch"}

    async def backend(_name: str, args: dict[str, Any]) -> dict[str, Any]:
        calls.append(args)
        return {"id": "ticket-1"}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return _binding()

    async with aiosqlite.connect(db_path) as conn:
        effects = await new_sqlite_effect_context(conn, policy_evaluator=binding_scope_policy)
        await effects.bindings.put(_binding())
        append = effects.event_store.append

        async def interrupted_append(event: EventEnvelope) -> EventEnvelope:
            if event.type.endswith("expected_effect_mismatch"):
                if append_committed:
                    await append(event)
                raise OSError("lost mismatch append acknowledgement")
            return await append(event)

        monkeypatch.setattr(effects.event_store, "append", interrupted_append)
        executor = GovernedToolExecutor(
            effects=effects,
            contracts=_registry(observed={"ticket_count": 2}),
            binding_for=binding_for,
            backend=backend,
        )
        with pytest.raises(OSError, match="lost mismatch append acknowledgement"):
            await executor.execute(
                "create_ticket", arguments, context=_CONTEXT, authorized_tools={"create_ticket"}
            )
        rows = await effects.invocation_store.list_effect(
            run_id=_CONTEXT.run_id,
            node_run_id=_CONTEXT.node_run_id,
            binding_id=_binding().binding_id,
            effect_key="tool:create_ticket:" + canonical_digest(arguments),
        )
        original = rows[0]
        assert original.expected_effect is not None
        assert original.expected_effect.matched is False
        prediction = original.expected_effect.model_dump(mode="json")

    # Rebuild the real durable composition, not just an executor over old stores.
    async with aiosqlite.connect(db_path) as conn:
        effects = await new_sqlite_effect_context(conn, policy_evaluator=binding_scope_policy)
        executor = GovernedToolExecutor(
            effects=effects,
            # A later observation must not turn the persisted mismatch into success.
            contracts=_registry(observed={"ticket_count": 1}),
            binding_for=binding_for,
            backend=backend,
        )
        for _ in range(2):
            with pytest.raises(PredictionMismatch):
                await executor.execute(
                    "create_ticket", arguments, context=_CONTEXT, authorized_tools={"create_ticket"}
                )
        persisted = await effects.invocation_store.get(original.invocation_id)
        assert persisted is not None
        assert persisted.expected_effect is not None
        evidence = persisted.expected_effect
        assert evidence.model_dump(mode="json") == prediction
        assert evidence.invocation_id == original.invocation_id
        assert evidence.capability == "ticketing"
        assert evidence.provider == persisted.binding.provider_name == "ticket-provider"
        assert evidence.materialized_arguments == arguments
        assert evidence.arguments_digest == canonical_digest(arguments)
        assert evidence.pre_state_digest == canonical_digest({"ticket_count": 0})
        assert evidence.expected_post_state == {"ticket_count": 1}
        assert evidence.observed_post_state == {"ticket_count": 2}
        assert evidence.policy_version == "tickets-v3"
        events = await effects.event_store.list_stream("workspace:ws-1")
        mismatches = [e for e in events if e.type.endswith("expected_effect_mismatch")]
        assert len(mismatches) == 1
        mismatch = mismatches[0]
        assert mismatch.invocation_id == original.invocation_id
        assert mismatch.run_id == _CONTEXT.run_id
        assert mismatch.node_run_id == _CONTEXT.node_run_id
        assert mismatch.attempt_id == _CONTEXT.attempt_id
        assert mismatch.payload["evidence_digest"] == evidence.evidence_digest
        assert mismatch.payload["observed_post_state"] == {"ticket_count": 2}
    assert calls == [arguments]


@pytest.mark.asyncio
async def test_agent_allowlist_and_unknown_schema_fail_before_backend() -> None:
    # The composition contract requires an explicit policy evaluator: a bare
    # context is an unavailable authority, not an implicit ALLOW (#846).
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("property_schema", "value"),
    [
        pytest.param({"type": "integre"}, "not-an-integer", id="unknown-type"),
        pytest.param({"type": ""}, "unrestricted", id="empty-type"),
        pytest.param({"type": None}, "unrestricted", id="null-type"),
        pytest.param({"type": ["string", "null"]}, "text", id="unsupported-union"),
        pytest.param({"type": {}}, "text", id="invalid-type"),
        pytest.param(
            {"type": "object", "properties": {"count": {"type": "integre"}}},
            {"count": "not-an-integer"},
            id="nested-object",
        ),
        pytest.param(
            {"type": "array", "items": {"type": "integre"}},
            ["not-an-integer"],
            id="nested-array",
        ),
    ],
)
async def test_unsupported_schema_type_refuses_before_binding_and_provider(
    property_schema: dict[str, Any], value: Any
) -> None:
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(_binding())
    registry = ToolContractRegistry()
    registry.register(
        ToolContract(
            name="typed_tool",
            schema={
                "type": "object",
                "properties": {"value": property_schema},
                "required": ["value"],
                "additionalProperties": False,
            },
            capability="ticketing",
            provider_name="ticket-provider",
        ),
        ToolRegistration(name="typed_tool", reversibility=ToolReversibility.INTERNAL),
    )
    admissions: list[str] = []

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        admissions.append("binding")
        return _binding()

    async def backend(_name: str, _arguments: dict[str, Any]) -> str:
        admissions.append("provider")
        return "executed"

    executor = GovernedToolExecutor(
        effects=effects, contracts=registry, binding_for=binding_for, backend=backend
    )
    with pytest.raises(ToolArgumentError, match="unsupported host-owned schema type"):
        await executor.execute(
            "typed_tool", {"value": value}, context=_CONTEXT, authorized_tools={"typed_tool"}
        )
    assert admissions == []
    assert await effects.event_store.list_stream("workspace:ws-1") == []


@pytest.mark.parametrize("declared_type", ["integre", "", None, ["object", "null"], {}])
def test_unsupported_root_schema_type_is_a_typed_refusal(declared_type: Any) -> None:
    # ReAct/artificer also validate model-facing schemas without constructing a
    # ToolContract, so the root declaration must not bypass the shared check.
    with pytest.raises(ToolArgumentError, match="unsupported host-owned schema type"):
        validate_tool_arguments({"type": declared_type}, {})


@pytest.mark.parametrize(
    ("declared_type", "value"),
    [
        ("object", {"context": "kept"}),
        ("array", ["item"]),
        ("string", "text"),
        ("integer", 2),
        ("number", 2.5),
        ("boolean", False),
        ("null", None),
    ],
)
def test_supported_schema_types_remain_valid(declared_type: str, value: Any) -> None:
    validate_tool_arguments(
        {"type": "object", "properties": {"value": {"type": declared_type}}},
        {"value": value},
    )


def test_high_impact_contract_without_expected_effect_fails_closed() -> None:
    """A configured high-impact tool cannot register without prediction inputs.

    Missing expected effects on high-impact actions must be detectable at
    registration, not discovered after an unrecorded mutating call (#57).
    """

    with pytest.raises(ExpectedEffectRequired):
        ToolContract(
            name="deploy",
            schema={"type": "object", "properties": {}, "additionalProperties": False},
            capability="deploy",
            provider_name="deploy-provider",
            high_impact=True,
        )
    # The same contract registers once the prediction contract is complete.
    ToolContract(
        name="deploy",
        schema={"type": "object", "properties": {}, "additionalProperties": False},
        capability="deploy",
        provider_name="deploy-provider",
        high_impact=True,
        policy_version="deploy-v1",
        pre_state=lambda _args: {},
        expected_post_state=lambda _args: {},
        observed_post_state=lambda _result: {},
    )


@pytest.mark.asyncio
async def test_effect_scope_distinguishes_logical_calls_without_widening() -> None:
    """Two logical tool calls with identical arguments are distinct effects;
    a retry of the same logical scope replays the recorded outcome.

    The scope cannot widen authorization: an unlisted name is still refused
    whatever scope is supplied, and the argument digest still binds the
    recorded evidence to the exact materialized arguments (#57).
    """
    # The composition contract requires an explicit policy evaluator: a bare
    # context is an unavailable authority, not an implicit ALLOW (#846).
    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(_binding())
    registry = _registry(observed={"ticket_count": 1})
    calls: list[str] = []

    async def backend(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append(arguments["title"])
        return {"title": arguments["title"]}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return _binding()

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=registry,
        binding_for=binding_for,
        backend=backend,
    )
    arguments = {"title": "same title"}
    first = await executor.execute(
        "create_ticket",
        dict(arguments),
        context=_CONTEXT,
        authorized_tools=frozenset({"create_ticket"}),
        effect_scope="call-1",
    )
    second = await executor.execute(
        "create_ticket",
        dict(arguments),
        context=_CONTEXT,
        authorized_tools=frozenset({"create_ticket"}),
        effect_scope="call-2",
    )
    replay = await executor.execute(
        "create_ticket",
        dict(arguments),
        context=_CONTEXT,
        authorized_tools=frozenset({"create_ticket"}),
        effect_scope="call-1",
    )
    assert first == second == replay
    assert calls == ["same title", "same title"]

    with pytest.raises(ToolNotAuthorized):
        await executor.execute(
            "undeclared",
            {},
            context=_CONTEXT,
            authorized_tools=frozenset({"create_ticket"}),
            effect_scope="call-3",
        )


class TestContractGuardBranches:
    """Every refusal direction of the tool-contract guards is exercised (#57).

    The diff-coverage gate scores changed lines per file; these tests close
    the guard directions the first #57 suites did not drive, so the gate
    measures real evidence rather than an accidental pass.
    """

    def test_contract_identity_gaps_are_typed_refusals(self) -> None:
        schema: dict[str, Any] = {"type": "object", "properties": {}}
        with pytest.raises(ValueError, match="capability, and provider_name are required"):
            ToolContract(
                name=" ", capability="ticketing", provider_name="ticket-provider", schema=schema
            )
        with pytest.raises(ValueError, match="capability, and provider_name are required"):
            ToolContract(
                name="create_ticket", capability="", provider_name="ticket-provider", schema=schema
            )
        with pytest.raises(ValueError, match="capability, and provider_name are required"):
            ToolContract(
                name="create_ticket", capability="ticketing", provider_name="  ", schema=schema
            )

    def test_contract_schema_must_be_an_object_schema(self) -> None:
        with pytest.raises(ValueError, match="object JSON schema"):
            ToolContract(name="t", schema=[], capability="c", provider_name="p")
        with pytest.raises(ValueError, match="object JSON schema"):
            ToolContract(name="t", schema={"type": "string"}, capability="c", provider_name="p")

    def test_registry_registration_name_mismatch_is_refused(self) -> None:
        from maistro.tools.contracts import ToolContract as _ToolContract

        registry = ToolContractRegistry()
        contract = _ToolContract(
            name="a", schema={"type": "object", "properties": {}}, capability="c", provider_name="p"
        )
        with pytest.raises(ValueError, match="names must match"):
            registry.register(
                contract,
                ToolRegistration(
                    name="b", reversibility=ToolReversibility.REVERSIBLE, compensator="undo"
                ),
            )

    def test_invocation_context_requires_canonical_ids(self) -> None:
        with pytest.raises(ValueError, match="canonical Workspace/Project/Run/NodeRun/Attempt"):
            ToolInvocationContext(
                workspace_id=" ", project_id="p", run_id="r", node_run_id="n", attempt_id="a"
            )

    def test_arguments_must_be_an_object(self) -> None:
        with pytest.raises(ToolArgumentError, match="must be an object"):
            validate_tool_arguments({"type": "object", "properties": {}}, ["nope"])

    def test_invalid_property_or_required_declarations_refuse(self) -> None:
        with pytest.raises(ToolArgumentError, match="invalid properties/required"):
            validate_tool_arguments({"type": "object", "properties": [], "required": []}, {})
        with pytest.raises(ToolArgumentError, match="invalid properties/required"):
            validate_tool_arguments({"type": "object", "properties": {}, "required": "title"}, {})

    def test_enum_violation_refuses_and_the_permitted_direction_stays_open(self) -> None:
        schema = {
            "type": "object",
            "properties": {"mode": {"type": "string", "enum": ["a", "b"]}},
            "required": ["mode"],
        }
        with pytest.raises(ToolArgumentError, match="not one of the permitted values"):
            validate_tool_arguments(schema, {"mode": "c"})
        validate_tool_arguments(schema, {"mode": "a"})

    def test_typeless_schema_is_accepted_without_a_type_check(self) -> None:
        validate_tool_arguments({"properties": {}}, {"any": "shape"})

    def test_non_mapping_property_schema_refuses(self) -> None:
        schema = {
            "type": "object",
            "properties": {"title": "string"},
            "required": ["title"],
        }
        with pytest.raises(ToolArgumentError, match="has no valid host-owned schema"):
            validate_tool_arguments(schema, {"title": "x"})

    @pytest.mark.asyncio
    async def test_provider_resolution_refuses_capability_and_provider_drift(self) -> None:
        from maistro.tools.contracts import ToolContractError, _resolve_provider

        drifted = _binding().model_copy(update={"binding_id": "b2", "capability": "cap-b"})
        capability_contract = ToolContract(
            name="t",
            schema={"type": "object", "properties": {}},
            capability="cap-a",
            provider_name="ticket-provider",
        )
        with pytest.raises(ToolContractError, match="capability does not match"):
            await _resolve_provider(drifted, capability_contract)
        provider_drift = _binding().model_copy(
            update={"binding_id": "b3", "provider_name": "prov-b"}
        )
        provider_contract = ToolContract(
            name="t",
            schema={"type": "object", "properties": {}},
            capability="ticketing",
            provider_name="prov-a",
        )
        with pytest.raises(ToolContractError, match="provider does not match"):
            await _resolve_provider(provider_drift, provider_contract)

    @pytest.mark.asyncio
    async def test_missing_binding_fails_closed_before_the_backend(self) -> None:
        effects = new_effect_context(policy_evaluator=binding_scope_policy)
        registry = _registry()

        async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> None:
            return None

        async def backend(_name: str, _arguments: dict[str, Any]) -> Any:
            raise AssertionError("the backend must not run without an admitted Binding")

        executor = GovernedToolExecutor(
            effects=effects, contracts=registry, binding_for=binding_for, backend=backend
        )
        with pytest.raises(ToolNotAuthorized, match="no authorized Binding exists"):
            await executor.execute(
                "create_ticket",
                {"title": "x"},
                context=_CONTEXT,
                authorized_tools=frozenset({"create_ticket"}),
            )

    @pytest.mark.asyncio
    async def test_binding_scope_mismatch_fails_closed(self) -> None:
        effects = new_effect_context(policy_evaluator=binding_scope_policy)
        await effects.bindings.put(_binding())
        registry = _registry()

        async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
            return _binding().model_copy(update={"workspace_id": "other-ws"})

        async def backend(_name: str, _arguments: dict[str, Any]) -> Any:
            raise AssertionError("the backend must not run for a scope-mismatched Binding")

        executor = GovernedToolExecutor(
            effects=effects, contracts=registry, binding_for=binding_for, backend=backend
        )
        with pytest.raises(ToolNotAuthorized, match="scope does not match"):
            await executor.execute(
                "create_ticket",
                {"title": "x"},
                context=_CONTEXT,
                authorized_tools=frozenset({"create_ticket"}),
            )

    @pytest.mark.asyncio
    async def test_low_impact_tool_skips_evidence_and_observation_guards_fail_loud(self) -> None:
        """A non-high-impact contract records no expected-effect evidence; the
        observation/mismatch-event guards then refuse rather than guess."""
        effects = new_effect_context(policy_evaluator=binding_scope_policy)
        await effects.bindings.put(_binding())
        registry = ToolContractRegistry()
        registry.register(
            ToolContract(
                name="lookup",
                schema={"type": "object", "properties": {}},
                capability="ticketing",
                provider_name="ticket-provider",
            ),
            ToolRegistration(
                name="lookup", reversibility=ToolReversibility.REVERSIBLE, compensator="undo_lookup"
            ),
        )

        async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
            return {"ok": True}

        async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
            return _binding()

        executor = GovernedToolExecutor(
            effects=effects, contracts=registry, binding_for=binding_for, backend=backend
        )
        result = await executor.execute(
            "lookup", {}, context=_CONTEXT, authorized_tools=frozenset({"lookup"})
        )
        assert result == {"ok": True}

        rows = await effects.invocation_store.list_effect(
            run_id="run-1",
            node_run_id="node-run-1",
            binding_id="tool-binding-1",
            effect_key="tool:lookup:" + canonical_digest({}),
        )
        assert len(rows) == 1
        assert rows[0].expected_effect is None

        with pytest.raises(KeyError, match="does not exist"):
            await effects.invocations.record_expected_effect_observation("no-such-invocation", {})
        with pytest.raises(ValueError, match="no expected-effect evidence"):
            await effects.invocations.record_expected_effect_observation(
                rows[0].invocation_id, {"ok": True}
            )
        with pytest.raises(ValueError, match="mismatch event requires a mismatch"):
            effects.invocations.expected_effect_mismatch_event(rows[0], tool_name="lookup")

    def test_expected_evidence_identity_gaps_and_digest_drift_are_refused(self) -> None:
        from maistro.tools.contracts import ExpectedEffectEvidence

        def evidence(**overrides: Any) -> Any:
            kwargs: dict[str, Any] = {
                "capability": "c",
                "provider": "p",
                "materialized_arguments": {},
                "expected_post_state": {"after": "effect"},
                "pre_state_digest": "pre",
                "policy_version": "v1",
            }
            kwargs.update(overrides)
            return ExpectedEffectEvidence(**kwargs)

        with pytest.raises(ValueError, match="capability and provider are required"):
            evidence(capability=" ")
        with pytest.raises(ValueError, match="capability and provider are required"):
            evidence(provider="")
        with pytest.raises(ValueError, match="pre-state digest and policy version are required"):
            evidence(pre_state_digest="  ")
        with pytest.raises(ValueError, match="pre-state digest and policy version are required"):
            evidence(policy_version="")
        with pytest.raises(ValueError, match="arguments_digest does not match"):
            evidence(
                materialized_arguments={"a": 1},
                arguments_digest="deadbeef",
            )
        pinned_digest = canonical_digest({"a": 1})
        pinned = evidence(
            materialized_arguments={"a": 1},
            arguments_digest=pinned_digest,
        )
        assert pinned.arguments_digest == pinned_digest


@dataclass
class _RecordingGate:
    outcome: str = "approved"
    plan_calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)
    escalation_calls: list[tuple[str, str]] = field(default_factory=list)

    async def request_plan_approval(
        self, task_id: str, irreversible_calls: tuple[str, ...]
    ) -> ApprovalDecision:
        self.plan_calls.append((task_id, irreversible_calls))
        return ApprovalDecision(
            task_id=task_id,
            target="plan",
            outcome=self.outcome,  # type: ignore[arg-type]
            latency_ms=1,
            decided_by="test",
        )

    async def request_escalation(
        self, task_id: str, call: str, impacts: tuple[Impact, ...]
    ) -> ApprovalDecision:
        self.escalation_calls.append((task_id, call))
        return ApprovalDecision(
            task_id=task_id,
            target="call",
            outcome=self.outcome,  # type: ignore[arg-type]
            latency_ms=1,
            decided_by="test",
        )


def _irreversible_registry() -> ToolContractRegistry:
    registry = ToolContractRegistry()
    registry.register(
        ToolContract(
            name="wipe_disk",
            schema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
            capability="destructive",
            provider_name="disk-provider",
        ),
        ToolRegistration(
            name="wipe_disk",
            reversibility=ToolReversibility.IRREVERSIBLE,
        ),
    )
    return registry


@pytest.mark.asyncio
async def test_irreversible_tool_without_gate_refuses() -> None:
    from maistro.tools.contracts import ToolApprovalRequired

    effects = new_effect_context(policy_evaluator=binding_scope_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("backend must not run")

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
    )
    with pytest.raises(ToolApprovalRequired, match="ApprovalGate"):
        await executor.execute(
            "wipe_disk",
            {"path": "/tmp/x"},
            context=_CONTEXT,
            authorized_tools=frozenset({"wipe_disk"}),
        )


async def _allow_irreversible_policy(_binding: Binding, _request: Any, _context: Any) -> Any:
    """Test-only: Invocation-layer approval is separate from the ADR-051 gate under test."""
    from maistro.policy.types import Decision, PolicyVerdict

    return PolicyVerdict(Decision.ALLOW, reason="test allow", rule="test.allow")


@pytest.mark.asyncio
async def test_irreversible_tool_with_approving_gate_dispatches() -> None:
    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)
    gate = _RecordingGate(outcome="approved")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def backend(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"ok": True}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=gate,
    )
    result = await executor.execute(
        "wipe_disk",
        {"path": "/tmp/x"},
        context=_CONTEXT,
        authorized_tools=frozenset({"wipe_disk"}),
    )
    assert result == {"ok": True}
    assert calls == [("wipe_disk", {"path": "/tmp/x"})]
    assert gate.plan_calls == [("run-1", ("wipe_disk",))]


@pytest.mark.asyncio
async def test_irreversible_declared_plan_skips_gate() -> None:
    from datetime import UTC, datetime

    from maistro.tools.approval.gate import PlanApprovalState

    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)
    gate = _RecordingGate(outcome="denied")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def backend(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"ok": True}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=gate,
        plan_state=PlanApprovalState(
            task_id="run-1",
            approved_calls=frozenset({"wipe_disk"}),
            approved_at=datetime.now(UTC),
        ),
    )
    result = await executor.execute(
        "wipe_disk",
        {"path": "/tmp/x"},
        context=_CONTEXT,
        authorized_tools=frozenset({"wipe_disk"}),
    )
    assert result == {"ok": True}
    assert gate.plan_calls == []
    assert gate.escalation_calls == []
    assert calls == [("wipe_disk", {"path": "/tmp/x"})]


@pytest.mark.asyncio
async def test_plan_state_task_id_must_match_run() -> None:
    from datetime import UTC, datetime

    from maistro.tools.approval.gate import PlanApprovalState
    from maistro.tools.contracts import ToolApprovalRequired

    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("must not run")

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        plan_state=PlanApprovalState(
            task_id="other-run",
            approved_calls=frozenset({"wipe_disk"}),
            approved_at=datetime.now(UTC),
        ),
    )
    with pytest.raises(ToolApprovalRequired, match="ApprovalGate"):
        await executor.execute(
            "wipe_disk",
            {"path": "/tmp/x"},
            context=_CONTEXT,
            authorized_tools=frozenset({"wipe_disk"}),
        )


@pytest.mark.asyncio
async def test_successful_plan_approval_covers_later_calls() -> None:
    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)
    gate = _RecordingGate(outcome="approved")

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=gate,
    )
    await executor.execute(
        "wipe_disk",
        {"path": "/tmp/a"},
        context=_CONTEXT,
        authorized_tools=frozenset({"wipe_disk"}),
    )
    await executor.execute(
        "wipe_disk",
        {"path": "/tmp/b"},
        context=_CONTEXT,
        authorized_tools=frozenset({"wipe_disk"}),
    )
    assert len(gate.plan_calls) == 1


@pytest.mark.asyncio
async def test_thresholds_without_impacts_fail_closed() -> None:
    from maistro.tools.approval.types import Threshold
    from maistro.tools.contracts import ToolApprovalRequired

    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("must not run")

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=_RecordingGate(outcome="approved"),
        escalation_thresholds=(Threshold(dimension="cost", gt=1.0),),
    )
    with pytest.raises(ToolApprovalRequired, match="no per-call impacts"):
        await executor.execute(
            "wipe_disk",
            {"path": "/tmp/x"},
            context=_CONTEXT,
            authorized_tools=frozenset({"wipe_disk"}),
        )


@pytest.mark.asyncio
async def test_impact_estimator_and_escalation_path() -> None:
    from datetime import UTC, datetime

    from maistro.tools.approval.gate import PlanApprovalState
    from maistro.tools.approval.types import Impact, Threshold

    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)
    gate = _RecordingGate(outcome="approved")
    calls: list[tuple[str, dict[str, Any]]] = []

    async def backend(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls.append((name, arguments))
        return {"ok": True}

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    def estimate(_name: str, _arguments: dict[str, Any]) -> tuple[Impact, ...]:
        return (Impact(dimension="cost", value=9.0),)

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=gate,
        plan_state=PlanApprovalState(
            task_id="run-1",
            approved_calls=frozenset({"wipe_disk"}),
            approved_at=datetime.now(UTC),
        ),
        escalation_thresholds=(Threshold(dimension="cost", gt=1.0),),
        impact_estimator=estimate,
    )
    result = await executor.execute(
        "wipe_disk",
        {"path": "/tmp/x"},
        context=_CONTEXT,
        authorized_tools=frozenset({"wipe_disk"}),
    )
    assert result == {"ok": True}
    assert gate.escalation_calls == [("run-1", "wipe_disk")]
    assert gate.plan_calls == []


@pytest.mark.asyncio
async def test_async_impact_estimator_and_denied_gate() -> None:
    from maistro.tools.approval.types import Impact
    from maistro.tools.contracts import ToolNotAuthorized

    effects = new_effect_context(policy_evaluator=_allow_irreversible_policy)
    binding = Binding(
        binding_id="tool-binding-wipe",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability="destructive",
        provider_name="disk-provider",
    )
    await effects.bindings.put(binding)
    gate = _RecordingGate(outcome="denied")

    async def backend(_name: str, _arguments: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("must not run")

    async def binding_for(_contract: ToolContract, _context: ToolInvocationContext) -> Binding:
        return binding

    async def estimate(_name: str, _arguments: dict[str, Any]) -> tuple[Impact, ...]:
        return (Impact(dimension="cost", value=0.1),)

    executor = GovernedToolExecutor(
        effects=effects,
        contracts=_irreversible_registry(),
        binding_for=binding_for,
        backend=backend,
        approval_gate=gate,
        impact_estimator=estimate,
    )
    with pytest.raises(ToolNotAuthorized, match="not approved"):
        await executor.execute(
            "wipe_disk",
            {"path": "/tmp/x"},
            context=_CONTEXT,
            authorized_tools=frozenset({"wipe_disk"}),
        )
    assert gate.plan_calls == [("run-1", ("wipe_disk",))]
