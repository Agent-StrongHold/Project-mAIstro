"""DAG cycle-detection tests.

Uses pytest-parameterized cases instead of Hypothesis to keep the
registry CI's dep set minimal per `engine#ADR-039`. Hypothesis property
tests can be added in a follow-up if behavioral contracts (per
`engine#ADR-032`) are formalized for this module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from maistro_registry.dag import Cycle, DuplicateId, find_cycles, find_duplicate_ids
from maistro_registry.schema import FrontMatter
from maistro_registry.validator import ValidationResult


def _make_result(item_id: str, path: str) -> ValidationResult:
    fm = _make_fm(item_id)
    return ValidationResult(path=Path(path), front_matter=fm)


def _make_fm(
    item_id: str,
    *,
    repo: str = "maistro-engine",
    supersedes: list[str] | None = None,
    blocks: list[str] | None = None,
) -> FrontMatter:
    payload: dict[str, Any] = {
        "id": item_id,
        "title": item_id,
        "repo": repo,
        "kind": "adr",
        "status": "Accepted",
        "created": "2026-05-07",
        "substrate": [],
        "implements": [],
        "related": [],
        "supersedes": supersedes or [],
        "blocks": blocks or [],
        "blocked-by": [],
        "contracts": [],
        "tests": [],
        "layer": "Foundation",
        "owners": ["@BlakeMatthews-dev"],
    }
    return FrontMatter.model_validate(payload)


def test_empty_input_returns_no_cycles() -> None:
    assert find_cycles([], "supersedes") == []


def test_single_node_no_edges_returns_no_cycles() -> None:
    fm = _make_fm("ADR-001")
    assert find_cycles([fm], "supersedes") == []


def test_acyclic_chain_returns_no_cycles() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002", supersedes=["maistro-engine#ADR-003"])
    c = _make_fm("ADR-003")
    assert find_cycles([a, b, c], "supersedes") == []


def test_self_loop_detected() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-001"])
    cycles = find_cycles([a], "supersedes")
    assert len(cycles) == 1
    assert cycles[0].nodes == ("maistro-engine#ADR-001",)


def test_two_node_cycle_detected() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002", supersedes=["maistro-engine#ADR-001"])
    cycles = find_cycles([a, b], "supersedes")
    assert len(cycles) == 1
    assert set(cycles[0].nodes) == {
        "maistro-engine#ADR-001",
        "maistro-engine#ADR-002",
    }


def test_three_node_cycle_detected() -> None:
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002", supersedes=["maistro-engine#ADR-003"])
    c = _make_fm("ADR-003", supersedes=["maistro-engine#ADR-001"])
    cycles = find_cycles([a, b, c], "supersedes")
    assert len(cycles) == 1
    assert set(cycles[0].nodes) == {
        "maistro-engine#ADR-001",
        "maistro-engine#ADR-002",
        "maistro-engine#ADR-003",
    }


def test_diamond_no_false_cycle() -> None:
    # A -> B, A -> C, B -> D, C -> D — acyclic
    a = _make_fm(
        "ADR-001",
        supersedes=[
            "maistro-engine#ADR-002",
            "maistro-engine#ADR-003",
        ],
    )
    b = _make_fm("ADR-002", supersedes=["maistro-engine#ADR-004"])
    c = _make_fm("ADR-003", supersedes=["maistro-engine#ADR-004"])
    d = _make_fm("ADR-004")
    assert find_cycles([a, b, c, d], "supersedes") == []


def test_disconnected_components_with_cycle_in_one() -> None:
    # Component 1: A -> B (acyclic)
    a = _make_fm("ADR-001", supersedes=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002")
    # Component 2: C <-> D (cycle)
    c = _make_fm("ADR-003", supersedes=["maistro-engine#ADR-004"])
    d = _make_fm("ADR-004", supersedes=["maistro-engine#ADR-003"])

    cycles = find_cycles([a, b, c, d], "supersedes")
    assert len(cycles) == 1
    assert set(cycles[0].nodes) == {
        "maistro-engine#ADR-003",
        "maistro-engine#ADR-004",
    }


def test_supersedes_and_blocks_independent() -> None:
    # blocks cycle exists; supersedes graph is clean
    a = _make_fm("ADR-001", blocks=["maistro-engine#ADR-002"])
    b = _make_fm("ADR-002", blocks=["maistro-engine#ADR-001"])
    assert find_cycles([a, b], "supersedes") == []
    assert len(find_cycles([a, b], "blocks")) == 1


def test_unknown_relationship_rejected() -> None:
    with pytest.raises(ValueError, match="unknown relationship"):
        find_cycles([], "unknown")  # type: ignore[arg-type]


def test_cycle_render_self_loop() -> None:
    cycle = Cycle(relationship="supersedes", nodes=("maistro-engine#ADR-001",))
    assert "self-loop" in cycle.render()


def test_cycle_render_multi_node() -> None:
    cycle = Cycle(
        relationship="blocks",
        nodes=("maistro-engine#ADR-001", "maistro-engine#ADR-002"),
    )
    rendered = cycle.render()
    assert "blocks cycle" in rendered
    assert "->" in rendered


def test_no_duplicates_among_unique_ids() -> None:
    results = [
        _make_result("ADR-001", "docs/adr/ADR-001-a.md"),
        _make_result("ADR-002", "docs/adr/ADR-002-b.md"),
    ]
    assert find_duplicate_ids(results) == []


def test_duplicate_id_detected() -> None:
    results = [
        _make_result("SPEC-184", "docs/specs/SPEC-184-a.md"),
        _make_result("SPEC-184", "docs/specs/SPEC-184-b.md"),
    ]
    duplicates = find_duplicate_ids(results)
    assert len(duplicates) == 1
    assert duplicates[0].id == "SPEC-184"
    assert duplicates[0].paths == (
        Path("docs/specs/SPEC-184-a.md"),
        Path("docs/specs/SPEC-184-b.md"),
    )


def test_results_without_front_matter_are_ignored() -> None:
    results = [
        ValidationResult(path=Path("docs/adr/ADR-broken.md"), front_matter=None, errors=["bad"]),
        _make_result("ADR-001", "docs/adr/ADR-001-a.md"),
    ]
    assert find_duplicate_ids(results) == []


def test_duplicate_id_render() -> None:
    dup = DuplicateId(
        id="SPEC-184",
        paths=(Path("docs/specs/SPEC-184-a.md"), Path("docs/specs/SPEC-184-b.md")),
    )
    rendered = dup.render()
    assert "SPEC-184" in rendered
    assert "SPEC-184-a.md" in rendered
    assert "SPEC-184-b.md" in rendered
