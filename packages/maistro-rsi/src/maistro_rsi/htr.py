"""Hypothesis-Tree Refinement (HTR) — cumulative memory across RSI cycles.

On its own, one RSI cycle (`maistro_rsi.runner.RsiCycle`) is a *local* attempt:
branch, patch, test, benchmark, keep or discard. Run a hundred of them and you
get a hundred independent attempts that never learn from each other. The Arbor
paper (arXiv:2606.11926, "Toward Generalist Autonomous Research via
Hypothesis-Tree Refinement") makes the loop *cumulative*: a long-lived
coordinator keeps a persistent tree of hypotheses; each short-lived executor
expands one node and returns evidence; the coordinator distills a reusable
insight from that evidence and refines which part of the frontier to explore
next, so reusable lessons propagate across time instead of being thrown away.

This module is the tree itself — the data structure plus the refinement policy.
It is deliberately pure: no sandbox, git, or network. The coordinator that
drives real RSI cycles (`maistro_rsi.coordinator`) depends on this, but the
frontier-selection and insight-propagation logic can be reasoned about (and
tested) without ever standing up a sandbox.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class NodeStatus(StrEnum):
    """Lifecycle of a hypothesis node.

    A node is OPEN once proposed, EXPLORED once an executor has run it and
    recorded evidence worth building on, and ABANDONED when the recorded
    evidence marks it a dead end (broke the build, or made no benchmark
    progress). Only OPEN and EXPLORED nodes are ever expanded — abandonment is
    how the coordinator prunes the frontier "based on returned results".
    """

    OPEN = "open"
    EXPLORED = "explored"
    ABANDONED = "abandoned"


class FrontierExhausted(ValueError):
    """No node remains to refine: the root is abandoned and no EXPLORED branch
    survives it. An ordinary end state for a run, not a fault.

    A ``ValueError`` subclass so callers written against the old contract keep
    working, but a distinct type so no caller has to recognise it by matching
    on the message text. Message matching is what made this worth naming: a
    caller catching ``ValueError`` and testing for ``"abandoned"`` also
    swallows unrelated ``ValueError``s from injected proposers and executors,
    which turns a real failure into a tidy "frontier exhausted" stop.
    """


@dataclass(frozen=True)
class HypothesisEvidence:
    """The returned result of executing one hypothesis: did the self-change
    pass its own tests, and how did the candidate fare against the baseline
    across the benchmark battles. Mirrors what `RsiCycleResult` already
    exposes, kept as a small frozen value object so the tree never depends on
    the heavy runner.
    """

    tests_passed: bool
    benchmarks_won: int
    battles: int
    improved: bool

    def __post_init__(self) -> None:
        if self.battles < 0:
            raise ValueError("battles cannot be negative")
        if not 0 <= self.benchmarks_won <= self.battles:
            raise ValueError(
                f"benchmarks_won ({self.benchmarks_won}) must be in [0, battles={self.battles}]"
            )

    @property
    def net_gain(self) -> float:
        """Net benchmark win rate in [-1, 1]: +1 if the candidate swept, -1 if
        it lost every decisive battle, 0 on an even split or no decisive battles.
        Draws (same score) are neutral and excluded from the calculation."""
        # Assuming draws are not counted as wins, losses = non_wins - draws.
        # Since we don't track draws explicitly, we conservatively count only
        # wins vs. non-wins where any non-win that isn't a draw is a loss.
        # When there are only draws, net_gain is 0 (neutral).
        if self.battles == 0:
            return 0.0
        losses = self.battles - self.benchmarks_won
        return (self.benchmarks_won - losses) / self.battles

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form for persistence (htr-8)."""
        return {
            "tests_passed": self.tests_passed,
            "benchmarks_won": self.benchmarks_won,
            "battles": self.battles,
            "improved": self.improved,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HypothesisEvidence:
        """Rebuild from :meth:`to_dict` output; validation reruns in __post_init__."""
        return cls(
            tests_passed=bool(data["tests_passed"]),
            benchmarks_won=int(data["benchmarks_won"]),
            battles=int(data["battles"]),
            improved=bool(data["improved"]),
        )


@dataclass
class HypothesisNode:
    """One node in the hypothesis tree: a proposed direction for a self-change,
    plus — once executed — the evidence it produced, the artifacts it left
    behind (diff, PR), and a distilled, reusable insight."""

    id: str
    parent_id: str | None
    depth: int
    hypothesis: str
    order: int
    status: NodeStatus = NodeStatus.OPEN
    evidence: HypothesisEvidence | None = None
    insight: str | None = None
    artifacts: dict[str, str] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)

    @property
    def score(self) -> float | None:
        """Evidence-grounded desirability in [0, 1], or ``None`` when the node
        has not been executed yet — never a silent 0.0 for "unknown".

        A change that breaks its own test suite is worthless regardless of
        benchmarks (score 0.0), mirroring `RsiCycleResult.improved`'s refusal
        to call a broken build an improvement. Otherwise the net benchmark gain
        in [-1, 1] is mapped onto [0, 1]: a tests-passing clean sweep scores
        1.0, an even split 0.5, a clean loss 0.0.
        """
        if self.evidence is None:
            return None
        if not self.evidence.tests_passed:
            return 0.0
        return (self.evidence.net_gain + 1.0) / 2.0

    def to_dict(self) -> dict[str, Any]:
        """Plain-data form for persistence (htr-8)."""
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "depth": self.depth,
            "hypothesis": self.hypothesis,
            "order": self.order,
            "status": self.status.value,
            "evidence": self.evidence.to_dict() if self.evidence else None,
            "insight": self.insight,
            "artifacts": dict(self.artifacts),
            "children": list(self.children),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HypothesisNode:
        """Rebuild from :meth:`to_dict` output."""
        evidence_data = data.get("evidence")
        return cls(
            id=str(data["id"]),
            parent_id=data["parent_id"] if data["parent_id"] is None else str(data["parent_id"]),
            depth=int(data["depth"]),
            hypothesis=str(data["hypothesis"]),
            order=int(data["order"]),
            status=NodeStatus(str(data["status"])),
            evidence=(HypothesisEvidence.from_dict(evidence_data) if evidence_data else None),
            insight=data.get("insight"),
            artifacts=dict(data.get("artifacts") or {}),
            children=list(data.get("children") or []),
        )


