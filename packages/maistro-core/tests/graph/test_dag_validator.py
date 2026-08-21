"""Tests for the DAG validator (structure + schema compatibility)."""

from __future__ import annotations

import contextlib
from dataclasses import FrozenInstanceError
from typing import ClassVar

import pytest
from pydantic import BaseModel

from maistro.graph.dag_validator import (
    ValidationFinding,
    validate_dag,
)
from maistro.graph.nodes import BaseNode, NodeContext, register_node

# --- Fixture nodes for the validator tests --------------------------------


class _AIn(BaseModel):
    a_in: str


class _AOut(BaseModel):
    a_out: str  # downstream's required field


class _ANode(BaseNode[_AIn, _AOut]):
    kind: ClassVar[str] = "test.validator_a"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _AIn
    output_schema: ClassVar[type[BaseModel]] = _AOut

    async def _execute(self, inputs: _AIn, ctx: NodeContext) -> _AOut:
        return _AOut(a_out=inputs.a_in)


class _BIn(BaseModel):
    a_out: str
    optional_field: str = "default"


class _BOut(BaseModel):
    b_result: str


class _BNode(BaseNode[_BIn, _BOut]):
    kind: ClassVar[str] = "test.validator_b"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _BIn
    output_schema: ClassVar[type[BaseModel]] = _BOut

    async def _execute(self, inputs: _BIn, ctx: NodeContext) -> _BOut:
        return _BOut(b_result=inputs.a_out)


class _CIn(BaseModel):
    requires_a_field_a_doesnt_have: str  # forces schema_mismatch on edge A→C


class _COut(BaseModel):
    c_result: str


class _CNode(BaseNode[_CIn, _COut]):
    kind: ClassVar[str] = "test.validator_c"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = _CIn
    output_schema: ClassVar[type[BaseModel]] = _COut

    async def _execute(self, inputs: _CIn, ctx: NodeContext) -> _COut:
        return _COut(c_result=inputs.requires_a_field_a_doesnt_have)


for _cls in (_ANode, _BNode, _CNode):
    with contextlib.suppress(ValueError):
        register_node(_cls)


# --- Valid DAG passes -----------------------------------------------------


def test_valid_minimal_dag_passes() -> None:
    dag = {
        "id": "ok",
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "b", "kind": "test.validator_b"},
        ],
        "edges": [{"from_node": "a", "to_node": "b"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert report.is_valid
    assert report.error_count == 0
    assert report.findings == []


def test_empty_nodes_with_no_entry_flags_no_entry() -> None:
    report = validate_dag({"nodes": [], "edges": []})
    assert not report.is_valid
    codes = {f.code for f in report.findings}
    assert "no_entry" in codes


def test_entry_node_not_in_node_list_flagged() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "test.validator_a"}],
        "edges": [],
        "entry_node": "nonexistent",
    }
    report = validate_dag(dag)
    assert not report.is_valid
    no_entry = [f for f in report.findings if f.code == "no_entry"]
    assert len(no_entry) == 1
    assert no_entry[0].node_id == "nonexistent"


# --- Structure failures ---------------------------------------------------


def test_duplicate_node_id_flagged() -> None:
    dag = {
        "nodes": [
            {"id": "x", "kind": "test.validator_a"},
            {"id": "x", "kind": "test.validator_a"},
        ],
        "edges": [],
        "entry_node": "x",
    }
    report = validate_dag(dag)
    assert any(f.code == "missing_node" and "Duplicate" in f.message for f in report.findings)


def test_node_missing_id_flagged() -> None:
    dag = {
        "nodes": [{"kind": "test.validator_a"}],
        "edges": [],
    }
    report = validate_dag(dag)
    assert any(f.code == "missing_node" and "missing 'id'" in f.message for f in report.findings)


def test_unknown_kind_flagged() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "nonexistent.kind"}],
        "edges": [],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert any(f.code == "unknown_kind" for f in report.findings)


def test_missing_kind_flagged() -> None:
    dag = {
        "nodes": [{"id": "a"}],  # no kind
        "edges": [],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert any(f.code == "unknown_kind" and "missing 'kind'" in f.message for f in report.findings)


def test_edge_with_unknown_endpoint_flagged() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "test.validator_a"}],
        "edges": [{"from_node": "a", "to_node": "ghost"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    edge_errors = [f for f in report.findings if f.code == "edge_missing_endpoint"]
    assert len(edge_errors) == 1
    assert "ghost" in edge_errors[0].message


def test_edge_with_unknown_from_endpoint_flagged() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "test.validator_a"}],
        "edges": [{"from_node": "ghost", "to_node": "a"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert any(f.code == "edge_missing_endpoint" and "ghost" in f.message for f in report.findings)


def test_cycle_detection() -> None:
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "b", "kind": "test.validator_b"},
        ],
        "edges": [
            {"from_node": "a", "to_node": "b"},
            {"from_node": "b", "to_node": "a"},  # cycle
        ],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert not report.is_valid
    assert any(f.code == "cycle" for f in report.findings)


