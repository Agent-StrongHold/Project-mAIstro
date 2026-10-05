"""One explicit provider activation on the canonical leased execution spine.

The route's config.write permission and deployment root scope remain the
admission contract. This adapter owns one-shot logical disposition, not physical
Attempt or Invocation settlement, retries, provider selection, or new authority.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import timedelta
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.model_chat import ModelCallResult
from maistro.graph.definitions import Graph, Node
from maistro.graph.node_types import build_default_node_type_registry
from maistro.observability.correlation import bind_execution_context, current_execution_context
from maistro.runs.execution import AttemptContextFactory
from maistro.runs.lifecycle import InvalidLifecycleTransition, is_reclaimed_attempt, transition_path
from maistro.runs.model import TERMINAL_RUN_STATUSES, Attempt, AttemptStatus, NodeRun, RunStatus
from maistro.runs.service import RunExecutionService
from maistro.runs.store import RunIntegrityError, RunStore
from maistro.runs.store_boundary import require_admitted_actor
from maistro.runtime import ExecutionCallable, PythonExecutionRuntime
from maistro.vault import SecretMissingError
from services.governed_model import (
    GovernedModelRuntime,
    ProviderAuthorizationError,
    ProviderHealthError,
)

_ACTIVATION_LEASE_TTL = timedelta(seconds=30)
logger = logging.getLogger(__name__)


class _ActivationRefused(asyncio.CancelledError):
    """Nothing was authorized to run; canonical execution records cancellation."""


async def _close_failed_operation(store: RunStore, attempt: Attempt) -> None:
    """Close this one-shot domain's parked failure without changing physical truth."""
    if attempt.status not in {
        AttemptStatus.FAILED,
        AttemptStatus.TIMED_OUT,
    } and not is_reclaimed_attempt(attempt):
        return
    node = await store.get_node_run(attempt.node_run_id)
    if node is None:
        raise RunIntegrityError("provider activation NodeRun disappeared")
    await _close_failed_record(store, node.run_id, node.node_run_id, attempt.error)
    current = await store.get_node_run(node.node_run_id)
    if current is not None and current.status is RunStatus.FAILED:
        await _close_failed_record(store, node.run_id, None, attempt.error)


async def _close_failed_record(
    store: RunStore, run_id: str, node_id: str | None, error: str | None
) -> None:
    """Move one logical record through legal transitions, respecting terminal wins."""
    while True:
        run = await store.get_run(run_id)
        if run is None:
            raise RunIntegrityError("provider activation Run disappeared")
        if run.status in TERMINAL_RUN_STATUSES:
            return
        record = await store.get_node_run(node_id) if node_id else run
        if record is None:
            raise RunIntegrityError("provider activation execution disappeared")
        if record.status in TERMINAL_RUN_STATUSES:
            return
        target = transition_path(record.status, RunStatus.FAILED)[0]
        try:
            if node_id:
                await store.transition_node_run(node_id, target, error=error)
            else:
                await store.transition_run(run_id, target, error=error)
        except (InvalidLifecycleTransition, RunIntegrityError):
            # Re-read the winner once before accepting a competing terminal.
            current = await store.get_node_run(node_id) if node_id else await store.get_run(run_id)
            if current is None or current.status not in TERMINAL_RUN_STATUSES:
                raise
            return


async def _drain(task: asyncio.Task[Any]) -> None:
    """Finish an owned settlement task despite repeated caller cancellation."""
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
        except Exception:
            logger.error("provider activation cancellation settlement unavailable")
            break
    with contextlib.suppress(asyncio.CancelledError, Exception):
        task.result()


async def _await_admission(service: RunExecutionService, admission: asyncio.Task[Any]) -> Any:
    """Retain the exact admitted identity if cancellation races its durable write."""
    try:
        return await asyncio.shield(admission)
    except asyncio.CancelledError:

        async def settle() -> None:
            run = await admission
            await service.cancel_run(run.run_id)

        await _drain(asyncio.create_task(settle()))
        raise


async def _await_execution(
    service: RunExecutionService,
    run_id: str,
    execution: asyncio.Task[Any],
    runtime: PythonExecutionRuntime,
    attempt_ids: list[str],
    cancelled: asyncio.Event,
) -> Any:
    """Signal the live owner promptly, then drain canonical persistence on cancel.

    Shielding the service task does not shield a live provider: cancel_run fences
    the Run and signals its registered Runtime. Only final settlement is drained,
    including repeated caller cancellation while its durable writes are pending.
    """
    try:
        return await asyncio.shield(execution)
    except asyncio.CancelledError:
        cancelled.set()

        async def settle() -> None:
            try:
                await service.cancel_run(run_id)
            except Exception:
                logger.error(
                    "provider activation cancellation fence unavailable; signalling local owner"
                )
                for attempt_id in attempt_ids:
                    await runtime.cancel(attempt_id)
            finally:
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await execution

        await _drain(asyncio.create_task(settle()))
        raise


async def _probe(
    *,
    runtime: GovernedModelRuntime,
    binding: Binding,
    provider_name: str,
    models: tuple[str, ...],
    vault: Any,
    secret_name: str,
    refused: list[Exception],
) -> ModelCallResult:
    from services import governed_model

    context = current_execution_context()
    try:
        result = await vault.use(
            secret_name,
            lambda api_key: governed_model.register_and_health_check(
                runtime=runtime,
                binding=binding,
                run_id=context.run_id,
                node_run_id=context.node_run_id,
                attempt_id=context.attempt_id,
                provider_name=provider_name,
                models=models,
                api_key=api_key,
            ),
        )
    except SecretMissingError:
        refused.append(SecretMissingError("provider key is missing"))
        raise _ActivationRefused from None
    except ProviderAuthorizationError:
        refused.append(ProviderAuthorizationError("provider health authorization failed"))
        raise _ActivationRefused from None
    except Exception as exc:
        # Health helpers emit safe typed errors. The vault/callback may not;
        # arbitrary dependency text must never become Attempt evidence.
        if isinstance(exc, ProviderHealthError):
            raise
        from services.governed_model import ProviderActivationError

        if isinstance(exc, ProviderActivationError):
            raise
        raise ProviderHealthError("provider health operation failed") from None
    return result


