from __future__ import annotations

import pytest

from maistro.graph.definitions import (
    Edge,
    Graph,
    GraphTemplate,
    Node,
    NodeTemplate,
    TemplateProvenance,
)


def test_node_template_instantiation_is_independent_and_records_exact_provenance() -> None:
    template = NodeTemplate(
        template_id="node-template",
        workspace_id="workspace-1",
        version=3,
        name="Researcher",
        node_type="agent",
        parameters={"model": "primary", "nested": {"temperature": 0.2}},
        binding_ids=["search"],
    )

    first = template.instantiate(node_id="node-1")
    second = template.instantiate(node_id="node-2")

    assert first.source_template is not None
    assert first.source_template.template_id == "node-template"
    assert first.source_template.template_version == 3
    assert first.source_template.template_hash == template.content_hash
    assert second.source_template == first.source_template

    first.parameters["nested"]["temperature"] = 0.9
    first.binding_ids.append("filesystem")

    assert second.parameters["nested"]["temperature"] == 0.2
    assert second.binding_ids == ["search"]
    assert template.parameters["nested"]["temperature"] == 0.2
    assert template.binding_ids == ["search"]


def test_template_change_does_not_retroactively_change_existing_node() -> None:
    original = NodeTemplate(
        template_id="node-template",
        workspace_id="workspace-1",
        version=1,
        name="Coder",
        node_type="agent",
        parameters={"model": "v1"},
    )
    instance = original.instantiate(node_id="node-1")

    updated = original.model_copy(
        deep=True,
        update={"version": 2, "parameters": {"model": "v2"}},
    )

    assert instance.parameters == {"model": "v1"}
    assert instance.source_template is not None
    assert instance.source_template.template_version == 1
    assert updated.instantiate().source_template.template_version == 2


def test_graph_template_instantiation_allocates_independent_topology_and_scope() -> None:
    source = Node(node_id="source", node_type="agent", name="Source", parameters={"x": [1]})
    sink = Node(node_id="sink", node_type="transform", name="Sink")
    template = GraphTemplate(
        template_id="graph-template",
        workspace_id="workspace-1",
        version=4,
        name="Pipeline",
        nodes=[source, sink],
        edges=[Edge(edge_id="edge", from_node="source", to_node="sink")],
        metadata={"labels": ["canonical"]},
    )

    first = template.instantiate(project_id="project-a", graph_id="graph-1")
    second = template.instantiate(project_id="project-b", graph_id="graph-2")

    assert first.workspace_id == "workspace-1"
    assert first.project_id == "project-a"
    assert second.project_id == "project-b"
    assert first.source_template is not None
    assert first.source_template.template_id == "graph-template"
    assert first.source_template.template_version == 4
    assert first.source_template.template_hash == template.content_hash
    assert "project_id" not in template.model_dump()

    first_ids = {node.node_id for node in first.nodes}
    second_ids = {node.node_id for node in second.nodes}
    assert first_ids.isdisjoint(second_ids)
    assert first.edges[0].from_node in first_ids
    assert first.edges[0].to_node in first_ids
    assert second.edges[0].from_node in second_ids
    assert second.edges[0].to_node in second_ids

    first.nodes[0].parameters["x"].append(2)
    first.metadata["labels"].append("changed")

    assert second.nodes[0].parameters["x"] == [1]
    assert template.nodes[0].parameters["x"] == [1]
    assert second.metadata["labels"] == ["canonical"]
    assert template.metadata["labels"] == ["canonical"]


