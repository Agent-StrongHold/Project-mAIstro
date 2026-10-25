"""`agent.spawn_harness` — spawn an external agent harness as a governed DAG effect.

A harness adapter remains provider-specific: it knows how to dispatch to Claude
Code, another Conductor, an in-process harness, or a generic HTTP endpoint. It
does not own universal effect lifecycle or authorization. First dispatch now
resolves a canonical Workspace/Project-scoped Binding and crosses the governed
Invocation boundary before the physical adapter call. The node then pauses the
canonical Run until the harness result is supplied on resume.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from maistro.capabilities.approval_store import approval_request_digest
from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.invocation import Invocation, InvocationStatus, UnsafeEffectRetry
from maistro.capabilities.slots.harness_runner import HarnessRunner
from maistro.capabilities.types import Unavailable
from maistro.graph.harness import (
    HarnessAdapter,
    HarnessHandle,
    HarnessRequest,
    HarnessResult,
    HarnessRunnerDispatchAdapter,
)

from . import register_node
from .base import (
    PAUSE_AWAITING_HARNESS,
    PAUSE_AWAITING_HUMAN_APPROVAL,
    RESUMED_PAUSE_KEY,
    BaseNode,
    NodeContext,
    ReplaySemantics,
    now_utc,
    pause_until,
    replay_effect_key,
    resumed_pause,
)
from .capability_effect import invoke_capability_effect


class SpawnHarnessIn(BaseModel):
    harness_type: str = Field(
        description="Harness provider kind: claude_code, conductor, generic_http, in_process"
    )
    task: str = Field(description="Task description handed to the harness")
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional context for the harness"
    )
    timeout_seconds: int = Field(default=3600, description="Hard deadline in seconds")
    workdir: str = Field(
        default="",
        description=(
            "Workspace hint handed to the harness provider (repo/checkout the "
            "harness acts on); recorded on the Invocation. Empty = provider default."
        ),
    )
    binding_id: str = Field(
        default="",
        description=(
            "Reference to a pre-authorized canonical Binding. Naming an id does not grant "
            "authority; the Binding store resolves it against the executing scope."
        ),
    )


class SpawnHarnessOut(BaseModel):
    status: Literal["completed", "failed", "timed_out"] = "completed"
    handle_id: str = ""
    output: str = ""
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def _detail_payload(handle: HarnessHandle) -> dict[str, Any]:
    """Adapter-vouched dispatch provenance for the Invocation result row."""
    detail = handle.detail
    return dict(detail) if isinstance(detail, dict) else {}


def _as_dispatch_adapter(provider: HarnessAdapter | HarnessRunner) -> HarnessAdapter:
    """Accept either a graph dispatch adapter or a session-protocol provider."""
    if isinstance(provider, HarnessAdapter):
        return provider
    if isinstance(provider, HarnessRunner):
        return HarnessRunnerDispatchAdapter(provider)
    raise TypeError(
        "harness adapter must be a HarnessAdapter or a HarnessRunner provider; "
        f"got {type(provider).__name__}"
    )


class HarnessWaitTimedOut(TimeoutError):
    """The local wait expired; remote execution and Invocation evidence survive."""

    def __init__(self, wait: _HarnessWait) -> None:
        super().__init__(f"harness wait expired at {wait.deadline_at}; remote outcome is unknown")
        self.result_metadata = {**wait.model_dump(), "remote_outcome": "unknown"}


class _HarnessWait(BaseModel):
    """Versioned traversal continuation, never a second effect lifecycle."""

    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    harness_wait_version: int
    dispatch_invocation_id: str = Field(min_length=1)
    binding_id: str = Field(min_length=1)
    provider_name: str = Field(min_length=1)
    handle_id: str = Field(min_length=1)
    harness_type: str = Field(min_length=1)
    deadline_at: str
    observation_index: int = Field(ge=0)

    @property
    def deadline(self) -> datetime:
        return _aware_time(self.deadline_at)

    @property
    def effect_key(self) -> str:
        return f"agent.spawn_harness.poll:{self.dispatch_invocation_id}:{self.observation_index}"

    def request(self) -> dict[str, Any]:
        return {
            "operation": "poll",
            **self.model_dump(exclude={"harness_wait_version", "deadline_at"}),
        }


def _aware_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("harness observation/deadline requires an aware ISO timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.utcoffset() is None:
        raise ValueError("harness observation/deadline requires a timezone")
    return parsed.astimezone(UTC)


def _park(wait: _HarnessWait) -> None:
    pause_until(
        PAUSE_AWAITING_HARNESS,
        resume_at=min(now_utc() + timedelta(seconds=10), wait.deadline),
        metadata={**wait.model_dump(), "invocation_id": wait.dispatch_invocation_id},
    )


def _request_payload(inputs: SpawnHarnessIn) -> dict[str, Any]:
    return inputs.model_dump(mode="json", exclude={"binding_id"})


def _approval_identity(pause: Mapping[str, Any], request: Any, key: str, binding_id: str) -> None:
    if pause.get("paused_reason") != PAUSE_AWAITING_HUMAN_APPROVAL:
        return
    if (
        pause.get("binding_id") != binding_id
        or pause.get("effect_key") != key
        or pause.get("request_digest") != approval_request_digest(request)
        or not isinstance(pause.get("approval_request_id"), str)
        or not pause["approval_request_id"].strip()
    ):
        raise ValueError("harness approval continuation does not match its immutable request")


def _decode_answer_pause(stamped: Any) -> dict[str, Any]:
    """Decode the server's answered-pause wrapper without trusting answer fields."""
    if not isinstance(stamped, Mapping) or not isinstance(stamped.get("metadata"), Mapping):
        raise ValueError("invalid server-stamped harness answer pause")
    return {**stamped["metadata"], "resume_at": stamped.get("resume_at")}


