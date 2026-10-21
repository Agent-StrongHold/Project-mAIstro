"""Pack Graph templates — materialized as canonical `GraphTemplate`s (M7-A4).

A pack's Graph shape is not a second graph model. `pack_graph_template`
projects the pack's `PackGraphShape` onto the canonical
`maistro.graph.definitions.GraphTemplate` bound to a caller-supplied
Workspace, so `instantiate()` produces an ordinary `Graph` that the canonical
durable executor runs as Run → NodeRun → Attempt — the same identity scheme
as every other Graph in the system (#793 invariant: switching pack mints no
new Run identity scheme).

Fence points ride into the Graph as node metadata (`pack.fenced`) and phase
labels (`pack.phase`); execute backends ride as canonical node `binding_ids`
on execute-phase nodes — backend names appear only as binding references,
never as pack or graph identity.
"""

from __future__ import annotations

from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro_design.packs.types import DomainPack

#: Template id prefix keeping pack templates distinguishable in a Workspace's
#: template store without giving any pack its own identity domain.
_TEMPLATE_ID_PREFIX = "pack"


def pack_graph_template(pack: DomainPack, *, workspace_id: str) -> GraphTemplate:
    """Materialize the pack's Graph shape as a Workspace-bound GraphTemplate.

    The template is definition-only (no runtime state — the template model's
    own R12 scan would refuse it) and `version=1`; content identity is the
    template's `content_hash`, which differs per pack because each pack's
    shape differs.
    """
    if not workspace_id.strip():
        raise ValueError("workspace_id must be a non-empty string")

    shape = pack.graph
    nodes: list[Node] = []
    for phase in shape.nodes:
        node = Node(
            node_id=phase.node_id,
            node_type=phase.kind,
            name=phase.node_id,
            metadata={"pack.phase": phase.phase, "pack.fenced": phase.fenced},
        )
        if phase.phase == "execute":
            # Execute backends are canonical binding references on the
            # execute-phase node — never a pack_id, never a graph id.
            node.binding_ids = sorted(backend.value for backend in pack.execute_backends)
        nodes.append(node)

    edges = [
        Edge(edge_id=f"{source}->{target}", from_node=source, to_node=target)
        for source, target in shape.edges
    ]

    return GraphTemplate(
        template_id=f"{_TEMPLATE_ID_PREFIX}.{pack.pack_id.value}",
        workspace_id=workspace_id,
        version=1,
        name=shape.name,
        description=pack.summary,
        nodes=nodes,
        edges=edges,
        metadata={
            "pack_id": pack.pack_id.value,
            "pack_version": pack.version,
            "entry_node": shape.entry_node,
            "artifact_kinds": list(pack.artifact_kinds),
            "execute_backends": sorted(backend.value for backend in pack.execute_backends),
            "fence_points": sorted(point.value for point in pack.fence_points),
            # What the explore phase establishes, riding with the template
            # like every other pack field — the explore nodes' contract is
            # inspectable without re-reading the manifest.
            "explore_focus": list(pack.explore_focus),
        },
    )
