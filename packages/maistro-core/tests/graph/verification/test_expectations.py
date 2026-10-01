"""Plan-queue post-state expectations: evaluation, policy parsing, ordering."""

from __future__ import annotations

import pytest

from maistro.graph import Graph, Node
from maistro.graph.verification import (
    PlanExpectationQueue,
    PostStateExpectation,
    ResultState,
    expectation_from_policy,
)


def _expectation(**kwargs: object) -> PostStateExpectation:
    return PostStateExpectation.model_validate({"node_id": "step", **kwargs})


def test_matching_output_subset_and_state() -> None:
    expectation = _expectation(
        expect_result_state=ResultState.TERMINAL,
        expected_output={"status": "done", "counts.total": 3},
        expected_output_contains={"summary": "shipped"},
    )
    verdict = expectation.evaluate(
        output={"status": "done", "counts": {"total": 3}, "summary": "feature shipped"},
        result_state=ResultState.TERMINAL,
    )
    assert verdict.matched
    assert verdict.violations == ()


def test_missing_output_path_is_a_violation_not_a_none_match() -> None:
    expectation = _expectation(expected_output={"counts.total": 3})
    verdict = expectation.evaluate(output={"counts": None}, result_state=None)
    assert not verdict.matched
    assert verdict.violations[0].kind == "missing_output"


def test_dotted_path_mismatch_reports_actual() -> None:
    expectation = _expectation(expected_output={"counts.total": 3})
    verdict = expectation.evaluate(output={"counts": {"total": 4}}, result_state=None)
    assert not verdict.matched
    assert verdict.violations[0].kind == "output_mismatch"
    assert verdict.violations[0].expected == 3
    assert verdict.violations[0].actual == 4


def test_non_string_contains_target_is_a_violation() -> None:
    expectation = _expectation(expected_output_contains={"summary": "shipped"})
    verdict = expectation.evaluate(output={"summary": 7}, result_state=None)
    assert verdict.violations[0].kind == "output_not_contained"


def test_non_mapping_output_violates_any_output_assertion() -> None:
    expectation = _expectation(expected_output={"a": 1})
    verdict = expectation.evaluate(output="just a string", result_state=None)
    assert not verdict.matched
    assert {violation.kind for violation in verdict.violations} == {"missing_output"}


def test_result_state_mismatch_names_both_sides() -> None:
    expectation = _expectation(expect_result_state=ResultState.TERMINAL)
    verdict = expectation.evaluate(output={}, result_state=ResultState.TRANSITIONAL)
    assert verdict.violations[0].expected == "terminal"
    assert verdict.violations[0].actual == "transitional"


def test_describe_renders_violations_for_durable_evidence() -> None:
    expectation = _expectation(expected_output={"a": 1})
    verdict = expectation.evaluate(output={"a": 2}, result_state=None)
    text = verdict.describe()
    assert "'step'" in text
    assert "output_mismatch" in text
    assert "expected 1" in text and "got 2" in text


def test_policy_absent_returns_none() -> None:
    assert expectation_from_policy("step", {}) is None
    assert expectation_from_policy("step", {"max_attempts": 2}) is None


def test_policy_parses_without_node_id() -> None:
    expectation = expectation_from_policy(
        "step",
        {"expect_post_state": {"expected_output": {"a": 1}}},
    )
    assert expectation is not None
    assert expectation.node_id == "step"
    assert expectation.expected_output == {"a": 1}


def test_policy_for_another_node_raises() -> None:
    with pytest.raises(ValueError, match="predict"):
        expectation_from_policy(
            "step",
            {"expect_post_state": {"node_id": "other", "expected_output": {"a": 1}}},
        )


def test_policy_wrong_shape_raises() -> None:
    with pytest.raises(ValueError, match="mapping"):
        expectation_from_policy("step", {"expect_post_state": "terminal"})


def test_queue_orders_topologically_and_consumes_in_order() -> None:
    from maistro.graph.definitions import Edge

    graph = Graph(
        workspace_id="ws",
        project_id="p",
        name="plan queue",
        nodes=[
            Node(
                node_id="b",
                node_type="noop",
                policies={"expect_post_state": {"expected_output": {"step": "b"}}},
            ),
            Node(
                node_id="a",
                node_type="noop",
                policies={"expect_post_state": {"expected_output": {"step": "a"}}},
            ),
            Node(node_id="c", node_type="noop"),
        ],
        edges=[Edge(from_node="a", to_node="b")],
    )
    queue = PlanExpectationQueue.from_graph(graph)
    assert [e.node_id for e in queue.expectations] == ["a", "b"]
    assert queue.pending_node_ids == ("a", "b")
    assert queue.expectation_for("c") is None

    first = queue.supervise("a", output={"step": "a"}, result_state=None)
    assert first is not None and first.matched
    assert queue.pending_node_ids == ("b",)

    second = queue.supervise("b", output={"step": "wrong"}, result_state=None)
    assert second is not None and not second.matched
    assert queue.pending_node_ids == ()


def test_queue_cycle_nodes_keep_deterministic_order() -> None:
    from maistro.graph.definitions import Edge

    graph = Graph(
        workspace_id="ws",
        project_id="p",
        name="cycle",
        nodes=[
            Node(node_id="z", node_type="noop", policies={"expect_post_state": {}}),
            Node(node_id="m", node_type="noop", policies={"expect_post_state": {}}),
        ],
        edges=[Edge(from_node="z", to_node="m"), Edge(from_node="m", to_node="z")],
    )
    queue = PlanExpectationQueue.from_graph(graph)
    assert [e.node_id for e in queue.expectations] == ["m", "z"]


def test_supervise_unknown_node_consumes_nothing() -> None:
    queue = PlanExpectationQueue((_expectation(),))
    assert queue.supervise("other", output={}, result_state=None) is None
    assert queue.pending_node_ids == ("step",)