def _terminal_result(value: Any, handle_id: str) -> SpawnHarnessOut:
    """Validate terminal provider evidence without coercing a foreign receipt."""
    if not isinstance(value, dict) or set(value) != {
        "handle_id",
        "success",
        "output",
        "error",
        "metadata",
    }:
        raise ValueError("invalid harness terminal observation shape")
    if value["handle_id"] != handle_id or type(value["success"]) is not bool:
        raise ValueError("harness terminal observation has a foreign handle or invalid success")
    if not isinstance(value["output"], str) or not isinstance(value["metadata"], dict):
        raise ValueError("invalid harness terminal output/metadata")
    if value["error"] is not None and not isinstance(value["error"], str):
        raise ValueError("invalid harness terminal error")
    # Reject non-JSON values, NaNs and mutable provider-owned containers before persistence.
    metadata = json.loads(json.dumps(value["metadata"], allow_nan=False))
    return SpawnHarnessOut(
        status="completed" if value["success"] else "failed",
        handle_id=handle_id,
        output=value["output"],
        error=value["error"],
        metadata=metadata,
    )


def _observation(result: HarnessResult | None, wait: _HarnessWait) -> dict[str, Any]:
    observed_at = now_utc().isoformat()
    if result is None:
        return {"state": "pending", "handle_id": wait.handle_id, "observed_at": observed_at}
    if not isinstance(result, HarnessResult):
        raise ValueError("harness poll must return HarnessResult or None")
    value = {
        "handle_id": result.handle_id,
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "metadata": result.metadata,
    }
    terminal = _terminal_result(value, wait.handle_id)
    value["metadata"] = terminal.metadata
    return {"state": "terminal", "observed_at": observed_at, "result": value}


def _validate_observation_time(invocation: Invocation, value: Any) -> datetime:
    observed = _aware_time(value)
    if invocation.started_at is None or observed < invocation.started_at:
        raise ValueError("harness observation time predates its physical Invocation")
    if invocation.finished_at is None or observed > invocation.finished_at:
        raise ValueError("harness observation time follows its canonical completion")
    return observed


