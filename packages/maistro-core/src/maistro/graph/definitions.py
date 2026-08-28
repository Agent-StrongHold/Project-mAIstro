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


#: Field names that carry live execution state, which SPEC-081226-bb3a R12
#: forbids from persisted NodeTemplate and GraphTemplate content. A template is
#: a definition; a Run/NodeRun/Attempt is one execution of it. A template that
#: has absorbed a `run_id` or a `deadline_at` is a record of something that
#: already happened, and instantiating it replays another execution's state.
#:
#: Grouped by the four categories R12 names, so a reader can check the list
#: against the requirement rather than trusting it. `tests/graph/
#: test_template_runtime_exclusion.py` pins every name here to a real field on
#: the canonical execution models -- the set cannot drift from them, and the
#: production module does not import them, because a reusable definition must
#: not depend on the execution records it is reused by.
RUNTIME_STATE_FIELDS: frozenset[str] = frozenset(
    {
        # Run/NodeRun/Attempt identifiers
        "run_id",
        "node_run_id",
        "attempt_id",
        "parent_run_id",
        "parent_node_run_id",
        # terminal state
        "status",
        "started_at",
        "finished_at",
        "accepted_outcome",
        # retry counters
        "ordinal",
        # runtime cancellation / deadline state
        "deadline_at",
        "execution_lease",
        "lease_epoch",
        "fencing_token",
        "expires_at",
        "holder",
        "issued_at",
        "resume_checkpoint_id",
        "retention_expires_at",
    }
)

#: Canonical execution-model fields deliberately NOT excluded, with the reason.
#: R12 permits "defaults/policies that influence future execution" as definition
#: data, and its forbidden list is four named categories rather than "every
#: field of an execution record". Recorded here rather than left as an absence,
#: because the next reader's question is why these are missing.
RUNTIME_STATE_ADMITTED: dict[str, str] = {
    "created_at": "record metadata, and a template has its own",
    "updated_at": "record metadata, and a template has its own",
    "result": "an output, not an identifier, terminal state, counter or deadline",
    "metrics": (
        "an output, like result and error; and a template may legitimately name "
        "which metrics its executions should emit, which is definition data"
    ),
    "error": "an output, not an identifier, terminal state, counter or deadline",
    "runtime_id": "an execution default R12 explicitly permits",
    "executor_id": "an execution default R12 explicitly permits",
    "workspace_id": "scope, which templates carry in their own right",
    "project_id": "scope, which templates carry in their own right",
    "node_id": "definition identity: a Node is the thing a template describes",
    "graph": "the definition an execution names, not execution state",
    "persona_id": "a definition-time binding, not execution state",
    "actor_principal_id": "authorization context, never template content",
    "provenance": "template provenance is TemplateProvenance, a distinct field",
}


class RuntimeStateInTemplate(ValueError):
    """Live execution state was supplied as reusable template content (R12).

    Raised rather than stripped when a template is constructed, because a caller
    that did not intend to carry execution state wants to hear about it, and one
    that did should say so by calling `separate_runtime_state` and keeping the
    projection it returns.
    """

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths
        listed = ", ".join(paths)
        super().__init__(
            f"template content carries live execution state: {listed}. "
            "A template is a definition; Run/NodeRun/Attempt state belongs to an "
            "execution of it (SPEC-081226-bb3a R12). Use separate_runtime_state() "
            "to split an execution record into a definition and its runtime "
            "projection."
        )


def _runtime_state_paths(value: Any, *, path: str = "") -> list[str]:
    """Every location under `value` whose key names live execution state."""

    found: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            here = f"{path}.{key}" if path else str(key)
            if key in RUNTIME_STATE_FIELDS:
                found.append(here)
            else:
                found.extend(_runtime_state_paths(nested, path=here))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            found.extend(_runtime_state_paths(nested, path=f"{path}[{index}]"))
    return found


def separate_runtime_state(content: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split content into what a template may keep and what it may not.

    R13 requires an adapter to separate runtime fields before projecting an
    execution-time record into a reusable template, rather than pretending the
    record is already one. This is that separation, and it returns the runtime
    half instead of discarding it so a caller can file it where it belongs.
    """

    definition: dict[str, Any] = {}
    runtime: dict[str, Any] = {}
    for key, value in content.items():
        if key in RUNTIME_STATE_FIELDS:
            runtime[key] = value
        elif isinstance(value, dict):
            nested_definition, nested_runtime = separate_runtime_state(value)
            definition[key] = nested_definition
            if nested_runtime:
                runtime[key] = nested_runtime
        else:
            definition[key] = value
    return definition, runtime


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

    @model_validator(mode="after")
    def _reject_runtime_state(self) -> NodeTemplate:
        paths = _runtime_state_paths(self._reusable_content())
        if paths:
            raise RuntimeStateInTemplate(paths)
        return self

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
        # A GraphTemplate embeds its Nodes by value, so runtime state smuggled
        # into one of them is template content just as surely as its own
        # metadata is. `node_id` is definition identity and stays; the scan
        # skips it because it is not in RUNTIME_STATE_FIELDS.
        paths = _runtime_state_paths(self._reusable_content())
        if paths:
            raise RuntimeStateInTemplate(paths)
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
        # Metadata can reference nodes by id (the executor's entry-frontier
        # keys); those references must follow the fresh node identities or the
        # instantiated Graph names nodes that no longer exist.
        metadata = self.model_copy(deep=True).metadata
        for key in ("entry_node", "entry"):
            reference = metadata.get(key)
            if isinstance(reference, str) and reference in node_id_map:
                metadata[key] = node_id_map[reference]
        return Graph(
            graph_id=graph_id or _id(),
            workspace_id=self.workspace_id,
            project_id=project_id,
            name=name if name is not None else self.name,
            description=self.description,
            nodes=nodes,
            edges=edges,
            metadata=metadata,
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
    "RUNTIME_STATE_ADMITTED",
    "RUNTIME_STATE_FIELDS",
    "Edge",
    "Graph",
    "GraphTemplate",
    "Node",
    "NodeTemplate",
    "RuntimeStateInTemplate",
    "TemplateProvenance",
    "separate_runtime_state",
]
