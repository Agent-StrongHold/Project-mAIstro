"""Host-owned contracts for model-requested tool execution.

A model-facing tool name is only an exposure.  The registry below owns the
schema, reversibility classification, and expected-effect callbacks; callers
cannot supply any of those values at dispatch time.  ``GovernedToolExecutor``
then uses the existing canonical Binding -> Invocation service for the actual
provider call.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol

from maistro.capabilities.binding import Binding, ResolvedCapabilityProvider
from maistro.capabilities.binding_store import BindingResolutionError
from maistro.capabilities.expected_effect import ExpectedEffectEvidence, canonical_digest
from maistro.tools.reversibility import ToolRegistration, ToolReversibility
from maistro.tools.reversibility_registry import ReversibilityRegistry

if TYPE_CHECKING:
    from maistro.capabilities.effect_context import CapabilityEffectContext


class ToolContractError(ValueError):
    """Base error for a tool request rejected before provider execution."""


class ToolNotAuthorized(ToolContractError):
    """The agent or host did not authorize the requested tool name."""


class UnknownToolSchema(ToolContractError):
    """A model-requested tool has no host-owned schema."""


class ToolArgumentError(ToolContractError):
    """Tool arguments do not satisfy the host-owned JSON schema."""


class ExpectedEffectRequired(ToolContractError):
    """A configured high-impact tool has no complete prediction contract."""


class PredictionMismatch(ToolContractError):
    """The observed provider outcome did not match the recorded prediction."""


ExpectedPostState = Callable[[dict[str, Any]], Any]
PreState = Callable[[dict[str, Any]], Any]
ObservedPostState = Callable[[Any], Any]


@dataclass(frozen=True)
class ToolContract:
    """Host-owned schema and prediction behavior for one exposed tool."""

    name: str
    schema: dict[str, Any]
    capability: str
    provider_name: str
    high_impact: bool = False
    policy_version: str = ""
    expected_post_state: ExpectedPostState | None = None
    pre_state: PreState | None = None
    observed_post_state: ObservedPostState | None = None

    def __post_init__(self) -> None:
        if not self.name.strip() or not self.capability.strip() or not self.provider_name.strip():
            raise ValueError("tool contract name, capability, and provider_name are required")
        if not isinstance(self.schema, dict) or self.schema.get("type") != "object":
            raise ValueError("tool contract schema must be an object JSON schema")
        if self.high_impact and (
            not self.policy_version.strip()
            or self.expected_post_state is None
            or self.pre_state is None
            or self.observed_post_state is None
        ):
            raise ExpectedEffectRequired(
                f"high-impact tool {self.name!r} requires policy version, pre-state, "
                "expected post-state, and observation callbacks"
            )


class ToolContractRegistry:
    """Canonical host registry for schemas and reversibility policy."""

    def __init__(self) -> None:
        self._contracts: dict[str, ToolContract] = {}
        self._reversibility = ReversibilityRegistry()

    def register(self, contract: ToolContract, registration: ToolRegistration) -> None:
        if contract.name != registration.name:
            raise ValueError("tool contract and reversibility registration names must match")
        self._reversibility.register(registration)
        self._contracts[contract.name] = contract

    def get(self, name: str) -> ToolContract | None:
        return self._contracts.get(name)

    def require(self, name: str) -> ToolContract:
        contract = self.get(name)
        if contract is None:
            raise UnknownToolSchema(f"no host-owned schema is registered for tool {name!r}")
        return contract

    def reversibility_of(self, name: str) -> ToolReversibility:
        # Unknown names do not get a caller-selected/default downgrade.
        self.require(name)
        return self._reversibility.reversibility_of(name)

    def names(self) -> frozenset[str]:
        return frozenset(self._contracts)


@dataclass(frozen=True)
class ToolInvocationContext:
    workspace_id: str
    project_id: str
    run_id: str
    node_run_id: str
    attempt_id: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.workspace_id,
                self.project_id,
                self.run_id,
                self.node_run_id,
                self.attempt_id,
            )
        ):
            raise ValueError(
                "tool Invocation context requires canonical Workspace/Project/Run/NodeRun/Attempt ids"
            )


class ToolBindingResolver(Protocol):
    async def __call__(
        self, contract: ToolContract, context: ToolInvocationContext
    ) -> Binding | None: ...


@dataclass(frozen=True)
class _ToolProvider:
    name: str
    slot: str
    trust_tier: str = "tool"


async def _resolve_provider(binding: Binding, contract: ToolContract) -> _ToolProvider:
    if binding.capability != contract.capability:
        raise ToolContractError("tool Binding capability does not match its host contract")
    if binding.provider_name and binding.provider_name != contract.provider_name:
        raise ToolContractError("tool Binding provider does not match its host contract")
    return _ToolProvider(name=contract.provider_name, slot=contract.capability)


def validate_tool_arguments(schema: Mapping[str, Any], arguments: Any, *, path: str = "$") -> None:
    """Validate the JSON-schema subset used at the model/provider boundary."""

    if not isinstance(arguments, dict):
        raise ToolArgumentError(f"{path} must be an object")
    properties = schema.get("properties", {})
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ToolArgumentError("tool schema has invalid properties/required declarations")
    missing = [name for name in required if name not in arguments]
    if missing:
        raise ToolArgumentError(f"missing required tool arguments: {', '.join(map(str, missing))}")
    if schema.get("additionalProperties") is False:
        unknown = sorted(set(arguments) - set(properties))
        if unknown:
            raise ToolArgumentError(f"unknown tool arguments: {', '.join(unknown)}")
    for name, value in arguments.items():
        if name in properties:
            _validate_schema_value(properties[name], value, f"$.{name}")


def _validate_schema_value(schema: Any, value: Any, path: str) -> None:
    if not isinstance(schema, dict):
        raise ToolArgumentError(f"{path} has no valid host-owned schema")
    if "enum" in schema and value not in schema["enum"]:
        raise ToolArgumentError(f"{path} is not one of the permitted values")
    expected = schema.get("type")
    type_ok = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }
    if expected and not type_ok.get(expected, False):
        raise ToolArgumentError(f"{path} must be a {expected}")
    if expected == "object":
        validate_tool_arguments(schema, value, path=path)
    if expected == "array" and "items" in schema:
        for index, item in enumerate(value):
            _validate_schema_value(schema["items"], item, f"{path}[{index}]")


class GovernedToolExecutor:
    """Tool adapter that admits only contract-valid calls to canonical Invocation."""

    def __init__(
        self,
        *,
        effects: CapabilityEffectContext,
        contracts: ToolContractRegistry,
        binding_for: ToolBindingResolver,
        backend: Callable[[str, dict[str, Any]], Awaitable[Any]],
    ) -> None:
        self._effects = effects
        self._contracts = contracts
        self._binding_for = binding_for
        self._backend = backend

    async def _authorized_binding(
        self, contract: ToolContract, binding: Binding, context: ToolInvocationContext
    ) -> Binding:
        if binding.workspace_id != context.workspace_id or binding.project_id != context.project_id:
            raise ToolNotAuthorized(
                "tool Binding scope does not match the canonical execution context"
            )
        try:
            return await self._effects.bindings.resolve(
                binding.binding_id,
                workspace_id=context.workspace_id,
                project_id=context.project_id,
                node_id=binding.node_id or context.node_run_id,
                capability=contract.capability,
            )
        except (BindingResolutionError, KeyError, ValueError) as exc:
            raise ToolNotAuthorized(
                "tool Binding is not registered in the canonical store"
            ) from exc

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        context: ToolInvocationContext,
        authorized_tools: frozenset[str] | set[str] | tuple[str, ...],
    ) -> Any:
        if tool_name not in authorized_tools:
            raise ToolNotAuthorized(f"tool {tool_name!r} is outside the Agent effective allowlist")
        contract = self._contracts.require(tool_name)
        validate_tool_arguments(contract.schema, arguments)
        binding = await self._binding_for(contract, context)
        if binding is None:
            raise ToolNotAuthorized(f"no authorized Binding exists for tool {tool_name!r}")
        binding = await self._authorized_binding(contract, binding, context)

        pre_state = contract.pre_state(arguments) if contract.pre_state is not None else None
        expected = (
            contract.expected_post_state(arguments)
            if contract.expected_post_state is not None
            else None
        )
        reversibility = self._contracts.reversibility_of(tool_name)
        request = {
            "_tool_name": tool_name,
            "_tool_reversibility": reversibility.value,
            "arguments": arguments,
        }

        async def resolver(_binding: Binding) -> ResolvedCapabilityProvider:
            return await _resolve_provider(_binding, contract)

        async def execute_provider(_provider: ResolvedCapabilityProvider, _request: Any) -> Any:
            return await self._backend(tool_name, arguments)

        # A high-impact contract is persisted before dispatch, including the
        # exact arguments and pre-state digest. The Invocation id/provider are
        # filled by the canonical lifecycle service once its Binding resolves.
        expected_evidence = None
        if contract.high_impact:
            expected_evidence = ExpectedEffectEvidence(
                capability=contract.capability,
                provider=contract.provider_name,
                materialized_arguments=arguments,
                pre_state_digest=canonical_digest(pre_state),
                expected_post_state=expected,
                policy_version=contract.policy_version,
            )
        invocation = await self._effects.invocations.invoke(
            binding=binding,
            run_id=context.run_id,
            node_run_id=context.node_run_id,
            attempt_id=context.attempt_id,
            effect_key=f"tool:{tool_name}:{canonical_digest(arguments)}",
            request=request,
            resolver=resolver,
            executor=execute_provider,
            expected_effect=expected_evidence,
        )
        if contract.high_impact and contract.observed_post_state is not None:
            observed = contract.observed_post_state(invocation.result)
            was_observed = (
                invocation.expected_effect is not None
                and invocation.expected_effect.matched is not None
            )
            settled = await self._effects.invocations.record_expected_effect_observation(
                invocation.invocation_id, observed
            )
            if (
                not was_observed
                and settled.expected_effect is not None
                and settled.expected_effect.matched is False
            ):
                await self._effects.event_store.append(
                    self._effects.invocations.expected_effect_mismatch_event(
                        settled, tool_name=tool_name
                    )
                )
            if settled.expected_effect is not None and settled.expected_effect.matched is False:
                raise PredictionMismatch(f"expected effect mismatch for tool {tool_name!r}")
            invocation = settled
        return invocation.result


__all__ = [
    "ExpectedEffectEvidence",
    "ExpectedEffectRequired",
    "GovernedToolExecutor",
    "PredictionMismatch",
    "ToolArgumentError",
    "ToolBindingResolver",
    "ToolContract",
    "ToolContractError",
    "ToolContractRegistry",
    "ToolInvocationContext",
    "ToolNotAuthorized",
    "UnknownToolSchema",
    "validate_tool_arguments",
]