def _consume_observation(invocation: Invocation, wait: _HarnessWait) -> SpawnHarnessOut:
    observation = invocation.result
    if not isinstance(observation, dict):
        raise ValueError("completed harness poll did not persist an observation")
    observed = _validate_observation_time(invocation, observation.get("observed_at"))
    state = observation.get("state")
    if state == "terminal":
        if set(observation) != {"state", "observed_at", "result"}:
            raise ValueError("invalid terminal harness observation")
        terminal = _terminal_result(observation["result"], wait.handle_id)
        if observed >= wait.deadline:
            raise HarnessWaitTimedOut(wait)
        return terminal
    _consume_pending(observation, wait)
    raise AssertionError("pause_until must raise")


def _consume_pending(observation: dict[str, Any], wait: _HarnessWait) -> None:
    if observation.get("state") != "pending" or set(observation) != {
        "state",
        "handle_id",
        "observed_at",
    }:
        raise ValueError("invalid pending harness observation")
    if observation["handle_id"] != wait.handle_id:
        raise ValueError("pending harness observation has a foreign handle")
    if now_utc() >= wait.deadline:
        raise HarnessWaitTimedOut(wait)
    _park(wait.model_copy(update={"observation_index": wait.observation_index + 1}))
    raise AssertionError("pause_until must raise")


@dataclass(frozen=True)
class _HarnessDispatchProvider:
    """Provider metadata plus the provider-specific adapter implementation."""

    name: str
    adapter: HarnessAdapter
    slot: str = "harness_runner"
    trust_tier: str = "configured"


