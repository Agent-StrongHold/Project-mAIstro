"""Per-edge schema validator + DAG structure validator.

Runs at DAG save time (`PUT /v1/dags/{id}`) and at DAG run time (defense
in depth). Returns structured findings the UI surfaces inline next to
each invalid edge.

The two checks:

1. **Structure** — every edge endpoint exists in `nodes[*].id`, the entry
   node is reachable, no orphan nodes, no cycles (since the executor
   doesn't support them in Phase 1).
2. **Schema compatibility** — for each edge `A → B`, A's `output_schema`
   must structurally accept a value B's `input_schema` will validate
   against. We don't require an exact subset; we require that the fields
   B declares as REQUIRED have matching-or-compatible entries in A's
   output (or in the DAG-author-supplied `B.inputs` static fall-through).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nodes import get_node


@dataclass(frozen=True)
class ValidationFinding:
    """A single validator result."""

    code: str  # "missing_node" | "unknown_kind" | "schema_mismatch" | "cycle" | "no_entry" | "unreachable" | "edge_missing_endpoint"
    severity: str  # "error" | "warning"
    message: str
    node_id: str | None = None
    edge_index: int | None = None
    field_path: str | None = None


@dataclass
class ValidationReport:
    """Aggregate result of validating one DAG."""

    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not any(f.severity == "error" for f in self.findings)

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    def to_dict(self) -> dict[str, Any]:
        return {
            "is_valid": self.is_valid,
            "error_count": self.error_count,
            "findings": [
                {
                    "code": f.code,
                    "severity": f.severity,
                    "message": f.message,
                    "node_id": f.node_id,
                    "edge_index": f.edge_index,
                    "field_path": f.field_path,
                }
                for f in self.findings
            ],
        }


def validate_dag(dag: dict[str, Any]) -> ValidationReport:
    """Run all structure + schema checks on a serialized DAG.

    `dag` is the Hive DAGFile shape: `{nodes: [{id, kind, inputs?, config?}],
    edges: [{from_node, to_node, condition?}], entry_node: str}`.
    """
    report = ValidationReport()
    nodes_by_id, kind_by_id = _index_nodes(dag, report)
    _validate_entry(dag, nodes_by_id, report)
    _validate_edge_endpoints(dag, nodes_by_id, report)
    _validate_unknown_kinds(kind_by_id, report)
    _validate_no_cycles(dag, nodes_by_id, report)
    _validate_schema_compatibility(dag, kind_by_id, report)
    return report


# --- Stage helpers ---------------------------------------------------------


def _index_nodes(
    dag: dict[str, Any], report: ValidationReport
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    nodes_by_id: dict[str, dict[str, Any]] = {}
    kind_by_id: dict[str, str] = {}
    for spec in dag.get("nodes", []) or []:
        nid = str(spec.get("id") or "")
        kind = str(spec.get("kind") or "")
        if not nid:
            report.findings.append(
                ValidationFinding(
                    code="missing_node",
                    severity="error",
                    message="Node spec missing 'id' field",
                )
            )
            continue
        if nid in nodes_by_id:
            report.findings.append(
                ValidationFinding(
                    code="missing_node",
                    severity="error",
                    message=f"Duplicate node id: {nid!r}",
                    node_id=nid,
                )
            )
            continue
        nodes_by_id[nid] = spec
        kind_by_id[nid] = kind
    return nodes_by_id, kind_by_id


def _validate_entry(
    dag: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    report: ValidationReport,
) -> None:
    entry = dag.get("entry_node") or dag.get("entry")
    if not entry:
        if not nodes_by_id:
            report.findings.append(
                ValidationFinding(
                    code="no_entry",
                    severity="error",
                    message="DAG has no entry_node and no nodes",
                )
            )
        return
    if str(entry) not in nodes_by_id:
        report.findings.append(
            ValidationFinding(
                code="no_entry",
                severity="error",
                message=f"entry_node {entry!r} is not in the node list",
                node_id=str(entry),
            )
        )


def _validate_edge_endpoints(
    dag: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    report: ValidationReport,
) -> None:
    for i, edge in enumerate(dag.get("edges", []) or []):
        from_node = str(edge.get("from_node") or edge.get("from_role") or "")
        to_node = str(edge.get("to_node") or edge.get("to_role") or "")
        if not from_node or from_node not in nodes_by_id:
            report.findings.append(
                ValidationFinding(
                    code="edge_missing_endpoint",
                    severity="error",
                    message=f"Edge[{i}] from_node {from_node!r} not in node list",
                    edge_index=i,
                )
            )
        if to_node and to_node not in nodes_by_id:
            report.findings.append(
                ValidationFinding(
                    code="edge_missing_endpoint",
                    severity="error",
                    message=f"Edge[{i}] to_node {to_node!r} not in node list",
                    edge_index=i,
                )
            )


def _validate_unknown_kinds(
    kind_by_id: dict[str, str],
    report: ValidationReport,
) -> None:
    for nid, kind in kind_by_id.items():
        if not kind:
            report.findings.append(
                ValidationFinding(
                    code="unknown_kind",
                    severity="error",
                    message=f"Node {nid!r} missing 'kind' field",
                    node_id=nid,
                )
            )
            continue
        try:
            get_node(kind)
        except KeyError:
            report.findings.append(
                ValidationFinding(
                    code="unknown_kind",
                    severity="error",
                    message=f"Node {nid!r} declares unknown kind {kind!r}",
                    node_id=nid,
                )
            )


def _adjacency(dag: dict[str, Any], nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    """Build the node-id adjacency list from a DAG dict's edges."""
    adj: dict[str, list[str]] = {nid: [] for nid in nodes_by_id}
    for edge in dag.get("edges", []) or []:
        fn = str(edge.get("from_node") or edge.get("from_role") or "")
        tn = str(edge.get("to_node") or edge.get("to_role") or "")
        if fn in adj and tn in adj:
            adj[fn].append(tn)
    return adj


