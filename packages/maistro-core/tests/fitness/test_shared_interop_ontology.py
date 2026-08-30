"""Executable conformance for the M1 cross-product interoperability ontology.

#471 published the versioned contract. These tests make that contract a
blocking architecture-fitness surface without creating another runtime model.
Cross-product behavioural parity remains owned by #459.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

import pytest

pytestmark = [pytest.mark.contract("boundary"), pytest.mark.scope("unit")]

_ROOT = Path(__file__).resolve().parents[4]
_CONTRACT_PATH = _ROOT / "quality" / "shared-interop-ontology-v1.json"
_DOC_PATH = _ROOT / "docs" / "architecture" / "INTEROP-ONTOLOGY-v1.md"

_EXECUTION_CHAIN = (
    "Workspace",
    "Project",
    "Graph",
    "Run",
    "NodeRun",
    "Attempt",
    "ExecutionRuntime",
)
_EFFECT_CHAIN = ("Capability", "Provider", "Binding", "Invocation")
_EXPECTED_LINEAGE = tuple(
    [
        *zip(_EXECUTION_CHAIN, _EXECUTION_CHAIN[1:]),
        *zip(_EFFECT_CHAIN, _EFFECT_CHAIN[1:]),
    ]
)

_EXPECTED_CONCEPTS: dict[str, dict[str, str]] = {
    "Workspace": {"owner": "maistro.workspaces", "identity": "workspace_id"},
    "Project": {
        "owner": "maistro.projects",
        "identity": "project_id",
        "parent": "Workspace",
    },
    "Persona": {"owner": "maistro.personas", "identity": "persona_id"},
    "Template": {"owner": "maistro.prompts", "identity": "template_id"},
    "Graph": {
        "owner": "maistro.graph",
        "identity": "graph_id",
        "scope": "Project",
    },
    "Run": {
        "owner": "maistro.runs",
        "identity": "run_id",
        "scope": "Project",
        "parent": "Graph",
    },
    "GraphExecutionState": {
        "owner": "maistro.graph",
        "identity": "run_id",
        "parent": "Run",
    },
    "NodeRun": {
        "owner": "maistro.runs",
        "identity": "node_run_id",
        "parent": "Run",
    },
    "Attempt": {
        "owner": "maistro.runs",
        "identity": "attempt_id",
        "parent": "NodeRun",
    },
    "ExecutionRuntime": {
        "owner": "maistro.runtime",
        "identity": "execution_id",
        "parent": "Attempt",
    },
    "Capability": {
        "owner": "maistro.capabilities",
        "identity": "capability_id",
    },
    "Provider": {
        "owner": "maistro.capabilities",
        "identity": "provider_id",
        "parent": "Capability",
    },
    "Binding": {
        "owner": "maistro.capabilities",
        "identity": "binding_id",
        "parent": "Provider",
    },
    "Invocation": {
        "owner": "maistro.capabilities",
        "identity": "invocation_id",
        "parent": "Binding",
    },
}

_REQUIRED_PRINCIPLES = frozenset(
    {
        "one canonical identity per shared concept",
        "product-local DTOs may project but may not redefine shared semantics",
        "cross-product references use canonical IDs",
        "ownership and execution lineage survive product boundaries",
        "contract evolution is explicit and versioned",
    }
)
_REQUIRED_CONSUMERS = {
    "builders": "M1",
    "conductor": "M1",
    "evolve": "M1",
    "canvas_design": "M1",
    "rsi": "M5",
}
_OWNER_RE = re.compile(r"^maistro(?:\.[a-z_][a-z0-9_]*)+$")
_ID_RE = re.compile(r"^[a-z][a-z0-9_]*_id$")
_VERSION_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)$")
_TABLE_ROW_RE = re.compile(
    r"^\|\s*([A-Za-z][A-Za-z0-9]*)\s*\|\s*`([^`]+)`\s*\|\s*`([^`]+)`\s*\|",
    re.MULTILINE,
)


def _load_contract() -> dict[str, Any]:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def _lineage(contract: Mapping[str, Any]) -> list[tuple[str, str]]:
    raw = contract.get("required_lineage")
    if not isinstance(raw, list):
        return []

    edges: list[tuple[str, str]] = []
    for edge in raw:
        valid = (
            isinstance(edge, list)
            and len(edge) == 2
            and all(isinstance(item, str) for item in edge)
        )
        if valid:
            edges.append((edge[0], edge[1]))
    return edges


def _metadata_drift(
    concepts: Mapping[str, Any],
    name: str,
    expected: Mapping[str, str],
) -> str | None:
    actual = concepts.get(name)
    if not isinstance(actual, dict):
        return f"{name} canonical metadata is missing or not an object"

    drift = {
        key: (value, actual.get(key))
        for key, value in expected.items()
        if actual.get(key) != value
    }
    if not drift:
        return None
    return f"{name} canonical metadata drifted: {drift!r}"


def _contract_failures(contract: Mapping[str, Any]) -> list[str]:
    """Return stable, reviewable violations of the v1 shared contract."""
    failures: list[str] = []

    version = contract.get("version")
    match = _VERSION_RE.fullmatch(version) if isinstance(version, str) else None
    if match is None:
        failures.append("version must be semantic MAJOR.MINOR.PATCH")
    elif match.group(1) != "1":
        failures.append("ontology-v1 contract must retain major version 1")

    if contract.get("issue") != 458:
        failures.append("issue owner must remain #458 for ontology v1")

    principles = contract.get("principles")
    if not isinstance(principles, list):
        failures.append("principles must be a list")
    elif not _REQUIRED_PRINCIPLES.issubset(set(principles)):
        failures.append("required interoperability principles are missing")

    concepts = contract.get("concepts")
    if not isinstance(concepts, dict):
        return [*failures, "concepts must be an object"]

    for name, expected in _EXPECTED_CONCEPTS.items():
        if drift := _metadata_drift(concepts, name, expected):
            failures.append(drift)

    for name, metadata in concepts.items():
        if not isinstance(name, str) or not isinstance(metadata, dict):
            failures.append(f"invalid concept entry: {name!r}")
            continue

        owner = metadata.get("owner")
        identity = metadata.get("identity")
        if not isinstance(owner, str) or _OWNER_RE.fullmatch(owner) is None:
            failures.append(f"{name} has invalid canonical owner {owner!r}")
        if not isinstance(identity, str) or _ID_RE.fullmatch(identity) is None:
            failures.append(f"{name} has invalid canonical identity {identity!r}")

        for relation in ("parent", "scope"):
            target = metadata.get(relation)
            if target is not None and target not in concepts:
                failures.append(f"{name}.{relation} references unknown concept {target!r}")

    edges = _lineage(contract)
    raw_lineage = contract.get("required_lineage")
    if not isinstance(raw_lineage, list) or len(edges) != len(raw_lineage):
        failures.append("required_lineage must contain only two-concept edges")
    if len(edges) != len(set(edges)):
        failures.append("required_lineage contains duplicate edges")

    expected_edges = set(_EXPECTED_LINEAGE)
    actual_edges = set(edges)
    if actual_edges != expected_edges:
        failures.append(
            "required_lineage drifted: "
            f"missing={sorted(expected_edges - actual_edges)!r} "
            f"unexpected={sorted(actual_edges - expected_edges)!r}"
        )

    for parent, child in edges:
        if parent not in concepts or child not in concepts:
            failures.append(f"lineage edge references unknown concept: {parent} -> {child}")
            continue

        child_metadata = concepts[child]
        if not isinstance(child_metadata, dict):
            continue
        if child_metadata.get("parent") != parent and child_metadata.get("scope") != parent:
            failures.append(
                f"lineage edge {parent} -> {child} disagrees with "
                f"{child} parent/scope metadata"
            )

    graph_state = concepts.get("GraphExecutionState")
    run = concepts.get("Run")
    if isinstance(graph_state, dict) and isinstance(run, dict):
        same_run_identity = graph_state.get("identity") == run.get("identity")
        if not same_run_identity or graph_state.get("parent") != "Run":
            failures.append(
                "GraphExecutionState must remain traversal state keyed by the Run identity"
            )
    if any("GraphExecutionState" in edge for edge in edges):
        failures.append("GraphExecutionState must not become a second execution lifecycle edge")

    consumers = contract.get("consumers")
    if not isinstance(consumers, dict):
        failures.append("consumers must be an object")
    else:
        for consumer, milestone in _REQUIRED_CONSUMERS.items():
            if consumers.get(consumer) != milestone:
                failures.append(f"consumer {consumer} must remain assigned to {milestone}")

    return failures


def _documentation_failures(contract: Mapping[str, Any], text: str) -> list[str]:
    """Keep the human contract and machine-readable contract semantically identical."""
    failures: list[str] = []
    concepts = contract.get("concepts")
    if not isinstance(concepts, dict):
        return ["cannot compare docs without concept metadata"]

    rows = {
        name: (owner, identity)
        for name, owner, identity in _TABLE_ROW_RE.findall(text)
    }
    expected_rows = {
        name: (metadata.get("owner"), metadata.get("identity"))
        for name, metadata in concepts.items()
        if isinstance(metadata, dict)
    }
    if rows != expected_rows:
        missing_or_changed = sorted(set(expected_rows.items()) - set(rows.items()))
        unexpected = sorted(set(rows.items()) - set(expected_rows.items()))
        failures.append(
            "documented concept table drifted from machine contract: "
            f"missing_or_changed={missing_or_changed!r} unexpected={unexpected!r}"
        )

    execution = " → ".join(_EXECUTION_CHAIN)
    effects = " → ".join(_EFFECT_CHAIN)
    if execution not in text:
        failures.append("documented canonical execution chain is missing or changed")
    if effects not in text:
        failures.append("documented canonical governed-effect chain is missing or changed")
    if "#459" not in text:
        failures.append("documentation must delegate live cross-product parity to #459")
    return failures


def test_live_shared_ontology_is_self_consistent() -> None:
    contract = _load_contract()
    assert not (failures := _contract_failures(contract)), "\n".join(failures)


def test_live_shared_ontology_documentation_matches_machine_contract() -> None:
    contract = _load_contract()
    text = _DOC_PATH.read_text(encoding="utf-8")
    assert not (failures := _documentation_failures(contract, text)), "\n".join(failures)


def test_validator_rejects_non_semantic_version() -> None:
    contract = _load_contract()
    contract["version"] = "v1"
    assert any("semantic" in failure for failure in _contract_failures(contract))


def test_validator_rejects_canonical_owner_and_identity_drift() -> None:
    owner_drift = _load_contract()
    owner_drift["concepts"]["Run"]["owner"] = "maistro.builders"
    owner_failures = _contract_failures(owner_drift)
    assert any("Run canonical metadata drifted" in failure for failure in owner_failures)

    identity_drift = _load_contract()
    identity_drift["concepts"]["Run"]["identity"] = "builder_run_id"
    identity_failures = _contract_failures(identity_drift)
    assert any("Run canonical metadata drifted" in failure for failure in identity_failures)


def test_validator_rejects_unknown_lineage_concept() -> None:
    contract = _load_contract()
    contract["required_lineage"].append(["Run", "PrivateRun"])
    failures = _contract_failures(contract)
    assert any("unknown concept" in failure for failure in failures)
    assert any("required_lineage drifted" in failure for failure in failures)


def test_validator_rejects_duplicate_lineage_edge() -> None:
    contract = _load_contract()
    contract["required_lineage"].append(["Run", "NodeRun"])
    failures = _contract_failures(contract)
    assert any("duplicate edges" in failure for failure in failures)


def test_validator_rejects_lineage_metadata_disagreement() -> None:
    contract = _load_contract()
    contract["concepts"]["Provider"]["parent"] = "Workspace"
    failures = _contract_failures(contract)
    assert any("Provider canonical metadata drifted" in failure for failure in failures)
    assert any("Capability -> Provider disagrees" in failure for failure in failures)


def test_validator_rejects_missing_required_consumer() -> None:
    contract = _load_contract()
    del contract["consumers"]["conductor"]
    failures = _contract_failures(contract)
    assert any("consumer conductor" in failure for failure in failures)


def test_validator_rejects_documentation_drift() -> None:
    contract = _load_contract()
    text = _DOC_PATH.read_text(encoding="utf-8")
    drifted = text.replace(
        "`maistro.runs` | `run_id`",
        "`maistro.builders` | `builder_run_id`",
        1,
    )
    failures = _documentation_failures(contract, drifted)
    assert any("concept table drifted" in failure for failure in failures)
