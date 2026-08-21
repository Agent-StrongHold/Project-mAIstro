from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator


def _id() -> str:
    return uuid.uuid4().hex


def _content_hash(payload: dict[str, Any]) -> str:
    """Return a stable digest for template and graph snapshot provenance."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


class TemplateProvenance(BaseModel):
    """Exact template revision from which a mutable object was instantiated."""

    template_id: str
    template_version: int = Field(ge=1)
    template_hash: str


class Node(BaseModel):
    """Canonical mutable executable position in a Graph.

    This is definition-only. Execution state belongs to NodeRun/Attempt.
    """

    node_id: str = Field(default_factory=_id)
    node_type: str
    name: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)
    binding_ids: list[str] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_template: TemplateProvenance | None = None


class Edge(BaseModel):
    """Canonical directed Graph edge."""

    edge_id: str = Field(default_factory=_id)
    from_node: str
    to_node: str
    condition: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Graph(BaseModel):
    """Canonical mutable composition filed in exactly one Workspace Project."""

    graph_id: str = Field(default_factory=_id)
    workspace_id: str
    project_id: str
    name: str
    description: str = ""
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_template: TemplateProvenance | None = None

    @model_validator(mode="after")
    def _validate_graph(self) -> Graph:
        if not self.workspace_id.strip():
            raise ValueError("workspace_id must be a non-empty string")
        if not self.project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        node_ids = {node.node_id for node in self.nodes}
        if len(node_ids) != len(self.nodes):
            raise ValueError("node_id values must be unique within a Graph")
        for edge in self.edges:
            if edge.from_node not in node_ids or edge.to_node not in node_ids:
                raise ValueError(
                    f"edge {edge.edge_id} references a node outside graph {self.graph_id}"
                )
        return self

    def _snapshot_content(self) -> dict[str, Any]:
        return self.model_dump(
            exclude={"graph_id", "workspace_id", "project_id"},
            mode="json",
        )

    @property
    def content_hash(self) -> str:
        return _content_hash(self._snapshot_content())


class NodeTemplate(BaseModel):
    """Versioned reusable Node definition with copy + provenance instantiation."""

    template_id: str = Field(default_factory=_id)
    workspace_id: str
    version: int = Field(default=1, ge=1)
    name: str
    node_type: str
    parameters: dict[str, Any] = Field(default_factory=dict)
    binding_ids: list[str] = Field(default_factory=list)
    permissions: dict[str, Any] = Field(default_factory=dict)
    policies: dict[str, Any] = Field(default_factory=dict)
    inputs: dict[str, Any] = Field(default_factory=dict)
    outputs: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def _reusable_content(self) -> dict[str, Any]:
        return self.model_dump(exclude={"template_id", "workspace_id", "version"}, mode="json")

    @property
    def content_hash(self) -> str:
        return _content_hash(self._reusable_content())

    def instantiate(self, *, node_id: str | None = None) -> Node:
        values = self.model_copy(deep=True)._reusable_content()
        return Node(
            node_id=node_id or _id(),
            **values,
            source_template=TemplateProvenance(
                template_id=self.template_id,
                template_version=self.version,
                template_hash=self.content_hash,
            ),
        )

    @classmethod
    def from_node(
        cls,
        node: Node,
        *,
        workspace_id: str,
        template_id: str | None = None,
        version: int = 1,
        name: str | None = None,
    ) -> NodeTemplate:
        values = node.model_copy(deep=True).model_dump(
            exclude={"node_id", "source_template", "name"}, mode="python"
        )
        return cls(
            template_id=template_id or _id(),
            workspace_id=workspace_id,
            version=version,
            name=name if name is not None else node.name,
            **values,
        )


class GraphTemplate(BaseModel):
    """Versioned Workspace-wide reusable Graph topology snapshot."""

    template_id: str = Field(default_factory=_id)
    workspace_id: str
    version: int = Field(default=1, ge=1)
    name: str
    description: str = ""
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_edges(self) -> GraphTemplate:
        node_ids = {node.node_id for node in self.nodes}
        for edge in self.edges:
            if edge.from_node not in node_ids or edge.to_node not in node_ids:
                raise ValueError(f"edge {edge.edge_id} references a node outside graph template")
        return self

    def _reusable_content(self) -> dict[str, Any]:
        return self.model_dump(exclude={"template_id", "workspace_id", "version"}, mode="json")

    @property
    def content_hash(self) -> str:
        return _content_hash(self._reusable_content())

    def instantiate(
        self,
        *,
        project_id: str,
        graph_id: str | None = None,
        name: str | None = None,
    ) -> Graph:
        node_id_map = {node.node_id: _id() for node in self.nodes}
        nodes = [
            node.model_copy(deep=True, update={"node_id": node_id_map[node.node_id]})
            for node in self.nodes
        ]
        edges = [
            edge.model_copy(
                deep=True,
                update={
                    "edge_id": _id(),
                    "from_node": node_id_map[edge.from_node],
                    "to_node": node_id_map[edge.to_node],
                },
            )
            for edge in self.edges
        ]
        return Graph(
            graph_id=graph_id or _id(),
            workspace_id=self.workspace_id,
            project_id=project_id,
            name=name if name is not None else self.name,
            description=self.description,
            nodes=nodes,
            edges=edges,
            metadata=self.model_copy(deep=True).metadata,
            source_template=TemplateProvenance(
                template_id=self.template_id,
                template_version=self.version,
                template_hash=self.content_hash,
            ),
        )

    @classmethod
    def from_graph(
        cls,
        graph: Graph,
        *,
        template_id: str | None = None,
        version: int = 1,
        name: str | None = None,
    ) -> GraphTemplate:
        snapshot = graph.model_copy(deep=True)
        return cls(
            template_id=template_id or _id(),
            workspace_id=snapshot.workspace_id,
            version=version,
            name=name if name is not None else snapshot.name,
            description=snapshot.description,
            nodes=snapshot.nodes,
            edges=snapshot.edges,
            metadata=snapshot.metadata,
        )


__all__ = [
    "Edge",
    "Graph",
    "GraphTemplate",
    "Node",
    "NodeTemplate",
    "TemplateProvenance",
]
