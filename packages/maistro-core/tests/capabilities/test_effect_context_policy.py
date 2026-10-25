"""The explicit effect-context policy keeps legacy mutating tools governed (#1094).

`binding_scope_policy` is the M1 baseline policy an application composition
root must select explicitly (``default_effect_context()`` does exactly that).
It is never installed implicitly by ``new_effect_context()``: since #846 an
omitted policy evaluator is an unavailable dependency, and the unnamed context
fails closed (see test_binding_invocation.py). With the baseline policy
selected, approval granted for workflow admission must not be inherited by
legacy tool effects marked mutate/destroy: those Bindings get their own
REQUIRE_APPROVAL decision at the canonical Invocation boundary, while ordinary
Bindings resolve through Binding scope alone.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import binding_scope_policy, new_effect_context
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
    # Explicit M1 baseline selection, exactly as default_effect_context() does;
    # an unnamed context denies instead of installing any policy implicitly.
    context = new_effect_context(policy_evaluator=binding_scope_policy)
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
    context = new_effect_context(policy_evaluator=binding_scope_policy)

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
