from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


def _id() -> str:
    return uuid.uuid4().hex


def _content_hash(payload: dict[str, Any]) -> str:
    """Return a stable digest for template and graph snapshot provenance."""

    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


#: Field names that identify live execution state unambiguously enough to
#: reject on sight, per SPEC-081226-bb3a R12. A template is a definition; a
#: Run/NodeRun/Attempt is one execution of it. A template that has absorbed a
#: `run_id` or an `execution_lease` is a record of something that already
#: happened, and instantiating it replays another execution's state.
#:
#: "Unambiguously" is the whole design of this set, and it is narrower than R12
#: reads. See RUNTIME_STATE_UNENFORCEABLE below for what that costs and why the
#: alternative is worse. `tests/graph/test_template_runtime_exclusion.py` pins
#: every name here to a real field on the canonical execution models -- the set
#: cannot drift from them, and the production module does not import them,
#: because a reusable definition must not depend on the records that execute it.
RUNTIME_STATE_FIELDS: frozenset[str] = frozenset(
    {
        # Run/NodeRun/Attempt identity
        "run_id",
        "node_run_id",
        "attempt_id",
        "parent_run_id",
        "parent_node_run_id",
        # the authorization identity of one execution, which must never be
        # reused: a template carrying it would run later work as that principal
        "actor_principal_id",
        # lease, checkpoint and settled-outcome state -- compound names with no
        # plausible reading as definition data
        "execution_lease",
        "lease_epoch",
        "fencing_token",
        "resume_checkpoint_id",
        "accepted_outcome",
        "retention_expires_at",
    }
)

#: Execution-state fields R12 names that this check deliberately does NOT
#: reject, because their names are ordinary words that legitimately appear in
#: definition data.
#:
#: R12 forbids "terminal state, retry counters, and runtime
#: cancellation/deadline state", and by name these are `status`, `ordinal`,
#: `started_at`, `finished_at`, `deadline_at`, `expires_at`, `issued_at` and
#: `holder`. Rejecting those keys anywhere in an open dict would refuse an HTTP
#: node's `parameters={"expected_response": {"status": 200}}`, an output schema
#: with a `status` property, a scheduled template's own `deadline_at`, or a
#: parameter named `holder`. Worse than refusing new work: template content is
#: revalidated when a durable store reconstructs it, so previously-valid
#: persisted templates would stop loading after an upgrade and take their
#: schedules with them.
#:
#: So this check enforces the half it can prove and states the half it cannot,
#: rather than enforcing R12 by name and breaking stored data. Closing the
#: residue needs structural detection or a reserved namespace, not a longer
#: list; that is raised on #40 rather than narrowed away in silence.
RUNTIME_STATE_UNENFORCEABLE: dict[str, str] = {
    "status": "an ordinary field name: HTTP status, document status, job status",
    "ordinal": "a position in any user-defined sequence, not only a retry count",
    "started_at": "a schedule or content timestamp as often as an execution one",
    "finished_at": "likewise",
    "deadline_at": "a scheduled template's own deadline is definition data",
    "expires_at": "a credential or cache TTL a template may legitimately define",
    "issued_at": "likewise",
    "holder": "an ordinary noun -- account holder, licence holder, lease holder",
}

#: Canonical execution-model fields that are not execution *state* at all, with
#: the reason. R12 permits "defaults/policies that influence future execution"
#: as definition data, and its forbidden list is four named categories rather
#: than "every field of an execution record". Recorded here rather than left as
#: an absence, because the next reader's question is why these are missing.
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
            continue
        # Lists are traversed because the validator traverses them. A helper
        # the refusal message names, whose output the validator then rejects,
        # is worse than no helper.
        kept, removed = _split_value(value)
        definition[key] = kept
        if removed is not None:
            runtime[key] = removed
    return definition, runtime


def _split_value(value: Any) -> tuple[Any, Any]:
    """Split one value into what a template keeps and what it must not."""

    if isinstance(value, dict):
        kept_dict, removed_dict = separate_runtime_state(value)
        return kept_dict, (removed_dict or None)
    if isinstance(value, list):
        kept_list: list[Any] = []
        removed_list: list[Any] = []
        found = False
        for item in value:
            kept_item, removed_item = _split_value(item)
            kept_list.append(kept_item)
            removed_list.append(removed_item)
            found = found or removed_item is not None
        return kept_list, (removed_list if found else None)
    return value, None


class TemplateProvenance(BaseModel):
    """Exact template revision from which a mutable object was instantiated."""

    template_id: str
    template_version: int = Field(ge=1)
    template_hash: str


class SourceObjectProvenance(BaseModel):
    """The Workspace object a template was saved from (ADR-082926-d0dc).

    `TemplateProvenance` runs object -> template: it says which template an
    instantiated object came from. This runs the other way, and only
    save-as-template creates it. Without it a template promoted out of a live
    object is indistinguishable from one authored from nothing.

    `object_source_template` is what makes lineage a chain rather than one hop:
    a Node instantiated from T@1, customized and saved as U@1 records both the
    Node it came from and that the Node itself came from T@1.
    """

    object_kind: Literal["node", "graph"]
    object_id: str
    object_hash: str
    object_source_template: TemplateProvenance | None = None


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
    saved_from: SourceObjectProvenance | None = None

    @model_validator(mode="after")
    def _reject_runtime_state(self) -> NodeTemplate:
        paths = _runtime_state_paths(self._reusable_content())
        if paths:
            raise RuntimeStateInTemplate(paths)
        return self

    def _reusable_content(self) -> dict[str, Any]:
        # `saved_from` is excluded for a stronger reason than the identity
        # fields beside it (ADR-082926-d0dc). Two templates saved from two
        # different Nodes that carry identical content *are* identical
        # content; if their origin entered the hash they would hash
        # differently, and the store's idempotent re-registration (AC-7)
        # would start refusing them as redefinition conflicts. Provenance
        # about where content came from must not change what the content is.
        return self.model_dump(
            exclude={"template_id", "workspace_id", "version", "saved_from"}, mode="json"
        )

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
            # AC-6's third clause. The Node's own `source_template` is carried
            # through rather than dropped, so lineage is a chain: this
            # template knows the Node it came from, and that the Node came
            # from a template before it.
            saved_from=SourceObjectProvenance(
                object_kind="node",
                object_id=node.node_id,
                object_hash=_content_hash(node.model_dump(exclude={"node_id"}, mode="json")),
                object_source_template=node.source_template,
            ),
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
    saved_from: SourceObjectProvenance | None = None

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
        # Excluded for the reason `NodeTemplate._reusable_content` records:
        # two Graphs saved with identical content are identical content, and
        # letting their origin reach the hash would turn re-registration into
        # a conflict (ADR-082926-d0dc).
        return self.model_dump(
            exclude={"template_id", "workspace_id", "version", "saved_from"}, mode="json"
        )

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
            saved_from=SourceObjectProvenance(
                object_kind="graph",
                object_id=graph.graph_id,
                object_hash=_content_hash(
                    graph.model_dump(
                        exclude={"graph_id", "workspace_id", "project_id"}, mode="json"
                    )
                ),
                object_source_template=graph.source_template,
            ),
        )


__all__ = [
    "RUNTIME_STATE_ADMITTED",
    "RUNTIME_STATE_FIELDS",
    "RUNTIME_STATE_UNENFORCEABLE",
    "Edge",
    "Graph",
    "GraphTemplate",
    "Node",
    "NodeTemplate",
    "RuntimeStateInTemplate",
    "SourceObjectProvenance",
    "TemplateProvenance",
    "separate_runtime_state",
]
