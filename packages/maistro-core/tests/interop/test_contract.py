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
    RelationshipSpec,
)

ROOT = Path(__file__).resolve().parents[4]
PUBLISHED_ONTOLOGY = ROOT / "quality" / "shared-interop-ontology-v1.json"
pytestmark = [pytest.mark.contract("behavioral")]


def test_executable_contract_exactly_matches_published_v1_schema() -> None:
    published = json.loads(PUBLISHED_ONTOLOGY.read_text(encoding="utf-8"))

    assert INTEROP_ONTOLOGY_V1.as_dict() == published


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


def test_goal_projection_requires_exact_revision_identity() -> None:
    with pytest.raises(
        InteropContractError,
        match="Goal projection must carry canonical revision field 'goal_revision'",
    ):
        INTEROP_ONTOLOGY_V1.validate_projection("Goal", {"goal_id": "goal-1"})

    assert (
        INTEROP_ONTOLOGY_V1.validate_projection(
            "Goal",
            {"goal_id": "goal-1", "goal_revision": 3},
        )
        == "goal-1"
    )


def test_unknown_concept_is_rejected_instead_of_becoming_product_local_authority() -> None:
    with pytest.raises(InteropContractError, match="unknown interoperability concept"):
        INTEROP_ONTOLOGY_V1.validate_projection(
            "BuildersRun",
            {"run_id": "run-1"},
        )


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


def test_goal_scope_is_required_without_making_goal_a_graph_parent() -> None:
    with pytest.raises(
        InteropContractError,
        match="Goal reference requires canonical parent Project",
    ):
        INTEROP_ONTOLOGY_V1.validate_reference_set(
            {"Workspace": "ws-1", "Goal": "goal-1"}
        )

    INTEROP_ONTOLOGY_V1.validate_reference_set(
        {
            "Workspace": "ws-1",
            "Project": "project-1",
            "Graph": "graph-1",
        }
    )


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


def test_goal_relationships_keep_accountability_distinct_from_execution() -> None:
    goal = INTEROP_ONTOLOGY_V1.concept("Goal")
    agent = INTEROP_ONTOLOGY_V1.concept("Agent")

    assert goal.owner == "maistro.goals"
    assert goal.identity == "goal_id"
    assert goal.parent == "Project"
    assert goal.revision == "goal_revision"
    assert agent.owner == "maistro.agents"
    assert agent.scope == "Workspace"

    ownership = INTEROP_ONTOLOGY_V1.relationships["agent_goal_ownership"]
    assert ownership.source == "Agent"
    assert ownership.target == "Goal"
    assert ownership.kind == "accountability"
    assert ownership.sources_per_target == "exactly-one"

    selection = INTEROP_ONTOLOGY_V1.relationships["goal_graph_selection"]
    assert selection.kind == "execution-strategy"
    assert selection.sources_per_target == "zero-or-many"

    evidence = INTEROP_ONTOLOGY_V1.relationships["goal_run_evidence"]
    assert evidence.kind == "execution-evidence"
    assert evidence.sources_per_target == "zero-or-one"


def test_major_version_drift_fails_loudly() -> None:
    INTEROP_ONTOLOGY_V1.require_compatible("1.9.0")

    with pytest.raises(InteropContractError, match="incompatible"):
        INTEROP_ONTOLOGY_V1.require_compatible("2.0.0")

    with pytest.raises(InteropContractError, match=r"semantic x\.y\.z"):
        INTEROP_ONTOLOGY_V1.require_compatible("v1")


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


def test_contract_rejects_unknown_relationship_endpoints_and_cardinality() -> None:
    relationships = dict(INTEROP_ONTOLOGY_V1.relationships)
    relationships["broken"] = RelationshipSpec(
        "Missing",
        "Goal",
        "accountability",
        "exactly-one",
        "zero-or-many",
    )

    with pytest.raises(InteropContractError, match="source references unknown concept 'Missing'"):
        replace(INTEROP_ONTOLOGY_V1, relationships=relationships)

    relationships["broken"] = RelationshipSpec(
        "Agent",
        "Goal",
        "accountability",
        "sometimes",
        "zero-or-many",
    )
    with pytest.raises(InteropContractError, match="invalid sources_per_target 'sometimes'"):
        replace(INTEROP_ONTOLOGY_V1, relationships=relationships)


def test_contract_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        INTEROP_ONTOLOGY_V1.concepts["Run"] = ConceptSpec(  # type: ignore[index]
            owner="product.builders",
            identity="builders_run_id",
        )

    with pytest.raises(TypeError):
        INTEROP_ONTOLOGY_V1.relationships["goal_graph_selection"] = RelationshipSpec(  # type: ignore[index]
            "Goal",
            "Graph",
            "ownership",
            "exactly-one",
            "exactly-one",
        )


def test_constructor_rejects_noncanonical_owner_and_identity() -> None:
    with pytest.raises(InteropContractError, match="canonical maistro module"):
        InteropOntology(
            version="1.1.0",
            status="test",
            issue=458,
            principles=("one owner",),
            concepts={
                "Run": ConceptSpec(
                    owner="builders.run",
                    identity="run_id",
                )
            },
            relationships={},
            required_lineage=(),
            consumers={"builders": "M1"},
        )

    with pytest.raises(InteropContractError, match=r"explicit \*_id field"):
        InteropOntology(
            version="1.1.0",
            status="test",
            issue=458,
            principles=("one identity",),
            concepts={
                "Run": ConceptSpec(
                    owner="maistro.runs",
                    identity="id",
                )
            },
            relationships={},
            required_lineage=(),
            consumers={"builders": "M1"},
        )
