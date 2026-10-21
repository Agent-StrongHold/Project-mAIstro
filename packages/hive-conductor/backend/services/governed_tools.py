"""Hive production wiring for governed tool execution (#57).

This module is the shipped constructor for maistro-core's
:class:`~maistro.tools.contracts.GovernedToolExecutor`. The boot Agent tool
seam and the chat web tools execute through it, so every shipped hive tool
effect crosses the canonical Binding -> Invocation boundary with host-owned
contracts: the JSON schema, the effective tool allowlist, and the ADR-050
reversibility tier are resolved from this module's registry -- never from
model arguments, strategy callbacks, or caller strings.

The raw effect implementations stay in ``services.tool_executor`` and run
only as the provider backends beneath a canonical Invocation recorded here
(the same arrangement ``execute_model_chat`` has for model egress, #56).

Fail-closed rules this seam keeps:

- No live canonical Run/NodeRun/Attempt (from the execution-correlation
  context) means refusal, not a fallback to a raw effect with no identity.
- An unknown tool name or a schema violation is refused before the backend.
- The workspace-scoped tool Binding is registered through
  ``register_boot_binding`` and re-resolved on every call, so revocation
  or a redefinition cannot be outlived by a stored executor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from maistro.capabilities.binding import Binding
from maistro.capabilities.binding_store import register_boot_binding
from maistro.capabilities.invocation import EffectNotApplied
from maistro.observability.correlation import current_execution_context
from maistro.runs.store import RunIntegrityError
from maistro.tools.contracts import (
    GovernedToolExecutor,
    ToolContract,
    ToolContractError,
    ToolContractRegistry,
    ToolInvocationContext,
    ToolRegistration,
    ToolReversibility,
    validate_tool_arguments,
)

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext

#: One capability slot for hive's whole model-facing tool surface. The tools
#: share it because admission (allowlist + schema + tier) is per *tool name*
#: at this seam, not per capability string.
HIVE_TOOL_CAPABILITY = "hive.tool"

# Host-owned argument schemas. The model sees descriptions in its tool
# definitions; these are the validation truth the executor enforces, so a
# drifted or extra argument is a refusal rather than silently passed through.
_WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "max_results": {"type": "integer"},
    },
    "required": ["query"],
    "additionalProperties": False,
}
_BROWSE_URL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "url": {"type": "string"},
        "task": {"type": "string"},
    },
    "required": ["url"],
    "additionalProperties": False,
}
_CLARIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string"}},
        "context": {"type": "object"},
    },
    "required": ["questions"],
    "additionalProperties": False,
}


def _contract(
    name: str, schema: dict[str, Any], *, high_impact: bool = False
) -> tuple[ToolContract, ToolRegistration]:
    """One host-owned contract plus its ADR-050 reversibility registration.

    All three hive tools are read-only or model-backed with no externally
    observable state change, so they carry ``internal``: free retry, no
    approval floor -- the same shipped semantics the legacy path's
    ``network`` effect class had. A future mutating hive tool must register
    its real tier (and, when high-impact, its prediction contract) here
    instead of widening this entry.
    """
    contract = ToolContract(
        name=name,
        schema=schema,
        capability=HIVE_TOOL_CAPABILITY,
        provider_name=f"hive.{name}",
        high_impact=high_impact,
    )
    registration = ToolRegistration(name=name, reversibility=ToolReversibility.INTERNAL)
    return contract, registration


def hive_tool_contracts() -> ToolContractRegistry:
    """Build the host-owned hive tool registry (fresh, for composition/tests)."""
    registry = ToolContractRegistry()
    for contract, registration in (
        _contract("web_search", _WEB_SEARCH_SCHEMA),
        _contract("browse_url", _BROWSE_URL_SCHEMA),
        _contract("clarify", _CLARIFY_SCHEMA),
    ):
        registry.register(contract, registration)
    return registry


_REGISTRY: ToolContractRegistry | None = None


def _registry() -> ToolContractRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = hive_tool_contracts()
    return _REGISTRY


def validate_hive_tool_arguments(name: str, arguments: dict[str, Any]) -> None:
    """Validate materialized legacy inputs with the same host-owned schemas.

    This is argument validation only: callers still need canonical Invocation
    admission. Legacy adapters run this pure stage before *any* batch effects,
    so refusal proves EffectNotApplied to their existing Invocation rather
    than leaving an unknown external outcome. Backend exceptions are not
    caught here and retain the canonical conservative settlement semantics.
    """
    try:
        validate_tool_arguments(_registry().require(name).schema, arguments)
    except ToolContractError as exc:
        raise EffectNotApplied(str(exc)) from exc


def hive_tool_reversibility(name: str) -> ToolReversibility:
    """Resolve legacy admission from the same host registry as Agent/chat tools.

    A raw dispatcher entry is not a contract: unregistered names must fail
    closed instead of acquiring a tier (and authority) from node metadata.
    """
    return _registry().reversibility_of(name)


def hive_tool_names() -> frozenset[str]:
    """The host-owned exposure: the only names this seam will admit."""
    return _registry().names()


def _live_container() -> Any:
    """The live core Container, or a fail-closed error when absent."""
    from services.engine import get_engine

    container = getattr(get_engine().agent_port, "container", None)
    if container is None:
        raise RuntimeError("governed hive tools require the maistro-core Container")
    return container


async def live_tool_context(container: Any) -> ToolInvocationContext:
    """Resolve the canonical execution identity for one tool effect.

    Reads the live execution-correlation context and re-reads the Run from
    the store (the pattern ``AdmittedModelCalls`` uses): the Invocation must
    correlate to records that exist and belong together, and the workspace /
    project scope comes from the Run record, not from caller strings.
    """
    live = current_execution_context()
    run_id, node_run_id, attempt_id = live.run_id, live.node_run_id, live.attempt_id
    if not (run_id.strip() and node_run_id.strip() and attempt_id.strip()):
        raise RunIntegrityError("hive tool effects require the live Run/NodeRun/Attempt")
    run = await container.run_store.get_run(run_id)
    node = await container.run_store.get_node_run(node_run_id)
    attempt = await container.run_store.get_attempt(attempt_id)
    if run is None or node is None or attempt is None:
        raise RunIntegrityError("hive tool execution records do not exist")
    if node.run_id != run.run_id or attempt.node_run_id != node.node_run_id:
        raise RunIntegrityError("hive tool execution records belong to different executions")
    workspace_id = live.workspace_id.strip() or run.workspace_id
    project_id = live.project_id.strip() or run.project_id
    if not (workspace_id.strip() and project_id.strip()):
        raise RunIntegrityError("hive tool effects require a Workspace/Project scope")
    return ToolInvocationContext(
        workspace_id=workspace_id,
        project_id=project_id,
        run_id=run_id,
        node_run_id=node_run_id,
        attempt_id=attempt_id,
    )


async def _hive_tool_binding(
    effects: CapabilityEffectContext, context: ToolInvocationContext
) -> Binding:
    """Register/reuse the immutable workspace-scoped hive tool Binding."""
    binding = Binding(
        workspace_id=context.workspace_id,
        project_id=context.project_id,
        binding_id=f"hive-tool:{context.workspace_id}:{context.project_id}",
        capability=HIVE_TOOL_CAPABILITY,
    )
    try:
        return await register_boot_binding(effects.bindings, binding)
    except ValueError:
        # Two first users can both observe no record before one wins put();
        # re-read once through the canonical helper (the legacy tool seam's
        # reconciliation pattern). A real redefinition still refuses.
        return await register_boot_binding(effects.bindings, binding)


async def _hive_tool_backend(
    name: str, arguments: dict[str, Any], *, model_call: Any = None
) -> Any:
    """Execute the shipped raw hive tool dispatcher as the provider backend.

    Late-bound through the module attribute so a test (or a future host
    override) that patches ``services.tool_executor`` replaces the backend
    without touching the admission path above it. Delegating to the one
    shipped dispatcher -- rather than re-listing its raw implementations
    here -- keeps the module-egress census honest: ``clarify`` is a
    model-backed wrapper, so calling it from this module would make
    ``services.governed_tools`` a new direct model-egress caller of the kind
    ``check-model-egress.py`` freezes against the trusted base. Beneath this
    seam the model-backed sub-effect still flows only through the caller's
    admitted ``model_call`` (the #55 model seam), never through egress of
    this module's own.
    """
    from services import tool_executor

    return await tool_executor.dispatch_tool(name, arguments, model_call=model_call)


def _governed_executor(
    effects: CapabilityEffectContext, *, model_call: Any = None
) -> GovernedToolExecutor:
    async def binding_for(_contract: ToolContract, context: ToolInvocationContext) -> Binding:
        return await _hive_tool_binding(effects, context)

    async def backend(name: str, arguments: dict[str, Any]) -> Any:
        return await _hive_tool_backend(name, arguments, model_call=model_call)

    return GovernedToolExecutor(
        effects=effects,
        contracts=_registry(),
        binding_for=binding_for,
        backend=backend,
    )


async def governed_hive_tool(
    name: str,
    arguments: dict[str, Any],
    *,
    model_call: Any = None,
    container: Any = None,
    authorized_tools: frozenset[str] | None = None,
    effect_scope: str = "",
) -> Any:
    """Execute one hive tool effect at the canonical governed boundary.

    ``authorized_tools`` defaults to the host-owned exposure; callers may
    narrow it (the boot Agent's effective allowlist) but never widen it past
    the registry. ``effect_scope`` carries the caller's logical tool-call
    identity so two logical calls with identical arguments inside one
    Attempt stay distinct while a retry of the same call replays.
    """
    if container is None:
        container = _live_container()
    effects: CapabilityEffectContext = container.capability_effects
    context = await live_tool_context(container)
    exposure = hive_tool_names()
    allowlist = exposure if authorized_tools is None else frozenset(authorized_tools) & exposure
    executor = _governed_executor(effects, model_call=model_call)
    return await executor.execute(
        name, arguments, context=context, authorized_tools=allowlist, effect_scope=effect_scope
    )


async def governed_web_search(
    query: str, max_results: int = 5, *, model_call: Any = None, container: Any = None
) -> dict[str, Any]:
    """Chat/boot entry point for one governed web search."""
    return await governed_hive_tool(
        "web_search",
        {"query": query, "max_results": max_results},
        model_call=model_call,
        container=container,
    )


async def governed_browse_url(
    url: str, task: str = "Extract key facts and quotes", *, container: Any = None
) -> dict[str, Any]:
    """Chat/boot entry point for one governed URL fetch."""
    return await governed_hive_tool(
        "browse_url",
        {"url": url, "task": task},
        container=container,
    )


__all__ = [
    "HIVE_TOOL_CAPABILITY",
    "governed_browse_url",
    "governed_hive_tool",
    "governed_web_search",
    "hive_tool_contracts",
    "hive_tool_names",
    "live_tool_context",
]