async def _close_reclaimed_execution(store: RunStore, attempt_ids: list[str]) -> bool:
    """Reconcile an already-durable recovery winner after the callback raised."""
    if not attempt_ids:
        return False
    attempt = await store.get_attempt(attempt_ids[-1])
    if attempt is None or not is_reclaimed_attempt(attempt):
        return False
    await _close_failed_operation(store, attempt)
    return True


async def activate(
    *,
    runtime: GovernedModelRuntime,
    binding: Binding,
    actor_principal_id: str,
    name: str,
    provider_name: str,
    models: tuple[str, ...],
    vault: Any,
    secret_name: str,
) -> ModelCallResult:
    """Execute a fresh, non-retrying health operation with transient vault access."""
    store = runtime.run_store
    if store is None:
        raise RuntimeError("canonical provider activation requires the Container run store")
    node = Node(
        node_id="control-plane",
        node_type="capability",
        name=f"provider-activation:{name}",
        binding_ids=(binding.binding_id,),
    )
    build_default_node_type_registry().validate_node(node)

    async def reconcile(attempt: Attempt) -> None:
        await _close_failed_operation(store, attempt)

    execution_runtime = PythonExecutionRuntime()
    service = RunExecutionService(
        store=store,
        runtime=execution_runtime,
        reconciler=reconcile,
        lease_ttl=_ACTIVATION_LEASE_TTL,
    )
    admission = asyncio.create_task(
        service.create_run(
            Graph(
                workspace_id=binding.workspace_id,
                project_id=binding.project_id,
                name=node.name,
                nodes=[node],
            ),
            actor_principal_id=require_admitted_actor(actor_principal_id),
            initial_status=RunStatus.QUEUED,
            provenance={
                "admission_source": "control-plane-operation",
                "operation": node.name,
                "activation_source": "routes.providers",
                "provider": name,
            },
        )
    )
    run = await _await_admission(service, admission)
    captured: list[ModelCallResult] = []
    refused: list[Exception] = []
    attempt_ids: list[str] = []
    cancelled = asyncio.Event()

    def capture_attempt(attempt: Attempt, _context: Any) -> None:
        attempt_ids.append(attempt.attempt_id)
        if cancelled.is_set():
            raise asyncio.CancelledError

    async def execute(_work: Any, _context: Any) -> dict[str, str]:
        result = await _probe(
            runtime=runtime,
            binding=binding,
            provider_name=provider_name,
            models=models,
            vault=vault,
            secret_name=secret_name,
            refused=refused,
        )
        captured.append(result)
        return {"invocation_id": result.invocation_id, "model": result.model}

    with bind_execution_context(workspace_id=run.workspace_id, project_id=run.project_id):
        execution = asyncio.create_task(
            _execute_activation(
                service, store, run.run_id, name, execute, capture_attempt, captured, attempt_ids
            )
        )
        try:
            return await _await_execution(
                service, run.run_id, execution, execution_runtime, attempt_ids, cancelled
            )
        except asyncio.CancelledError:
            caller = asyncio.current_task()
            if refused and (caller is None or not caller.cancelling()):
                raise refused[0] from None
            raise


async def _execute_activation(
    service: RunExecutionService,
    store: RunStore,
    run_id: str,
    name: str,
    executor: ExecutionCallable,
    context_factory: AttemptContextFactory,
    captured: list[ModelCallResult],
    attempt_ids: list[str],
) -> ModelCallResult:
    """Own physical execution and one-shot disposition through durable settlement."""
    try:
        node_run, attempt = await service.execute_node(
            run_id,
            "control-plane",
            {"provider": name},
            None,
            executor=executor,
            executor_id="provider-activation",
            context_factory=context_factory,
        )
    except Exception:
        if await _close_reclaimed_execution(store, attempt_ids):
            raise ProviderHealthError(
                "provider activation lease was reclaimed before completion"
            ) from None
        raise
    return await _activation_result(service, store, run_id, node_run, attempt, captured)


async def _activation_result(
    service: RunExecutionService,
    store: RunStore,
    run_id: str,
    node_run: NodeRun,
    attempt: Attempt,
    captured: list[ModelCallResult],
) -> ModelCallResult:
    # A recovered physical winner may be returned without this service owning
    # its reconciliation. This one-shot domain owes no retry decision: close
    # the logical operation without rewriting the winner's physical evidence.
    if is_reclaimed_attempt(attempt):
        await _close_failed_operation(store, attempt)
        raise ProviderHealthError(
            "provider activation lease was reclaimed; inspect the recorded Invocation outcome before retrying"
        )
    if attempt.status is AttemptStatus.CANCELLED:
        await service.cancel_run(run_id)
        raise asyncio.CancelledError
    await _close_failed_operation(store, attempt)
    current = await store.get_run(run_id)
    if (
        not captured
        or current is None
        or current.status is not RunStatus.COMPLETED
        or node_run.status is not RunStatus.COMPLETED
        or attempt.status is not AttemptStatus.COMPLETED
    ):
        raise ProviderHealthError("provider activation did not complete canonically")
    return captured[0]
