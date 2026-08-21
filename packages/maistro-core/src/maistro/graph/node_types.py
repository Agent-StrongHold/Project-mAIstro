from __future__ import annotations

import threading
from dataclasses import dataclass

from pydantic import BaseModel, ConfigDict

from maistro.graph.definitions import Node


class OpenNodeParameters(BaseModel):
    """Permissive parameter contract used until a NodeType defines a stricter schema."""

    model_config = ConfigDict(extra="allow")


def _is_valid_identifier(value: str) -> bool:
    return (
        bool(value)
        and value == value.strip()
        and not any(character.isspace() for character in value)
    )


@dataclass(frozen=True, slots=True)
class NodeTypeSpec:
    """Domain metadata required to validate and dispatch a Node definition.

    The registration contains no permission grants. Permissions remain on the
    Workspace/Persona/Graph/Node/Binding authorization chain and are evaluated
    separately at execution time.
    """

    type_id: str
    parameter_model: type[BaseModel]
    executor_strategy: str
    binding_strategy: str
    owner_package: str = "maistro-core"
    aliases: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        identifiers = (self.type_id, *self.aliases)
        if not all(_is_valid_identifier(value) for value in identifiers):
            raise ValueError("NodeType identifiers must be non-empty and contain no whitespace")
        if self.type_id in self.aliases:
            raise ValueError("NodeType cannot alias itself")
        if not self.executor_strategy:
            raise ValueError("NodeType executor_strategy is required")
        if self.binding_strategy not in {"none", "optional", "required"}:
            raise ValueError("NodeType binding_strategy must be none, optional, or required")
        if not issubclass(self.parameter_model, BaseModel):
            raise TypeError("NodeType parameter_model must be a Pydantic BaseModel type")


class NodeTypeRegistry:
    """Thread-safe registry for NodeType validation and dispatch metadata."""

    def __init__(self) -> None:
        self._types: dict[str, NodeTypeSpec] = {}
        self._aliases: dict[str, str] = {}
        self._lock = threading.RLock()

    def register(self, spec: NodeTypeSpec) -> None:
        with self._lock:
            identifiers = (spec.type_id, *spec.aliases)
            collisions = [
                identifier
                for identifier in identifiers
                if identifier in self._types or identifier in self._aliases
            ]
            if collisions:
                raise ValueError(f"NodeType identifier already registered: {collisions[0]}")

            self._types[spec.type_id] = spec
            for alias in spec.aliases:
                self._aliases[alias] = spec.type_id

    def resolve(self, type_id: str) -> NodeTypeSpec:
        with self._lock:
            canonical = self._aliases.get(type_id, type_id)
            spec = self._types.get(canonical)
        if spec is None:
            raise KeyError(f"Unknown NodeType '{type_id}'")
        return spec

    def canonical_type_id(self, type_id: str) -> str:
        return self.resolve(type_id).type_id

    def type_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(sorted(self._types))

    def aliases(self) -> dict[str, str]:
        with self._lock:
            return dict(self._aliases)

    def validate_parameters(self, type_id: str, parameters: dict[str, object]) -> BaseModel:
        spec = self.resolve(type_id)
        return spec.parameter_model.model_validate(parameters)

    def validate_node(self, node: Node) -> BaseModel:
        return self.validate_parameters(node.node_type, node.parameters)


DEFAULT_NODE_TYPES: tuple[NodeTypeSpec, ...] = (
    NodeTypeSpec(
        type_id="agent",
        parameter_model=OpenNodeParameters,
        executor_strategy="agent",
        binding_strategy="optional",
    ),
    NodeTypeSpec(
        type_id="api",
        parameter_model=OpenNodeParameters,
        executor_strategy="capability",
        binding_strategy="required",
    ),
    NodeTypeSpec(
        type_id="capability",
        aliases=("tool",),
        parameter_model=OpenNodeParameters,
        executor_strategy="capability",
        binding_strategy="required",
    ),
    NodeTypeSpec(
        type_id="harness",
        parameter_model=OpenNodeParameters,
        executor_strategy="harness",
        binding_strategy="required",
    ),
    NodeTypeSpec(
        type_id="human",
        parameter_model=OpenNodeParameters,
        executor_strategy="human",
        binding_strategy="none",
    ),
    NodeTypeSpec(
        type_id="evaluation",
        parameter_model=OpenNodeParameters,
        executor_strategy="evaluation",
        binding_strategy="optional",
    ),
    NodeTypeSpec(
        type_id="transform",
        parameter_model=OpenNodeParameters,
        executor_strategy="transform",
        binding_strategy="optional",
    ),
    NodeTypeSpec(
        type_id="control",
        aliases=("router",),
        parameter_model=OpenNodeParameters,
        executor_strategy="control",
        binding_strategy="none",
    ),
    NodeTypeSpec(
        type_id="subgraph",
        parameter_model=OpenNodeParameters,
        executor_strategy="subgraph",
        binding_strategy="none",
    ),
)


def build_default_node_type_registry() -> NodeTypeRegistry:
    registry = NodeTypeRegistry()
    for spec in DEFAULT_NODE_TYPES:
        registry.register(spec)
    return registry
