"""Fail-closed guard arms of the reconstructible approval-gated node (#2405).

`infra.approval_gated_action` rebuilds its governed collaborators from durable
facts on resume. Every rebuild step has a refusal arm: a resume that cannot
rebuild the effect_context, the durable Binding reference, or the Container
registry authority must raise instead of dispatching an ungoverned host call.
These tests execute each refusal arm directly; deleting a guard (the mutation)
must fail its test, or a reconstruction gap would dispatch from nothing.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_effect_context
from maistro.graph.nodes.infra_approval_action import InfraApprovalActionNode


def _binding() -> Binding:
    return Binding(
        binding_id="builtin:self-repair:infra-action",
        workspace_id="default",
        project_id="default",
        node_id="self-repair",
        capability="infra_action",
    )


async def test_a_bare_node_refuses_dispatch_without_an_effect_context() -> None:
    """No `effect_context` authority: nothing governed to dispatch through."""
    node = InfraApprovalActionNode()
    with pytest.raises(LookupError, match="no effect_context authority"):
        node._effective_context()


async def test_a_node_without_a_durable_binding_reference_refuses_dispatch() -> None:
    """No Binding reference (injected or persisted): no identity to authorize."""
    node = InfraApprovalActionNode(effect_context=new_effect_context())
    with pytest.raises(LookupError, match="no durable Binding reference"):
        await node._effective_binding()


async def test_a_scope_mismatched_durable_binding_refuses_dispatch() -> None:
    """The live authority resolving a different Binding fails the resume."""
    replaced = _binding().model_copy(update={"binding_id": "builtin:other:infra-action"})

    class _AlienBindingStore:
        async def resolve(self, binding_id: str, **_kwargs: Any) -> Binding:
            return replaced

    node = InfraApprovalActionNode(
        effect_context=new_effect_context(binding_store=_AlienBindingStore()),
        binding_id=_binding().binding_id,
    )
    with pytest.raises(LookupError, match="invalid durable self_repair binding"):
        await node._effective_binding()


async def test_a_node_without_a_registry_refuses_to_resolve_a_provider() -> None:
    """No `capability_registry` authority: never resolve a provider from nothing."""
    node = InfraApprovalActionNode(
        effect_context=new_effect_context(),
        capability_registry=None,
    )
    with pytest.raises(LookupError, match="no capability_registry authority"):
        await node._default_resolve_provider(_binding())


async def test_a_non_action_provider_refuses_resolution() -> None:
    """A registry slot resolved to a non-InfraAction provider fails closed."""
    resolved: list[Any] = []

    class _NotAnAction:
        name = "not-an-action"

    class _Registry:
        async def resolve(self, slot: str) -> Any:
            resolved.append(slot)
            return _NotAnAction()

    node = InfraApprovalActionNode(
        effect_context=new_effect_context(),
        capability_registry=_Registry(),
    )
    with pytest.raises(LookupError, match="infra_action unavailable"):
        await node._default_resolve_provider(_binding())
    assert resolved == ["infra_action"]
