"""Contract tests for the versioned cross-product interoperability ontology (#458)."""

from __future__ import annotations

import json
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
    "Persona": "maistro.personas",
    "Template": "maistro.prompts",
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
    "Persona": "persona_id",
    "Template": "template_id",
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

    assert ontology["version"] == "1.0.0"
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


def test_execution_lineage_is_one_canonical_chain() -> None:
    lineage = _ontology()["required_lineage"]
    assert isinstance(lineage, list)

    expected_pairs = [list(pair) for pair in zip(EXPECTED_EXECUTION, EXPECTED_EXECUTION[1:])]
    assert all(pair in lineage for pair in expected_pairs)


def test_effect_lineage_is_one_canonical_chain() -> None:
    lineage = _ontology()["required_lineage"]
    assert isinstance(lineage, list)

    expected_pairs = [list(pair) for pair in zip(EXPECTED_EFFECT, EXPECTED_EFFECT[1:])]
    assert all(pair in lineage for pair in expected_pairs)


def test_rsi_is_a_later_consumer_not_an_m1_product_blocker() -> None:
    consumers = _ontology()["consumers"]
    assert isinstance(consumers, dict)

    assert consumers["builders"] == "M1"
    assert consumers["conductor"] == "M1"
    assert consumers["evolve"] == "M1"
    assert consumers["canvas_design"] == "M1"
    assert consumers["rsi"] == "M5"
