"""M8-D research harness — planning strategies, Goal decomposition, Graph synthesis.

Issue #903 (epic M8-D), initiative #879. Leaves: #925 (ReAct vs plan-and-execute
vs canonical Graph on the same Goals), #926 (automatic canonical Graph synthesis
from Goals and constraints), #927 (observation-driven replanning after failures
and changed constraints), #928 (bounded beam/tree-style search over candidate
plans), #929 (induction and reuse of successful Graph patterns).

This module is a RESEARCH ARTIFACT, not product code. It implements the
deterministic measurement machinery the M8-D contract demands — a pinned
Goal corpus, a discrete-event executor for canonical-shaped Graph candidates,
strategy/replan/search/reuse policies, and the cost/quality/recovery metrics
the epic's contract lists — so each leaf's benchmark procedure is reproducible
before any provider experiment is run.

Trust boundary (the epic's contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing in this module
  reads or writes a Goal, a Graph, a Run/NodeRun/Attempt, a template store, or
  any authorization surface. It imports nothing from ``maistro`` at all, so it
  cannot become a parallel execution authority by accident (M8 guardrail 1;
  the epic: "No research planner may become a parallel execution authority").
- All planners — synthesis, replanning, search, motif reuse — emit candidate
  Graph artifacts that are validated for legality and then executed by the ONE
  ``execute_plan`` function shared by every strategy in this module. There is
  no second runtime here, mirroring the epic constraint that generated Graphs
  are candidates executed through normal runtime.
- The environment is a deterministic stand-in: capabilities are costed in
  tokens/ticks with seeded failpoints, and "planner" policies are fixed rules.
  Findings are mechanism findings about policy shapes, NOT evidence about
  real models. Latency is measured in deterministic ticks, never wall-clock.

The experiment records and terminal dispositions live in
``docs/research/903-planning-goal-decomposition-graph-synthesis.md``.
"""

from __future__ import annotations

import heapq
import sys
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-D output as an
#: execution authority or a second runtime.
ADVISORY_ONLY = True


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Capability:
    """A tool/model capability the environment can execute.

    ``produces`` is the artifact key the capability yields on success;
    ``tokens`` is the standing per-call model cost; ``ticks`` is the
    deterministic latency of one call; ``alternates`` names capabilities that
    produce the same artifact (the seam a local-repair policy swaps to).
    """

    name: str
    produces: str
    tokens: int
    ticks: int
    alternates: tuple[str, ...] = ()


@dataclass(frozen=True)
class Step:
    """One node of the canonical Goal decomposition: produce ``artifact``
    after ``deps`` are available. The Goal's step list IS its decomposition;
    strategies differ only in how much of it they declare upfront and how
    they wire it."""

    artifact: str
    deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class Goal:
    """A pinned Goal: a decomposition into artifact-producing steps."""

    goal_id: str
    family: str
    steps: tuple[Step, ...]
    difficulty: int = 1

    @property
    def required(self) -> frozenset[str]:
        return frozenset(s.artifact for s in self.steps)


@dataclass(frozen=True)
class PlanNode:
    """One node of a candidate Graph artifact (evidence model, not the
    canonical ``NodeConfig``): bind ``capability`` to produce the step's
    artifact once ``deps`` (artifact keys) are available."""

    node_id: str
    artifact: str
    capability: str
    deps: tuple[str, ...] = ()


@dataclass(frozen=True)
class PlanCandidate:
    """A canonical-shaped Graph candidate: nodes plus data dependencies.

    Every strategy in this module — react, plan-and-execute, synthesized
    graphs, beam-search winners, motif-derived graphs — compiles to THIS
    artifact and executes through the ONE executor below."""

    strategy: str
    nodes: tuple[PlanNode, ...]

    @property
    def edges(self) -> tuple[tuple[str, str], ...]:
        """Artifact-level edges: (producer artifact, consumer artifact)."""
        by_artifact = {n.artifact: n.node_id for n in self.nodes}
        out: list[tuple[str, str]] = []
        for node in self.nodes:
            for dep in node.deps:
                if dep in by_artifact:
                    out.append((dep, node.artifact))
        return tuple(sorted(set(out)))

    @property
    def signatures(self) -> frozenset[tuple[str, str]]:
        """Structural node fingerprints: (artifact, capability) pairs."""
        return frozenset((n.artifact, n.capability) for n in self.nodes)


@dataclass(frozen=True)
class CallRecord:
    """One capability invocation, recorded for inspection and cost."""

    goal_id: str
    node_id: str
    capability: str
    call_number: int  # goal-execution-wide count for this capability
    ok: bool
    tokens: int
    ticks: int
    at_tick: int
    produced: str | None


@dataclass(frozen=True)
class ExecutionResult:
    """Measured outcome of one execution. Evidence only."""

    goal_id: str
    strategy: str
    success: bool
    records: tuple[CallRecord, ...]
    tokens: int
    makespan: int
    tool_errors: int
    unnecessary_calls: int
    artifacts: dict[str, str]  # artifact -> producing node_id (provenance)
    swaps: int
    replans: int
    declared_nodes: int  # nodes declared before execution began

    def row(self) -> dict[str, object]:
        return {
            "goal_id": self.goal_id,
            "strategy": self.strategy,
            "success": self.success,
            "calls": len(self.records),
            "tool_errors": self.tool_errors,
            "unnecessary": self.unnecessary_calls,
            "tokens": self.tokens,
            "ticks": self.makespan,
            "swaps": self.swaps,
            "replans": self.replans,
            "declared": self.declared_nodes,
        }


@dataclass(frozen=True)
class ValidationFinding:
    """A legality finding on a candidate, mirroring the shipped validator's
    shape (``maistro.graph.dag_validator``: code / severity / message)."""

    code: str  # unknown_kind | missing_node | cycle | no_entry | unreachable
    message: str
    node_id: str | None = None


@dataclass
class ValidationReport:
    findings: list[ValidationFinding] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.findings

    @property
    def error_count(self) -> int:
        return len(self.findings)


@dataclass(frozen=True)
class ToolWorld:
    """The deterministic environment: capability registry + seeded failpoints.

    ``failpoints[(goal_id, capability)] = f`` means the first ``f`` calls of
    that capability within that goal's execution fail (a transient fault an
    attempt budget can absorb); the value 99 models permanent unavailability.
    The call counter is per (goal execution, capability) across all nodes and
    replan generations, matching "the provider's first f calls fail".
    """

    capabilities: dict[str, Capability]
    failpoints: dict[tuple[str, str], int] = field(default_factory=dict)

    def cap(self, name: str) -> Capability:
        return self.capabilities[name]

    def meta(self, name: str) -> Capability | None:
        """Capability metadata, INCLUDING retired capabilities: a planner (or
        a mined motif) may remember what this world's registry no longer
        offers, and repair needs that memory to rebind. Fabricated names have
        no record anywhere and return None."""
        return self.capabilities.get(name) or _capabilities().get(name)

    def available(self, name: str) -> bool:
        """A capability is available unless permanently faulted for the goal
        (failpoint 99). Transient failpoints do not affect binding legality."""
        return all(fp < 99 for (gid, cap), fp in self.failpoints.items() if cap == name)


# ---------------------------------------------------------------------------
# Pinned corpus: 12 Goals across 4 families (the decomposition templates)
# ---------------------------------------------------------------------------


def _capabilities() -> dict[str, Capability]:
    caps: list[Capability] = [
        Capability("scout", "context", 300, 2, alternates=("quick_scan",)),
        Capability("quick_scan", "context", 150, 1),
        Capability("plan_task", "spec", 300, 2, alternates=("outline",)),
        Capability("outline", "spec", 150, 1),
        Capability("implement_a", "mod_a", 500, 3),
        Capability("implement_b", "mod_b", 500, 3, alternates=("implement_b_alt",)),
        Capability("implement_b_alt", "mod_b", 550, 3),
        Capability("implement_c", "mod_c", 500, 3),
        Capability("integrate", "integrated", 400, 3),
        Capability("review", "review", 300, 2, alternates=("deep_review",)),
        Capability("deep_review", "review", 500, 4),
        Capability("diagnose", "diagnosis", 400, 3, alternates=("bisect",)),
        Capability("bisect", "diagnosis", 450, 4),
        Capability("fix", "fix", 500, 3, alternates=("patch",)),
        Capability("patch", "fix", 550, 3),
        Capability("test", "verified", 300, 2, alternates=("test_suite",)),
        Capability("test_suite", "verified", 450, 3),
        Capability("brainstorm", "candidates", 400, 3),
        Capability("select", "selected", 200, 1),
        Capability("validate", "validated", 300, 2, alternates=("deep_validation",)),
        Capability("deep_validation", "validated", 450, 3),
    ]
    return {c.name: c for c in caps}


