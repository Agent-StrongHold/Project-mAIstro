"""Contract tests for the versioned cross-product interoperability ontology (#458)."""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_PATH = ROOT / "quality" / "shared-interop-ontology-v1.json"

EXPECTED_EXECUTION = [
    "Workspace",
    "Project",
    "Graph",
    "Run",
    "NodeRun",
    "Attempt",
    "ExecutionRuntime",
]
EXPECTED_EFFECT = ["Capability", "Provider", "Binding", "Invocation"]
EXPECTED_OWNERS = {
    "Workspace": "maistro.workspaces",
    "Project": "maistro.projects",
    "Agent": "maistro.agents",
    "Persona": "maistro.personas",
    "Template": "maistro.prompts",
    "Goal": "maistro.goals",
    "Graph": "maistro.graph",
    "Run": "maistro.runs",
    "GraphExecutionState": "maistro.graph",
    "NodeRun": "maistro.runs",
    "Attempt": "maistro.runs",
    "ExecutionRuntime": "maistro.runtime",
    "Capability": "maistro.capabilities",
    "Provider": "maistro.capabilities",
    "Binding": "maistro.capabilities",
    "Invocation": "maistro.capabilities",
}
EXPECTED_IDENTITIES = {
    "Workspace": "workspace_id",
    "Project": "project_id",
    "Agent": "agent_id",
    "Persona": "persona_id",
    "Template": "template_id",
    "Goal": "goal_id",
    "Graph": "graph_id",
    "Run": "run_id",
    "GraphExecutionState": "run_id",
    "NodeRun": "node_run_id",
    "Attempt": "attempt_id",
    "ExecutionRuntime": "execution_id",
    "Capability": "capability_id",
    "Provider": "provider_id",
    "Binding": "binding_id",
    "Invocation": "invocation_id",
}


def _ontology() -> dict[str, object]:
    return json.loads(ONTOLOGY_PATH.read_text(encoding="utf-8"))


def test_ontology_is_explicitly_versioned_v1() -> None:
    ontology = _ontology()

    assert ontology["version"] == "1.1.0"
    assert ontology["issue"] == 458
    assert ontology["status"] == "m1-freeze-candidate"


def test_every_shared_concept_has_the_frozen_owner_and_identity() -> None:
    concepts = _ontology()["concepts"]
    assert isinstance(concepts, dict)

    assert set(concepts) == set(EXPECTED_OWNERS)
    for name, owner in EXPECTED_OWNERS.items():
        definition = concepts[name]
        assert isinstance(definition, dict)
        assert definition["owner"] == owner
        assert definition["identity"] == EXPECTED_IDENTITIES[name]


def test_goal_is_project_scoped_versioned_accountability_not_execution() -> None:
    ontology = _ontology()
    concepts = ontology["concepts"]
    relationships = ontology["relationships"]
    lineage = ontology["required_lineage"]
    assert isinstance(concepts, dict)
    assert isinstance(relationships, dict)
    assert isinstance(lineage, list)

    assert concepts["Goal"]["parent"] == "Project"
    assert concepts["Goal"]["revision"] == "goal_revision"
    assert ["Project", "Goal"] in lineage
    assert ["Goal", "Graph"] not in lineage

    ownership = relationships["agent_goal_ownership"]
    assert ownership["source"] == "Agent"
    assert ownership["target"] == "Goal"
    assert ownership["kind"] == "accountability"
    assert ownership["sources_per_target"] == "exactly-one"

    selection = relationships["goal_graph_selection"]
    assert selection["kind"] == "execution-strategy"
    assert selection["sources_per_target"] == "zero-or-many"


def test_execution_lineage_is_one_canonical_physical_chain() -> None:
    lineage = _ontology()["required_lineage"]
    assert isinstance(lineage, list)

    expected_pairs = [list(pair) for pair in pairwise(EXPECTED_EXECUTION)]
    assert all(pair in lineage for pair in expected_pairs)


def test_effect_lineage_is_one_canonical_chain() -> None:
    lineage = _ontology()["required_lineage"]
    assert isinstance(lineage, list)

    expected_pairs = [list(pair) for pair in pairwise(EXPECTED_EFFECT)]
    assert all(pair in lineage for pair in expected_pairs)


def test_later_consumers_are_explicit_without_becoming_m1_blockers() -> None:
    consumers = _ontology()["consumers"]
    assert isinstance(consumers, dict)

    assert consumers["builders"] == "M1"
    assert consumers["conductor"] == "M1"
    assert consumers["evolve"] == "M1"
    assert consumers["canvas_design"] == "M1"
    assert consumers["workspace_agent"] == "M3"
    assert consumers["design_studio"] == "M3"
    assert consumers["rsi"] == "M5"
