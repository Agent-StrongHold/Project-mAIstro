from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from maistro.graph.definitions import Node
from maistro.graph.node_types import (
    NodeTypeRegistry,
    NodeTypeSpec,
    build_default_node_type_registry,
)


class SearchParameters(BaseModel):
    query: str
    limit: int = 5


def test_default_registry_supports_canonical_types_and_compatibility_aliases() -> None:
    registry = build_default_node_type_registry()

    assert set(registry.type_ids()) == {
        "agent",
        "api",
        "capability",
        "harness",
        "human",
        "evaluation",
        "transform",
        "control",
        "subgraph",
    }
    assert registry.canonical_type_id("tool") == "capability"
    assert registry.canonical_type_id("router") == "control"
    assert registry.resolve("api").executor_strategy == "capability"
    assert registry.resolve("api").binding_strategy == "required"


def test_package_specific_type_can_register_strict_parameter_contract() -> None:
    registry = build_default_node_type_registry()
    registry.register(
        NodeTypeSpec(
            type_id="search.query",
            parameter_model=SearchParameters,
            executor_strategy="capability",
            binding_strategy="required",
            owner_package="maistro-design",
        )
    )

    validated = registry.validate_node(
        Node(
            node_id="search",
            node_type="search.query",
            parameters={"query": "workspace architecture", "limit": 10},
        )
    )

    assert isinstance(validated, SearchParameters)
    assert validated.query == "workspace architecture"
    assert validated.limit == 10

    with pytest.raises(ValidationError):
        registry.validate_parameters("search.query", {"limit": 1})


def test_duplicate_type_or_alias_registration_is_rejected() -> None:
    registry = NodeTypeRegistry()
    registry.register(
        NodeTypeSpec(
            type_id="capability",
            aliases=("tool",),
            parameter_model=SearchParameters,
            executor_strategy="capability",
            binding_strategy="required",
        )
    )

    with pytest.raises(ValueError, match="already registered"):
        registry.register(
            NodeTypeSpec(
                type_id="tool",
                parameter_model=SearchParameters,
                executor_strategy="other",
                binding_strategy="none",
            )
        )


def test_default_registry_instances_are_independent_for_package_extensions() -> None:
    first = build_default_node_type_registry()
    second = build_default_node_type_registry()
    first.register(
        NodeTypeSpec(
            type_id="custom.node",
            parameter_model=SearchParameters,
            executor_strategy="custom",
            binding_strategy="optional",
        )
    )

    assert first.resolve("custom.node").type_id == "custom.node"
    with pytest.raises(KeyError, match="Unknown NodeType"):
        second.resolve("custom.node")


def test_registration_cannot_supply_permissions_and_unknown_type_fails_closed() -> None:
    fields = set(NodeTypeSpec.__dataclass_fields__)
    assert "permissions" not in fields
    assert "permission" not in fields

    registry = build_default_node_type_registry()
    with pytest.raises(KeyError, match="Unknown NodeType"):
        registry.resolve("not.registered")
