from __future__ import annotations

import pytest

from maistro.graph.definitions import Edge, Graph, GraphTemplate, Node, NodeTemplate


@pytest.mark.ac("SPEC-081226-bb3a/AC-1")
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

    before_edit = first.source_template.model_copy(deep=True)
    first.parameters["nested"]["temperature"] = 0.9
    first.binding_ids.append("filesystem")

    assert second.parameters["nested"]["temperature"] == 0.2
    assert second.binding_ids == ["search"]
    assert template.parameters["nested"]["temperature"] == 0.2
    assert template.binding_ids == ["search"]

    # AC-1's second clause, and the half an "objects are independent" test
    # naturally omits: editing the Node must not cost it the identity of the
    # version it came from. Asserted *after* the edit, because before it the
    # claim is about instantiation rather than about editing.
    assert first.source_template == before_edit
    assert first.source_template.template_version == 3
    assert first.source_template.template_hash == template.content_hash


@pytest.mark.ac("SPEC-081226-bb3a/AC-2")
def test_template_change_does_not_retroactively_change_existing_node() -> None:
    """AC-2 says *two* Nodes, and it means it.

    One Node proves the copy is independent of the template object. Two prove
    the property AC-2 actually names -- that publishing T@2 reaches none of the
    objects already instantiated from T@1 -- because a mechanism that updated
    live objects would have to reach both, and a test holding one cannot see
    the difference between "not updated" and "there was only one".
    """
    original = NodeTemplate(
        template_id="node-template",
        workspace_id="workspace-1",
        version=1,
        name="Coder",
        node_type="agent",
        # Nested on purpose. Pydantic rebuilds a top-level `dict[str, Any]`
        # during validation, so a flat fixture is protected from aliasing by
        # accident and this test would pass against a Node that shares its
        # template's containers. The nested value is where sharing shows.
        parameters={"model": "v1", "tuning": {"temperature": 0.2}},
    )
    first = original.instantiate(node_id="node-1")
    second = original.instantiate(node_id="node-2")
    before = [first.model_copy(deep=True), second.model_copy(deep=True)]

    original.model_copy(deep=True, update={"version": 2, "parameters": {"model": "v2"}})

    # Publishing via `model_copy` cannot reach anything by construction, so on
    # its own the assertions below hold for a design that got this wrong. The
    # stronger precondition is the one that makes them falsifiable: mutate the
    # template object *in place*, which is the most aggressive form of "T
    # changed" available, and require the Nodes still not to move. A design in
    # which a Node aliased its template's containers, or resolved them lazily,
    # fails here and passes without it.
    original.parameters["tuning"]["temperature"] = 0.9
    original.parameters["model"] = "v2-in-place"
    original.binding_ids.append("leaked")
    original.metadata["leaked"] = True

    # "unchanged until an explicit update is invoked": whole-object equality,
    # not a field spot-check, so a new field that did leak would fail here.
    assert first == before[0]
    assert second == before[1]
    for node in (first, second):
        assert node.parameters == {"model": "v1", "tuning": {"temperature": 0.2}}
        assert node.source_template is not None
        assert node.source_template.template_version == 1


@pytest.mark.ac("SPEC-081226-bb3a/AC-3")
def test_instantiation_binds_to_an_exact_version() -> None:
    """Each Node materializes its own version's definition, and says which.

    The hash is asserted, not just the version number: provenance that names a
    version without pinning the content it had is what lets a redefined version
    go unnoticed, and it is the pairing `Node.source_template` exists to carry.
    """
    v1 = NodeTemplate(
        template_id="node-template",
        workspace_id="workspace-1",
        version=1,
        name="Coder",
        node_type="agent",
        parameters={"model": "v1"},
    )
    v2 = v1.model_copy(deep=True, update={"version": 2, "parameters": {"model": "v2"}})

    from_v1 = v1.instantiate(node_id="node-1")
    from_v2 = v2.instantiate(node_id="node-2")

    # "each materializes its own version's definition"
    assert from_v1.parameters == {"model": "v1"}
    assert from_v2.parameters == {"model": "v2"}

    # "and each carries that version and hash as provenance"
    assert from_v1.source_template is not None
    assert from_v2.source_template is not None
    assert from_v1.source_template.template_version == 1
    assert from_v2.source_template.template_version == 2
    assert from_v1.source_template.template_hash == v1.content_hash
    assert from_v2.source_template.template_hash == v2.content_hash
    # Two versions with different content are two different hashes; without
    # this the two assertions above would also hold if the hash ignored
    # content entirely.
    assert v1.content_hash != v2.content_hash