def _corpus() -> tuple[Goal, ...]:
    """12 Goals, 3 per family. Each family's step list is its canonical
    decomposition template; strategies linearize or parallelize the SAME
    decomposition, so strategy comparisons stay apples-to-apples."""

    def chain(gid: str, family: str, tail: tuple[Step, ...], difficulty: int) -> Goal:
        return Goal(gid, family, (Step("context"), *tail), difficulty)

    goals: list[Goal] = [
        # pipeline family: context -> spec -> work -> review (pure chain)
        chain(
            "pipe_1",
            "pipeline",
            (Step("spec", ("context",)), Step("mod_a", ("spec",)), Step("review", ("mod_a",))),
            1,
        ),
        chain(
            "pipe_2",
            "pipeline",
            (Step("spec", ("context",)), Step("mod_b", ("spec",)), Step("review", ("mod_b",))),
            1,
        ),
        chain(
            "pipe_3",
            "pipeline",
            (Step("spec", ("context",)), Step("fix", ("spec",)), Step("review", ("fix",))),
            2,
        ),
        # fanout family: context -> {a, b, c} -> integrated (parallel waves)
        Goal(
            "fan_1",
            "fanout",
            (
                Step("context"),
                Step("mod_a", ("context",)),
                Step("mod_b", ("context",)),
                Step("mod_c", ("context",)),
                Step("integrated", ("mod_a", "mod_b", "mod_c")),
            ),
            2,
        ),
        Goal(
            "fan_2",
            "fanout",
            (
                Step("context"),
                Step("mod_a", ("context",)),
                Step("mod_b", ("context",)),
                Step("integrated", ("mod_a", "mod_b")),
            ),
            2,
        ),
        Goal(
            "fan_3",
            "fanout",
            (
                Step("context"),
                Step("fix", ("context",)),
                Step("mod_c", ("context",)),
                Step("integrated", ("fix", "mod_c")),
            ),
            2,
        ),
        # repair family: context -> diagnosis -> fix -> verified
        chain(
            "rep_1",
            "repair",
            (
                Step("diagnosis", ("context",)),
                Step("fix", ("diagnosis",)),
                Step("verified", ("fix",)),
            ),
            2,
        ),
        chain(
            "rep_2",
            "repair",
            (
                Step("diagnosis", ("context",)),
                Step("fix", ("diagnosis",)),
                Step("verified", ("fix",)),
            ),
            2,
        ),
        chain(
            "rep_3",
            "repair",
            (
                Step("diagnosis", ("context",)),
                Step("fix", ("diagnosis",)),
                Step("verified", ("fix",)),
            ),
            3,
        ),
        # explore family: context -> candidates -> selected -> validated
        chain(
            "exp_1",
            "explore",
            (
                Step("candidates", ("context",)),
                Step("selected", ("candidates",)),
                Step("validated", ("selected",)),
            ),
            2,
        ),
        chain(
            "exp_2",
            "explore",
            (
                Step("candidates", ("context",)),
                Step("selected", ("candidates",)),
                Step("validated", ("selected",)),
            ),
            2,
        ),
        chain(
            "exp_3",
            "explore",
            (
                Step("candidates", ("context",)),
                Step("selected", ("candidates",)),
                Step("validated", ("selected",)),
            ),
            3,
        ),
    ]
    return tuple(goals)


#: Capability that produces each artifact (the synthesis binding table).
ARTIFACT_CAPABILITY: dict[str, str] = {
    "context": "scout",
    "spec": "plan_task",
    "mod_a": "implement_a",
    "mod_b": "implement_b",
    "mod_c": "implement_c",
    "integrated": "integrate",
    "review": "review",
    "diagnosis": "diagnose",
    "fix": "fix",
    "verified": "test",
    "candidates": "brainstorm",
    "selected": "select",
    "validated": "validate",
}


def topological_order(goal: Goal) -> tuple[Step, ...]:
    """Deterministic chain linearization of a Goal's decomposition (the shape
    sequential strategies execute). Kahn's algorithm with stable input order;
    raises on a cyclic decomposition."""
    remaining = list(goal.steps)
    done: set[str] = set()
    out: list[Step] = []
    while remaining:
        progressed = False
        for step in list(remaining):
            if all(d in done for d in step.deps):
                out.append(step)
                done.add(step.artifact)
                remaining.remove(step)
                progressed = True
        if not progressed:
            raise ValueError(f"cyclic decomposition in {goal.goal_id}")
    return tuple(out)


def graph_candidate(goal: Goal, world: ToolWorld, strategy: str = "graph") -> PlanCandidate:
    """Compile the decomposition AS a DAG candidate (canonical shape): the
    step list already carries the fan-out/fan-in structure, so the graph
    strategy executes it with dataflow concurrency."""
    nodes = tuple(
        PlanNode(
            node_id=f"{goal.goal_id}:{step.artifact}",
            artifact=step.artifact,
            capability=ARTIFACT_CAPABILITY[step.artifact],
            deps=step.deps,
        )
        for step in goal.steps
    )
    del world
    return PlanCandidate(strategy=strategy, nodes=nodes)


def chain_candidate(goal: Goal, world: ToolWorld, strategy: str = "chain") -> PlanCandidate:
    """Strict linearization: each node depends on the previous artifact, so
    the executor's waves degenerate to one node — a plan that has lost the
    decomposition's parallel structure."""
    order = topological_order(goal)
    nodes: list[PlanNode] = []
    previous: str | None = None
    for step in order:
        deps = (previous,) if previous is not None else ()
        nodes.append(
            PlanNode(
                node_id=f"{goal.goal_id}:c:{step.artifact}",
                artifact=step.artifact,
                capability=ARTIFACT_CAPABILITY[step.artifact],
                deps=deps,
            )
        )
        previous = step.artifact
    del world
    return PlanCandidate(strategy=strategy, nodes=tuple(nodes))


def react_candidate(goal: Goal, world: ToolWorld) -> PlanCandidate:
    """ReAct stand-in candidate: a strict chain plus periodic context re-deriva
    tion nodes (the deterministic stand-in for observation-driven refresh — the
    policy re-scouts after every second work step while work remains). The
    policy's real defining property — deciding one step at a time from
    observations instead of declaring a plan — is captured by the declared=0
    inspectability flag and the blind-retry failure policy in ``run_react``."""
    base = chain_candidate(goal, world, "react")
    order = topological_order(goal)
    nodes: list[PlanNode] = []
    for i, node in enumerate(base.nodes):
        nodes.append(node)
        if i % 2 == 1 and i < len(order) - 1:
            nodes.append(
                PlanNode(
                    node_id=f"{goal.goal_id}:r:recap{i}",
                    artifact="context",
                    capability="scout",
                    deps=(node.artifact,),
                )
            )
    return PlanCandidate(strategy="react", nodes=tuple(nodes))


# ---------------------------------------------------------------------------
# Legality validation (mirrors the shipped dag_validator finding codes)
# ---------------------------------------------------------------------------


def _kahn_state(candidate: PlanCandidate) -> tuple[Counter, dict[str, list[str]]]:
    """Indegree/adjacency over artifact-resolved edges — shared by the cycle
    check and the back-edge repair. A dependency no node produces contributes
    nothing (it is already flagged ``missing_node``)."""
    producer_of = {n.artifact: n.node_id for n in candidate.nodes}
    indeg: Counter = Counter()
    edges: dict[str, list[str]] = {}
    for node in candidate.nodes:
        for dep in node.deps:
            producer = producer_of.get(dep)
            if producer is None:
                continue
            indeg[node.node_id] += 1
            edges.setdefault(producer, []).append(node.node_id)
    return indeg, edges


def _kahn_blocked(candidate: PlanCandidate) -> set[str]:
    """Node ids that never settle in Kahn's order (cycle participants and
    everything downstream of the cycle)."""
    indeg, edges = _kahn_state(candidate)
    ready = [n.node_id for n in candidate.nodes if indeg[n.node_id] == 0]
    settled = set(ready)
    while ready:
        current = ready.pop()
        for nxt in edges.get(current, ()):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                ready.append(nxt)
                settled.add(nxt)
    return {n.node_id for n in candidate.nodes} - settled


def _reachable_artifacts(candidate: PlanCandidate, entry: PlanNode) -> frozenset[str]:
    """Artifacts reachable from the entry over RESOLVED dependencies only: a
    dead dependency is a binding defect (already flagged ``missing_node``),
    not a reachability defect, so it must not cascade into one."""
    produced = {n.artifact for n in candidate.nodes}
    reach = {entry.artifact}
    changed = True
    while changed:
        changed = False
        for node in candidate.nodes:
            if node.artifact not in reach and set(node.deps) & produced <= reach:
                reach.add(node.artifact)
                changed = True
    return frozenset(reach)


def _structure_findings(candidate: PlanCandidate) -> list[ValidationFinding]:
    """Entry-count, acyclicity, and reachability — structure legality with
    root-cause-clean diagnosis: ``unreachable`` is suppressed whenever a cycle
    is present (nodes behind a cycle are unreachable only BECAUSE the cycle
    blocks the walk; the cycle is the defect) and whenever the entry count is
    broken (with zero or several entries there is no "the entry" to measure
    reachability from). Each injected defect class therefore yields exactly
    its named finding, which is what the repair-round measurement needs."""
    findings: list[ValidationFinding] = []
    if not candidate.nodes:
        return findings
    artifacts = {n.artifact for n in candidate.nodes}
    roots = [n for n in candidate.nodes if not (set(n.deps) & artifacts)]
    if len(roots) != 1:
        findings.append(
            ValidationFinding(
                "no_entry", f"candidate has {len(roots)} entry nodes, expected exactly 1"
            )
        )
        if _kahn_blocked(candidate):
            findings.append(ValidationFinding("cycle", "candidate contains a dependency cycle"))
        return findings
    if _kahn_blocked(candidate):
        findings.append(ValidationFinding("cycle", "candidate contains a dependency cycle"))
        return findings
    reach = _reachable_artifacts(candidate, roots[0])
    for node in candidate.nodes:
        if node.artifact not in reach:
            findings.append(
                ValidationFinding(
                    "unreachable",
                    f"node {node.node_id} is unreachable from the entry",
                    node.node_id,
                )
            )
    return findings


def validate_candidate(candidate: PlanCandidate, world: ToolWorld) -> ValidationReport:
    """Structural legality of a Graph candidate: known capabilities, resolvable
    endpoints, acyclic, unique entry, everything reachable. Deliberately the
    same check families as the shipped ``dag_validator`` (structure + binding),
    re-implemented for measurement only."""
    findings = _structure_findings(candidate)
    artifacts = {n.artifact for n in candidate.nodes}
    for node in candidate.nodes:
        if node.capability not in world.capabilities:
            findings.append(
                ValidationFinding(
                    "unknown_kind",
                    f"node {node.node_id} binds unknown capability {node.capability!r}",
                    node.node_id,
                )
            )
        for dep in node.deps:
            if dep not in artifacts:
                findings.append(
                    ValidationFinding(
                        "missing_node",
                        f"node {node.node_id} depends on {dep!r} which no node produces",
                        node.node_id,
                    )
                )
    return ValidationReport(findings)