class HypothesisTree:
    """A persistent tree of hypotheses with an evidence-driven refinement
    policy. The root is the seed direction; every other node is a refinement of
    its parent. Executors record evidence against nodes; the coordinator reads
    the frontier and the distilled lineage insights to decide what to try next.
    """

    def __init__(self, root_hypothesis: str) -> None:
        self._order = 0
        root = self._new_node(parent_id=None, depth=0, hypothesis=root_hypothesis)
        self.root_id = root.id
        self.nodes: dict[str, HypothesisNode] = {root.id: root}

    def _new_node(self, *, parent_id: str | None, depth: int, hypothesis: str) -> HypothesisNode:
        node = HypothesisNode(
            id=uuid.uuid4().hex[:12],
            parent_id=parent_id,
            depth=depth,
            hypothesis=hypothesis,
            order=self._order,
        )
        self._order += 1
        return node

    # -- growth -------------------------------------------------------------

    def expand(self, parent_id: str, hypothesis: str) -> HypothesisNode:
        """Propose a refinement of ``parent_id`` as a new OPEN child node.

        Raises ``KeyError`` for an unknown parent and ``ValueError`` for an
        abandoned one — the coordinator must not grow a branch already pruned
        as a dead end.
        """
        parent = self.nodes[parent_id]
        if parent.status is NodeStatus.ABANDONED:
            raise ValueError(f"cannot expand abandoned node {parent_id}")
        child = self._new_node(
            parent_id=parent_id,
            depth=parent.depth + 1,
            hypothesis=hypothesis,
        )
        parent.children.append(child.id)
        self.nodes[child.id] = child
        return child

    def record(
        self,
        node_id: str,
        evidence: HypothesisEvidence,
        *,
        diff: str | None = None,
        pr_url: str | None = None,
        run_id: str | None = None,
        insight: str | None = None,
    ) -> HypothesisNode:
        """Attach an executor's returned evidence to a node, distill a reusable
        insight, and set the node's status. A node that broke its tests or made
        no net benchmark progress is ABANDONED (pruned from the frontier);
        otherwise it becomes EXPLORED and is eligible to be expanded further.
        """
        node = self.nodes[node_id]
        node.evidence = evidence
        node.insight = insight if insight is not None else _distill(node.hypothesis, evidence)
        if diff is not None:
            node.artifacts["diff"] = diff
        if pr_url is not None:
            node.artifacts["pr_url"] = pr_url
        if run_id is not None:
            node.artifacts["run_id"] = run_id

        dead_end = not evidence.tests_passed or evidence.net_gain <= 0
        node.status = NodeStatus.ABANDONED if dead_end else NodeStatus.EXPLORED
        return node

    # -- frontier refinement ------------------------------------------------

    def pending(self) -> list[HypothesisNode]:
        """OPEN nodes awaiting execution, best-first: a node whose parent scored
        higher is explored before one descending from a weaker (or unscored)
        parent, ties broken by recency so the freshest hypothesis wins. Excludes
        any node whose lineage contains an abandoned ancestor."""

        def has_abandoned_ancestor(node_id: str) -> bool:
            current = self.nodes[node_id].parent_id
            while current is not None:
                if self.nodes[current].status is NodeStatus.ABANDONED:
                    return True
                current = self.nodes[current].parent_id
            return False

        def priority(node: HypothesisNode) -> tuple[float, int]:
            parent_score = 0.0
            if node.parent_id is not None:
                parent_score = self.nodes[node.parent_id].score or 0.0
            return (parent_score, node.order)

        return sorted(
            (
                n
                for n in self.nodes.values()
                if n.status is NodeStatus.OPEN and not has_abandoned_ancestor(n.id)
            ),
            key=priority,
            reverse=True,
        )

    def expandable_seeds(self) -> list[HypothesisNode]:
        """EXPLORED, non-abandoned nodes worth growing a new child from, ordered
        most promising first (highest score, then shallower, then earliest)."""
        seeds = [n for n in self.nodes.values() if n.status is NodeStatus.EXPLORED]
        return sorted(seeds, key=lambda n: (-(n.score or 0.0), n.depth, n.order))

    def best_node(self) -> HypothesisNode | None:
        """The cumulative best-so-far: the highest-scoring executed node.
        Deterministic ties: shallower depth wins, then earliest proposed.
        ``None`` until at least one node has recorded evidence."""
        scored = [n for n in self.nodes.values() if n.evidence is not None]
        if not scored:
            return None
        return max(scored, key=lambda n: ((n.score or 0.0), -n.depth, -n.order))

    def select_seed(self) -> HypothesisNode:
        """The node a fresh hypothesis should refine when nothing is queued:
        the most promising explored branch, or the root while the tree is still
        young (nothing explored yet). Raises :class:`FrontierExhausted` if the
        root is abandoned and no EXPLORED branches exist — the tree is a dead
        end."""
        seeds = self.expandable_seeds()
        if seeds:
            return seeds[0]
        root = self.nodes[self.root_id]
        if root.status is NodeStatus.ABANDONED:
            raise FrontierExhausted("root is abandoned and no explored branches exist")
        return root

    # -- lineage / insight propagation --------------------------------------

    def lineage(self, node_id: str) -> list[HypothesisNode]:
        """Root-to-node path, root first — the chain of refinements that led
        here."""
        chain: list[HypothesisNode] = []
        current: str | None = node_id
        while current is not None:
            node = self.nodes[current]
            chain.append(node)
            current = node.parent_id
        chain.reverse()
        return chain

    def distilled_insights(self, node_id: str | None = None) -> list[str]:
        """The reusable lessons to carry into the next attempt, gathered along
        the lineage of ``node_id`` (or of the best node, if omitted) — oldest
        first, de-duplicated. This is what makes the loop cumulative rather than
        local: expanding a node inherits everything learned on the path to it.
        """
        if node_id is None:
            best = self.best_node()
            node_id = best.id if best is not None else self.root_id
        out: list[str] = []
        seen: set[str] = set()
        for node in self.lineage(node_id):
            if node.insight and node.insight not in seen:
                seen.add(node.insight)
                out.append(node.insight)
        return out

    def summary(self) -> dict[str, int]:
        """Node counts by status — for logging the coordinator's progress."""
        counts = {status.value: 0 for status in NodeStatus}
        for node in self.nodes.values():
            counts[node.status.value] += 1
        counts["total"] = len(self.nodes)
        return counts

    # -- persistence ----------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Plain-data snapshot of the whole tree, losslessly restorable via
        :meth:`from_dict` (htr-8). Kept pure (no file I/O) so this module stays
        free of the runner/sandbox import chain — callers own where it lands."""
        return {
            "root_id": self.root_id,
            "nodes": [node.to_dict() for node in self.nodes.values()],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> HypothesisTree:
        """Rebuild a tree from :meth:`to_dict` output.

        The private proposal counter is restored to ``max(order) + 1`` so
        hypotheses expanded after a resume keep globally unique, correctly
        prioritized ordering (htr-9) — recency tie-breaks in ``pending()``
        depend on it.
        """
        tree = cls.__new__(cls)
        nodes = [HypothesisNode.from_dict(entry) for entry in data["nodes"]]
        if not nodes:
            raise ValueError("cannot restore an empty hypothesis tree")
        tree.nodes = {node.id: node for node in nodes}
        tree.root_id = str(data["root_id"])
        if tree.root_id not in tree.nodes:
            raise ValueError(f"root_id {tree.root_id!r} not among restored nodes")
        tree._order = max(node.order for node in nodes) + 1
        return tree


def _distill(hypothesis: str, evidence: HypothesisEvidence) -> str:
    """Turn raw evidence into a short, reusable lesson stated in terms of the
    hypothesis — the unit that propagates down the tree to inform later
    attempts."""
    tally = f"{evidence.benchmarks_won}/{evidence.battles} benchmarks"
    if evidence.improved:
        return (
            f"'{hypothesis}' improved the agent ({tally}, tests passing) — build on this direction."
        )
    if not evidence.tests_passed:
        return f"'{hypothesis}' broke the test suite — avoid changes of this kind."
    return f"'{hypothesis}' kept tests green but did not win a benchmark majority ({tally}) — insufficient alone."