@pytest.mark.ac("SPEC-081226-bb3a/AC-4")
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

    template_before = template.model_copy(deep=True)
    first.nodes[0].parameters["x"].append(2)
    first.metadata["labels"].append("changed")
    # AC-4 names a Node *and an Edge*. The edge was the untested half: edges
    # are remapped onto fresh ids during instantiation, so an aliased edge
    # would be a different defect from an aliased node and would survive a
    # test that only ever mutated nodes.
    first.edges[0].condition = "always"
    first.edges[0].metadata["touched"] = True

    assert second.nodes[0].parameters["x"] == [1]
    assert template.nodes[0].parameters["x"] == [1]
    assert second.metadata["labels"] == ["canonical"]
    assert template.metadata["labels"] == ["canonical"]
    assert second.edges[0].condition is None
    assert template.edges[0].condition is None
    assert template.edges[0].metadata == {}
    # "Then GT@1 is unchanged" -- the whole template, not the fields this test
    # happened to poke.
    assert template == template_before


@pytest.mark.ac("SPEC-081226-bb3a/AC-5")
def test_a_graph_template_version_pins_its_nested_node_templates() -> None:
    """Updating a NodeTemplate cannot reach a GraphTemplate already published.

    The pin is structural rather than enforced: `GraphTemplate.nodes` holds
    `Node` snapshots, not NodeTemplate references, so there is no live edge for
    an update to travel along. That is worth an executable assertion precisely
    *because* it is structural -- the obvious "improvement" of storing
    `(template_id, version)` and resolving it at instantiation would satisfy
    every other criterion in this file while silently breaking this one, and
    nothing else here would notice.

    The comparison is the whole effective definition, modulo the identities
    that are freshly allocated by design (AC-4 covers those), so a change
    leaking in through any field fails this rather than only the ones a
    spot-check thought to name.
    """
    node_template = NodeTemplate(
        template_id="node-template",
        workspace_id="workspace-1",
        version=1,
        name="Researcher",
        node_type="agent",
        parameters={"model": "v1"},
    )
    graph_template = GraphTemplate(
        template_id="graph-template",
        workspace_id="workspace-1",
        version=1,
        name="Pipeline",
        nodes=[node_template.instantiate(node_id="researcher")],
    )

    def effective(graph):
        """Everything the definition says, minus the freshly-allocated ids."""
        return [node.model_dump(exclude={"node_id"}, mode="json") for node in graph.nodes]

    before = effective(graph_template.instantiate(project_id="project-a"))

    # The NodeTemplate moves on. A new version, because redefining version 1
    # in place is refused by the store (AC-7) -- so this is the only shape the
    # update can legitimately take.
    node_template.model_copy(deep=True, update={"version": 2, "parameters": {"model": "v2"}})

    after = effective(graph_template.instantiate(project_id="project-b"))

    assert after == before
    assert graph_template.nodes[0].parameters == {"model": "v1"}
    # Still pinned to the version it was published against, not the latest.
    assert after[0]["source_template"]["template_version"] == 1
    assert after[0]["source_template"]["template_hash"] == node_template.content_hash


def test_objects_can_be_saved_as_new_workspace_wide_templates() -> None:
    node = Node(
        node_id="live-node",
        node_type="agent",
        name="Edited Coder",
        parameters={"model": "new-model"},
    )
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
