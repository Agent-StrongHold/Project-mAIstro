"""The default effect-context policy keeps legacy mutating tools governed (#1094).

`_m1_binding_authorized_policy` is the composed policy behind
`new_effect_context()`. Approval granted for workflow admission must not be
inherited by legacy tool effects marked mutate/destroy: those Bindings get
their own REQUIRE_APPROVAL decision at the canonical Invocation boundary,
while ordinary Bindings resolve through Binding scope alone.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import new_effect_context
from maistro.capabilities.governed_invocation import InvocationApprovalRequired


def _legacy_binding(effect: str) -> Binding:
    return Binding(
        binding_id="binding-legacy-1",
        workspace_id="ws-1",
        project_id="project-1",
        node_id="node-1",
        capability=f"legacy_tool:deploy_{effect}",
        config={"effect": effect},
    )


class SimpleProvider:
    name = "legacy-provider"
    trust_tier = "trusted"

    def __init__(self, slot: str) -> None:
        self.slot = slot


async def _resolver(binding: Binding) -> Any:
    return SimpleProvider(binding.capability)


@pytest.mark.asyncio
@pytest.mark.parametrize("effect", ["mutate", "destroy"])
async def test_legacy_mutating_effect_requires_its_own_approval(effect: str) -> None:
    context = new_effect_context()
    executed: list[Any] = []

    async def executor(_provider: Any, request: Any) -> dict[str, Any]:
        executed.append(request)
        return {"committed": request}

    with pytest.raises(InvocationApprovalRequired):
        await context.invocations.invoke(
            binding=_legacy_binding(effect),
            run_id="run-1",
            node_run_id="node-run-1",
            attempt_id="attempt-1",
            effect_key=f"legacy:{effect}:1",
            request={"value": 1},
            resolver=_resolver,
            executor=executor,
        )

    assert executed == []


@pytest.mark.asyncio
async def test_legacy_read_effect_resolves_through_binding_scope() -> None:
    context = new_effect_context()

    async def executor(_provider: Any, request: Any) -> dict[str, Any]:
        return {"committed": request}

    invocation = await context.invocations.invoke(
        binding=_legacy_binding("read"),
        run_id="run-1",
        node_run_id="node-run-1",
        attempt_id="attempt-1",
        effect_key="legacy:read:1",
        request={"value": 2},
        resolver=_resolver,
        executor=executor,
    )

    assert invocation.result == {"committed": {"value": 2}}
