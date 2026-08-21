"""Builder pipeline graph data model — PipelineNode and PipelineGraph.

Recreates the Stronghold Epic-15 "builder pipeline as a proper graph" model:
nodes declare explicit ``depends_on`` edges, ``skip_if`` predicates, and
``on_complete`` hooks; the graph validates itself (cycles, orphans, duplicate
names) before any execution begins.

Extension beyond Epic-15: a node may declare a *gate* — a verifiable
acceptance predicate evaluated after the node completes. A failed gate routes
execution back to ``revise_target`` (which must be an ancestor), bounded by
``max_revisions`` and the executor's shared iteration budget. This replaces
Epic-15's halt-on-first-failure (INV-07) with a bounded verify-and-revise
loop while keeping the underlying dependency graph acyclic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator

# Maps node_name → output text produced by that node, plus run parameters
# (issue_number, title, repo, …) and `<node>_feedback` entries written when a
# gate routes execution back for revision.
RunContext = dict[str, Any]

GateExhaustedPolicy = Literal["fail", "continue"]


@dataclass(frozen=True)
class PipelineNode:
    """A single node in the builder pipeline DAG."""

    name: str
    agent_name: str
    prompt_template: str
    depends_on: tuple[str, ...] = ()
    skip_if: Callable[[RunContext], bool] | None = None
    timeout_seconds: float = 600.0
    on_complete: Callable[[Any, str], Awaitable[None]] | None = None

    # Verify-and-revise loop. ``gate`` is evaluated against the run context
    # after the node completes; returning False sends execution back to
    # ``revise_target``. ``gate_exhausted`` decides what happens when
    # ``max_revisions`` is spent and the gate still fails.
    gate: Callable[[RunContext], bool] | None = None
    revise_target: str | None = None
    max_revisions: int = 2
    gate_exhausted: GateExhaustedPolicy = "fail"


class PipelineGraph:
    """Directed acyclic graph of PipelineNodes."""

    def __init__(self, nodes: Iterable[PipelineNode]) -> None:
        self._nodes: dict[str, PipelineNode] = {}
        for node in nodes:
            if node.name in self._nodes:
                raise ValueError(f"Duplicate node name: {node.name!r}")
            self._nodes[node.name] = node

    def ready(
        self,
        completed: frozenset[str],
        skipped: frozenset[str],
    ) -> list[PipelineNode]:
        """Nodes whose every dependency is in completed | skipped, and which
        are not themselves already in completed | skipped."""
        satisfied = completed | skipped
        return [
            node
            for node in self._nodes.values()
            if node.name not in satisfied and all(dep in satisfied for dep in node.depends_on)
        ]

    def ancestors(self, name: str) -> frozenset[str]:
        """All transitive dependencies of *name* (excluding itself)."""
        seen: set[str] = set()
        stack = list(self._nodes[name].depends_on)
        while stack:
            dep = stack.pop()
            if dep in seen or dep not in self._nodes:
                continue
            seen.add(dep)
            stack.extend(self._nodes[dep].depends_on)
        return frozenset(seen)

    def descendants(self, name: str) -> frozenset[str]:
        """All nodes that transitively depend on *name* (excluding itself)."""
        seen: set[str] = set()
        frontier = {name}
        while frontier:
            current = frontier.pop()
            for node in self._nodes.values():
                if node.name not in seen and current in node.depends_on:
                    seen.add(node.name)
                    frontier.add(node.name)
        return frozenset(seen)

    def validate(self) -> list[str]:
        """Return error strings. Empty list means the graph is valid."""
        errors = self._validate_dependencies()
        errors.extend(self._detect_cycles())
        if errors:
            return errors
        return self._validate_revise_edges()

    def _validate_dependencies(self) -> list[str]:
        errors: list[str] = []
        for node in self._nodes.values():
            for dep in node.depends_on:
                if dep not in self._nodes:
                    errors.append(f"Node {node.name!r} depends on undeclared node {dep!r}")
        return errors

    def _detect_cycles(self) -> list[str]:
        # Three-color DFS cycle detection (0=white/unvisited, 1=gray/active, 2=black/done)
        errors: list[str] = []
        color: dict[str, int] = dict.fromkeys(self._nodes, 0)

        def _dfs(name: str) -> bool:
            color[name] = 1
            node = self._nodes.get(name)
            if node:
                for dep in node.depends_on:
                    if dep not in color:
                        continue
                    if color[dep] == 1:
                        errors.append(f"Cycle detected involving node {dep!r}")
                        return True
                    if color[dep] == 0 and _dfs(dep):
                        return True
            color[name] = 2
            return False

        for name in self._nodes:
            if color[name] == 0:
                _dfs(name)
        return errors

    def _validate_revise_edges(self) -> list[str]:
        # Revise edges are only meaningful on gated nodes, and must point at
        # an ancestor — otherwise the revise loop could never re-reach the gate.
        errors: list[str] = []
        for node in self._nodes.values():
            if node.revise_target is None:
                continue
            if node.gate is None:
                errors.append(f"Node {node.name!r} declares revise_target without a gate")
            elif node.revise_target not in self._nodes:
                errors.append(
                    f"Node {node.name!r} revise_target {node.revise_target!r} is not in the graph"
                )
            elif node.revise_target not in self.ancestors(node.name):
                errors.append(
                    f"Node {node.name!r} revise_target {node.revise_target!r} "
                    "is not an ancestor of the gated node"
                )
        return errors

    def __len__(self) -> int:
        return len(self._nodes)

    def __contains__(self, name: object) -> bool:
        return name in self._nodes

    def __iter__(self) -> Iterator[PipelineNode]:
        return iter(self._nodes.values())
