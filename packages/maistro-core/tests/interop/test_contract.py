"""Behavioral contract tests for the executable interoperability ontology (#458)."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from maistro.interop import (
    INTEROP_ONTOLOGY_V1,
    ConceptSpec,
    InteropContractError,
    InteropOntology,
)

ROOT = Path(__file__).resolve().parents[4]
PUBLISHED_ONTOLOGY = ROOT / "quality" / "shared-interop-ontology-v1.json"


@pytest.mark.behavioral
def test_executable_contract_exactly_matches_published_v1_schema() -> None:
    published = json.loads(PUBLISHED_ONTOLOGY.read_text(encoding="utf-8"))

    assert INTEROP_ONTOLOGY_V1.as_dict() == published


@pytest.mark.behavioral
def test_projection_requires_the_canonical_identity_field() -> None:
    with pytest.raises(
        InteropContractError,
        match="Run projection must carry canonical identity field 'run_id'",
    ):
        INTEROP_ONTOLOGY_V1.validate_projection(
            "Run",
            {"graph_id": "graph-1", "project_id": "project-1"},
        )

    assert (
        INTEROP_ONTOLOGY_V1.validate_projection(
            "Run",
            {
                "run_id": "run-1",
                "graph_id": "graph-1",
                "project_id": "project-1",
            },
        )
        == "run-1"
    )


@pytest.mark.behavioral
def test_unknown_concept_is_rejected_instead_of_becoming_product_local_authority() -> None:
    with pytest.raises(InteropContractError, match="unknown interoperability concept"):
        INTEROP_ONTOLOGY_V1.validate_projection(
            "BuildersRun",
            {"run_id": "run-1"},
        )


@pytest.mark.behavioral
def test_reference_set_requires_execution_parent_and_scope_lineage() -> None:
    with pytest.raises(
        InteropContractError,
        match="Run reference requires canonical parent Graph",
    ):
        INTEROP_ONTOLOGY_V1.validate_reference_set(
            {"Workspace": "ws-1", "Project": "project-1", "Run": "run-1"}
        )

    INTEROP_ONTOLOGY_V1.validate_reference_set(
        {
            "Workspace": "ws-1",
            "Project": "project-1",
            "Graph": "graph-1",
            "Run": "run-1",
            "NodeRun": "node-run-1",
            "Attempt": "attempt-1",
            "ExecutionRuntime": "execution-1",
        }
    )


@pytest.mark.behavioral
def test_reference_set_requires_effect_lineage() -> None:
    with pytest.raises(
        InteropContractError,
        match="Invocation reference requires canonical parent Binding",
    ):
        INTEROP_ONTOLOGY_V1.validate_reference_set(
            {"Capability": "cap-1", "Provider": "provider-1", "Invocation": "inv-1"}
        )

    INTEROP_ONTOLOGY_V1.validate_reference_set(
        {
            "Capability": "cap-1",
            "Provider": "provider-1",
            "Binding": "binding-1",
            "Invocation": "invocation-1",
        }
    )


@pytest.mark.behavioral
def test_major_version_drift_fails_loudly() -> None:
    INTEROP_ONTOLOGY_V1.require_compatible("1.9.0")

    with pytest.raises(InteropContractError, match="incompatible"):
        INTEROP_ONTOLOGY_V1.require_compatible("2.0.0")

    with pytest.raises(InteropContractError, match="semantic x.y.z"):
        INTEROP_ONTOLOGY_V1.require_compatible("v1")


@pytest.mark.behavioral
def test_contract_rejects_broken_required_lineage_at_construction() -> None:
    with pytest.raises(
        InteropContractError,
        match="Run declares parent 'Graph' without required lineage",
    ):
        replace(
            INTEROP_ONTOLOGY_V1,
            required_lineage=tuple(
                edge
                for edge in INTEROP_ONTOLOGY_V1.required_lineage
                if edge != ("Graph", "Run")
            ),
        )


@pytest.mark.behavioral
def test_contract_rejects_unknown_parent_or_scope_concepts() -> None:
    concepts = dict(INTEROP_ONTOLOGY_V1.concepts)
    concepts["Run"] = ConceptSpec(
        owner="maistro.runs",
        identity="run_id",
        parent="Graph",
        scope="Tenant",
    )

    with pytest.raises(InteropContractError, match="scope references unknown concept 'Tenant'"):
        replace(INTEROP_ONTOLOGY_V1, concepts=concepts)


@pytest.mark.behavioral
def test_contract_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        INTEROP_ONTOLOGY_V1.concepts["Run"] = ConceptSpec(  # type: ignore[index]
            owner="product.builders",
            identity="builders_run_id",
        )


def test_constructor_rejects_noncanonical_owner_and_identity() -> None:
    with pytest.raises(InteropContractError, match="canonical maistro module"):
        InteropOntology(
            version="1.0.0",
            status="test",
            issue=458,
            principles=("one owner",),
            concepts={
                "Run": ConceptSpec(
                    owner="builders.run",
                    identity="run_id",
                )
            },
            required_lineage=(),
            consumers={"builders": "M1"},
        )

    with pytest.raises(InteropContractError, match=r"explicit \*_id field"):
        InteropOntology(
            version="1.0.0",
            status="test",
            issue=458,
            principles=("one identity",),
            concepts={
                "Run": ConceptSpec(
                    owner="maistro.runs",
                    identity="id",
                )
            },
            required_lineage=(),
            consumers={"builders": "M1"},
        )
