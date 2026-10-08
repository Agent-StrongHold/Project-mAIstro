"""Canonical execution of third-party tools (M9-E3, issue #964).

Every extension tool call crosses the accepted
``Capability -> Provider -> Binding -> Invocation`` seam
(ADR-081226-6b46): the call is resolved against an authorized Binding,
admitted by policy, dispatched to the extension handler as the provider, and
recorded as one attributable :class:`~maistro.capabilities.invocation.Invocation`.
There is deliberately no second dispatch path — a built-in tool and an
extension tool are the same governed shape (:mod:`.conformance` holds them to
the same suite).

What the seam produces is canonical and attributable:

* **Results** are :class:`ExtensionToolOutcome` values whose ``status`` is the
  canonical :class:`~maistro.capabilities.invocation.InvocationStatus` — the
  one work-state vocabulary this seam reports, exactly as the Invocation
  ledger recorded it — plus the ``Run -> NodeRun -> Attempt`` correlation the
  call ran under.
* **Errors** are typed and machine-readable (``error_code``), mapped from the
  canonical failure families: policy denial, approval required, capability
  unavailable, provider exception. All of them surface as
  ``InvocationStatus.FAILED`` with the family named in ``error_code`` —
  refused-before-dispatch calls (denial, approval, unavailable) never created
  an Invocation, and that distinction lives in ``error_code``, not in a
  second status vocabulary.
* **Cancellation** (``asyncio.CancelledError``, deadline expiry included via
  :func:`asyncio.wait_for`) surfaces as ``InvocationStatus.UNKNOWN`` with the
  Invocation the cancellation interrupted — mirroring the row the Invocation
  service itself already terminalized as ``UNKNOWN`` — with the interruption
  family named in ``error_code`` (``cancelled`` / ``deadline_exceeded``).

The host re-validates the extension's per-call effect claim against the
contract floor (:func:`validate_effect_claim`) before dispatch, so the
classification the effect ran under is always a host fact.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.effect_context import CapabilityEffectContext
from maistro.capabilities.governed_invocation import (
    InvocationApprovalRequired,
    InvocationDenied,
)
from maistro.capabilities.invocation import (
    CapabilityUnavailable,
    Invocation,
    InvocationStatus,
)
from maistro.extensions.tool_skill.contracts import (
    EffectClass,
    EffectDowngradeRefused,
    validate_effect_claim,
)
from maistro.extensions.tool_skill.registration import (
    TOOL_CAPABILITY_PREFIX,
    RegisteredExtensionTool,
    ToolAccessPolicy,
    ToolNotAllowlisted,
)


class UnknownToolError(LookupError):
    """A call named a tool no package registered."""


#: Error codes the canonical mapping produces. Machine-readable so callers
#: (and the model) branch without parsing prose. These — not a second status
#: enum — are how the refusal and interruption families stay distinguishable
#: from an ordinary failed dispatch: the outcome's ``status`` is always the
#: canonical Invocation vocabulary, so ``FAILED`` + ``policy_denied`` reads
#: "refused by policy, nothing dispatched" and ``UNKNOWN`` + ``cancelled``
#: reads "interrupted mid-flight, remote outcome unknown".
ERROR_CODE_DENIAL = "policy_denied"
ERROR_CODE_APPROVAL = "approval_required"
ERROR_CODE_UNAVAILABLE = "capability_unavailable"
ERROR_CODE_DOWNGRADE_REFUSED = "effect_downgrade_refused"
ERROR_CODE_TIMEOUT = "deadline_exceeded"
ERROR_CODE_CANCELLED = "cancelled"
ERROR_CODE_HANDLER_ERROR = "handler_error"
ERROR_CODE_UNKNOWN = "unknown_outcome"


@dataclass(frozen=True)
class ExtensionToolOutcome:
    """The canonical, attributable result of one extension tool call."""

    status: InvocationStatus
    tool_id: str
    run_id: str
    node_run_id: str
    attempt_id: str
    invocation: Invocation | None = None
    result: Any = None
    error_code: str = ""
    error: str = ""
    approval_request_id: str = ""
    effect: EffectClass | None = None

    @property
    def success(self) -> bool:
        """Whether the call completed with a usable result."""
        return self.status is InvocationStatus.COMPLETED

    @property
    def invocation_id(self) -> str:
        """The Invocation that records this call, when one was created."""
        return self.invocation.invocation_id if self.invocation is not None else ""


class ExtensionToolRunner:
    """Name-based entry the model-facing governed tool surface calls.

    Resolves a registered third-party tool by its canonical id and dispatches
    one governed call (AC: out-of-tree packages register without core edits —
    the surface needs the catalog, not per-tool code). An unknown id is a
    typed lookup failure before any Binding is resolved or policy consulted.

    The runner is constructed with the caller's :class:`ToolAccessPolicy` and
    enforces it on every lookup: exposure hiding a tool is not the boundary —
    a caller or model that names an excluded id directly is refused here,
    before any Binding is resolved or handler dispatched (AC: tool access is
    constrained by Agent/Workspace allowlists).
    """

    def __init__(
        self,
        effects: CapabilityEffectContext,
        catalog: Any,
        *,
        access: ToolAccessPolicy,
    ) -> None:
        self._effects = effects
        self._catalog = catalog
        self._access = access

    async def invoke(
        self,
        tool_id: str,
        binding: Binding,
        arguments: Mapping[str, Any],
        *,
        run_id: str,
        node_run_id: str,
        attempt_id: str,
        actor_id: str = "",
        timeout_s: float | None = None,
        effect_claim: EffectClass | None = None,
    ) -> ExtensionToolOutcome:
        """Resolve ``tool_id`` in the catalog and run it governed."""
        tool = self._catalog.get(tool_id)
        if tool is None:
            raise UnknownToolError(f"no third-party tool registered as {tool_id!r}")
        if not self._access.allows(tool.tool_id):
            # The allowlist is the boundary, not the exposure list: a known
            # id named directly is refused before any Binding is resolved.
            raise ToolNotAllowlisted(
                f"{tool.tool_id!r} is not admitted by the Agent/Workspace tool allowlist"
            )
        return await invoke_extension_tool(
            self._effects,
            tool,
            binding,
            arguments,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            actor_id=actor_id,
            timeout_s=timeout_s,
            effect_claim=effect_claim,
        )


def effect_key_for(tool_id: str, arguments: Mapping[str, Any]) -> str:
    """The stable logical-effect key for one tool call.

    Same tool + same arguments = same logical effect, so the Invocation
    ledger's admission guard can dedup/unsafe-retry across retries of the
    same NodeRun exactly as it does for built-in capability effects.
    """
    digest = hashlib.sha256(
        json.dumps(dict(arguments), sort_keys=True, default=str).encode()
    ).hexdigest()[:16]
    return f"{TOOL_CAPABILITY_PREFIX}:{tool_id}:{digest}"


def _resolve_handler_provider(tool: RegisteredExtensionTool) -> Any:
    """The resolver-side provider: the registered handler itself.

    Exposes the ``ResolvedCapabilityProvider`` metadata surface (name, slot,
    trust_tier) so the canonical Invocation snapshot can record the decision
    without knowing anything extension-specific about the object.
    """

    class HandlerProvider:
        @property
        def name(self) -> str:
            return tool.tool_id

        @property
        def slot(self) -> str:
            return tool.capability

        @property
        def trust_tier(self) -> str:
            return "extension"

    return HandlerProvider()


async def _dispatch_handler(
    tool: RegisteredExtensionTool,
    arguments: Mapping[str, Any],
    *,
    timeout_s: float | None,
) -> Any:
    """Dispatch one handler call, sync or async, under the host deadline.

    Cancellation mechanics (timeout included) are enforced here at the
    dispatch boundary; a deadline expiry propagates as ``CancelledError``
    so the canonical cancellation mapping runs for both cases.
    """
    handler = tool.handler
    if asyncio.iscoroutinefunction(handler):
        coro = handler(**dict(arguments))
    else:
        coro = asyncio.to_thread(handler, **dict(arguments))
    if timeout_s is not None:
        return await asyncio.wait_for(coro, timeout=timeout_s)
    return await coro


def _dispatch_pair(
    tool: RegisteredExtensionTool,
    effects: CapabilityEffectContext,
    arguments: Mapping[str, Any],
    timeout_s: float | None,
) -> tuple[Any, Any]:
    """Build the (resolver, executor) pair one governed dispatch uses.

    Secret material follows the canonical authority: only a handler that
    declares the ``credential_provider`` surface is routed through the
    credential pool (references on the Binding, values resolved just in time
    and never persisted). Everything else dispatches without credentials — an
    extension cannot obtain secret material by omitting the declaration.
    """
    routing = effects.credential_routing()
    provider = _resolve_handler_provider(tool)

    async def resolve(_binding: Binding) -> Any:
        return provider

    async def execute(_provider: Any, _request: Any) -> Any:
        return await _dispatch_handler(tool, arguments, timeout_s=timeout_s)

    if getattr(tool.handler, "credential_provider", ""):
        return routing.resolver(resolve), routing.executor(execute)
    return resolve, execute


async def invoke_extension_tool(
    effects: CapabilityEffectContext,
    tool: RegisteredExtensionTool,
    binding: Binding,
    arguments: Mapping[str, Any],
    *,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    actor_id: str = "",
    timeout_s: float | None = None,
    effect_claim: EffectClass | None = None,
    logical_effect: bool = False,
) -> ExtensionToolOutcome:
    """Run one third-party tool call through the canonical effect seam.

    The Binding must be the canonical ``extension.tool:*`` Binding for this
    tool (``tool_binding``). Policy sees it before dispatch; the Invocation
    ledger sees it after; nothing in between bypasses either.
    """
    if binding.capability != tool.capability:
        raise ValueError(
            f"binding capability {binding.capability!r} does not match tool {tool.tool_id!r}"
        )
    effect: EffectClass | None
    try:
        # Host validation of the per-call claim: a downgrade below the floor
        # is refused before anything is dispatched or admitted.
        effect = (
            validate_effect_claim(tool.contract, effect_claim) if effect_claim is not None else None
        )
    except EffectDowngradeRefused as exc:
        return ExtensionToolOutcome(
            status=InvocationStatus.FAILED,
            tool_id=tool.tool_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            error_code=ERROR_CODE_DOWNGRADE_REFUSED,
            error=str(exc),
            effect=tool.contract.effect_floor,
        )

    resolver, executor = _dispatch_pair(tool, effects, arguments, timeout_s)

    try:
        invocation = await effects.invocations.invoke(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            effect_key=effect_key_for(tool.tool_id, arguments),
            request=dict(arguments),
            resolver=resolver,
            executor=executor,
            actor_id=actor_id,
            logical_effect=logical_effect,
        )
    except (InvocationDenied, InvocationApprovalRequired, CapabilityUnavailable) as exc:
        return _refusal_outcome(
            tool,
            exc,
            effect=effect,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
        )
    except TimeoutError as exc:
        # Host deadline expiry: the dispatch was cancelled mid-flight, the
        # remote outcome is unknown (the Invocation service has already
        # recorded UNKNOWN), and the disposition is the canonical cancelled
        # family — attributable, never a clean failure.
        raise ExtensionToolCancellation(
            await _cancellation_outcome(
                effects,
                tool,
                binding,
                arguments,
                effect=effect,
                run_id=run_id,
                node_run_id=node_run_id,
                attempt_id=attempt_id,
                logical_effect=logical_effect,
                error_code=ERROR_CODE_TIMEOUT,
                error=f"tool invocation exceeded the {timeout_s}s deadline",
            )
        ) from exc
    except asyncio.CancelledError as exc:
        # The Invocation service has already terminalized the interrupted
        # call as UNKNOWN with the cancellation named. Attach the canonical
        # attributable outcome to the in-flight cancellation and re-raise the
        # SAME error: cancellation belongs to the caller's execution model,
        # and swallowing it here is how cancellation bugs hide. Callers that
        # want the disposition read ``exc.outcome``.
        exc.outcome = await _cancellation_outcome(  # type: ignore[attr-defined]
            effects,
            tool,
            binding,
            arguments,
            effect=effect,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            logical_effect=logical_effect,
            error_code=ERROR_CODE_CANCELLED,
            error="tool invocation cancelled",
        )
        raise
    except Exception as exc:
        # A provider exception is recorded UNKNOWN by the Invocation service
        # (the remote effect may have landed); the caller's disposition is a
        # FAILED outcome with the typed handler-error code — attributable to
        # the UNKNOWN Invocation row, never laundered into a clean failure.
        interrupted = await _latest_invocation(
            effects,
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            effect_key=effect_key_for(tool.tool_id, arguments),
            logical_effect=logical_effect,
        )
        return ExtensionToolOutcome(
            status=InvocationStatus.FAILED,
            tool_id=tool.tool_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            invocation=interrupted,
            error_code=ERROR_CODE_HANDLER_ERROR,
            error=str(exc) or type(exc).__name__,
            effect=effect or tool.contract.effect_floor,
        )

    return _completed_outcome(
        tool,
        invocation,
        effect=effect,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
    )


class ExtensionToolCancellation(asyncio.CancelledError):
    """A cancelled tool call carrying its canonical attributable outcome.

    Subclasses :class:`asyncio.CancelledError` so ordinary cancellation
    handling (task teardown, deadline accounting, ``except CancelledError``)
    keeps working unchanged; the canonical disposition rides along on
    ``exc.outcome`` for callers that attribute it.
    """

    def __init__(self, outcome: ExtensionToolOutcome) -> None:
        super().__init__(outcome.error or "tool invocation cancelled")
        self.outcome = outcome


def _refusal_outcome(
    tool: RegisteredExtensionTool,
    exc: Exception,
    *,
    effect: EffectClass | None,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
) -> ExtensionToolOutcome:
    """Map the canonical refusal family onto attributable outcomes.

    Denial and approval gating are policy facts; capability unavailability is
    a provider fact. All three refuse execution without an external effect,
    so all three carry the classification the decision ran on and the
    execution scope it ran in. None of them created an Invocation — the
    family is typed by ``error_code`` on a ``FAILED`` status, never by a
    second status vocabulary.
    """
    if isinstance(exc, InvocationDenied):
        return ExtensionToolOutcome(
            status=InvocationStatus.FAILED,
            tool_id=tool.tool_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            error_code=ERROR_CODE_DENIAL,
            error=str(exc) or "tool invocation denied by policy",
            effect=effect or tool.contract.effect_floor,
        )
    if isinstance(exc, InvocationApprovalRequired):
        return ExtensionToolOutcome(
            status=InvocationStatus.FAILED,
            tool_id=tool.tool_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            error_code=ERROR_CODE_APPROVAL,
            error=str(exc) or "tool invocation requires approval",
            approval_request_id=getattr(exc, "request_id", ""),
            effect=effect or tool.contract.effect_floor,
        )
    return ExtensionToolOutcome(
        status=InvocationStatus.FAILED,
        tool_id=tool.tool_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        error_code=ERROR_CODE_UNAVAILABLE,
        error=str(exc),
        effect=effect or tool.contract.effect_floor,
    )


async def _cancellation_outcome(
    effects: CapabilityEffectContext,
    tool: RegisteredExtensionTool,
    binding: Binding,
    arguments: Mapping[str, Any],
    *,
    effect: EffectClass | None,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
    logical_effect: bool,
    error_code: str,
    error: str,
) -> ExtensionToolOutcome:
    """Build the canonical interruption outcome for a cancelled dispatch.

    Attribution is best-effort on the cancel path: the Invocation service has
    already terminalized the call (UNKNOWN, cancellation named); re-reading
    the ledger must never mask the cancellation itself. The outcome status
    mirrors that row (``UNKNOWN``) and the interruption family is typed by
    ``error_code``.
    """
    interrupted = await _latest_invocation(
        effects,
        binding=binding,
        run_id=run_id,
        node_run_id=node_run_id,
        effect_key=effect_key_for(tool.tool_id, arguments),
        logical_effect=logical_effect,
    )
    return ExtensionToolOutcome(
        status=InvocationStatus.UNKNOWN,
        tool_id=tool.tool_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        invocation=interrupted,
        error_code=error_code,
        error=error,
        effect=effect or tool.contract.effect_floor,
    )


def _completed_outcome(
    tool: RegisteredExtensionTool,
    invocation: Invocation,
    *,
    effect: EffectClass | None,
    run_id: str,
    node_run_id: str,
    attempt_id: str,
) -> ExtensionToolOutcome:
    """Interpret one terminal Invocation into the canonical outcome."""
    if invocation.status is not InvocationStatus.COMPLETED:
        # Only a prior FAILED record is dispatchable, and replays return
        # COMPLETED; anything else reaching here is a ledger state the
        # caller must reconcile explicitly.
        return ExtensionToolOutcome(
            status=invocation.status,
            tool_id=tool.tool_id,
            run_id=run_id,
            node_run_id=node_run_id,
            attempt_id=attempt_id,
            invocation=invocation,
            error_code=ERROR_CODE_UNKNOWN,
            error=invocation.error or f"invocation {invocation.status.value}",
            effect=effect or tool.contract.effect_floor,
        )
    return ExtensionToolOutcome(
        status=InvocationStatus.COMPLETED,
        tool_id=tool.tool_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
        invocation=invocation,
        result=invocation.result,
        effect=effect or tool.contract.effect_floor,
    )


async def _latest_invocation(
    effects: CapabilityEffectContext,
    *,
    binding: Binding,
    run_id: str,
    node_run_id: str,
    effect_key: str,
    logical_effect: bool,
) -> Invocation | None:
    try:
        return await effects.invocations.latest_effect(
            binding=binding,
            run_id=run_id,
            node_run_id=node_run_id,
            effect_key=effect_key,
            logical_effect=logical_effect,
        )
    except Exception:
        return None
