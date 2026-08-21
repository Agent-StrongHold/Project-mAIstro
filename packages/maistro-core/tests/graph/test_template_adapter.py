"""Tests for the legacy-snapshot → canonical GraphTemplate projection."""

from __future__ import annotations

import pytest

from maistro.graph.dag_registry import DagRegistry
from maistro.graph.template_adapter import descriptor_to_template, snapshot_to_template

_SNAPSHOT = {
    "id": "sample",
    "name": "Sample",
    "description": "sample snapshot",
    "use_case": "pm_fleet",
    "max_cycles": 3,
    "entry_node": "a",
    "nodes": [
        {"id": "a", "kind": "transform.alias_keys", "config": {"mapping": {"x": "y"}}},
        {
            "id": "b",
            "kind": "transform.format_markdown",
            "inputs": {"header": "H", "template": "- {x}"},
            "extra": 1,
        },
    ],
    "edges": [
        {"from_node": "a", "to_node": "b", "weight": 2},
    ],
}


def test_snapshot_projects_fields_onto_template() -> None:
    template = snapshot_to_template(dict(_SNAPSHOT), workspace_id="w1")
    assert template.template_id == "sample"
    assert template.workspace_id == "w1"
    assert template.name == "Sample"
    assert template.description == "sample snapshot"
    assert template.metadata["entry_node"] == "a"
    assert template.metadata["use_case"] == "pm_fleet"
    assert template.metadata["max_cycles"] == 3
    assert [node.node_id for node in template.nodes] == ["a", "b"]
    assert template.nodes[0].parameters == {"mapping": {"x": "y"}}
    assert template.nodes[1].inputs == {"header": "H", "template": "- {x}"}
    assert template.nodes[1].metadata == {"extra": 1}
    assert template.edges[0].from_node == "a"
    assert template.edges[0].to_node == "b"
    assert template.edges[0].metadata == {"weight": 2}


def test_snapshot_edge_referencing_unknown_node_is_rejected() -> None:
    bad = dict(_SNAPSHOT, edges=[{"from_node": "a", "to_node": "ghost"}])
    with pytest.raises(ValueError, match="references a node outside"):
        snapshot_to_template(bad, workspace_id="w1")


def test_instantiate_carries_provenance_and_remaps_entry() -> None:
    template = snapshot_to_template(dict(_SNAPSHOT), workspace_id="w1")
    graph = template.instantiate(project_id="p1")
    assert graph.source_template is not None
    assert graph.source_template.template_id == "sample"
    assert graph.source_template.template_version == 1
    assert graph.source_template.template_hash == template.content_hash
    node_a = next(node for node in graph.nodes if node.name == "a")
    assert graph.metadata["entry_node"] == node_a.node_id
    assert node_a.node_id != "a"


def test_content_hash_is_stable_across_identical_snapshots() -> None:
    first = snapshot_to_template(dict(_SNAPSHOT), workspace_id="w1")
    second = snapshot_to_template(dict(_SNAPSHOT), workspace_id="w2")
    assert first.content_hash == second.content_hash


def test_descriptor_version_becomes_template_version() -> None:
    registry = DagRegistry()
    registry.register(dict(_SNAPSHOT))
    registry.register(dict(_SNAPSHOT))  # re-registration bumps the version
    descriptor = registry.get("sample")
    assert descriptor is not None and descriptor.version == 2
    template = descriptor_to_template(descriptor, workspace_id="w1")
    assert template.template_id == "sample"
    assert template.version == 2
    graph = template.instantiate(project_id="p1")
    assert graph.source_template.template_version == 2
