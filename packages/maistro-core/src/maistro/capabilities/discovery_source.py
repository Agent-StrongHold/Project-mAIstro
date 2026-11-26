"""Governed egress for discovery source fetches (#1051).

Mirrors :func:`maistro.capabilities.pm_polling.invoke_jira_poll`: one fetch is
one Binding-authorized, policy-evaluated, recorded Invocation tied to the
calling Run/NodeRun/Attempt. Unlike the PM helpers this provider consumes no
credential pool, so the raw resolver/executor pair is wired — the Binding
itself (its declared ``sources`` allowlist) is the authorization.
"""

from __future__ import annotations

from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.invocation import Invocation
from maistro.capabilities.providers.discovery_source import (
    DISCOVERY_SOURCE_CAPABILITY,
    DiscoverySourceRequest,
    execute_discovery_source,
    resolve_discovery_source_provider,
)


async def invoke_discovery_source(
    effects: CapabilityEffectContext,
    *,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    effect_key: str,
    request: DiscoverySourceRequest,
    timeout_s: float,
    actor_id: str = "",
) -> Invocation:
    """Route one source fetch through Binding, policy and Invocation."""

    if binding.capability != DISCOVERY_SOURCE_CAPABILITY:
        raise ValueError(f"unexpected discovery capability {binding.capability!r}")

    async def execute(provider: Any, payload: Any) -> Any:
        return await execute_discovery_source(provider, payload, timeout_s=timeout_s)

    return await effects.invocations.invoke(
        binding=binding,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        effect_key=effect_key,
        request=request,
        resolver=resolve_discovery_source_provider,
        executor=execute,
        actor_id=actor_id,
    )


__all__ = ["invoke_discovery_source"]
