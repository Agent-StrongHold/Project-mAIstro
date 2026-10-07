"""Shared governance fixtures for `agent.delegate_remote` external dispatch.

Issue #959 made a cross-instance delegation a governed capability effect:
canonical identity binding, an authorized `agent_delegation` Binding, and one
recorded Invocation. Every test that drives the external path needs the same
minimal wiring, so it lives here once.
"""

from __future__ import annotations

from typing import Any

from maistro.a2a.delegation_context import DelegationContext
from maistro.a2a.guest_peers import GuestPeerManager, PeerTrust
from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    binding_scope_policy,
    new_in_memory_effect_context,
)
from maistro.graph.nodes.agent_delegate_remote import AGENT_DELEGATION_CAPABILITY


def delegation_context(
    *,
    caller: str = "actor-1",
    agent: str = "planner",
    workspace_id: str = "workspace-1",
    project_id: str = "project-1",
    run_id: str = "run-1",
    node_run_id: str = "node-run-1",
    attempt_id: str = "attempt-1",
    key: str = "effect-1",
    **overrides: Any,
) -> DelegationContext:
    """One canonical delegation context; tests override single fields."""
    return DelegationContext(
        caller_principal_id=caller,
        delegating_agent=agent,
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        delegation_key=key,
        **overrides,
    )


async def delegation_effects(
    *,
    workspace_id: str,
    project_id: str,
    binding_id: str = "binding-hub",
    provider_name: str = "",
) -> CapabilityEffectContext:
    """An in-memory effect context with one `agent_delegation` Binding.

    The Binding is operator-declared authority, exactly as a deployment would
    bootstrap it; the scope policy is the M1 baseline (allow after Binding
    resolution), so tests exercise the admission machinery, not policy.
    """
    effects = new_in_memory_effect_context(policy_evaluator=binding_scope_policy)
    await effects.bindings.put(
        Binding(
            binding_id=binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            capability=AGENT_DELEGATION_CAPABILITY,
            provider_name=provider_name,
        )
    )
    return effects


def guest_peers_with_hub(**peer_overrides: Any) -> GuestPeerManager:
    """A peer manager with the registered `hub` peer tests delegate to."""
    peers = GuestPeerManager()
    peers.register_peer(
        PeerTrust(
            peer_url=peer_overrides.pop("peer_url", "http://hub"),
            peer_name=peer_overrides.pop("peer_name", "hub"),
            **peer_overrides,
        )
    )
    return peers
