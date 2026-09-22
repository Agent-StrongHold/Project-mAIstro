"""Canonical execution composition for the reachable Turing chat surface (#753).

Turing owns conversation/self-model/memory state. The platform execution spine
owns Workspace/Project/Run/NodeRun/Attempt identity. This module only composes
those existing public contracts for the standalone Turing backend; it does not
introduce a Turing lifecycle or activate dormant cognition.
"""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from pydantic import BaseModel

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.effect_context import (
    CapabilityEffectContext,
    new_in_memory_effect_context,
)
from maistro.capabilities.invocation import Invocation, InvocationStatus
from maistro.capabilities.model_chat import MODEL_CHAT_CAPABILITY
from maistro.capabilities.providers.llm_gateway import ModelChatRequest
from maistro.graph import Graph, Node
from maistro.graph.durable_runs import (
    CanonicalDurableRunStore,
    DurableRunRecord,
    InMemoryGraphContinuationStore,
    run_durable_graph,
)
from maistro.graph.nodes import BaseNode, NodeContext
from maistro.projects.scope_store import InMemoryProjectScopeStore
from maistro.runs import InMemoryRunStore
from maistro.runs.chat_admission import ADMISSION_INCOMPLETE, MAX_RETAINED_CHAT_RUNS
from maistro.runs.model import (
    TERMINAL_ATTEMPT_STATUSES,
    TERMINAL_RUN_STATUSES,
    AttemptStatus,
    RunStatus,
)
from maistro.runs.retention import RetentionPolicy, RunRetentionSweeper
from maistro.runs.sources import ADMISSION_SOURCE, CHAT_SOURCE
from maistro.workspaces.store import InMemoryWorkspaceStore
from maistro_turing.bridge import TuringProviderBridge
from maistro_turing.runtime import TuringChatSession

logger = logging.getLogger(__name__)

_CHAT_NODE_ID = "turing-chat-turn"
_CHAT_NODE_KIND = "turing.chat_turn"
_CANCELLED_ERROR = "execution cancelled"


class TuringAdmissionUnavailable(RuntimeError):
    """Canonical audit admission failed before Turing dispatched the chat turn."""


class _ChatInput(BaseModel):
    message: str


class _ChatOutput(BaseModel):
    reply: str


class _TuringChatProvider:
    """Adapt Turing's configured provider to the canonical model-chat slot."""

    def __init__(self, bridge: TuringProviderBridge) -> None:
        self.bridge = bridge

    @property
    def name(self) -> str:
        return "turing-provider"

    @property
    def slot(self) -> str:
        return MODEL_CHAT_CAPABILITY

    @property
    def trust_tier(self) -> str:
        return "t1"


def _resolver_for(
    bridge: TuringProviderBridge,
) -> Callable[[Binding], Any]:
    async def resolve(_binding: Binding) -> ResolvedCapabilityProvider:
        return _TuringChatProvider(bridge)

    return resolve


async def _execute_turing_provider(
    provider: ResolvedCapabilityProvider,
    payload: Any,
) -> dict[str, Any]:
    if not isinstance(provider, _TuringChatProvider):
        raise TypeError("Turing chat resolved a foreign Provider")
    if not isinstance(payload, ModelChatRequest):
        raise TypeError("Turing chat Invocation received a foreign request")
    response = await asyncio.to_thread(
        provider.bridge.complete,
        str(payload.messages[-1]["content"]),
        max_tokens=payload.max_tokens,
    )
    return {"choices": [{"message": {"content": response}}]}


