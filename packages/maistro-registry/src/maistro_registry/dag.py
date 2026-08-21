"""DAG validation for ADR/spec relationships per `engine#ADR-031`.

The `supersedes` and `blocks` relationships must form a DAG — cycles
are invalid by construction (an ADR cannot supersede itself, even
transitively, and the same for blocks).

This module finds cycles using a colored DFS:

- WHITE: unvisited
- GRAY: in the current DFS path
- BLACK: fully explored

A back edge to a GRAY node is a cycle. Self-loops are reported as
cycles of length 1.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from maistro_registry.schema import FrontMatter
from maistro_registry.validator import ValidationResult

Relationship = Literal["supersedes", "blocks"]
_VALID_RELATIONSHIPS: frozenset[Relationship] = frozenset({"supersedes", "blocks"})


@dataclass(frozen=True)
class DuplicateId:
    id: str
    paths: tuple[Path, ...]

    def render(self) -> str:
        paths = ", ".join(str(p) for p in self.paths)
        return f"duplicate id {self.id}: {paths}"


def find_duplicate_ids(results: list[ValidationResult]) -> list[DuplicateId]:
    """Return ids claimed by more than one file's front-matter.

    Each `id:` (e.g. `SPEC-184`) must be globally unique across the walked
    tree — collisions make `<repo>#<id>` cross-references ambiguous.
    """
    by_id: dict[str, list[Path]] = {}
    for r in results:
        if r.front_matter is None:
            continue
        by_id.setdefault(r.front_matter.id, []).append(r.path)

    return [
        DuplicateId(id=item_id, paths=tuple(paths))
        for item_id, paths in sorted(by_id.items())
        if len(paths) > 1
    ]


@dataclass(frozen=True)
class Cycle:
    relationship: Relationship
    nodes: tuple[str, ...]  # nodes in the cycle, in traversal order

    def render(self) -> str:
        if len(self.nodes) == 1:
            return f"{self.relationship} self-loop: {self.nodes[0]}"
        chain = " -> ".join(self.nodes)
        return f"{self.relationship} cycle: {chain} -> {self.nodes[0]}"


def _build_graph(
    front_matters: list[FrontMatter],
    relationship: Relationship,
) -> dict[str, list[str]]:
    """Build adjacency-list graph keyed by `<repo>#<id>` source."""
    graph: dict[str, list[str]] = {}
    for fm in front_matters:
        src = f"{fm.repo.value}#{fm.id}"
        edges: list[str] = list(getattr(fm, relationship))
        graph.setdefault(src, []).extend(edges)
        for dst in edges:
            graph.setdefault(dst, [])
    return graph


def find_cycles(
    front_matters: list[FrontMatter],
    relationship: Relationship,
) -> list[Cycle]:
    """Return all cycles in the chosen relationship graph.

    A cycle is reported once per back edge encountered; if multiple
    cycles share nodes, each back-edge cycle appears separately. Empty
    or acyclic input returns an empty list.
    """
    if relationship not in _VALID_RELATIONSHIPS:
        raise ValueError(
            f"unknown relationship {relationship!r}; expected one of {_VALID_RELATIONSHIPS}"
        )

    graph = _build_graph(front_matters, relationship)

    WHITE, GRAY, BLACK = 0, 1, 2
    color: dict[str, int] = dict.fromkeys(graph, WHITE)
    cycles: list[Cycle] = []

    def dfs(node: str, path: list[str]) -> None:
        color[node] = GRAY
        path.append(node)
        for neighbor in graph.get(node, []):
            color.setdefault(neighbor, WHITE)
            if color[neighbor] == GRAY:
                # back edge → cycle starts at first occurrence of neighbor in path
                start = path.index(neighbor)
                cycle = tuple(path[start:])
                cycles.append(Cycle(relationship=relationship, nodes=cycle))
            elif color[neighbor] == WHITE:
                dfs(neighbor, path)
        path.pop()
        color[node] = BLACK

    for node in list(graph):
        if color.get(node, WHITE) == WHITE:
            dfs(node, [])

    return cycles