@register_node
class AgentSpawnHarnessNode(BaseNode[SpawnHarnessIn, SpawnHarnessOut]):
    """Dispatch through Binding -> governed Invocation, then pause for the result."""

    kind: ClassVar[str] = "agent.spawn_harness"
    # Both degrade truthfully when absent: no adapters means every harness
    # request is refused as unknown, and the process-default effect context
    # registers no Bindings and therefore authorizes nothing.
    optional_authorities: ClassVar[Mapping[str, str]] = {
        "adapters": "harness_adapters",
        "effect_context": "effect_context",
    }
    kind_category: ClassVar = "wait"
    input_schema: ClassVar[type[BaseModel]] = SpawnHarnessIn
    output_schema: ClassVar[type[BaseModel]] = SpawnHarnessOut
    cost_hint: ClassVar[float] = 5.0
    replay_semantics: ClassVar[ReplaySemantics] = ReplaySemantics.EFFECT_KEY
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Agent: spawn harness"
    description: ClassVar[str] = (
        "Dispatch a task to an authorized external agent-harness provider through "
        "canonical Binding/Invocation semantics and pause until it completes."
    )
    capability: ClassVar[str] = "harness_runner"

    def __init__(
        self,
        adapters: Mapping[str, HarnessAdapter | HarnessRunner] | None = None,
        *,
        effect_context: CapabilityEffectContext | None = None,
    ) -> None:
        # Adding a harness is a Provider + Binding, not a new product (#1613):
        # a provider speaking the SPEC-208 HarnessRunner session protocol is
        # wrapped in the one bridging adapter here, so callers can pass either
        # shape. Everything then crosses the same governed Invocation seam.
        self._adapters: dict[str, HarnessAdapter] = {
            name: _as_dispatch_adapter(adapter) for name, adapter in (adapters or {}).items()
        }
        self._effects = effect_context or default_effect_context()

    def replay_effect_key(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> str:
        return replay_effect_key(
            ctx,
            "agent.spawn_harness.dispatch",
            {
                "harness_type": inputs.harness_type,
                "task": inputs.task,
                "context": inputs.context,
                "timeout_seconds": inputs.timeout_seconds,
            },
        )

    @staticmethod
    def _resume_output(resumed: Any) -> SpawnHarnessOut:
        """Retain explicitly typed legacy domain answers, with no provider side door."""
        if not isinstance(resumed, Mapping) or resumed.get("status") not in {
            "completed",
            "failed",
            "timed_out",
        }:
            raise ValueError("harness answer requires an explicit terminal status")
        handle_id = resumed.get("handle_id")
        if not isinstance(handle_id, str) or not handle_id.strip():
            raise ValueError("harness answer requires a valid handle")
        return SpawnHarnessOut.model_validate(
            {key: resumed[key] for key in SpawnHarnessOut.model_fields if key in resumed}
        )

    async def _legacy_dispatch(
        self, binding: Binding, inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> Invocation | None:
        """A completed dispatch recorded under this node's previous effect key.

        #1319 changed the key from ``agent.spawn_harness.dispatch:<harness
        type>`` to one that also carries the Run, the graph node and a digest
        of the request. That is the right identity, but it is a *different*
        identity, and the change is not free during a rollout: a deployment
        that upgrades after the adapter dispatched but before the node
        persisted its pause would compute the new key, find no Invocation
        under it, and dispatch the same external harness task a second time.
        The harness has already started work that nothing is tracking.

        So the old key is read first, and only on this Run. Returning its
        recorded result is a replay, not a second effect: the dispatch handle
        it carries is the one the harness actually issued.

        Reads are scoped to the Run, so this cannot resurrect an effect from
        some other Run that happened to use the same harness type -- which the
        old key, carrying nothing but the type, could not distinguish.
        """

        read_history = getattr(self._effects.invocations, "latest_effect", None)
        if read_history is None:
            # A composition that cannot read effect history cannot answer the
            # rollout question either. That is not a reason to refuse the
            # dispatch -- it is the pre-#1319 behaviour, unchanged.
            return None
        legacy_key = f"agent.spawn_harness.dispatch:{inputs.harness_type}"
        legacy = await read_history(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=legacy_key,
            effect_scope=legacy_key,
        )
        if not isinstance(legacy, Invocation):
            return None
        self._require_legacy_node(legacy, ctx)
        if legacy.status in {
            InvocationStatus.CREATED,
            InvocationStatus.RUNNING,
            InvocationStatus.UNKNOWN,
        }:
            raise UnsafeEffectRetry(
                "legacy harness dispatch needs canonical reconciliation before retry"
            )
        return legacy if legacy.status is InvocationStatus.COMPLETED else None

    @staticmethod
    def _require_legacy_node(invocation: Invocation, ctx: NodeContext) -> None:
        # The pre-#1319 type-only key does not name a graph node. A wildcard
        # Binding cannot establish that another NodeRun was this same logical
        # node, so neither adopting its receipt nor retrying under a new key
        # is safe. Preserve that evidence for explicit operator disposition.
        if invocation.node_run_id != ctx.node_run_id and invocation.binding.node_id != ctx.node_id:
            raise UnsafeEffectRetry("legacy harness dispatch lacks exact logical-node provenance")

    async def _dispatch(
        self,
        binding: Binding,
        inputs: SpawnHarnessIn,
        ctx: NodeContext,
        *,
        request_payload: dict[str, Any],
        resolver: Any,
        executor: Any,
    ) -> Invocation:
        """The dispatch, replayed from either effect key or newly made."""

        replayed = await self._legacy_dispatch(binding, inputs, ctx)
        if replayed is not None:
            return replayed
        # Include the logical request in the key: a changed task is explicit
        # new work, while a retry with a new NodeRun keeps the same identity.
        # The scope carries that identity into admission: the graph may retry
        # this logical node with a new NodeRun, and the stable Run/node/input
        # scope -- not the physical visit -- is what deduplicates the dispatch.
        effect_key = self.replay_effect_key(inputs, ctx)
        invocation = await invoke_capability_effect(
            lambda: self._effects.invocations.invoke(
                binding=binding,
                run_id=ctx.run_id,
                node_run_id=ctx.node_run_id,
                attempt_id=ctx.attempt_id,
                effect_key=effect_key,
                effect_scope=effect_key,
                request=request_payload,
                resolver=resolver,
                executor=executor,
            ),
            effect_key=effect_key,
            continuation_metadata={
                "harness_effect_phase": "dispatch",
                "binding_id": binding.binding_id,
            },
            request_digest=approval_request_digest(request_payload),
        )
        return invocation

    def _wait_from_dispatch(
        self, invocation: Invocation, inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> _HarnessWait:
        result = invocation.result
        if not isinstance(result, dict):
            raise RuntimeError("completed harness Invocation did not persist a dispatch result")
        started_at, original_request = self._validate_dispatch_scope(invocation, inputs, ctx)
        # Old payloads omitted default-valued fields; recover schema defaults,
        # never values from the new visit or from a redacted approval display.
        original = SpawnHarnessIn.model_validate(
            {**original_request, "binding_id": inputs.binding_id}
        )
        if _request_payload(original) != _request_payload(inputs):
            raise ValueError("harness dispatch request differs from the resumed task")
        if invocation.effect_key not in {
            self.replay_effect_key(inputs, ctx),
            f"agent.spawn_harness.dispatch:{inputs.harness_type}",
        }:
            raise ValueError("harness continuation references a non-dispatch Invocation")
        if invocation.effect_key == f"agent.spawn_harness.dispatch:{inputs.harness_type}":
            self._require_legacy_node(invocation, ctx)
        if original.timeout_seconds <= 0:
            raise ValueError("harness wait requires a positive original timeout")
        if result.get("harness_type") != original.harness_type:
            raise ValueError("harness dispatch receipt has a foreign harness type")
        handle_id = result.get("handle_id")
        if not isinstance(handle_id, str) or not handle_id.strip():
            raise ValueError("harness dispatch receipt lacks a valid handle")
        return _HarnessWait(
            harness_wait_version=1,
            observation_index=0,
            dispatch_invocation_id=invocation.invocation_id,
            binding_id=inputs.binding_id,
            provider_name=invocation.binding.provider_name,
            handle_id=handle_id,
            harness_type=result["harness_type"],
            deadline_at=(started_at + timedelta(seconds=original.timeout_seconds)).isoformat(),
        )

    def _validate_dispatch_scope(
        self, invocation: Invocation, inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> tuple[datetime, dict[str, Any]]:
        if (
            not isinstance(invocation, Invocation)
            or invocation.status is not InvocationStatus.COMPLETED
        ):
            raise ValueError("harness wait requires completed canonical dispatch evidence")
        expected = (
            ctx.run_id,
            str(ctx.workspace_id or ""),
            str(ctx.project_id or ""),
            inputs.binding_id,
        )
        actual = (
            invocation.run_id,
            invocation.workspace_id,
            invocation.project_id,
            invocation.binding.binding_id,
        )
        if actual != expected or invocation.binding.node_id not in {"", ctx.node_id}:
            raise ValueError("harness dispatch receipt belongs to another execution")
        if invocation.binding.capability != self.capability:
            raise ValueError("harness dispatch receipt has another capability")
        if invocation.started_at is None or not isinstance(invocation.request, dict):
            raise ValueError("harness dispatch is missing original timing/request evidence")
        return invocation.started_at, invocation.request

    async def _load_wait(
        self, pause: Mapping[str, Any], inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> _HarnessWait:
        wait = _HarnessWait.model_validate(
            {key: pause[key] for key in _HarnessWait.model_fields if key in pause}
        )
        if wait.harness_wait_version != 1:
            raise ValueError("unsupported harness continuation version")
        invocation = await self._effects.invocation_store.get(wait.dispatch_invocation_id)
        if invocation is None:
            raise ValueError("harness continuation has no canonical dispatch receipt")
        original = self._wait_from_dispatch(invocation, inputs, ctx)
        if wait.model_dump(exclude={"observation_index"}) != original.model_dump(
            exclude={"observation_index"}
        ):
            raise ValueError("harness continuation differs from canonical dispatch receipt")
        return wait

    async def _poll(
        self, wait: _HarnessWait, inputs: SpawnHarnessIn, ctx: NodeContext, pause: Mapping[str, Any]
    ) -> SpawnHarnessOut:
        binding = await self._resolve_binding(inputs, ctx)
        request = wait.request()
        _approval_identity(pause, request, wait.effect_key, wait.binding_id)
        latest = await self._effects.invocations.latest_effect(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=wait.effect_key,
            # The poll is a logical effect: its stable scope (the wait's own
            # poll key, derived from the dispatch Invocation id) spans NodeRuns,
            # so a graph retry resumes the same observation instead of
            # re-polling the provider (#1194).
            effect_scope=wait.effect_key,
        )
        if latest is not None:
            self._validate_poll_receipt(latest, wait, ctx)
        if latest is not None and latest.status is InvocationStatus.COMPLETED:
            return _consume_observation(latest, wait)
        if now_utc() >= wait.deadline:
            raise HarnessWaitTimedOut(wait)
        if latest is not None and latest.status in {
            InvocationStatus.CREATED,
            InvocationStatus.RUNNING,
            InvocationStatus.UNKNOWN,
        }:
            _park(wait)

        invocation = await self._invoke_poll(wait, inputs, ctx, binding)
        self._validate_poll_receipt(invocation, wait, ctx)
        return _consume_observation(invocation, wait)

    async def _poll_provider(
        self, provider: ResolvedCapabilityProvider, wait: _HarnessWait
    ) -> dict[str, Any]:
        if not isinstance(provider, _HarnessDispatchProvider):
            raise TypeError("harness poll resolved a non-harness provider")
        remaining = (wait.deadline - now_utc()).total_seconds()
        if remaining <= 0:
            raise HarnessWaitTimedOut(wait)
        async with asyncio.timeout(remaining):
            result = await provider.adapter.poll(
                HarnessHandle(handle_id=wait.handle_id, harness_type=wait.harness_type)
            )
        return _observation(result, wait)

    async def _invoke_poll(
        self, wait: _HarnessWait, inputs: SpawnHarnessIn, ctx: NodeContext, binding: Binding
    ) -> Invocation:
        async def resolve_provider(authorized: Binding) -> ResolvedCapabilityProvider | Unavailable:
            current = await self._resolve_binding(inputs, ctx)
            if current != authorized:
                return Unavailable(
                    slot=self.capability, reason="harness Binding changed before poll"
                )
            return self._provider(current, wait.provider_name)

        async def execute_provider(provider: ResolvedCapabilityProvider, _request: Any) -> Any:
            return await self._poll_provider(provider, wait)

        request = wait.request()
        try:
            return await invoke_capability_effect(
                lambda: self._effects.invocations.invoke(
                    binding=binding,
                    run_id=ctx.run_id,
                    node_run_id=ctx.node_run_id,
                    attempt_id=ctx.attempt_id,
                    effect_key=wait.effect_key,
                    effect_scope=wait.effect_key,
                    request=request,
                    resolver=resolve_provider,
                    executor=execute_provider,
                ),
                effect_key=wait.effect_key,
                continuation_metadata={**wait.model_dump(), "harness_effect_phase": "poll"},
                resume_at=wait.deadline,
                request_digest=approval_request_digest(request),
            )
        except Exception:
            # A failed physical read may leave UNKNOWN. Only canonical
            # reconciliation can authorize a retry of that same observation.
            await self._repark_ambiguous(wait, ctx, binding)
            raise

    async def _repark_ambiguous(
        self, wait: _HarnessWait, ctx: NodeContext, binding: Binding
    ) -> None:
        latest = await self._effects.invocations.latest_effect(
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            effect_key=wait.effect_key,
            effect_scope=wait.effect_key,
        )
        if latest is None or latest.status not in {
            InvocationStatus.CREATED,
            InvocationStatus.RUNNING,
            InvocationStatus.UNKNOWN,
        }:
            return
        self._validate_poll_receipt(latest, wait, ctx)
        if now_utc() >= wait.deadline:
            raise HarnessWaitTimedOut(wait) from None
        _park(wait)

    @staticmethod
    def _validate_poll_receipt(
        invocation: Invocation, wait: _HarnessWait, ctx: NodeContext
    ) -> None:
        if (
            invocation.run_id != ctx.run_id
            or invocation.workspace_id != ctx.workspace_id
            or invocation.project_id != ctx.project_id
            or invocation.binding.binding_id != wait.binding_id
            or invocation.binding.provider_name != wait.provider_name
            or invocation.effect_key != wait.effect_key
            or invocation.request != wait.request()
            or invocation.effect_scope != wait.effect_key
        ):
            raise ValueError(
                "harness observation Invocation has mismatched receipt/request evidence"
            )

    def _provider(
        self, binding: Binding, provider_name: str
    ) -> ResolvedCapabilityProvider | Unavailable:
        adapter = self._adapters.get(provider_name)
        if adapter is None or (binding.provider_name and binding.provider_name != provider_name):
            return Unavailable(
                slot=self.capability,
                reason=f"historical harness provider {provider_name!r} is unavailable or unauthorized",
            )
        return _HarnessDispatchProvider(name=provider_name, adapter=adapter)

    async def _resolve_binding(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> Binding:
        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "agent.spawn_harness requires a pre-authorized binding_id before dispatch"
            )
        return await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=self.capability,
        )

    @staticmethod
    def _resume_evidence(ctx: NodeContext) -> tuple[dict[str, Any], Any]:
        answers = (ctx.metadata or {}).get("hitl_answers") or {}
        answer = answers.get(ctx.node_id) if isinstance(answers, Mapping) else None
        if RESUMED_PAUSE_KEY in ctx.metadata:
            carried = ctx.metadata[RESUMED_PAUSE_KEY]
            if not isinstance(carried, Mapping) or not carried:
                raise ValueError("invalid server-authored harness pause")
            return resumed_pause(ctx), answer
        if isinstance(answer, Mapping) and "_pause" in answer:
            return _decode_answer_pause(answer["_pause"]), answer
        return {}, answer

    async def _resume_approval(
        self, pause: Mapping[str, Any], inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> SpawnHarnessOut | None:
        phase = pause.get("harness_effect_phase")
        if phase == "poll":
            return await self._poll(await self._load_wait(pause, inputs, ctx), inputs, ctx, pause)
        if phase != "dispatch":
            raise ValueError("harness approval lacks its server-authored effect phase")
        _approval_identity(
            pause, _request_payload(inputs), self.replay_effect_key(inputs, ctx), inputs.binding_id
        )
        return None

    async def _resume_legacy_pause(
        self, pause: Mapping[str, Any], answer: Any, inputs: SpawnHarnessIn, ctx: NodeContext
    ) -> SpawnHarnessOut:
        invocation = await self._effects.invocation_store.get(str(pause["invocation_id"]))
        if invocation is None:
            raise ValueError("legacy harness pause has no canonical dispatch receipt")
        wait = self._wait_from_dispatch(invocation, inputs, ctx)
        if (
            pause.get("handle_id") != wait.handle_id
            or pause.get("harness_type") != wait.harness_type
        ):
            raise ValueError("legacy harness pause differs from canonical dispatch receipt")
        if answer is not None:
            terminal = self._resume_output(answer)
            if terminal.handle_id != wait.handle_id:
                raise ValueError("harness terminal answer has a foreign handle")
            return terminal
        _park(wait)
        raise AssertionError("pause_until must raise")

    async def _resume(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> SpawnHarnessOut | None:
        pause, answer = self._resume_evidence(ctx)
        reason = pause.get("paused_reason")
        if reason == PAUSE_AWAITING_HUMAN_APPROVAL:
            return await self._resume_approval(pause, inputs, ctx)
        if "harness_wait_version" in pause:
            if reason != PAUSE_AWAITING_HARNESS:
                raise ValueError("harness continuation has the wrong pause reason")
            return await self._poll(await self._load_wait(pause, inputs, ctx), inputs, ctx, pause)
        if {"dispatch_invocation_id", "observation_index", "deadline_at"}.intersection(pause):
            raise ValueError("harness continuation is missing its version")
        if reason == PAUSE_AWAITING_HARNESS and "invocation_id" in pause:
            return await self._resume_legacy_pause(pause, answer, inputs, ctx)
        if answer is not None:
            if pause:
                raise ValueError("harness answer lacks canonical dispatch receipt provenance")
            return self._resume_output(answer)
        if pause:
            raise ValueError("harness continuation lacks canonical dispatch receipt provenance")
        return None

    async def _execute(self, inputs: SpawnHarnessIn, ctx: NodeContext) -> SpawnHarnessOut:
        resumed = await self._resume(inputs, ctx)
        if resumed is not None:
            return resumed
        if inputs.timeout_seconds <= 0:
            raise ValueError("harness wait requires a positive timeout before dispatch")
        binding = await self._resolve_binding(inputs, ctx)
        request_payload = _request_payload(inputs)

        async def resolve_provider(
            authorized: Binding,
        ) -> ResolvedCapabilityProvider | Unavailable:
            adapter = self._adapters.get(inputs.harness_type)
            if adapter is None:
                return Unavailable(
                    slot=self.capability,
                    reason=(
                        f"no harness provider registered for {inputs.harness_type!r}; "
                        f"available={sorted(self._adapters)}"
                    ),
                )
            if authorized.provider_name and authorized.provider_name != inputs.harness_type:
                return Unavailable(
                    slot=self.capability,
                    reason=(
                        f"Binding pins provider {authorized.provider_name!r}, not "
                        f"requested harness provider {inputs.harness_type!r}"
                    ),
                )
            return _HarnessDispatchProvider(name=inputs.harness_type, adapter=adapter)

        async def execute_provider(provider: ResolvedCapabilityProvider, request: Any) -> Any:
            if not isinstance(provider, _HarnessDispatchProvider):
                raise TypeError("harness Invocation resolved a non-harness provider")
            payload = dict(request)
            harness_request = HarnessRequest(
                harness_type=str(payload["harness_type"]),
                task=str(payload["task"]),
                context=dict(payload.get("context") or {}),
                timeout_seconds=int(payload.get("timeout_seconds") or 3600),
                # Workspace hint (issue #1613): the adapter starts the harness
                # session here; the value also lands on the persisted Invocation
                # result so the row records where the harness was pointed.
                metadata={"workdir": str(payload.get("workdir") or "")},
            )
            handle = await provider.adapter.dispatch(harness_request)
            if not handle.handle_id or not handle.harness_type:
                raise RuntimeError("harness provider returned an invalid dispatch handle")
            return {
                "handle_id": handle.handle_id,
                "harness_type": handle.harness_type,
                # Dispatch provenance (issue #1613): harness session id,
                # workspace hint, provider name. Adapter-supplied, so the
                # Invocation row records the session/workspace, not just an
                # opaque handle. A misbehaving adapter's non-dict detail is
                # dropped rather than persisted.
                **_detail_payload(handle),
            }

        invocation = await self._dispatch(
            binding,
            inputs,
            ctx,
            request_payload=request_payload,
            resolver=resolve_provider,
            executor=execute_provider,
        )
        _park(self._wait_from_dispatch(invocation, inputs, ctx))
        raise AssertionError("pause_until must raise")
