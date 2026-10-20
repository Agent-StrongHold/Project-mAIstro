"""Thin model-call adapter over the existing Run, Binding and Invocation owners.

Correlation strings alone authorize nothing. Shipped callers resolve their
current execution through the Container's RunStore and select an explicitly
configured Binding before crossing ModelChatEgress. This adapter creates no
Run, Binding, credential pool entry, policy or Invocation ledger.
"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.model_chat import ModelCallResult, ModelChatEgress
from maistro.capabilities.provider_adapters import ProviderAdapterCatalog
from maistro.capabilities.providers.llm_gateway import MODEL_CHAT_CAPABILITY
from maistro.observability.correlation import current_execution_context

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext
    from maistro.capabilities.providers.llm_gateway import GatewayEndpoint, ModelChatRequest
    from maistro.providers.protocols import LLMProviderRegistry, LLMRouter
    from maistro.runs.model import Attempt, NodeRun, Run
    from maistro.runs.store import RunStore


class AdmittedModelCalls:
    """Compose one configured model consumer with canonical execution records."""

    def __init__(
        self,
        effects: CapabilityEffectContext,
        *,
        registry: LLMProviderRegistry,
        router: LLMRouter,
        endpoint: GatewayEndpoint,
        run_store: RunStore,
        binding_ids: tuple[str, ...],
        adapters: ProviderAdapterCatalog | None = None,
    ) -> None:
        self._effects = effects
        self._registry = registry
        self._router = router
        self._endpoint = endpoint
        self._runs = run_store
        self._binding_ids = tuple(dict.fromkeys(binding_ids))
        # Keep this consumer bound to its owning Container catalog. A missing
        # catalog means no adapters, never another Container's process default.
        self._adapters = adapters if adapters is not None else ProviderAdapterCatalog()

    def _timeout(self, timeout_s: float | None, deadline_at: datetime | None) -> float:
        from maistro.runs.store import RunIntegrityError

        timeout = self._endpoint.timeout_s if timeout_s is None else timeout_s
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("model timeout_s must be finite and positive")
        if deadline_at is not None:
            remaining = (deadline_at - datetime.now(UTC)).total_seconds()
            if remaining <= 0:
                raise RunIntegrityError("model call Attempt deadline has expired")
            timeout = min(timeout, remaining)
        return timeout

    async def _authorize(
        self, identity: tuple[str, str, str] | None, binding_id: str
    ) -> tuple[Binding, str, tuple[str, str, str], datetime | None]:
        from maistro.runs.store import RunIntegrityError
        from maistro.runs.store_boundary import require_admitted_actor

        selected = _identity(identity)
        run_id, node_run_id, attempt_id = selected
        run = await self._runs.get_run(run_id)
        node = await self._runs.get_node_run(node_run_id)
        attempt = await self._runs.get_attempt(attempt_id)
        if run is None or node is None or attempt is None:
            raise RunIntegrityError("model call execution records do not exist")
        if node.run_id != run.run_id or attempt.node_run_id != node.node_run_id:
            raise RunIntegrityError("model call execution records belong to different executions")
        _require_running(run, node, attempt)
        _require_scope(run)
        actor = require_admitted_actor(run.actor_principal_id)
        binding = await self._binding(
            binding_id,
            workspace_id=run.workspace_id,
            project_id=run.project_id,
            node_id=node.node_id,
        )
        return binding, actor, selected, attempt.deadline_at

    async def _binding(
        self, binding_id: str, *, workspace_id: str, project_id: str, node_id: str
    ) -> Binding:
        if binding_id and binding_id not in self._binding_ids:
            raise BindingResolutionError("model Binding was not declared by this composition")
        candidates = []
        for configured_id in (binding_id,) if binding_id else self._binding_ids:
            binding = await self._effects.bindings.get(configured_id)
            if binding is not None and _covers(binding, workspace_id, project_id, node_id):
                candidates.append(binding.binding_id)
        if len(candidates) != 1:
            raise BindingResolutionError(
                "model call requires exactly one configured Binding in its admitted scope; "
                "select an explicit binding_id when several are configured"
            )
        # Re-resolve every call; a stored client cannot outlive revocation or
        # substitute a new Binding to escape disabled/credential/policy scope.
        return await self._effects.bindings.resolve(
            candidates[0],
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )

    async def complete(
        self,
        *,
        request: ModelChatRequest,
        effect_key: str,
        identity: tuple[str, str, str] | None = None,
        binding_id: str = "",
        timeout_s: float | None = None,
    ) -> ModelCallResult:
        binding, actor, selected, deadline_at = await self._authorize(identity, binding_id)
        timeout = self._timeout(timeout_s, deadline_at)
        egress = ModelChatEgress(
            self._effects,
            registry=self._registry,
            router=self._router,
            endpoint=self._endpoint.model_copy(update={"timeout_s": timeout}),
            adapters=self._adapters,
        )
        # Provider adapters retain their own transport limits. The outer bound
        # also enforces this consumer's deadline for that path; cancellation
        # after dispatch is settled UNKNOWN by the existing Invocation owner.
        async with asyncio.timeout(timeout):
            return await egress.complete(
                binding=binding,
                run_id=selected[0],
                node_run_id=selected[1],
                attempt_id=selected[2],
                actor_id=actor,
                effect_key=effect_key,
                request=request,
            )


def _identity(identity: tuple[str, str, str] | None) -> tuple[str, str, str]:
    from maistro.runs.store import RunIntegrityError

    context = current_execution_context()
    live = (context.run_id, context.node_run_id, context.attempt_id)
    selected = identity if identity is not None else live
    if any(not value.strip() for value in selected):
        raise RunIntegrityError("model call requires an admitted Run/NodeRun/Attempt")
    if any(live) and live != selected:
        raise RunIntegrityError("model call identity does not match the live execution")
    return selected


def _require_running(run: Run, node: NodeRun, attempt: Attempt) -> None:
    from maistro.runs.model import AttemptStatus, RunStatus
    from maistro.runs.store import RunIntegrityError

    if (
        run.status is not RunStatus.RUNNING
        or node.status is not RunStatus.RUNNING
        or attempt.status is not AttemptStatus.RUNNING
    ):
        raise RunIntegrityError("model call requires running canonical execution records")
    lease = attempt.execution_lease
    if lease is None:
        raise RunIntegrityError("model call Attempt is missing its execution lease")
    if lease.expires_at is not None and lease.expires_at <= datetime.now(UTC):
        raise RunIntegrityError("model call Attempt lease has expired")


def _require_scope(run: Run) -> None:
    from maistro.runs.store import RunIntegrityError

    context = current_execution_context()
    if (context.workspace_id and context.workspace_id != run.workspace_id) or (
        context.project_id and context.project_id != run.project_id
    ):
        raise RunIntegrityError("model call scope does not match its admitted Run")


def _covers(binding: Binding, workspace_id: str, project_id: str, node_id: str) -> bool:
    return (
        binding.workspace_id == workspace_id
        and binding.project_id == project_id
        and binding.capability == MODEL_CHAT_CAPABILITY
        and binding.node_id in ("", node_id)
    )


__all__ = ["AdmittedModelCalls"]
