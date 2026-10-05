"""Governed execution of third-party tools (M9-E3, #964).

Every test routes through the real canonical effect seam —
``new_in_memory_effect_context`` composing the Binding store, governed
Invocation service, event store and (where approval matters) approval store —
because the acceptance criteria are about *that* path:

* a state-changing tool executes through canonical Invocation (AC2);
* results, errors, denial, approval and cancellation are canonical and
  attributable (AC5);
* a runtime effect claim below the host floor is refused before dispatch,
  and never creates an Invocation (AC3).
"""

from __future__ import annotations

import asyncio

import pytest

from maistro.capabilities.approval_store import ApprovalStatus, InMemoryApprovalStore
from maistro.capabilities.effect_context import new_in_memory_effect_context
from maistro.capabilities.governed_invocation import InvocationPolicyContext
from maistro.capabilities.invocation import InvocationStatus
from maistro.extensions.tool_skill import (
    EffectClass,
    ExtensionContract,
    ExtensionToolCancellation,
    ExtensionToolCatalog,
    ExtensionToolOutcome,
    ExtensionToolRunner,
    ToolOutcomeStatus,
    UnknownToolError,
    effect_key_for,
    invoke_extension_tool,
)
from maistro.policy.types import Decision, PolicyVerdict

RUN_ID = "run-1"
NODE_RUN_ID = "node-1"
ATTEMPT_ID = "attempt-1"


def replace_tool_handler(tool, handler):
    """Swap the dispatch target under test (RegisteredExtensionTool is frozen)."""
    from dataclasses import replace

    return replace(tool, handler=handler)


async def _allow(binding, request, context: InvocationPolicyContext) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(Decision.ALLOW, reason="test allows", rule="test.allow")


async def _deny(binding, request, context: InvocationPolicyContext) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(Decision.DENY, reason="test denies", rule="test.deny")


async def _require_approval(binding, request, context: InvocationPolicyContext) -> PolicyVerdict:
    del binding, request, context
    return PolicyVerdict(
        Decision.REQUIRE_APPROVAL,
        reason="mutating effect needs a human",
        rule="test.approval",
    )


def mutate_manifest() -> dict[str, object]:
    """A state-changing tool: declares mutating honestly."""
    return {
        "id": "acme.counter",
        "publisher": "acme",
        "version": "2.0.0",
        "title": "Counter",
        "description": "Bumps a counter and reports the value.",
        "contract": ">=1.0.0,<2.0.0",
        "family": "tool",
        "capabilities": ["workspace.write"],
        "effects": ["mutating"],
        "data": {"scopes": ["workspace"]},
        "entrypoint": {"module": "acme_counter.plugin", "object": "PLUGIN"},
    }


def counter_entrypoint() -> dict[str, object]:
    return {
        "kind": "tool",
        "name": "acme.counter",
        "version": "2.0.0",
        "capabilities": ["workspace.write"],
        "handler": "bump",
    }


def make_counter_tool(calls: list[int]):
    """A state-changing handler whose dispatches the tests can count."""

    async def bump(amount: int = 1) -> dict:
        calls.append(amount)
        return {"value": sum(calls), "bumped_by": amount}

    return bump


def register_counter(catalog: ExtensionToolCatalog, calls: list[int]):
    contract = ExtensionContract.from_manifest(mutate_manifest(), digest="beef")
    return catalog.register(contract, counter_entrypoint(), handler=make_counter_tool(calls))


def counter_binding(catalog: ExtensionToolCatalog, tool):
    return catalog.tool_binding(tool, workspace_id="ws-1", project_id="pr-1")


async def test_state_changing_tool_executes_through_invocation_seam() -> None:
    """AC2: the effect crosses Binding -> policy -> Invocation, and the
    Invocation row is the canonical attributable record of the call."""
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 3},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
        actor_id="user-9",
    )

    assert calls == [3]
    assert outcome.status is ToolOutcomeStatus.COMPLETED
    assert outcome.success
    assert outcome.result == {"value": 3, "bumped_by": 3}
    assert outcome.invocation is not None
    assert outcome.invocation_id == outcome.invocation.invocation_id
    # Canonical attribution: the record carries the whole execution identity.
    assert outcome.invocation.run_id == RUN_ID
    assert outcome.invocation.node_run_id == NODE_RUN_ID
    assert outcome.invocation.attempt_id == ATTEMPT_ID
    assert outcome.invocation.workspace_id == "ws-1"
    assert outcome.invocation.actor_id == "user-9"
    assert outcome.invocation.binding.capability == "extension.tool:acme.counter"
    assert outcome.invocation.status is InvocationStatus.COMPLETED