def repair_candidate(candidate: PlanCandidate, world: ToolWorld) -> tuple[PlanCandidate, int]:
    """Deterministic bounded repair loop applying MINIMAL fixes: cycles are
    repaired by removing the offending back-edge (not the node), dangling
    dependencies by removing the dead edge, unknown bindings by rebinding to
    the first available alternate (node dropped only when none exists),
    multiple entries by re-rooting extras, unreachables by dropping the orphan
    node. Returns (candidate, repair rounds used)."""
    current = candidate
    for round_used in range(1, 5):
        report = validate_candidate(current, world)
        if report.is_valid:
            return current, round_used - 1
        artifacts = {n.artifact for n in current.nodes}
        roots = [n for n in current.nodes if not (set(n.deps) & artifacts)]
        nodes = list(current.nodes)
        if any(f.code == "cycle" for f in report.findings):
            current = _remove_back_edge(current)
            if current.nodes != tuple(nodes):
                continue
            nodes.remove(max(nodes, key=lambda n: len(n.deps)))  # fallback: drop worst
        elif any(f.code == "no_entry" for f in report.findings) and len(roots) > 1:
            first_root = roots[0]
            extras = {r.node_id for r in roots[1:]}
            nodes = [
                PlanNode(n.node_id, n.artifact, n.capability, (*n.deps, first_root.artifact))
                if n.node_id in extras
                else n
                for n in nodes
            ]
        else:
            by_code = {f.code: f for f in report.findings}
            if "unknown_kind" in by_code:
                nodes = [_rebind_or_drop(n, world) for n in nodes]
                nodes = [n for n in nodes if n is not None]
            elif "missing_node" in by_code:
                produced = {n.artifact for n in nodes}
                nodes = [
                    PlanNode(
                        n.node_id,
                        n.artifact,
                        n.capability,
                        tuple(d for d in n.deps if d in produced),
                    )
                    for n in nodes
                ]
            elif "unreachable" in by_code:
                drop = {f.node_id for f in report.findings if f.code == "unreachable" and f.node_id}
                nodes = [n for n in nodes if n.node_id not in drop]
            else:
                return current, round_used  # unrepairable
        current = PlanCandidate(strategy=current.strategy, nodes=tuple(nodes))
    return current, 4


def _remove_back_edge(candidate: PlanCandidate) -> PlanCandidate:
    """Remove one dependency that participates in a cycle (Kahn-blocked node
    whose dep is produced by another blocked node) — the minimal repair."""
    blocked_ids = _kahn_blocked(candidate)
    if not blocked_ids:
        return candidate
    producer_of = {n.artifact: n.node_id for n in candidate.nodes}
    for node in candidate.nodes:
        if node.node_id not in blocked_ids:
            continue
        for dep in node.deps:
            if producer_of.get(dep) in blocked_ids:
                trimmed = tuple(d for d in node.deps if d != dep)
                return PlanCandidate(
                    strategy=candidate.strategy,
                    nodes=tuple(
                        PlanNode(
                            n.node_id,
                            n.artifact,
                            n.capability,
                            trimmed if n.node_id == node.node_id else n.deps,
                        )
                        for n in candidate.nodes
                    ),
                )
    return candidate


def _rebind_or_drop(node: PlanNode, world: ToolWorld) -> PlanNode | None:
    """Rebind an unknown capability to its first available alternate; drop the
    node (return None) when no alternate exists. Alternate metadata comes from
    the CANONICAL registry, not the world's: a candidate may reference a
    capability this world has retired entirely (the planner remembers what the
    environment no longer offers), and a fabricated binding has no record at
    all — that node is dropped."""
    if node.capability in world.capabilities:
        return node
    known = _capabilities().get(node.capability)
    alternate = (
        next((a for a in known.alternates if a in world.capabilities), None)
        if known is not None
        else None
    )
    if alternate is None:
        return None
    return PlanNode(node.node_id, node.artifact, alternate, node.deps)


# ---------------------------------------------------------------------------
# The ONE executor (discrete-event, tick-based, deterministic)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplanOutcome:
    """A full-replan policy decision: a fresh candidate plus whether already
    produced artifacts carry over (work reuse) or are discarded."""

    candidate: PlanCandidate
    carry_artifacts: bool


ExecutePolicy = Callable[
    [PlanCandidate, Goal, ToolWorld, dict[str, str], list[tuple[str, bool]]], ReplanOutcome | None
]


def _no_replan(
    candidate: PlanCandidate,
    goal: Goal,
    world: ToolWorld,
    artifacts: dict[str, str],
    exhausted: list[tuple[str, bool]],
) -> ReplanOutcome | None:
    del candidate, goal, world, artifacts, exhausted
    return None


def _unproduced_failed_nodes(
    current: PlanCandidate, artifacts: dict[str, str], records: list[CallRecord]
) -> list[PlanNode]:
    """Nodes whose artifact never got produced by a capability that exhausted
    its attempt budget — the trigger set for local swap / full replan."""
    exhausted = {r.capability for r in records if not r.ok}
    return [n for n in current.nodes if n.artifact not in artifacts and n.capability in exhausted]


def _local_swap_step(
    current: PlanCandidate, failed: list[PlanNode], artifacts: dict[str, str], world: ToolWorld
) -> tuple[PlanCandidate | None, int]:
    """Swap every failed node to its first AVAILABLE alternate producing the
    same artifact. Returns (new candidate | None when nothing could swap — the
    bounded give-up, swaps performed)."""
    nodes = list(current.nodes)
    swaps = 0
    for i, node in enumerate(nodes):
        if node.artifact in artifacts or node not in failed:
            continue
        alternate = next(
            (
                a
                for a in world.cap(node.capability).alternates
                if a in world.capabilities and world.available(a)
            ),
            None,
        )
        if alternate is not None:
            nodes[i] = PlanNode(node.node_id, node.artifact, alternate, node.deps)
            swaps += 1
    if swaps == 0:
        return None, 0
    return PlanCandidate(strategy=current.strategy, nodes=tuple(nodes)), swaps


def _start_ready_nodes(
    world: ToolWorld,
    goal: Goal,
    *,
    carried: frozenset[str],
    attempts_per_node: int,
    produced: set[str],
    states: dict[str, list],
    running: list[tuple[int, int, str, int]],
    records: list[CallRecord],
    call_numbers: Counter[str],
    seq: int,
    now: int,
) -> int:
    """Start every dependency-satisfied, under-budget node of the generation;
    mutates ``running``/``records``/``states`` in place. Returns the advanced
    sequence number (the event heap's insertion-order tie-break)."""
    for state in states.values():
        node, calls, exhausted, done = state
        if done or node.artifact in carried or exhausted or calls >= attempts_per_node:
            continue
        if any(r[2] == node.node_id for r in running):
            continue
        if not all(d in produced for d in node.deps):
            continue
        capability = world.capabilities.get(node.capability)
        if capability is None:
            # Stale binding: the provider does not exist in this world. The
            # call cannot even be attempted — the node is unrunnable, so the
            # generation quiesces without it and the run fails its goal. An
            # illegal candidate FAILS CLEANLY; it never crashes the executor.
            state[2] = True  # exhausted
            continue
        call_numbers[node.capability] += 1
        number = call_numbers[node.capability]
        rec_idx = len(records)
        records.append(
            CallRecord(
                goal.goal_id,
                node.node_id,
                node.capability,
                number,
                False,
                capability.tokens,
                capability.ticks,
                now,
                None,
            )
        )
        heapq.heappush(running, (now + capability.ticks, seq, node.node_id, rec_idx))
        seq += 1
        state[1] = calls + 1
    return seq


def _simulate_generation(
    world: ToolWorld,
    goal: Goal,
    *,
    cap: PlanCandidate,
    carried: frozenset[str],
    attempts_per_node: int,
    artifacts: dict[str, str],
    records: list[CallRecord],
    call_numbers: Counter[str],
    now: int,
) -> int:
    """Run one candidate generation to quiescence. ``carried`` lists artifacts
    produced by EARLIER generations (replan reuse): nodes for carried
    artifacts are skipped entirely — that is what reuse means — while
    re-derivation nodes inside a generation always run. Returns the tick the
    generation finished at (the caller's clock only moves forward)."""
    states: dict[str, list] = {
        n.node_id: [n, 0, False, False] for n in cap.nodes
    }  # [node, calls, exhausted, done]
    produced = set(carried)  # dep satisfaction includes carried artifacts
    running: list[tuple[int, int, str, int]] = []  # (finish, seq, node_id, rec_idx)
    seq = 0
    while True:
        seq = _start_ready_nodes(
            world,
            goal,
            carried=carried,
            attempts_per_node=attempts_per_node,
            produced=produced,
            states=states,
            running=running,
            records=records,
            call_numbers=call_numbers,
            seq=seq,
            now=now,
        )
        if not running:
            break
        finish, _, node_id, rec_idx = heapq.heappop(running)
        now = finish
        state = states[node_id]
        node = state[0]
        fp = world.failpoints.get((goal.goal_id, node.capability), 0)
        ok = call_numbers[node.capability] > fp
        rec = records[rec_idx]
        records[rec_idx] = CallRecord(
            rec.goal_id,
            rec.node_id,
            rec.capability,
            rec.call_number,
            ok,
            rec.tokens,
            rec.ticks,
            rec.at_tick,
            node.artifact if ok else None,
        )
        if ok:
            produced.add(node.artifact)
            artifacts[node.artifact] = node.node_id
            state[3] = True
        elif state[1] >= attempts_per_node:
            state[2] = True
    return now