# --- Schema-compatibility failures ----------------------------------------


def test_schema_mismatch_on_incompatible_edge_flagged() -> None:
    """A → C where C requires a field A does not produce → flag."""
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "c", "kind": "test.validator_c"},
        ],
        "edges": [{"from_node": "a", "to_node": "c"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert not report.is_valid
    mismatches = [f for f in report.findings if f.code == "schema_mismatch"]
    assert len(mismatches) == 1
    assert mismatches[0].field_path == "requires_a_field_a_doesnt_have"
    assert mismatches[0].node_id == "c"
    assert mismatches[0].edge_index == 0


def test_schema_mismatch_recovered_when_static_inputs_provide_field() -> None:
    """Even when A doesn't produce the required field, the downstream
    node's static `inputs` can satisfy it → no error."""
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {
                "id": "c",
                "kind": "test.validator_c",
                "inputs": {"requires_a_field_a_doesnt_have": "static-fill"},
            },
        ],
        "edges": [{"from_node": "a", "to_node": "c"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert report.is_valid, [f.message for f in report.findings]


def test_optional_fields_not_required() -> None:
    """B has 'optional_field' with a default; A→B should pass even though
    A doesn't produce it."""
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "b", "kind": "test.validator_b"},
        ],
        "edges": [{"from_node": "a", "to_node": "b"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert report.is_valid


# --- Report serialization -------------------------------------------------


def test_report_to_dict_shape() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "test.validator_a"}],
        "edges": [{"from_node": "a", "to_node": "ghost"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    out = report.to_dict()
    assert out["is_valid"] is False
    assert out["error_count"] == 1
    assert len(out["findings"]) == 1
    finding = out["findings"][0]
    assert finding["code"] == "edge_missing_endpoint"
    assert finding["severity"] == "error"
    assert finding["edge_index"] == 0


def test_validation_finding_immutable() -> None:
    f = ValidationFinding(code="x", severity="error", message="m")
    with pytest.raises(FrozenInstanceError):
        f.code = "y"  # type: ignore[misc]


def test_empty_dag_with_explicit_entry_no_nodes_has_no_entry_finding() -> None:
    """Edge case: entry_node set but nodes is empty."""
    dag = {"nodes": [], "edges": [], "entry_node": "phantom"}
    report = validate_dag(dag)
    assert not report.is_valid
    assert any(f.code == "no_entry" for f in report.findings)


def test_edge_with_to_role_alias_accepted() -> None:
    """`to_role` / `from_role` aliases (engineering-domain shape) work."""
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "b", "kind": "test.validator_b"},
        ],
        "edges": [{"from_role": "a", "to_role": "b"}],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert report.is_valid


def test_alias_keys_in_edges_get_used_for_cycle_detection() -> None:
    """Cycles must be detected even when alias keys (from_role/to_role)
    are used in place of from_node/to_node."""
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "b", "kind": "test.validator_b"},
        ],
        "edges": [
            {"from_role": "a", "to_role": "b"},
            {"from_role": "b", "to_role": "a"},
        ],
        "entry_node": "a",
    }
    report = validate_dag(dag)
    assert not report.is_valid
    assert any(f.code == "cycle" for f in report.findings)


def test_self_cycle_reports_exact_cycle_finding() -> None:
    dag = {
        "nodes": [{"id": "a", "kind": "test.validator_a"}],
        "edges": [{"from_node": "a", "to_node": "a"}],
        "entry_node": "a",
    }

    report = validate_dag(dag)

    cycles = [f for f in report.findings if f.code == "cycle"]
    assert len(cycles) == 1
    assert cycles[0].severity == "error"
    assert cycles[0].node_id == "a"
    assert "a" in cycles[0].message


def test_multiple_failures_have_stable_finding_codes_and_locations() -> None:
    dag = {
        "nodes": [
            {"id": "a", "kind": "test.validator_a"},
            {"id": "c", "kind": "test.validator_c"},
            {"id": "ghost-kind", "kind": "missing.kind"},
        ],
        "edges": [
            {"from_node": "a", "to_node": "c"},
            {"from_node": "a", "to_node": "missing-node"},
        ],
        "entry_node": "a",
    }

    report = validate_dag(dag)

    observed = [(f.code, f.node_id, f.edge_index, f.field_path) for f in report.findings]
    assert observed == [
        ("edge_missing_endpoint", None, 1, None),
        ("unknown_kind", "ghost-kind", None, None),
        ("schema_mismatch", "c", 0, "requires_a_field_a_doesnt_have"),
    ]
