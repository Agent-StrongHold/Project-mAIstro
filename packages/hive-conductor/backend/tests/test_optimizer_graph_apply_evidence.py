"""Live optimizer graph apply fails closed without governed evidence (#861, #854).

``_apply_topology_mutation`` is the function that writes an accepted topology
edit onto the stored DAG. It used to succeed with no candidate id and with a
single sample. It now refuses unless the evidence record names a candidate,
at least two independent results, and the incumbent.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

_DAG_ID = "dag-apply-evidence"
_PROPOSAL_ID = "prop-apply-evidence"


def _evidence(**overrides: Any) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "candidate_id": "candidate-7",
        "incumbent_id": "incumbent-1",
        "independent_results": [
            {"result_id": "run-a", "score": 0.4},
            {"result_id": "run-b", "score": 0.9},
        ],
    }
    evidence.update(overrides)
    return evidence


def _proposal(evidence: Any = None, *, include_evidence: bool = True) -> dict[str, Any]:
    proposal: dict[str, Any] = {
        "id": _PROPOSAL_ID,
        "dag_id": _DAG_ID,
        "kind": "topology_mutation",
        "decision": "pending",
        "topology_proposal": {
            "kind": "swap_model",
            "target_node_id": "n1",
            "to_value": "new-model",
        },
    }
    if include_evidence:
        proposal["evidence"] = _evidence() if evidence is None else evidence
    return proposal


def _seed_dag() -> None:
    import stores

    stores.dags[_DAG_ID] = {
        "id": _DAG_ID,
        "nodes": [{"id": "n1", "model": "old-model", "prompt": "hi"}],
        "edges": [],
    }


def _model() -> str:
    import stores

    return str(stores.dags[_DAG_ID]["nodes"][0]["model"])


@pytest.fixture
def dag() -> Any:
    import stores

    _seed_dag()
    stores.optimizer_proposals.pop(_PROPOSAL_ID, None)
    yield
    stores.dags.pop(_DAG_ID, None)
    stores.optimizer_proposals.pop(_PROPOSAL_ID, None)


@pytest.mark.parametrize(
    ("evidence", "match"),
    [
        (None, "evidence record is required"),
        ({}, "no candidate id"),
        ({"candidate_id": "  "}, "no candidate id"),
        (
            {
                "candidate_id": "candidate-7",
                "incumbent_id": "incumbent-1",
                "independent_results": [{"result_id": "only-one"}],
            },
            "two independent results",
        ),
        (
            {
                "candidate_id": "candidate-7",
                "incumbent_id": "incumbent-1",
                "independent_results": [
                    {"result_id": "same"},
                    {"run_id": "same"},
                ],
            },
            "two independent results",
        ),
        (
            {
                "candidate_id": "candidate-7",
                "independent_results": [
                    {"result_id": "run-a"},
                    {"result_id": "run-b"},
                ],
            },
            "does not name the incumbent",
        ),
        (
            {
                "candidate_id": "candidate-7",
                "incumbent_id": "   ",
                "independent_results": [
                    {"result_id": "run-a"},
                    {"result_id": "run-b"},
                ],
            },
            "does not name the incumbent",
        ),
    ],
)
def test_graph_apply_refuses_without_governed_evidence(dag: Any, evidence: Any, match: str) -> None:
    from services.optimizer import _apply_topology_mutation

    proposal = _proposal(evidence, include_evidence=evidence is not None)
    with pytest.raises(ValueError, match=match):
        _apply_topology_mutation(proposal)
    assert _model() == "old-model"


def test_graph_apply_commits_when_evidence_names_candidate_results_and_incumbent(
    dag: Any,
) -> None:
    from services.optimizer import _apply_topology_mutation

    _apply_topology_mutation(_proposal())
    assert _model() == "new-model"


def test_accept_does_not_record_a_decision_when_apply_evidence_is_missing(dag: Any) -> None:
    import stores
    from services.optimizer import record_decision

    stores.optimizer_proposals[_PROPOSAL_ID] = _proposal(include_evidence=False)
    with pytest.raises(ValueError, match="evidence record is required"):
        record_decision(_PROPOSAL_ID, "accepted", actor="alice")
    assert stores.optimizer_proposals[_PROPOSAL_ID]["decision"] == "pending"
    assert _model() == "old-model"


def test_accept_applies_only_after_the_evidence_record_is_complete(dag: Any) -> None:
    import stores
    from services.optimizer import record_decision

    stores.optimizer_proposals[_PROPOSAL_ID] = _proposal()
    decision = record_decision(_PROPOSAL_ID, "accepted", actor="alice")
    assert decision["decision"] == "accepted"
    assert stores.optimizer_proposals[_PROPOSAL_ID]["decision"] == "accepted"
    assert _model() == "new-model"
