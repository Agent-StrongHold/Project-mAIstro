"""Governed egress for Jira and Airtable polling Providers."""

from __future__ import annotations

from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.invocation import Invocation
from maistro.capabilities.providers.pm_polling import (
    AIRTABLE_POLL_CAPABILITY,
    JIRA_POLL_CAPABILITY,
    JIRA_SUBTASKS_CAPABILITY,
    AirtablePollRequest,
    JiraPollRequest,
    JiraSubtasksRequest,
    execute_airtable,
    execute_jira,
    resolve_airtable_provider,
    resolve_jira_provider,
)


async def invoke_jira_poll(
    effects: CapabilityEffectContext,
    *,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    effect_key: str,
    request: JiraPollRequest | JiraSubtasksRequest,
    timeout_s: float,
) -> Invocation:
    """Route one Jira read through Binding, credential, policy and Invocation."""

    if binding.capability not in {JIRA_POLL_CAPABILITY, JIRA_SUBTASKS_CAPABILITY}:
        raise ValueError(f"unexpected Jira capability {binding.capability!r}")
    routing = effects.credential_routing()
    resolver = routing.resolver(resolve_jira_provider)

    async def execute(provider: Any, payload: Any) -> Any:
        return await execute_jira(provider, payload, timeout_s=timeout_s)

    return await effects.invocations.invoke(
        binding=binding,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        effect_key=effect_key,
        request=request,
        resolver=resolver,
        executor=routing.executor(execute),
    )


async def invoke_airtable_poll(
    effects: CapabilityEffectContext,
    *,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    effect_key: str,
    request: AirtablePollRequest,
    timeout_s: float,
) -> Invocation:
    """Route one Airtable read through Binding, credential, policy and Invocation."""

    if binding.capability != AIRTABLE_POLL_CAPABILITY:
        raise ValueError(f"unexpected Airtable capability {binding.capability!r}")
    routing = effects.credential_routing()

    async def execute(provider: Any, payload: Any) -> Any:
        return await execute_airtable(provider, payload, timeout_s=timeout_s)

    return await effects.invocations.invoke(
        binding=binding,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        effect_key=effect_key,
        request=request,
        resolver=routing.resolver(resolve_airtable_provider),
        executor=routing.executor(execute),
    )


__all__ = [
    "AIRTABLE_POLL_CAPABILITY",
    "JIRA_POLL_CAPABILITY",
    "JIRA_SUBTASKS_CAPABILITY",
    "AirtablePollRequest",
    "JiraPollRequest",
    "JiraSubtasksRequest",
    "invoke_airtable_poll",
    "invoke_jira_poll",
]