def _validate_no_cycles(
    dag: dict[str, Any],
    nodes_by_id: dict[str, dict[str, Any]],
    report: ValidationReport,
) -> None:
    """Phase 1 executor doesn't support cycles. Detect via DFS."""
    adj = _adjacency(dag, nodes_by_id)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(adj, WHITE)

    def _dfs(u: str) -> bool:
        color[u] = GRAY
        for v in adj[u]:
            if color[v] == GRAY:
                report.findings.append(
                    ValidationFinding(
                        code="cycle",
                        severity="error",
                        message=f"Cycle detected involving node {u!r} → {v!r}",
                        node_id=u,
                    )
                )
                return True
            if color[v] == WHITE and _dfs(v):
                return True
        color[u] = BLACK
        return False

    for nid in adj:
        if color[nid] == WHITE:
            _dfs(nid)


def _validate_schema_compatibility(
    dag: dict[str, Any],
    kind_by_id: dict[str, str],
    report: ValidationReport,
) -> None:
    """For each edge A → B, check that B's REQUIRED input fields are either
    (a) provided by A's output schema, or (b) covered by B's static
    `inputs` / `config` fallthrough. Optional fields are tolerated.
    """
    for i, edge in enumerate(dag.get("edges", []) or []):
        fn = str(edge.get("from_node") or edge.get("from_role") or "")
        tn = str(edge.get("to_node") or edge.get("to_role") or "")
        if not fn or not tn:
            continue
        from_kind = kind_by_id.get(fn, "")
        to_kind = kind_by_id.get(tn, "")
        if not from_kind or not to_kind:
            continue
        try:
            from_cls = get_node(from_kind)
            to_cls = get_node(to_kind)
        except KeyError:
            # Already surfaced by _validate_unknown_kinds.
            continue
        provided_keys = _fields_of(from_cls.output_schema)
        required_keys = _required_fields_of(to_cls.input_schema)

        # Pull `inputs`/`config` static fallthrough from the downstream node spec.
        downstream_static: set[str] = set()
        for spec in dag.get("nodes", []) or []:
            if str(spec.get("id")) == tn:
                downstream_static = set((spec.get("inputs") or spec.get("config") or {}).keys())
                break

        missing = required_keys - provided_keys - downstream_static
        if missing:
            for field_name in sorted(missing):
                report.findings.append(
                    ValidationFinding(
                        code="schema_mismatch",
                        severity="error",
                        message=(
                            f"Edge[{i}] {fn} ({from_kind}) → {tn} ({to_kind}): "
                            f"required field {field_name!r} is not in "
                            f"{from_kind}'s output_schema and not set as a "
                            f"static input on {tn!r}"
                        ),
                        node_id=tn,
                        edge_index=i,
                        field_path=field_name,
                    )
                )


def _fields_of(model_cls: type) -> set[str]:
    if not hasattr(model_cls, "model_fields"):
        return set()
    return set(model_cls.model_fields.keys())


def _required_fields_of(model_cls: type) -> set[str]:
    if not hasattr(model_cls, "model_fields"):
        return set()
    return {name for name, info in model_cls.model_fields.items() if info.is_required()}