def execute_plan(
    candidate: PlanCandidate,
    goal: Goal,
    world: ToolWorld,
    *,
    strategy: str,
    attempts_per_node: int = 1,
    on_exhausted: str = "fail",  # fail | local_swap | full_replan
    max_replans: int = 2,
    replan: ExecutePolicy = _no_replan,
    declared_nodes: int | None = None,
) -> ExecutionResult:
    """Execute a Graph candidate under the discrete-event tick model.

    All nodes with satisfied dependencies run concurrently (one call each per
    wave); sequential strategies simply have chain candidates, so their waves
    degenerate to one node. Failed calls retry in place up to
    ``attempts_per_node`` (canonical attempt semantics); exhaustion then
    consults the policy: ``local_swap`` swaps the node's capability for an
    alternate producing the same artifact, ``full_replan`` asks the replan
    policy for a fresh candidate. ``fail`` (the canonical default) fails the
    run — a run cannot claim success over a failed node. Never loops: every
    repair path is bounded (attempt budgets, swap bound, replan bound).
    """
    artifacts: dict[str, str] = {}
    records: list[CallRecord] = []
    call_numbers: Counter[str] = Counter()
    swaps = 0
    replans = 0
    declared = len(candidate.nodes) if declared_nodes is None else declared_nodes
    current = candidate
    now = 0
    while True:
        now = _simulate_generation(
            world,
            goal,
            cap=current,
            carried=frozenset(artifacts),
            attempts_per_node=attempts_per_node,
            artifacts=artifacts,
            records=records,
            call_numbers=call_numbers,
            now=now,
        )
        if _goal_satisfied(goal, artifacts):
            break
        failed_nodes = _unproduced_failed_nodes(current, artifacts, records)
        if not failed_nodes:
            break
        if on_exhausted == "local_swap" and swaps < 4:
            swapped, added = _local_swap_step(current, failed_nodes, artifacts, world)
            if swapped is None:
                break  # no alternate: bounded give-up
            current = swapped
            swaps += added
            continue
        if on_exhausted == "full_replan" and replans < max_replans:
            exhausted_report = [(n.capability, True) for n in failed_nodes]
            outcome = replan(current, goal, world, dict(artifacts), exhausted_report)
            if outcome is None:
                break
            current = outcome.candidate
            replans += 1
            if not outcome.carry_artifacts:
                artifacts.clear()
            continue
        break

    success = _goal_satisfied(goal, artifacts)
    tool_errors = sum(1 for r in records if not r.ok)
    produced_counts = Counter(r.produced for r in records if r.ok)
    unnecessary = sum(count - 1 for count in produced_counts.values())
    tokens = sum(r.tokens for r in records)
    return ExecutionResult(
        goal_id=goal.goal_id,
        strategy=strategy,
        success=success,
        records=tuple(records),
        tokens=tokens,
        makespan=now,
        tool_errors=tool_errors,
        unnecessary_calls=unnecessary,
        artifacts=artifacts,
        swaps=swaps,
        replans=replans,
        declared_nodes=declared,
    )


def _goal_satisfied(goal: Goal, artifacts: dict[str, str]) -> bool:
    return goal.required <= set(artifacts)


# ---------------------------------------------------------------------------
# Strategy drivers (D1) — all through the one executor
# ---------------------------------------------------------------------------


