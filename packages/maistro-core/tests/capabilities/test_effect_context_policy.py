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
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    _clear_default_effect_context,
    binding_scope_policy,
    configure_default_effect_context,
    default_effect_context,
    new_effect_context,
    release_default_effect_context,
)
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


class TestNestedContainersHandTheDefaultBack:
    """Containers nest, so the process default has to be a stack.

    A test or an embedder can build a second Container inside the lifetime of
    the first. With one slot, closing the inner one left the process with no
    published context at all, so every later registry-constructed node -- the
    bare `RunConsumer` fallback among them -- got a fresh empty context and
    failed Binding resolution while a perfectly usable Container was still
    open (Codex, #1362).
    """

    @staticmethod
    def _published() -> CapabilityEffectContext:
        return new_effect_context(policy_evaluator=binding_scope_policy)

    def setup_method(self) -> None:
        _clear_default_effect_context()

    def teardown_method(self) -> None:
        _clear_default_effect_context()

    def test_closing_the_inner_container_restores_the_outer(self) -> None:
        outer, inner = self._published(), self._published()
        configure_default_effect_context(outer)
        configure_default_effect_context(inner)
        assert default_effect_context() is inner

        release_default_effect_context(inner)

        assert default_effect_context() is outer

    def test_closing_out_of_order_leaves_the_rest_in_place(self) -> None:
        """An embedder may close the outer Container first."""

        outer, inner = self._published(), self._published()
        configure_default_effect_context(outer)
        configure_default_effect_context(inner)

        release_default_effect_context(outer)

        assert default_effect_context() is inner

    def test_the_last_release_falls_back_rather_than_returning_none(self) -> None:
        only = self._published()
        configure_default_effect_context(only)

        release_default_effect_context(only)

        fallback = default_effect_context()
        assert fallback is not only
        # Still one shared instance, so nodes do not each get a private ledger.
        assert default_effect_context() is fallback

    def test_republishing_does_not_leave_a_stale_duplicate(self) -> None:
        """Re-publishing moves a context to the top, it does not record it twice.

        Otherwise one release would withdraw only the newer entry and the
        older duplicate would keep answering as the default.
        """

        outer, inner = self._published(), self._published()
        configure_default_effect_context(outer)
        configure_default_effect_context(inner)
        configure_default_effect_context(outer)
        assert default_effect_context() is outer

        release_default_effect_context(outer)

        assert default_effect_context() is inner