async def test_completed_invocation_is_persisted_in_the_ledger() -> None:
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)
    await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 1},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )

    history = await effects.invocation_store.list_effect(
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        binding_id=binding.binding_id,
        effect_key=effect_key_for("acme.counter", {"amount": 1}),
    )
    assert [row.status for row in history] == [InvocationStatus.COMPLETED]


async def test_same_arguments_replay_without_redispatch() -> None:
    """The effect_key ledger dedups: a retry of the same logical effect is a
    replay of the recorded Invocation, not a second dispatch."""
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)
    first = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 5},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )
    second = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 5},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id="attempt-2",
    )

    assert calls == [5]
    assert second.invocation_id == first.invocation_id
    assert second.result == {"value": 5, "bumped_by": 5}


async def test_denied_call_is_attributable_and_dispatches_nothing() -> None:
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_deny)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 1},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )

    assert outcome.status is ToolOutcomeStatus.DENIED
    assert not outcome.success
    assert outcome.error_code == "policy_denied"
    assert "test denies" in outcome.error
    assert outcome.effect is EffectClass.MUTATING
    # Attribution survives refusal: the execution scope is on the outcome.
    assert (outcome.run_id, outcome.node_run_id, outcome.attempt_id) == (
        RUN_ID,
        NODE_RUN_ID,
        ATTEMPT_ID,
    )
    assert calls == []


async def test_approval_gate_returns_request_id() -> None:
    """AC5/ADR-051: the approval-required disposition carries the durable
    request id a human resolves later."""
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    approvals = InMemoryApprovalStore()
    effects = new_in_memory_effect_context(
        policy_evaluator=_require_approval, approval_store=approvals
    )

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 2},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )

    assert outcome.status is ToolOutcomeStatus.APPROVAL_REQUIRED
    assert outcome.error_code == "approval_required"
    assert outcome.approval_request_id
    stored = await approvals.get(outcome.approval_request_id)
    assert stored is not None
    assert stored.status is ApprovalStatus.PENDING
    assert calls == []


async def test_handler_exception_is_failed_and_recorded_unknown() -> None:
    """An exception after dispatch may have applied the remote effect: the
    outcome is FAILED for the caller, and the ledger records UNKNOWN."""

    async def explode() -> None:
        raise RuntimeError("remote said no")

    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(mutate_manifest(), digest="beef")
    tool = catalog.register(
        contract,
        {
            "kind": "tool",
            "name": "acme.counter",
            "version": "2.0.0",
            "capabilities": ["workspace.write"],
            "handler": "explode",
        },
        handler=explode,
    )
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )

    assert outcome.status is ToolOutcomeStatus.FAILED
    assert outcome.error_code == "handler_error"
    assert "remote said no" in outcome.error
    assert outcome.invocation_id  # attributable to a real Invocation row
    assert outcome.invocation is not None
    assert outcome.invocation.status is InvocationStatus.UNKNOWN


async def test_deadline_expiry_is_the_canonical_cancellation_family() -> None:
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    async def slow(amount: int = 1) -> dict:
        await asyncio.sleep(5)
        return {"value": amount}

    tool = replace_tool_handler(tool, slow)

    with pytest.raises(ExtensionToolCancellation) as excinfo:
        await invoke_extension_tool(
            effects,
            tool,
            binding,
            {"amount": 1},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
            timeout_s=0.05,
        )
    outcome = excinfo.value.outcome
    assert outcome.status is ToolOutcomeStatus.CANCELLED
    assert outcome.error_code == "deadline_exceeded"
    assert not outcome.success
    # The ledger recorded the interrupted call as UNKNOWN — the remote
    # outcome of a cancelled dispatch is never claimed as clean.
    assert outcome.invocation is not None
    assert outcome.invocation.status is InvocationStatus.UNKNOWN
    assert calls == []


async def test_external_cancellation_rethrows_with_attributable_outcome() -> None:
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    async def slow(amount: int = 1) -> dict:
        await asyncio.sleep(5)
        return {"value": amount}

    tool = replace_tool_handler(tool, slow)

    async def caller() -> ExtensionToolOutcome:
        return await invoke_extension_tool(
            effects,
            tool,
            binding,
            {"amount": 1},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
        )

    task = asyncio.ensure_future(caller())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError) as excinfo:
        await task
    outcome = getattr(excinfo.value, "outcome", None)
    assert isinstance(outcome, ExtensionToolOutcome)
    assert outcome.status is ToolOutcomeStatus.CANCELLED
    assert outcome.error_code == "cancelled"
    assert outcome.invocation is not None
    assert outcome.invocation.status is InvocationStatus.UNKNOWN


