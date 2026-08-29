"""Project legacy editable DAG snapshots onto the canonical template layer.

The DagRegistry (and Hive's DagBuilder) store the historical editable DAGFile
dict. That format stays user-facing, but it is not a second definition
authority: this module is the single reviewed projection from a snapshot into
a canonical ``GraphTemplate``, so every product boundary instantiates
``Graph`` objects through ``GraphTemplate.instantiate`` and Runs carry
``TemplateProvenance`` back to the exact registered revision. Products should
not hand-roll their own snapshot conversion (Hive's daily-status runner used
to; that converter now lives here for every caller).
"""

from __future__ import annotations

from typing import Any

from maistro.graph.dag_registry import DagAgentDescriptor
from maistro.graph.definitions import Edge, GraphTemplate, Node
from maistro.graph.import_provenance import SOURCE_IMPORT_PROVENANCE, import_provenance

_NODE_OWN_KEYS = {"id", "kind", "node_type", "name", "config", "parameters", "inputs", "outputs"}
_EDGE_OWN_KEYS = {"id", "edge_id", "from_node", "from_role", "to_node", "to_role", "condition"}
_SNAPSHOT_OWN_KEYS = {"id", "name", "description", "nodes", "edges", "entry_node", "entry"}


def _str_of(*candidates: Any) -> str:
    """First truthy candidate as a string, else empty."""
    for candidate in candidates:
        if candidate:
            return str(candidate)
    return ""


def _dict_of(*candidates: Any) -> dict[str, Any]:
    """Copy of the first truthy mapping candidate, else empty."""
    for candidate in candidates:
        if candidate:
            return dict(candidate)
    return {}


def _node_from_raw(raw: dict[str, Any]) -> Node:
    node_id = _str_of(raw.get("id"))
    return Node(
        node_id=node_id,
        node_type=_str_of(raw.get("kind"), raw.get("node_type")),
        name=_str_of(raw.get("name"), node_id),
        parameters=_dict_of(raw.get("config"), raw.get("parameters")),
        inputs=_dict_of(raw.get("inputs")),
        outputs=_dict_of(raw.get("outputs")),
        metadata={key: value for key, value in raw.items() if key not in _NODE_OWN_KEYS},
    )


def _edge_from_raw(raw: dict[str, Any], index: int) -> Edge:
    return Edge(
        edge_id=_str_of(raw.get("edge_id"), raw.get("id"), f"edge-{index}"),
        from_node=_str_of(raw.get("from_node"), raw.get("from_role")),
        to_node=_str_of(raw.get("to_node"), raw.get("to_role")),
        condition=str(raw["condition"]) if raw.get("condition") is not None else None,
        metadata={key: value for key, value in raw.items() if key not in _EDGE_OWN_KEYS},
    )


def snapshot_to_template(
    snapshot: dict[str, Any],
    *,
    workspace_id: str,
    template_id: str | None = None,
    version: int = 1,
) -> GraphTemplate:
    """Project a legacy editable DAG snapshot into a canonical GraphTemplate.

    Node ids in the template keep the snapshot's editable ids;
    ``GraphTemplate.instantiate`` assigns fresh identities (and remaps the
    entry reference) per instantiated Graph. Credential-bearing runtime
    inputs must be overlaid on the *instantiated* Graph, never here — the
    template's ``content_hash`` is provenance and has to stay secret-free.
    """
    metadata = {key: value for key, value in snapshot.items() if key not in _SNAPSHOT_OWN_KEYS}
    entry = _str_of(snapshot.get("entry_node"), snapshot.get("entry"))
    if entry:
        metadata["entry_node"] = entry
    # AC-10's second example. The agent half has recorded where it came from
    # since #525/#526; this half recorded nothing, so a projected DAG was
    # indistinguishable from a canonically authored GraphTemplate and no
    # audit could trace a Run back to the legacy definition behind it.
    # Hashed over the snapshot as received, before any of the key-splitting
    # above, so the digest names the source rather than this projection's
    # reading of it.
    metadata[SOURCE_IMPORT_PROVENANCE] = import_provenance(
        snapshot,
        source_format="dag_snapshot",
        source_definition="DAGFile",
        source_name=_str_of(snapshot.get("name"), snapshot.get("id")),
    )
    identity: dict[str, str] = {}
    resolved_template_id = _str_of(template_id, snapshot.get("id"))
    if resolved_template_id:
        identity["template_id"] = resolved_template_id
    return GraphTemplate(
        **identity,
        workspace_id=workspace_id,
        version=version,
        name=_str_of(snapshot.get("name"), snapshot.get("id")),
        description=_str_of(snapshot.get("description")),
        nodes=[_node_from_raw(dict(raw)) for raw in snapshot.get("nodes", [])],
        edges=[
            _edge_from_raw(dict(raw), index)
            for index, raw in enumerate(snapshot.get("edges", []), start=1)
        ],
        metadata=metadata,
    )


def descriptor_to_template(
    descriptor: DagAgentDescriptor,
    *,
    workspace_id: str,
) -> GraphTemplate:
    """Project a registered DAG-as-agent descriptor into a GraphTemplate.

    The registry's registration counter becomes the template version, so
    ``TemplateProvenance`` on instantiated Graphs names the exact registered
    revision a Run executed.
    """
    return snapshot_to_template(
        dict(descriptor.snapshot),
        workspace_id=workspace_id,
        template_id=descriptor.dag_id,
        version=descriptor.version,
    )


__all__ = ["descriptor_to_template", "snapshot_to_template"]
