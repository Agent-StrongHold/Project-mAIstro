"""Tests for the PipelineNode/PipelineGraph data model (Epic-15 invariants)."""

from __future__ import annotations

import pytest

from maistro.builders.graph import PipelineGraph, PipelineNode


def _node(name: str, deps: tuple[str, ...] = (), **kwargs: object) -> PipelineNode:
    return PipelineNode(
        name=name,
        agent_name=f"agent-{name}",
        prompt_template=f"do {name}",
        depends_on=deps,
        **kwargs,  # type: ignore[arg-type]
    )


def test_duplicate_node_name_rejected() -> None:
    with pytest.raises(ValueError, match="Duplicate node name"):
        PipelineGraph([_node("a"), _node("a")])


def test_ready_returns_roots_first() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",)), _node("c", ("a",))])

    ready = graph.ready(frozenset(), frozenset())
    assert [n.name for n in ready] == ["a"]


def test_ready_after_completion_offers_dependents() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",)), _node("c", ("a",))])

    ready = graph.ready(frozenset({"a"}), frozenset())
    assert sorted(n.name for n in ready) == ["b", "c"]


def test_node_with_two_upstream_dependencies_waits_for_both() -> None:
    graph = PipelineGraph([_node("a"), _node("b"), _node("c", ("a", "b"))])

    assert "c" not in {n.name for n in graph.ready(frozenset({"a"}), frozenset())}
    assert "c" in {n.name for n in graph.ready(frozenset({"a", "b"}), frozenset())}


def test_skipped_node_satisfies_dependents() -> None:
    # INV-03: a skipped node satisfies the dependency requirement.
    graph = PipelineGraph([_node("a"), _node("b", ("a",))])

    ready = graph.ready(frozenset(), frozenset({"a"}))
    assert [n.name for n in ready] == ["b"]


def test_completed_and_skipped_nodes_not_offered_again() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",))])

    assert graph.ready(frozenset({"b"}), frozenset({"a"})) == []


def test_validate_flags_undeclared_dependency() -> None:
    # INV-06
    graph = PipelineGraph([_node("a", ("ghost",))])

    errors = graph.validate()
    assert any("undeclared" in e for e in errors)


def test_validate_flags_cycle() -> None:
    # INV-05
    graph = PipelineGraph([_node("a", ("b",)), _node("b", ("a",))])

    errors = graph.validate()
    assert any("Cycle" in e for e in errors)


def test_validate_accepts_valid_dag() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",)), _node("c", ("a", "b"))])

    assert graph.validate() == []


def test_validate_flags_revise_target_without_gate() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",), revise_target="a")])

    errors = graph.validate()
    assert any("without a gate" in e for e in errors)


def test_validate_flags_unknown_revise_target() -> None:
    graph = PipelineGraph(
        [_node("a"), _node("b", ("a",), gate=lambda ctx: True, revise_target="ghost")]
    )

    errors = graph.validate()
    assert any("not in the graph" in e for e in errors)


def test_validate_flags_non_ancestor_revise_target() -> None:
    graph = PipelineGraph(
        [
            _node("a"),
            _node("b", ("a",), gate=lambda ctx: True, revise_target="c"),
            _node("c", ("a",)),
        ]
    )

    errors = graph.validate()
    assert any("not an ancestor" in e for e in errors)


def test_validate_accepts_ancestor_revise_target() -> None:
    graph = PipelineGraph(
        [
            _node("a"),
            _node("b", ("a",)),
            _node("c", ("b",), gate=lambda ctx: True, revise_target="a"),
        ]
    )

    assert graph.validate() == []


def test_ancestors_and_descendants() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a",)), _node("c", ("b",)), _node("d", ("a",))])

    assert graph.ancestors("c") == frozenset({"a", "b"})
    assert graph.descendants("a") == frozenset({"b", "c", "d"})
    assert graph.descendants("c") == frozenset()


def test_ancestors_skips_dependency_not_present_in_graph() -> None:
    graph = PipelineGraph([_node("a"), _node("b", ("a", "missing"))])

    assert graph.ancestors("b") == frozenset({"a"})


def test_dunder_protocol() -> None:
    nodes = [_node("a"), _node("b", ("a",))]
    graph = PipelineGraph(nodes)

    assert len(graph) == 2
    assert "a" in graph
    assert "ghost" not in graph
    assert sorted(n.name for n in graph) == ["a", "b"]