def _reply_from_invocation(invocation: Invocation) -> str:
    if invocation.status is not InvocationStatus.COMPLETED:
        raise RuntimeError(invocation.error or "Turing chat Invocation failed")
    body = invocation.result
    if not isinstance(body, dict):
        raise RuntimeError("Turing chat Invocation produced no response body")
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise RuntimeError("Turing chat Invocation produced no choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise RuntimeError("Turing chat Invocation produced no message")
    return str(message.get("content") or "")


class _ChatSession(Protocol):
    """Turing conversation state used by the canonical chat Node."""

    async def prepare_message(self, message: str) -> str: ...

    async def record_response(self, message: str, reply: str) -> None: ...


class _ChatNode(BaseNode[_ChatInput, _ChatOutput]):
    """Execute one Turing domain chat turn under canonical Attempt evidence."""

    kind: ClassVar[str] = _CHAT_NODE_KIND
    kind_category: ClassVar = "sync.llm"
    input_schema: ClassVar[type[BaseModel]] = _ChatInput
    output_schema: ClassVar[type[BaseModel]] = _ChatOutput
    display_name: ClassVar[str] = "Turing chat turn"
    description: ClassVar[str] = "Execute one reachable Turing chat request."
    idempotent: ClassVar[bool] = False
    external_io: ClassVar[bool] = True

    def __init__(
        self,
        session: _ChatSession,
        provider: TuringProviderBridge,
        invoke_chat: Callable[..., Any],
    ) -> None:
        self._session = session
        self._provider = provider
        self._invoke_chat = invoke_chat

    async def _execute(self, inputs: _ChatInput, ctx: NodeContext) -> _ChatOutput:
        prompt = await self._session.prepare_message(inputs.message)
        reply = await self._invoke_chat(
            bridge=self._provider,
            prompt=prompt,
            max_tokens=1000,
            context=ctx,
        )
        await self._session.record_response(inputs.message, reply)
        return _ChatOutput(reply=reply)


class TuringExecutionPlane:
    """Compose canonical in-memory ownership/execution stores for this service.

    The standalone backend is already explicitly process-local. Using the
    canonical in-memory stores therefore improves identity semantics without
    pretending this slice adds restart durability. A durable deployment can
    replace these implementations through the same public store contracts.

    Chat admission still follows the canonical chat retention contract: the Run
    is marked with ``CHAT_SOURCE``, gets a durable retention deadline, and is
    tracked in a small per-process window so high-volume turns do not evict
    longer-lived task Runs from a shared store.
    """

    def __init__(
        self,
        *,
        max_retained: int = MAX_RETAINED_CHAT_RUNS,
        retention: RetentionPolicy | None = None,
    ) -> None:
        if max_retained < 1:
            raise ValueError("max_retained must be >= 1")
        self.project_store = InMemoryProjectScopeStore()
        self.workspace_store = InMemoryWorkspaceStore(project_store=self.project_store)
        self.run_store = InMemoryRunStore(project_store=self.project_store)
        self.durable_store = CanonicalDurableRunStore(
            self.run_store,
            InMemoryGraphContinuationStore(),
        )
        self.effects: CapabilityEffectContext = new_in_memory_effect_context()
        self._workspace_by_user: dict[str, str] = {}
        self._binding_by_workspace: dict[str, str] = {}
        self._invocation_ids_by_run: dict[str, str] = {}
        self._scope_lock = asyncio.Lock()
        self._retained_runs: OrderedDict[str, None] = OrderedDict()
        self._retention_lock = asyncio.Lock()
        self._max_retained = max_retained
        self._retention = retention if retention is not None else RetentionPolicy()
        self._retention_sweeper = RunRetentionSweeper(self.run_store, self._retention)

    @property
    def retained(self) -> int:
        """How many Turing chat Runs this process still tracks."""
        return len(self._retained_runs)

    async def _scope_for(self, user_id: str) -> tuple[str, str]:
        async with self._scope_lock:
            workspace_id = self._workspace_by_user.get(user_id)
            if workspace_id is None:
                workspace = await self.workspace_store.create(
                    creator_user_id=user_id,
                    name=f"Turing workspace for {user_id}",
                    description="Canonical scope for the standalone Turing chat surface.",
                )
                workspace_id = workspace.workspace_id
                self._workspace_by_user[user_id] = workspace_id
            root = await self.project_store.root_for_workspace(workspace_id)
            if workspace_id not in self._binding_by_workspace:
                binding = Binding(
                    workspace_id=workspace_id,
                    project_id=root.project_id,
                    node_id=_CHAT_NODE_ID,
                    capability=MODEL_CHAT_CAPABILITY,
                    config={"source": "turing.chat"},
                )
                await self.effects.bindings.put(binding)
                self._binding_by_workspace[workspace_id] = binding.binding_id
            return workspace_id, root.project_id

    async def invocation_for_run(self, run_id: str) -> Invocation | None:
        """Return the canonical model Invocation projected for a Turing Run."""
        invocation_id = self._invocation_ids_by_run.get(run_id)
        if invocation_id is None:
            return None
        return await self.effects.invocation_store.get(invocation_id)

    async def _invoke_chat(
        self,
        *,
        bridge: TuringProviderBridge,
        prompt: str,
        max_tokens: int | None,
        context: Any,
    ) -> str:
        """Run one Turing model call through Binding -> Provider -> Invocation."""
        workspace_id = str(context.workspace_id or "")
        project_id = str(context.project_id or "")
        binding_id = self._binding_by_workspace.get(workspace_id)
        if binding_id is None:
            raise RuntimeError("Turing chat Binding is not admitted for this Workspace")
        binding = await self.effects.bindings.resolve(
            binding_id,
            workspace_id=workspace_id,
            project_id=project_id,
            node_id=context.node_id,
            capability=MODEL_CHAT_CAPABILITY,
        )
        request = ModelChatRequest(
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max_tokens,
        )

        try:
            invocation = await self.effects.invocations.invoke(
                binding=binding,
                run_id=context.run_id,
                node_run_id=context.node_run_id,
                attempt_id=context.attempt_id,
                effect_key="turing.chat.complete",
                request=request,
                resolver=_resolver_for(bridge),
                executor=_execute_turing_provider,
            )
        except BaseException:
            # The governed service terminalizes unknown provider outcomes before
            # re-raising. Recover that canonical evidence for the Run projection.
            latest = await self.effects.invocations.latest_effect(
                binding=binding,
                run_id=context.run_id,
                node_run_id=context.node_run_id,
                effect_key="turing.chat.complete",
            )
            if latest is not None:
                self._invocation_ids_by_run[context.run_id] = latest.invocation_id
            raise
        self._invocation_ids_by_run[context.run_id] = invocation.invocation_id
        return _reply_from_invocation(invocation)

    async def _track_admission(self, run_id: str) -> None:
        self._retained_runs[run_id] = None
        async with self._retention_lock:
            for retained_id in list(self._retained_runs):
                if len(self._retained_runs) <= self._max_retained:
                    break
                retained = await self.run_store.get_run(retained_id)
                if retained is None:
                    self._retained_runs.pop(retained_id, None)
                    continue
                if retained.status not in TERMINAL_RUN_STATUSES:
                    continue
                await self.run_store.delete_run(retained_id)
                self._retained_runs.pop(retained_id, None)
        await self._retention_sweeper.maybe_sweep()

    async def _clear_continuation(self, run_id: str) -> None:
        """Clear runnable frontier after a compensated/cancelled Turing Run."""
        try:
            record = await self.durable_store.get(run_id)
            if record is None:
                return
            state = record.graph_state.model_copy(update={"active_node_ids": ()})
            await self.durable_store.update(
                record.model_copy(
                    update={
                        "graph_state": state,
                        "resume_at": None,
                        "version": record.version + 1,
                    }
                )
            )
        except Exception:
            logger.warning("Turing continuation cleanup failed for Run %s", run_id, exc_info=True)

    async def _cancel_incomplete_admission(self, run_id: str | None) -> None:
        """Compensate a Run persisted before canonical graph admission completed."""
        if run_id is None:
            return
        try:
            current = await self.run_store.get_run(run_id)
            if current is None or current.status in TERMINAL_RUN_STATUSES:
                return
            # Canonical adoption advances a QUEUED Run to RUNNING before the
            # first continuation checkpoint. Until node resolution begins, that
            # RUNNING state is still incomplete admission, not dispatched work.
            await self.run_store.transition_run(
                run_id,
                RunStatus.CANCELLED,
                error=ADMISSION_INCOMPLETE,
            )
            await self._clear_continuation(run_id)
        except Exception:
            logger.warning(
                "stranded Turing chat Run %s could not be compensated",
                run_id,
                exc_info=True,
            )

    async def _cancel_execution(self, run_id: str) -> None:
        """Best-effort outer cancellation guard around durable Graph execution."""
        try:
            for node_run in await self.run_store.list_node_runs(run_id):
                for attempt in await self.run_store.list_attempts(node_run.node_run_id):
                    if attempt.status in TERMINAL_ATTEMPT_STATUSES:
                        continue
                    lease = attempt.execution_lease
                    token = lease.fencing_token if lease is not None else None
                    await self.run_store.transition_attempt(
                        attempt.attempt_id,
                        AttemptStatus.CANCELLED,
                        error=_CANCELLED_ERROR,
                        fencing_token=token,
                    )
                current_node = await self.run_store.get_node_run(node_run.node_run_id)
                if current_node is not None and current_node.status not in TERMINAL_RUN_STATUSES:
                    await self.run_store.transition_node_run(
                        current_node.node_run_id,
                        RunStatus.CANCELLED,
                        error=_CANCELLED_ERROR,
                    )

            current = await self.run_store.get_run(run_id)
            if current is not None and current.status not in TERMINAL_RUN_STATUSES:
                await self.run_store.transition_run(
                    run_id,
                    RunStatus.CANCELLED,
                    error=_CANCELLED_ERROR,
                )
            await self._clear_continuation(run_id)
        except Exception:
            logger.warning("Turing cancellation cleanup failed for Run %s", run_id, exc_info=True)

    async def run_chat(
        self,
        *,
        session: TuringChatSession,
        user_id: str,
        session_id: str,
        message: str,
    ) -> DurableRunRecord:
        """Execute one chat request as one canonical Graph/Run.

        Failure before node resolution is an admission failure: no provider
        work has been dispatched, so the incomplete admission is cancelled and
        ``TuringAdmissionUnavailable`` is raised. The HTTP boundary fails
        closed with a fixed 503 and never replays the user turn outside the
        Run/NodeRun/Attempt spine. Once the node has been resolved, failures
        belong to canonical execution and are likewise never replayed outside
        the spine.
        """
        admitted_run_id: str | None = None
        try:
            workspace_id, project_id = await self._scope_for(user_id)
            graph = Graph(
                workspace_id=workspace_id,
                project_id=project_id,
                name="Turing chat turn",
                description="One request on the reachable standalone Turing chat surface.",
                nodes=[
                    Node(
                        node_id=_CHAT_NODE_ID,
                        node_type=_CHAT_NODE_KIND,
                        name="Turing chat turn",
                        parameters={"message": message},
                        policies={"max_attempts": 1},
                    )
                ],
                metadata={
                    "entry_node": _CHAT_NODE_ID,
                    "execution_owner": "canonical_run",
                    "product": "turing",
                },
            )
            provenance = {
                ADMISSION_SOURCE: CHAT_SOURCE,
                "product": "turing",
                "session_id": session_id,
            }
            admitted = await self.run_store.create_run(
                graph,
                actor_principal_id=user_id,
                provenance=provenance,
                retention_expires_at=self._retention.deadline(),
                initial_status=RunStatus.QUEUED,
            )
            admitted_run_id = admitted.run_id
            await self._track_admission(admitted.run_id)
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel_incomplete_admission(admitted_run_id))
            raise
        except Exception as exc:
            await self._cancel_incomplete_admission(admitted_run_id)
            raise TuringAdmissionUnavailable("canonical Turing chat admission failed") from exc

        provider = getattr(session, "provider_bridge", TuringProviderBridge())
        if not isinstance(provider, TuringProviderBridge):
            raise TypeError("Turing chat session has no canonical provider bridge")
        node = _ChatNode(session, provider, self._invoke_chat)
        dispatch_prepared = False

        def resolve(node_id: str, _graph: Graph) -> BaseNode[Any, Any]:
            nonlocal dispatch_prepared
            # Resolver entry means canonical execution has moved beyond audit
            # admission. From here on an exception is an execution/programming
            # failure and must never replay the user turn outside the spine.
            dispatch_prepared = True
            if node_id != _CHAT_NODE_ID:
                raise KeyError(f"unknown Turing canonical node {node_id!r}")
            return node

        try:
            return await run_durable_graph(
                graph,
                store=self.durable_store,
                node_resolver=resolve,
                actor_principal_id=user_id,
                run_id=admitted.run_id,
                provenance=provenance,
                run_store=self.run_store,
            )
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel_execution(admitted.run_id))
            raise
        except Exception as exc:
            if not dispatch_prepared:
                await self._cancel_incomplete_admission(admitted.run_id)
                raise TuringAdmissionUnavailable(
                    "canonical Turing chat checkpoint admission failed"
                ) from exc
            raise


_execution_plane = TuringExecutionPlane()


def get_execution_plane() -> TuringExecutionPlane:
    """Return the process-local canonical execution composition."""
    return _execution_plane


def reset_execution_plane() -> TuringExecutionPlane:
    """Replace process-local execution composition; used for test isolation."""
    global _execution_plane
    _execution_plane = TuringExecutionPlane()
    return _execution_plane


__all__ = [
    "TuringAdmissionUnavailable",
    "TuringExecutionPlane",
    "get_execution_plane",
    "reset_execution_plane",
]