@pytest.mark.ac("SPEC-081226-bb3a/AC-6")
def test_objects_can_be_saved_as_new_workspace_wide_templates() -> None:
    """All three clauses, including the one that had no field to bind to.

    "Their provenance identifies the source Node" was unassertable until
    ADR-082926-d0dc gave templates a `saved_from`: `TemplateProvenance` runs
    object -> template, and nothing ran the other way. A template promoted out
    of a live object was indistinguishable from one authored from nothing.
    """
    node = Node(
        node_id="live-node",
        node_type="agent",
        name="Edited Coder",
        parameters={"model": "new-model", "tuning": {"temperature": 0.4}},
        source_template=TemplateProvenance(
            template_id="upstream", template_version=2, template_hash="upstream-hash"
        ),
    )
    node_before = node.model_copy(deep=True)
    node_template = NodeTemplate.from_node(
        node,
        workspace_id="workspace-1",
        template_id="saved-node-template",
        version=1,
    )

    graph = Graph(
        graph_id="live-graph",
        workspace_id="workspace-1",
        project_id="project-a",
        name="Edited Pipeline",
        nodes=[node],
    )
    graph_template = GraphTemplate.from_graph(
        graph,
        template_id="saved-graph-template",
        version=1,
    )

    new_node = node_template.instantiate()
    new_graph = graph_template.instantiate(project_id="project-b")

    assert new_node.node_id != node.node_id
    assert new_node.source_template is not None
    assert new_node.source_template.template_id == "saved-node-template"
    assert new_graph.graph_id != graph.graph_id
    assert new_graph.workspace_id == graph.workspace_id
    assert new_graph.project_id == "project-b"
    assert "project_id" not in graph_template.model_dump()
    assert new_graph.source_template is not None
    assert new_graph.source_template.template_id == "saved-graph-template"
    assert new_graph.nodes[0].node_id != node.node_id

    # "and their provenance identifies the source Node"
    assert node_template.saved_from is not None
    assert node_template.saved_from.object_kind == "node"
    assert node_template.saved_from.object_id == "live-node"
    assert node_template.saved_from.object_hash
    # Lineage is a chain, not one hop: this template knows the Node it came
    # from, and that the Node itself came from `upstream@2`.
    assert node_template.saved_from.object_source_template == node.source_template

    assert graph_template.saved_from is not None
    assert graph_template.saved_from.object_kind == "graph"
    assert graph_template.saved_from.object_id == "live-graph"

    # "and the Node itself is unchanged" -- whole-object equality, after the
    # save and after both instantiations, not a field spot-check.
    assert node == node_before


def test_saved_from_stays_out_of_the_content_hash() -> None:
    """The load-bearing half of ADR-082926-d0dc.

    Two templates saved from two *different* Nodes carrying identical content
    are identical content. If `saved_from` reached the hash they would hash
    differently, and AC-7's idempotent re-registration ("re-registering
    identical content is a no-op") would start refusing them as redefinition
    conflicts. Provenance about where content came from must not change what
    the content is.
    """
    shared = {
        "node_type": "agent",
        "name": "Coder",
        "parameters": {"model": "m", "tuning": {"temperature": 0.4}},
    }
    first = Node(node_id="node-a", **shared)
    second = Node(
        node_id="node-b",
        source_template=TemplateProvenance(
            template_id="elsewhere", template_version=7, template_hash="other-hash"
        ),
        **shared,
    )

    a = NodeTemplate.from_node(first, workspace_id="workspace-1", template_id="t-a")
    b = NodeTemplate.from_node(second, workspace_id="workspace-2", template_id="t-b")

    assert a.saved_from != b.saved_from
    assert a.content_hash == b.content_hash


def test_graph_requires_workspace_project_scope_and_unique_node_ids() -> None:
    with pytest.raises(ValueError, match="workspace_id"):
        Graph(
            workspace_id="",
            project_id="project-a",
            name="Bad",
            nodes=[Node(node_id="one", node_type="agent")],
        )

    with pytest.raises(ValueError, match="project_id"):
        Graph(
            workspace_id="workspace-1",
            project_id="",
            name="Bad",
            nodes=[Node(node_id="one", node_type="agent")],
        )

    with pytest.raises(ValueError, match="node_id values must be unique"):
        Graph(
            workspace_id="workspace-1",
            project_id="project-a",
            name="Bad",
            nodes=[
                Node(node_id="duplicate", node_type="agent"),
                Node(node_id="duplicate", node_type="transform"),
            ],
        )


def test_graph_content_hash_changes_with_definition_not_filing_identity() -> None:
    first = Graph(
        graph_id="graph-a",
        workspace_id="workspace-1",
        project_id="project-a",
        name="Pipeline",
        nodes=[Node(node_id="node", node_type="agent", parameters={"model": "a"})],
    )
    same_definition = first.model_copy(
        deep=True,
        update={
            "graph_id": "graph-b",
            "workspace_id": "workspace-2",
            "project_id": "project-b",
        },
    )
    changed = first.model_copy(deep=True)
    changed.nodes[0].parameters["model"] = "b"

    assert first.content_hash == same_definition.content_hash
    assert first.content_hash != changed.content_hash


def test_graph_template_instantiation_remaps_entry_metadata_to_fresh_ids() -> None:
    template = GraphTemplate(
        workspace_id="workspace-1",
        name="Entry",
        nodes=[
            Node(node_id="start", node_type="agent"),
            Node(node_id="finish", node_type="transform"),
        ],
        edges=[Edge(from_node="start", to_node="finish")],
        metadata={"entry_node": "start", "unrelated": "start"},
    )

    graph = template.instantiate(project_id="project-a")

    fresh_ids = {node.node_id for node in graph.nodes}
    assert graph.metadata["entry_node"] in fresh_ids
    assert graph.metadata["entry_node"] != "start"
    # Only the executor's entry keys carry node-id semantics; other metadata
    # values that happen to collide with a template node id stay verbatim.
    assert graph.metadata["unrelated"] == "start"