def run_react(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """ReAct stand-in: nothing declarable upfront, blind in-place retry once
    (attempts=2), then give up — no replanning, no alternates."""
    return execute_plan(
        react_candidate(goal, world),
        goal,
        world,
        strategy="react",
        attempts_per_node=2,
        declared_nodes=0,
    )


def run_plan_execute(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Plan-and-execute stand-in: the full linear plan declared upfront
    (sequential), one attempt per step; on exhaustion, re-plan the remaining
    chain, keeping produced artifacts (naive reuse)."""

    def replan(
        candidate: PlanCandidate,
        g: Goal,
        w: ToolWorld,
        have: dict[str, str],
        exhausted: list[tuple[str, bool]],
    ) -> ReplanOutcome | None:
        del candidate, exhausted
        remaining = [s for s in topological_order(g) if s.artifact not in have]
        if not remaining:
            return None
        nodes = []
        for step in remaining:
            deps = tuple(d for d in step.deps if d in have) or (
                (nodes[-1].artifact,) if nodes else ()
            )
            nodes.append(
                PlanNode(
                    f"{g.goal_id}:p:{step.artifact}",
                    step.artifact,
                    ARTIFACT_CAPABILITY[step.artifact],
                    deps,
                )
            )
        return ReplanOutcome(PlanCandidate("plan_execute", tuple(nodes)), carry_artifacts=True)

    start = chain_candidate(goal, world, "plan_execute")
    return execute_plan(
        start,
        goal,
        world,
        strategy="plan_execute",
        attempts_per_node=1,
        on_exhausted="full_replan",
        max_replans=3,
        replan=replan,
    )


def run_graph(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Canonical Graph stand-in: the full DAG declared upfront, attempt-budget
    retries, no replanning (the shipped default)."""
    return execute_plan(
        graph_candidate(goal, world), goal, world, strategy="graph", attempts_per_node=3
    )


STRATEGIES: dict[str, Callable[[Goal, ToolWorld], ExecutionResult]] = {
    "react": run_react,
    "plan_execute": run_plan_execute,
    "graph": run_graph,
}


def run_benchmark(
    goals: tuple[Goal, ...],
    world: ToolWorld,
    strategies: dict[str, Callable[[Goal, ToolWorld], ExecutionResult]] | None = None,
) -> list[ExecutionResult]:
    strategies = strategies or STRATEGIES
    rows: list[ExecutionResult] = []
    for goal in goals:
        for driver in strategies.values():
            rows.append(driver(goal, world))
    return rows


def percentile(sorted_values: list[int], p: float) -> int:
    """Nearest-rank percentile on a pre-sorted list (hand-checkable)."""
    if not sorted_values:
        return 0
    rank = max(1, -(-int(len(sorted_values) * p * 100) // 100))
    return sorted_values[min(len(sorted_values), rank) - 1]


def summarize(rows: list[ExecutionResult]) -> dict[str, dict[str, float]]:
    """Aggregate per strategy: success rate, means, p50/p95 makespan (ticks)."""
    out: dict[str, dict[str, float]] = {}
    by_strategy: dict[str, list[ExecutionResult]] = {}
    for row in rows:
        by_strategy.setdefault(row.strategy, []).append(row)
    for name, group in by_strategy.items():
        ticks = sorted(r.makespan for r in group)
        out[name] = {
            "success_rate": sum(1 for r in group if r.success) / len(group),
            "mean_calls": sum(len(r.records) for r in group) / len(group),
            "mean_tool_errors": sum(r.tool_errors for r in group) / len(group),
            "mean_unnecessary": sum(r.unnecessary_calls for r in group) / len(group),
            "mean_tokens": sum(r.tokens for r in group) / len(group),
            "p50_ticks": float(percentile(ticks, 0.5)),
            "p95_ticks": float(percentile(ticks, 0.95)),
            "declared": sum(r.declared_nodes for r in group) / len(group),
        }
    return out


# ---------------------------------------------------------------------------
# Synthesis (D2): Goal + constraints -> candidate Graph -> validate -> repair
# ---------------------------------------------------------------------------


def synthesize(
    goal: Goal, world: ToolWorld, available: frozenset[str] | None = None
) -> PlanCandidate:
    """Synthesis stand-in (the rule synthesizer): bind each decomposition step
    to a capability — the primary, or an available alternate when constrained.
    Emits a candidate ONLY; legality is the validator's job and execution the
    canonical executor's."""

    def bind(artifact: str) -> str:
        primary = ARTIFACT_CAPABILITY[artifact]
        meta = world.meta(primary)
        alternates = meta.alternates if meta is not None else ()
        if available is not None:
            # Explicit constraint set: membership decides, the live environment
            # is NOT consulted — a world-blind planner binds the registry
            # default even where it is faulted (the D4 naive candidate); a
            # replanner binds the registry minus what just broke.
            if primary in available:
                return primary
            for alt in alternates:
                if alt in available:
                    return alt
            return primary  # stale binding: the validator must flag it
        # Environment-aware default: registry membership AND live availability.
        if primary in world.capabilities and world.available(primary):
            return primary
        for alt in alternates:
            if alt in world.capabilities and world.available(alt):
                return alt
        return primary  # stale binding: the validator must flag it

    nodes = tuple(
        PlanNode(f"{goal.goal_id}:s:{step.artifact}", step.artifact, bind(step.artifact), step.deps)
        for step in goal.steps
    )
    return PlanCandidate(strategy="synth", nodes=nodes)


def synthesis_with_repair(
    goal: Goal, world: ToolWorld, available: frozenset[str] | None = None
) -> tuple[PlanCandidate, int, ValidationReport]:
    """The synthesis loop the leaf #926 benchmark measures: emit, validate,
    repair to legality; report repair iterations and the final report."""
    candidate = synthesize(goal, world, available)
    report = validate_candidate(candidate, world)
    if report.is_valid:
        return candidate, 0, report
    fixed, iterations = repair_candidate(candidate, world)
    return fixed, iterations, validate_candidate(fixed, world)


def defective(candidate: PlanCandidate, defect: str) -> PlanCandidate:
    """Inject one structural defect for validator/repair measurement. Each
    injection is crafted to be a SINGLE pathology: the entry stays the sole
    root (a defect that consumed the entry would conflate its own code with
    ``no_entry``), so the validator's diagnosis names exactly the defect."""
    nodes = list(candidate.nodes)
    if defect == "cycle" and len(nodes) >= 3:
        first, second = nodes[1], nodes[2]
        nodes[1] = PlanNode(
            first.node_id, first.artifact, first.capability, (*first.deps, second.artifact)
        )
    elif defect == "dangling_edge" and len(nodes) >= 2:
        first = nodes[1]
        nodes[1] = PlanNode(
            first.node_id, first.artifact, first.capability, (*first.deps, "ghost_artifact")
        )
    elif defect == "unknown_binding" and nodes:
        first = nodes[0]
        nodes[0] = PlanNode(first.node_id, first.artifact, "retired_capability", first.deps)
    elif defect == "orphan" and len(nodes) >= 2:
        nodes.append(PlanNode(f"{nodes[0].node_id}:orphan", "orphan_artifact", "scout", ()))
    elif defect == "two_entries" and len(nodes) >= 2:
        nodes[1] = PlanNode(nodes[1].node_id, nodes[1].artifact, nodes[1].capability, ())
    return PlanCandidate(strategy=candidate.strategy, nodes=tuple(nodes))


# ---------------------------------------------------------------------------
# Replanning policies (D3): none | local repair | full replan (fresh / reuse)
# ---------------------------------------------------------------------------


def run_policy_none(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Canonical default: attempt-budget retries only; a node that exhausts
    its budget fails the run (no planner in the loop)."""
    return execute_plan(
        graph_candidate(goal, world), goal, world, strategy="policy_none", attempts_per_node=3
    )


def run_policy_local_repair(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Local repair: swap only the exhausted node's capability for an
    alternate producing the same artifact; all completed work carries."""
    return execute_plan(
        graph_candidate(goal, world),
        goal,
        world,
        strategy="policy_local",
        attempts_per_node=3,
        on_exhausted="local_swap",
    )


def _full_replan_policy(carry: bool) -> ExecutePolicy:
    def policy(
        candidate: PlanCandidate,
        goal: Goal,
        world: ToolWorld,
        have: dict[str, str],
        exhausted: list[tuple[str, bool]],
    ) -> ReplanOutcome | None:
        del candidate, have
        broken = {capability for capability, _ in exhausted}
        available = frozenset(c for c in world.capabilities if c not in broken)
        return ReplanOutcome(synthesize(goal, world, available), carry_artifacts=carry)

    return policy


def run_policy_full_replan_fresh(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Full replan, no reuse: re-synthesize from scratch and discard all
    completed work (the wasteful extreme)."""
    return execute_plan(
        graph_candidate(goal, world),
        goal,
        world,
        strategy="policy_replan_fresh",
        attempts_per_node=3,
        on_exhausted="full_replan",
        max_replans=2,
        replan=_full_replan_policy(carry=False),
    )


def run_policy_full_replan_reuse(goal: Goal, world: ToolWorld) -> ExecutionResult:
    """Full replan with reuse: re-synthesize but carry completed artifacts."""
    return execute_plan(
        graph_candidate(goal, world),
        goal,
        world,
        strategy="policy_replan_reuse",
        attempts_per_node=3,
        on_exhausted="full_replan",
        max_replans=2,
        replan=_full_replan_policy(carry=True),
    )


REPLAN_POLICIES: dict[str, Callable[[Goal, ToolWorld], ExecutionResult]] = {
    "policy_none": run_policy_none,
    "policy_local": run_policy_local_repair,
    "policy_replan_fresh": run_policy_full_replan_fresh,
    "policy_replan_reuse": run_policy_full_replan_reuse,
}


# ---------------------------------------------------------------------------
# Bounded search over candidate plans (D4)
# ---------------------------------------------------------------------------


def candidate_variants(goal: Goal, world: ToolWorld) -> list[PlanCandidate]:
    """K structurally distinct candidates for one Goal: v0 minimal (primary
    bindings, emitted WITHOUT environment knowledge — the naive default a
    planner produces when it does not inspect the world), v1 canonical DAG
    (same bindings, same shape here — a control), v2 robust (alternate
    bindings for every steppable artifact), v3 under-provisioned (drops the
    last step; fails the rubric)."""
    base = synthesize(goal, world, available=frozenset(world.capabilities))
    robust_nodes = []
    for node in base.nodes:
        alternate = next(
            (
                a
                for a in world.cap(node.capability).alternates
                if a in world.capabilities and world.available(a)
            ),
            node.capability,
        )
        robust_nodes.append(PlanNode(node.node_id, node.artifact, alternate, node.deps))
    under = base.nodes[:-1] if len(base.nodes) > 1 else base.nodes
    return [
        PlanCandidate("search_v0_minimal", base.nodes),
        PlanCandidate("search_v1_dag", graph_candidate(goal, world).nodes),
        PlanCandidate("search_v2_robust", tuple(robust_nodes)),
        PlanCandidate("search_v3_under", tuple(under)),
    ]


def rubric_coverage(candidate: PlanCandidate, goal: Goal, world: ToolWorld) -> float:
    """Verifier stand-in: fraction of required artifacts the candidate can
    produce through capabilities that are AVAILABLE in this world (permanently
    faulted capabilities bind, but cannot ever succeed — the verifier inspects
    environment state, which is what a real planner's verifier can do)."""
    producible = {n.artifact for n in candidate.nodes if world.available(n.capability)}
    if not goal.required:
        return 1.0
    return len(producible & goal.required) / len(goal.required)


def plan_search(
    goal: Goal, world: ToolWorld, *, verifier_misses: frozenset[int] = frozenset()
) -> tuple[PlanCandidate, int]:
    """Bounded beam: generate K candidates, score each with the verifier, pick
    the best (ties -> earliest candidate). ``verifier_misses`` lists candidate
    indices the verifier mis-scores to 0.0 — the ranker-error stand-in.
    Returns (winner, planning calls spent = K)."""
    variants = candidate_variants(goal, world)
    scores = [
        0.0 if i in verifier_misses else rubric_coverage(cand, goal, world)
        for i, cand in enumerate(variants)
    ]
    winner_index = max(range(len(variants)), key=lambda i: (scores[i], -i))
    return variants[winner_index], len(variants)


# ---------------------------------------------------------------------------
# Motif induction and reuse (D5)
# ---------------------------------------------------------------------------


def mine_motifs(goals: tuple[Goal, ...], world: ToolWorld) -> dict[str, PlanCandidate]:
    """Mine one motif per family from successful runs: the family's winning
    candidate shape (the stand-in for clustering successful Runs by task
    structure and extracting the shared subgraph)."""
    motifs: dict[str, PlanCandidate] = {}
    for goal in goals:
        candidate = synthesize(goal, world)
        if not validate_candidate(candidate, world).is_valid:
            continue
        result = execute_plan(candidate, goal, world, strategy="motif_mine", attempts_per_node=3)
        if result.success and goal.family not in motifs:
            motifs[goal.family] = candidate
    return motifs


def adapt_motif(motif: PlanCandidate, goal: Goal, world: ToolWorld) -> PlanCandidate:
    """Reuse: re-bind the motif's SHAPE onto the goal's artifacts in
    topological order. A chain motif applied to a fan-out goal re-wires the
    goal's joins into a chain — reuse loses parallel structure it never saw."""
    if not motif.nodes:
        raise ValueError("cannot adapt an empty motif")
    order = topological_order(goal)
    nodes: list[PlanNode] = []
    for i, step in enumerate(order):
        template = motif.nodes[i] if i < len(motif.nodes) else None
        keep_deps = template is not None and template.deps == step.deps
        deps = step.deps if keep_deps else ((order[i - 1].artifact,) if i > 0 else ())
        nodes.append(
            PlanNode(
                f"{goal.goal_id}:m:{step.artifact}",
                step.artifact,
                ARTIFACT_CAPABILITY[step.artifact],
                deps,
            )
        )
    del world
    return PlanCandidate(strategy="motif_reuse", nodes=tuple(nodes))


def edit_distance(a: PlanCandidate, b: PlanCandidate) -> int:
    """Structural edit distance: node-signature symmetric difference (artifact,
    capability) plus artifact-level edge symmetric difference."""
    return len(a.signatures ^ b.signatures) + len(set(a.edges) ^ set(b.edges))


# ---------------------------------------------------------------------------
# Pinned environment instantiations
# ---------------------------------------------------------------------------


def clean_world() -> ToolWorld:
    return ToolWorld(capabilities=_capabilities(), failpoints={})


def transient_fault_world() -> ToolWorld:
    """D1 fault run: the second decomposition step's capability fails its
    first two calls in every goal (recoverable by an attempt budget of 3,
    not by 2; replanning recovers only by burning full re-plans)."""
    world = clean_world()
    faults: dict[tuple[str, str], int] = {}
    for goal in _corpus():
        mid = topological_order(goal)[1]
        faults[(goal.goal_id, ARTIFACT_CAPABILITY[mid.artifact])] = 2
    return ToolWorld(capabilities=world.capabilities, failpoints=faults)


def permanent_fault_world(capability: str = "fix") -> ToolWorld:
    """D3/D4 surprise: one capability is permanently unavailable (failpoint
    99) in every goal — the provider is gone; only repair/replan to an
    alternate can recover."""
    world = clean_world()
    faults = {(g.goal_id, capability): 99 for g in _corpus()}
    return ToolWorld(capabilities=world.capabilities, failpoints=faults)


def stuck_pair_world(goal: Goal, artifact: str = "fix") -> ToolWorld:
    """Oscillation probe: BOTH the artifact's primary capability and its
    alternates are permanently unavailable — every repair policy must
    terminate bounded, not loop."""
    world = clean_world()
    primary = ARTIFACT_CAPABILITY[artifact]
    faults = {(goal.goal_id, primary): 99}
    for alternate in world.cap(primary).alternates:
        faults[(goal.goal_id, alternate)] = 99
    return ToolWorld(capabilities=world.capabilities, failpoints=faults)


if __name__ == "__main__":  # pragma: no cover - manual table printer
    goals = _corpus()
    print("== D1 clean ==")
    for name, agg in summarize(run_benchmark(goals, clean_world())).items():
        print(name, {k: round(v, 3) for k, v in agg.items()})
    print("== D1 transient faults ==")
    for name, agg in summarize(run_benchmark(goals, transient_fault_world())).items():
        print(name, {k: round(v, 3) for k, v in agg.items()})
    print("== D3 permanent fault on 'fix' ==")
    w3 = permanent_fault_world()
    for name, driver in REPLAN_POLICIES.items():
        rows = [driver(g, w3) for g in goals]
        print(
            name,
            {
                "recovered": sum(1 for r in rows if r.success),
                "of": len(rows),
                "calls": sum(len(r.records) for r in rows),
                "duplicates": sum(r.unnecessary_calls for r in rows),
                "tokens": sum(r.tokens for r in rows),
                "ticks": sum(r.makespan for r in rows),
                "replans": sum(r.replans for r in rows),
                "swaps": sum(r.swaps for r in rows),
            },
        )
    print("== D4 search (difficult slice, permanent fault on 'fix') ==")
    difficult = [g for g in goals if g.difficulty >= 2]
    for misses in (frozenset(), frozenset({2})):
        wins, calls = [], 0
        for g in difficult:
            cand, spent = plan_search(g, w3, verifier_misses=misses)
            calls += spent
            wins.append(execute_plan(cand, g, w3, strategy="beam", attempts_per_node=3).success)
        print(
            f"verifier_misses={sorted(misses)}",
            {"success": sum(wins), "of": len(wins), "planning_calls": calls},
        )
    print("== D5 reuse (held-out rep_3/exp_3, motifs from the rest) ==")
    train = tuple(g for g in goals if g.goal_id not in {"rep_3", "exp_3"})
    motifs = mine_motifs(train, clean_world())
    for g in (goals[8], goals[11]):
        scratch, iters, _ = synthesis_with_repair(g, clean_world())
        motif = motifs.get(g.family)
        reused = adapt_motif(motif, g, clean_world())
        wm = execute_plan(reused, g, clean_world(), strategy="m", attempts_per_node=3)
        ws = execute_plan(scratch, g, clean_world(), strategy="s", attempts_per_node=3)
        print(
            g.goal_id,
            {
                "edit_vs_scratch": edit_distance(reused, scratch),
                "scratch_repair_iters": iters,
                "motif": (wm.success, wm.tokens, wm.makespan),
                "scratch": (ws.success, ws.tokens, ws.makespan),
            },
        )
    print("== D5 cross-family transfer (pipeline motif -> fanout goal) ==")
    pipe_motif = motifs["pipeline"]
    fan = goals[3]
    adapted = adapt_motif(pipe_motif, fan, clean_world())
    scratch_fan = synthesize(fan, clean_world())
    print(
        fan.goal_id,
        {
            "edit_distance": edit_distance(adapted, scratch_fan),
            "adapted_ticks": execute_plan(
                adapted, fan, clean_world(), strategy="m", attempts_per_node=3
            ).makespan,
            "scratch_ticks": execute_plan(
                scratch_fan, fan, clean_world(), strategy="s", attempts_per_node=3
            ).makespan,
        },
    )


# ---------------------------------------------------------------------------
# Tests — instruments first, then the pinned benchmark findings
# ---------------------------------------------------------------------------


def test_advisory_only_contract():
    """The evidence-only marker cannot rot silently (M8 guardrail 1)."""
    assert ADVISORY_ONLY is True


class TestMetricIdentities:
    """The instruments before the measurement: hand-checked metric math."""

    def test_percentile_nearest_rank_hand_checked(self):
        values = list(range(1, 13))  # 1..12 sorted
        assert percentile(values, 0.5) == 6  # rank ceil(6) -> 6th
        assert percentile(values, 0.95) == 12  # rank ceil(11.4) -> 12th
        assert percentile([7], 0.95) == 7
        assert percentile([], 0.5) == 0

    def test_success_and_unnecessary_on_a_toy_recap_execution(self):
        goal = Goal("t1", "pipeline", (Step("context"), Step("spec", ("context",))))
        world = clean_world()
        recap = PlanCandidate(
            "toy",
            (
                PlanNode("t1:context", "context", "scout"),
                PlanNode("t1:spec", "spec", "plan_task", ("context",)),
                PlanNode("t1:recap", "context", "scout", ("spec",)),
            ),
        )
        result = execute_plan(recap, goal, world, strategy="toy", attempts_per_node=1)
        assert result.success is True
        assert result.unnecessary_calls == 1  # context produced twice
        assert result.tool_errors == 0

    def test_edit_distance_hand_checked(self):
        world = clean_world()
        goal = Goal("e1", "pipeline", (Step("context"), Step("spec", ("context",))))
        a = graph_candidate(goal, world)
        assert edit_distance(a, a) == 0
        # swap one binding: the old signature leaves and the new one enters
        swapped = PlanCandidate(
            "s", (a.nodes[0], PlanNode("e1:spec", "spec", "outline", ("context",)))
        )
        assert edit_distance(a, swapped) == 2
        # rewire one edge: one edge op (context->spec becomes transitively chained)
        rewired = PlanCandidate("s", (a.nodes[0], PlanNode("e1:spec", "spec", "plan_task", ())))
        assert edit_distance(a, rewired) == 1

    def test_rubric_coverage_hand_checked(self):
        world = clean_world()
        goal = Goal(
            "c1",
            "repair",
            (
                Step("context"),
                Step("diagnosis", ("context",)),
                Step("fix", ("diagnosis",)),
                Step("verified", ("fix",)),
            ),
        )
        base = synthesize(goal, world)
        assert rubric_coverage(base, goal, world) == 1.0
        under = PlanCandidate("u", base.nodes[:-1])
        assert rubric_coverage(under, goal, world) == 0.75
        dead = ToolWorld(capabilities=world.capabilities, failpoints={(goal.goal_id, "fix"): 99})
        assert rubric_coverage(base, goal, dead) == 0.75

    def test_synthesis_is_deterministic(self):
        goal = _corpus()[3]
        first = synthesize(goal, clean_world())
        second = synthesize(goal, clean_world())
        assert first.nodes == second.nodes
        assert first.edges == second.edges


class TestCorpusSanity:
    def test_corpus_shape_and_binding_integrity(self):
        goals = _corpus()
        assert len(goals) == 12
        families = Counter(g.family for g in goals)
        assert families == Counter({"pipeline": 3, "fanout": 3, "repair": 3, "explore": 3})
        assert len({g.goal_id for g in goals}) == 12
        world = clean_world()
        for goal in goals:
            for step in goal.steps:
                capability = ARTIFACT_CAPABILITY[step.artifact]
                assert capability in world.capabilities
                assert world.cap(capability).tokens > 0
                assert world.cap(capability).ticks > 0

    def test_clean_graph_run_is_the_solvable_floor(self):
        """Every goal is solvable with zero waste and zero errors — the
        reference solution other rows are measured against."""
        world = clean_world()
        for goal in _corpus():
            result = run_graph(goal, world)
            assert result.success, goal.goal_id
            assert result.unnecessary_calls == 0
            assert result.tool_errors == 0
            assert result.swaps == 0 and result.replans == 0

    def test_fanout_critical_path_is_hand_checkable(self):
        goal = _corpus()[3]  # fan_1: context(2) -> {a,b,c}(3) -> integrate(3)
        result = run_graph(goal, clean_world())
        assert result.makespan == 8  # 2 + max(3,3,3) + 3, NOT the 14-tick chain
        chain = run_plan_execute(goal, clean_world())
        assert chain.makespan == 14  # strict sequential plan pays the sum

    def test_benchmark_is_repeatable_byte_for_byte(self):
        """The epic's repeatability metric: two full clean runs are
        indistinguishable row by row (deterministic environment)."""
        first = [r.row() for r in run_benchmark(_corpus(), clean_world())]
        second = [r.row() for r in run_benchmark(_corpus(), clean_world())]
        assert first == second

    def test_failpoint_arming_shape(self):
        transient = transient_fault_world()
        assert len(transient.failpoints) == 12
        assert set(transient.failpoints.values()) == {2}
        permanent = permanent_fault_world()
        assert set(permanent.failpoints.values()) == {99}
        assert transient.available("plan_task") is True  # transient != unavailability
        assert permanent.available("fix") is False


class TestD1StrategyBenchmark:
    """Leaf #925: ReAct vs plan-and-execute vs canonical Graph, same Goals."""

    def test_all_strategies_succeed_clean(self):
        summary = summarize(run_benchmark(_corpus(), clean_world()))
        assert set(summary) == {"react", "plan_execute", "graph"}
        for name, agg in summary.items():
            assert agg["success_rate"] == 1.0, name

    def test_react_pays_calls_and_tokens_on_every_goal(self):
        rows = run_benchmark(_corpus(), clean_world())
        by_goal: dict[str, dict[str, ExecutionResult]] = {}
        for row in rows:
            by_goal.setdefault(row.goal_id, {})[row.strategy] = row
        for goal_id, per in by_goal.items():
            assert len(per["react"].records) > len(per["plan_execute"].records), goal_id
            assert per["react"].unnecessary_calls >= 1, goal_id
            assert per["react"].tokens > per["plan_execute"].tokens, goal_id
            assert per["plan_execute"].tokens == per["graph"].tokens, goal_id
        summary = summarize(rows)
        assert summary["react"]["mean_unnecessary"] == pytest.approx(1.083, abs=0.01)
        assert summary["react"]["mean_tokens"] == pytest.approx(1816.67, abs=0.01)

    def test_inspectability_gradient_is_structural(self):
        """Declared-before-execution: graph declares the full DAG,
        plan-and-execute declares its initial linear plan, react declares
        nothing (its trace IS the plan, after the fact)."""
        rows = run_benchmark(_corpus(), clean_world())
        for row in rows:
            if row.strategy == "react":
                assert row.declared_nodes == 0
            elif row.strategy == "graph":
                assert row.declared_nodes == len(
                    next(s for s in _corpus() if s.goal_id == row.goal_id).steps
                )
            else:
                assert row.declared_nodes > 0

    def test_graph_wins_latency_exactly_where_parallelism_exists(self):
        world = clean_world()
        for goal in _corpus():
            graph = run_graph(goal, world)
            plan = run_plan_execute(goal, world)
            if goal.family == "fanout":
                assert graph.makespan < plan.makespan, goal.goal_id
            else:
                assert graph.makespan == plan.makespan, goal.goal_id

    def test_transient_fault_recovery_gradient(self):
        """f=2 with budget 3: the canonical attempt budget absorbs the fault;
        react's blind retry cannot; plan-and-execute recovers only by
        re-planning. No strategy gains success by planning harder here."""
        world = transient_fault_world()
        rows = run_benchmark(_corpus(), world)
        by_strategy: dict[str, list[ExecutionResult]] = {}
        for row in rows:
            by_strategy.setdefault(row.strategy, []).append(row)
        assert sum(1 for r in by_strategy["react"] if r.success) == 0
        assert sum(1 for r in by_strategy["plan_execute"] if r.success) == 12
        assert sum(1 for r in by_strategy["graph"] if r.success) == 12
        assert all(r.replans == 0 for r in by_strategy["graph"])
        assert all(r.replans >= 1 for r in by_strategy["plan_execute"])

    def test_replanning_buys_nothing_for_transient_faults(self):
        """The mechanism finding: with f=2/budget=3, naive replanning and
        in-place attempts recover the same Goals at the same corpus cost —
        replanning's value appears for permanent surprises, not transients."""
        world = transient_fault_world()
        rows = run_benchmark(_corpus(), world)
        by_strategy: dict[str, list[ExecutionResult]] = {}
        for row in rows:
            by_strategy.setdefault(row.strategy, []).append(row)
        plan_calls = sum(len(r.records) for r in by_strategy["plan_execute"])
        graph_calls = sum(len(r.records) for r in by_strategy["graph"])
        plan_tokens = sum(r.tokens for r in by_strategy["plan_execute"])
        graph_tokens = sum(r.tokens for r in by_strategy["graph"])
        assert (plan_calls, plan_tokens) == (graph_calls, graph_tokens)

    def test_clean_latency_summary_pins(self):
        summary = summarize(run_benchmark(_corpus(), clean_world()))
        assert summary["graph"]["p50_ticks"] == 8.0
        assert summary["plan_execute"]["p50_ticks"] == 9.0
        assert summary["graph"]["p95_ticks"] == 10.0
        assert summary["react"]["p95_ticks"] == 14.0
        assert summary["graph"]["mean_calls"] == pytest.approx(4.083, abs=0.01)


class TestD2SynthesisValidation:
    """Leaf #926: synthesis -> validation -> repair; candidates, never runtime."""

    def test_clean_synthesis_is_legal_first_pass_everywhere(self):
        world = clean_world()
        for goal in _corpus():
            candidate, iterations, report = synthesis_with_repair(goal, world)
            assert report.is_valid, goal.goal_id
            assert iterations == 0, goal.goal_id
            reference = graph_candidate(goal, world)
            assert candidate.signatures == reference.signatures
            assert candidate.edges == reference.edges

    def test_each_injected_defect_yields_its_named_code(self):
        goal = _corpus()[0]
        world = clean_world()
        base = synthesize(goal, world)
        assert validate_candidate(base, world).is_valid
        expected = {
            "cycle": "cycle",
            "dangling_edge": "missing_node",
            "unknown_binding": "unknown_kind",
            "orphan": "no_entry",
            "two_entries": "no_entry",
        }
        for defect, code in expected.items():
            report = validate_candidate(defective(base, defect), world)
            codes = {f.code for f in report.findings}
            assert codes == {code}, (defect, codes)

    def test_dead_deps_do_not_cascade_into_unreachable(self):
        """The old validator semantics would report a node hung on a dead
        dependency as BOTH ``missing_node`` AND ``unreachable`` (the
        reachability walk cannot cross the unresolvable dep). Reachability is
        computed over RESOLVED edges, so the dead pointer is named once — by
        its binding code — and downstream structure is judged on its own
        merits. One defect, one finding: that is what makes the repair-round
        measurement interpretable."""
        goal = _corpus()[0]
        world = clean_world()
        base = synthesize(goal, world)
        assert validate_candidate(base, world).is_valid
        dangling = defective(base, "dangling_edge")
        assert {f.code for f in validate_candidate(dangling, world).findings} == {"missing_node"}

    def test_repair_converges_within_two_rounds_for_single_defects(self):
        goal = _corpus()[0]
        world = clean_world()
        base = synthesize(goal, world)
        for defect in ("cycle", "dangling_edge", "unknown_binding", "orphan", "two_entries"):
            fixed, iterations = repair_candidate(defective(base, defect), world)
            report = validate_candidate(fixed, world)
            assert report.is_valid, defect
            assert iterations <= 2, (defect, iterations)

    def test_repair_rounds_grow_with_defect_count(self):
        """Two defects needing different fix classes (a back-edge and an
        orphan node) take strictly more repair rounds than either alone."""
        goal = _corpus()[0]
        world = clean_world()
        base = synthesize(goal, world)
        cycle_only = defective(base, "cycle")
        orphan_only = defective(base, "orphan")
        both = defective(defective(base, "cycle"), "orphan")
        _, cycle_rounds = repair_candidate(cycle_only, world)
        _, orphan_rounds = repair_candidate(orphan_only, world)
        both_fixed, both_rounds = repair_candidate(both, world)
        assert validate_candidate(both_fixed, world).is_valid
        assert both_rounds > cycle_rounds
        assert both_rounds > orphan_rounds

    def test_accepted_candidates_execute_on_the_one_shared_executor(self):
        """No second runtime: synthesis output is a CANDIDATE that goes through
        the same execute_plan every D1 strategy uses (epic contract)."""
        world = clean_world()
        for goal in _corpus():
            candidate, _, report = synthesis_with_repair(goal, world)
            assert report.is_valid
            result = execute_plan(candidate, goal, world, strategy="synth", attempts_per_node=3)
            assert result.success, goal.goal_id
            assert result.strategy == "synth"

    def test_constraint_aware_binding_swaps_to_alternates(self):
        goal = _corpus()[8]  # rep_3 uses fix
        faulted = permanent_fault_world("fix")
        candidate, iterations, report = synthesis_with_repair(goal, faulted)
        assert report.is_valid and iterations == 0
        bindings = {n.capability for n in candidate.nodes}
        assert "patch" in bindings and "fix" not in bindings
        result = execute_plan(candidate, goal, faulted, strategy="synth", attempts_per_node=3)
        assert result.success

    def test_validator_catches_real_cycles_and_passes_chains(self):
        """Load-bearing validator: a genuinely cyclic candidate must be
        flagged, and the artifact-level Kahn walk must not flag legal chains
        (regression guard for the walk's key space)."""
        goal = _corpus()[0]
        world = clean_world()
        base = synthesize(goal, world)
        assert validate_candidate(base, world).is_valid
        cyclic = PlanCandidate(
            "c",
            (
                PlanNode("a", "context", "scout", ("spec",)),  # back edge
                PlanNode("b", "spec", "plan_task", ("context",)),
            ),
        )
        report = validate_candidate(cyclic, world)
        assert "cycle" in {f.code for f in report.findings}


class TestD3ReplanningPolicies:
    """Leaf #927: surprises -> none | local repair | full replan (fresh/reuse)."""

    def _run_all(self, world: ToolWorld) -> dict[str, list[ExecutionResult]]:
        out: dict[str, list[ExecutionResult]] = {}
        for name, driver in REPLAN_POLICIES.items():
            out[name] = [driver(g, world) for g in _corpus()]
        return out

    def test_recovery_gradient_under_permanent_fault(self):
        rows = self._run_all(permanent_fault_world("fix"))
        recovered = {name: sum(1 for r in rs if r.success) for name, rs in rows.items()}
        assert recovered == {
            "policy_none": 7,  # the 5 fix-using goals fail without a planner
            "policy_local": 12,
            "policy_replan_fresh": 12,
            "policy_replan_reuse": 12,
        }

    def test_duplication_and_cost_ordering(self):
        rows = self._run_all(permanent_fault_world("fix"))
        totals = {
            name: (
                sum(len(r.records) for r in rs),
                sum(r.tokens for r in rs),
                sum(r.unnecessary_calls for r in rs),
            )
            for name, rs in rows.items()
        }
        assert totals["policy_none"] == (54, 21300, 0)
        assert totals["policy_local"] == (64, 25650, 0)
        assert totals["policy_replan_reuse"] == (64, 25650, 0)
        assert totals["policy_replan_fresh"] == (74, 29150, 10)
        # local repair and reuse-replan tie on cost here; discard-replan pays
        # strictly more, and its duplicates are exactly the re-done work.
        assert totals["policy_replan_fresh"][0] > totals["policy_local"][0]

    def test_mechanism_counters_pin_the_policy_shape(self):
        rows = self._run_all(permanent_fault_world("fix"))
        assert sum(r.swaps for r in rows["policy_local"]) == 5
        assert sum(r.replans for r in rows["policy_local"]) == 0
        assert sum(r.swaps for r in rows["policy_replan_fresh"]) == 0
        assert sum(r.replans for r in rows["policy_replan_fresh"]) == 5
        assert sum(r.replans for r in rows["policy_none"]) == 0

    def test_provenance_local_keeps_identity_fresh_rebinds_it(self):
        """Provenance correctness of preserved work: local repair keeps the
        original producing node identity for completed steps; discard-replan
        re-records every artifact under the new candidate's identity."""
        world = permanent_fault_world("fix")
        goal = _corpus()[6]  # rep_1
        local = run_policy_local_repair(goal, world)
        fresh = run_policy_full_replan_fresh(goal, world)
        assert local.success and fresh.success
        assert all(nid.startswith(f"{goal.goal_id}:") for nid in local.artifacts.values())
        assert all(":s:" in nid for nid in fresh.artifacts.values())

    def test_oscillation_is_bounded_when_both_bindings_are_dead(self):
        """Both fix and patch permanently faulted: every policy terminates
        with bounded swaps/replans — no repair livelock."""
        goal = _corpus()[6]
        world = stuck_pair_world(goal, artifact="fix")
        for name, driver in REPLAN_POLICIES.items():
            result = driver(goal, world)
            assert result.success is False, name
            assert result.swaps <= 4, name
            assert result.replans <= 2, name
            assert len(result.records) <= 24, name  # hand bound, not a hang

    def test_policies_are_inert_without_surprises(self):
        clean = clean_world()
        baseline = [run_policy_none(g, clean) for g in _corpus()]
        for name, driver in REPLAN_POLICIES.items():
            if name == "policy_none":
                continue
            for goal, base_row in zip(_corpus(), baseline, strict=True):
                row = driver(goal, clean)
                assert row.success and base_row.success
                assert (len(row.records), row.tokens) == (len(base_row.records), base_row.tokens), (
                    name,
                    goal.goal_id,
                )
                assert row.swaps == 0 and row.replans == 0


class TestD4BoundedSearch:
    """Leaf #928: bounded candidate search pays only when the world invalidates
    the default plan AND the verifier can see it."""

    DIFFICULT = tuple(g for g in _corpus() if g.difficulty >= 2)

    def test_search_is_useless_in_a_clean_world(self):
        world = clean_world()
        for goal in self.DIFFICULT:
            winner, planning_calls = plan_search(goal, world)
            assert planning_calls == 4
            assert winner.strategy == "search_v0_minimal"  # ties resolve earliest
            result = execute_plan(winner, goal, world, strategy="beam", attempts_per_node=3)
            one_shot = execute_plan(
                candidate_variants(goal, world)[0],
                goal,
                world,
                strategy="one_shot",
                attempts_per_node=3,
            )
            assert result.success and one_shot.success
            assert result.tokens == one_shot.tokens  # identical run, 4 calls spent

    def test_beam_uplift_under_permanent_fault(self):
        world = permanent_fault_world("fix")
        beam_wins = 0
        one_shot_wins = 0
        planning_calls = 0
        for goal in self.DIFFICULT:
            winner, spent = plan_search(goal, world)
            planning_calls += spent
            beam_wins += execute_plan(
                winner, goal, world, strategy="beam", attempts_per_node=3
            ).success
            one_shot_wins += execute_plan(
                candidate_variants(goal, world)[0],
                goal,
                world,
                strategy="one_shot",
                attempts_per_node=3,
            ).success
        assert (beam_wins, one_shot_wins, planning_calls) == (10, 5, 40)

    def test_verifier_error_closes_the_uplift_exactly(self):
        world = permanent_fault_world("fix")
        wins = 0
        for goal in self.DIFFICULT:
            winner, _ = plan_search(goal, world, verifier_misses=frozenset({2}))
            wins += execute_plan(winner, goal, world, strategy="beam", attempts_per_node=3).success
        assert wins == 5  # back to the one-shot baseline: ranker error is fatal

    def test_candidates_are_pairwise_structurally_distinct(self):
        """Search diversity, measured honestly. v1_dag is a documented CONTROL
        that collapses onto v0's structure (same bindings, same dataflow edges
        — only the emitter's node-id namespace differs), so the K=4 budget
        really explores THREE distinct plans. That collapse is itself the
        leaf's diversity finding: a naive candidate generator spends a quarter
        of its planning budget on a duplicate. Every non-control pair differs,
        so the beam still chooses among genuinely different shapes."""
        world = permanent_fault_world("fix")
        for goal in self.DIFFICULT:
            variants = candidate_variants(goal, world)
            assert len(variants) == 4
            assert edit_distance(variants[0], variants[1]) == 0, goal.goal_id  # the control
            for i in range(len(variants)):
                for j in range(i + 1, len(variants)):
                    if (i, j) == (0, 1):
                        continue
                    assert edit_distance(variants[i], variants[j]) >= 1, (goal.goal_id, i, j)
            shapes = {(v.signatures, v.edges) for v in variants}
            assert len(shapes) == 3, goal.goal_id

    def test_underprovisioned_candidate_never_wins(self):
        world = clean_world()
        for goal in self.DIFFICULT:
            variants = candidate_variants(goal, world)
            scores = [rubric_coverage(v, goal, world) for v in variants]
            assert scores[3] < 1.0  # v3 drops a required step
            assert scores[3] < scores[0]
            winner, _ = plan_search(goal, world)
            assert winner.strategy != "search_v3_under"

    def test_robust_variant_wins_exactly_where_the_fault_bites(self):
        world = permanent_fault_world("fix")
        for goal in self.DIFFICULT:
            winner, _ = plan_search(goal, world)
            uses_fix = any(ARTIFACT_CAPABILITY[s.artifact] == "fix" for s in goal.steps)
            if uses_fix:
                assert winner.strategy == "search_v2_robust", goal.goal_id
            else:
                assert winner.strategy == "search_v0_minimal", goal.goal_id


class TestD5MotifReuse:
    """Leaf #929: mining successful runs into motifs; reuse vs from-scratch."""

    TRAIN = tuple(g for g in _corpus() if g.goal_id not in {"rep_3", "exp_3"})

    def test_mining_yields_one_valid_motif_per_family(self):
        motifs = mine_motifs(self.TRAIN, clean_world())
        assert set(motifs) == {"pipeline", "fanout", "repair", "explore"}
        world = clean_world()
        for family, motif in motifs.items():
            goal = next(g for g in self.TRAIN if g.family == family)
            assert validate_candidate(motif, world).is_valid
            reference = synthesize(goal, world)
            assert motif.signatures == reference.signatures
            assert motif.edges == reference.edges

    def test_matched_family_reuse_is_structure_preserving(self):
        motifs = mine_motifs(self.TRAIN, clean_world())
        world = clean_world()
        for goal in (_corpus()[8], _corpus()[11]):  # rep_3, exp_3
            reused = adapt_motif(motifs[goal.family], goal, world)
            scratch = synthesize(goal, world)
            assert edit_distance(reused, scratch) == 0, goal.goal_id
            assert validate_candidate(reused, world).is_valid
            run_reused = execute_plan(
                reused, goal, world, strategy="motif_reuse", attempts_per_node=3
            )
            run_scratch = execute_plan(
                scratch, goal, world, strategy="scratch", attempts_per_node=3
            )
            assert run_reused.success and run_scratch.success
            assert (run_reused.tokens, run_reused.makespan) == (
                run_scratch.tokens,
                run_scratch.makespan,
            )

    def test_cross_family_transfer_loses_parallel_structure(self):
        motifs = mine_motifs(self.TRAIN, clean_world())
        world = clean_world()
        goal = _corpus()[3]  # fan_1
        adapted = adapt_motif(motifs["pipeline"], goal, world)
        scratch = synthesize(goal, world)
        assert edit_distance(adapted, scratch) == 6
        run_adapted = execute_plan(
            adapted, goal, world, strategy="motif_reuse", attempts_per_node=3
        )
        run_scratch = execute_plan(scratch, goal, world, strategy="scratch", attempts_per_node=3)
        assert run_adapted.makespan == 14  # the chain the motif imposed
        assert run_scratch.makespan == 8  # the goal's own fan-out
        assert run_adapted.success and run_scratch.success

    def test_stale_motif_is_caught_then_repaired_to_an_alternate_binding(self):
        """A motif referencing a retired capability is ILLEGAL; validation
        flags it, and both repair paths converge: the repair loop rebinds the
        dead node to the surviving alternate, while constraint-aware synthesis
        binds it on the first pass (0 repair rounds). Both execute."""
        retired = {k: v for k, v in _capabilities().items() if k != "diagnose"}
        world = ToolWorld(capabilities=retired, failpoints={})
        motifs = mine_motifs(self.TRAIN, clean_world())  # mined in the FULL world
        goal = _corpus()[6]  # rep_1: context -> diagnosis -> fix -> verified
        stale = adapt_motif(motifs["repair"], goal, world)
        findings = validate_candidate(stale, world)
        assert {f.code for f in findings.findings} == {"unknown_kind"}
        assert execute_plan(stale, goal, world, strategy="x", attempts_per_node=3).success is False
        repaired, _rounds = repair_candidate(stale, world)
        report = validate_candidate(repaired, world)
        assert report.is_valid
        assert "bisect" in {n.capability for n in repaired.nodes}
        assert execute_plan(repaired, goal, world, strategy="x", attempts_per_node=3).success
        constrained, iterations, constraint_report = synthesis_with_repair(goal, world)
        assert constraint_report.is_valid and iterations == 0
        assert "bisect" in {n.capability for n in constrained.nodes}
        assert execute_plan(constrained, goal, world, strategy="synth", attempts_per_node=3).success

    def test_module_has_no_maistro_imports(self):
        """Guardrail 2 enforced mechanically: this research module imports
        nothing from maistro, so it cannot reach a canonical authority."""
        module = sys.modules[__name__]
        with open(module.__file__, encoding="utf-8") as handle:
            source = handle.read()
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("import ", "from ")):
                assert not stripped.startswith(("import maistro", "from maistro")), stripped
