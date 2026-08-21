"""Focused parity coverage for durable graph edge routing."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from maistro.graph.durable_runs.executor import _next_node
from maistro.graph.nodes.base import NodeResult
from maistro.runs.lifecycle import transition_node_run
from maistro.runs.model import NodeRun, RunStatus

from .._canonical_helpers import durable_record, graph_from_dag


class _Review(BaseModel):
    approved: bool
    score: float


class _Envelope(BaseModel):
    review: _Review


def _result(output: dict[str, Any] | BaseModel | None) -> NodeResult:
    return NodeResult(success=True, status="completed", output=output)


def _target(dag: dict[str, Any], current_id: str, result: NodeResult) -> str | None:
    graph = graph_from_dag(dag)
    target, _ = _next_node(graph, current_id, "node-run-1", result)
    return target


def test_node_result_preserves_mapping_output() -> None:
    payload = {"review": {"approved": True, "score": 9.0}}

    assert _result(payload).output == payload


def test_false_condition_falls_through_to_matching_condition() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "wrong"}, {"id": "right"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "wrong",
                "condition": "review.approved == False",
            },
            {
                "from_node": "start",
                "to_node": "right",
                "condition": "review.approved == True",
            },
        ],
    }

    assert _target(dag, "start", _result({"review": {"approved": True}})) == "right"


def test_false_condition_falls_through_to_unconditional_edge() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "conditional"}, {"id": "fallback"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "conditional",
                "condition": "review.approved == True",
            },
            {"from_node": "start", "to_node": "fallback"},
        ],
    }

    assert _target(dag, "start", _result({"review": {"approved": False}})) == "fallback"


def test_numeric_comparison_uses_canonical_predicate_dialect() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "high"}, {"id": "low"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "high",
                "condition": "review.score >= 8",
            },
            {"from_node": "start", "to_node": "low"},
        ],
    }

    assert _target(dag, "start", _result({"review": {"score": 8.5}})) == "high"


def test_pydantic_output_supports_dotted_condition_paths() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "approved"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "approved",
                "condition": "review.approved is True",
            }
        ],
    }
    output = _Envelope(review=_Review(approved=True, score=9.0))

    assert _target(dag, "start", _result(output)) == "approved"


def test_typed_reviewer_output_uses_canonical_review_namespace() -> None:
    dag = {
        "nodes": [
            {"id": "reviewer", "kind": "llm.review"},
            {"id": "approved"},
        ],
        "edges": [
            {
                "from_node": "reviewer",
                "to_node": "approved",
                "condition": "review.approved == True",
            }
        ],
    }

    assert _target(dag, "reviewer", _result(_Review(approved=True, score=9.0))) == "approved"


def test_condition_can_read_prior_canonical_node_output() -> None:
    dag = {
        "id": "routing-state",
        "nodes": [
            {"id": "planner", "kind": "llm.plan"},
            {"id": "coder", "kind": "llm.code"},
            {"id": "ready"},
        ],
        "edges": [
            {
                "from_node": "coder",
                "to_node": "ready",
                "condition": "plan.summary == 'ready'",
            }
        ],
    }
    node_run = NodeRun(run_id="r-routing", node_id="planner", ordinal=1)
    node_run = transition_node_run(node_run, RunStatus.QUEUED)
    node_run = transition_node_run(node_run, RunStatus.RUNNING)
    node_run = transition_node_run(
        node_run,
        RunStatus.COMPLETED,
        result={"summary": "ready"},
    )
    record = durable_record(
        dag,
        run_id="r-routing",
        active_node_id="coder",
        node_runs=(node_run,),
    )
    graph = graph_from_dag(dag)

    target, _ = _next_node(
        graph,
        "coder",
        "node-run-coder",
        _result({"artifact": "code"}),
        record,
    )
    assert target == "ready"


def test_missing_condition_path_does_not_match() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "missing"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "missing",
                "condition": "review.score >= 8",
            }
        ],
    }

    assert _target(dag, "start", _result({"other": {"score": 10}})) is None


def test_first_matching_edge_keeps_document_order_precedence() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "first"}, {"id": "second"}],
        "edges": [
            {
                "from_node": "start",
                "to_node": "first",
                "condition": "review.approved == True",
            },
            {"from_node": "start", "to_node": "second"},
        ],
    }

    assert _target(dag, "start", _result({"review": {"approved": True}})) == "first"


def test_targetless_legacy_edge_does_not_hide_later_route() -> None:
    dag = {
        "nodes": [{"id": "start"}, {"id": "next"}],
        "edges": [
            {"from_node": "start", "condition": "review.approved == True"},
            {"from_node": "start", "to_node": "next"},
        ],
    }

    assert _target(dag, "start", _result({"review": {"approved": True}})) == "next"