async def test_downgrade_claim_refused_before_any_invocation_exists() -> None:
    """AC3: the refused relabeling happens pre-dispatch — no Binding
    resolution, no policy event, no Invocation row to launder."""
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 1},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
        effect_claim=EffectClass.READ_ONLY,  # floor is MUTATING
    )

    assert outcome.status is ToolOutcomeStatus.FAILED
    assert outcome.error_code == "effect_downgrade_refused"
    assert outcome.invocation_id == ""
    assert calls == []
    history = await effects.invocation_store.list_effect(
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        binding_id=binding.binding_id,
        effect_key=effect_key_for("acme.counter", {"amount": 1}),
    )
    assert history == []


async def test_honest_higher_claim_runs_under_the_stricter_classification() -> None:
    """A claim above the floor is adopted: the extension can take the
    irreversible gate for one destructive call."""
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"amount": 1},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
        effect_claim=EffectClass.IRREVERSIBLE,
    )

    assert outcome.status is ToolOutcomeStatus.COMPLETED
    assert outcome.effect is EffectClass.IRREVERSIBLE


async def test_runner_resolves_by_tool_id_or_fails_typed() -> None:
    calls: list[int] = []
    catalog = ExtensionToolCatalog()
    tool = register_counter(catalog, calls)
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)
    runner = ExtensionToolRunner(effects, catalog)

    outcome = await runner.invoke(
        "acme.counter",
        binding,
        {"amount": 4},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )
    assert outcome.success and outcome.result["value"] == 4

    other_tool_binding = counter_binding(catalog, tool)
    with pytest.raises(UnknownToolError):
        await runner.invoke(
            "acme.ghost",
            other_tool_binding,
            {},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
        )


async def test_binding_for_another_tool_is_refused() -> None:
    catalog = ExtensionToolCatalog()
    calls: list[int] = []
    tool = register_counter(catalog, calls)
    contract = ExtensionContract.from_manifest(
        {
            **mutate_manifest(),
            "id": "acme.other",
            "capabilities": ["workspace.write"],
        },
        digest="beef",
    )
    other = catalog.register(
        contract,
        {
            "kind": "tool",
            "name": "acme.other",
            "version": "2.0.0",
            "capabilities": ["workspace.write"],
            "handler": "noop",
        },
        handler=make_counter_tool([]),
    )
    effects = new_in_memory_effect_context(policy_evaluator=_allow)
    wrong_binding = counter_binding(catalog, other)

    with pytest.raises(ValueError, match="does not match"):
        await invoke_extension_tool(
            effects,
            tool,
            wrong_binding,
            {},
            run_id=RUN_ID,
            node_run_id=NODE_RUN_ID,
            attempt_id=ATTEMPT_ID,
        )


async def test_sync_handler_runs_off_loop_and_completes() -> None:
    def sync_greet(target: str = "world") -> str:
        return f"Hello, {target}!"

    catalog = ExtensionToolCatalog()
    contract = ExtensionContract.from_manifest(
        {
            "id": "acme.greeter",
            "publisher": "acme",
            "version": "1.0.0",
            "title": "Greeter",
            "description": "Greets.",
            "contract": ">=1.0.0,<2.0.0",
            "family": "tool",
            "capabilities": [],
            "effects": ["read-only"],
            "data": {"scopes": []},
            "entrypoint": {"module": "x", "object": "P"},
        },
        digest="cafe",
    )
    tool = catalog.register(
        contract,
        {
            "kind": "tool",
            "name": "acme.greeter",
            "version": "1.0.0",
            "capabilities": [],
            "handler": "greet",
        },
        handler=sync_greet,
    )
    binding = counter_binding(catalog, tool)
    effects = new_in_memory_effect_context(policy_evaluator=_allow)

    outcome = await invoke_extension_tool(
        effects,
        tool,
        binding,
        {"target": "m9"},
        run_id=RUN_ID,
        node_run_id=NODE_RUN_ID,
        attempt_id=ATTEMPT_ID,
    )
    assert outcome.status is ToolOutcomeStatus.COMPLETED
    assert outcome.result == "Hello, m9!"
    assert outcome.invocation is not None
    assert outcome.invocation.request == {"target": "m9"}
