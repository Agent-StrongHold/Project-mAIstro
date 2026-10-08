#!/usr/bin/env python3
"""Offline Graph-pattern induction/reuse research bench (issue #929, RESEARCH M8-D5).

Answers, with numbers instead of guesses, whether successful Runs can be mined
into reusable Graph motifs that make future planning cheaper and more reliable
than planning from scratch — without overfitting to one task instance or
silently serving stale patterns after the world drifts. Everything is
deterministic and offline. The canonical seams are real, not re-implemented:

* successful Runs are mined through the real execution spine — `Run` over a
  real `GraphSnapshot` (`GraphSnapshot.from_graph` / `Run.graph.materialize()`)
  with `NodeRun`/`Attempt`/`AttemptResult`/`AcceptedNodeOutcome` records,
  constructed exactly as `maistro.runs.model` validates them;
* induced motifs are registered as real `GraphTemplate` objects in the real
  `InMemoryGraphTemplateStore`, flipped to ``lifecycle="candidate"`` — versioned
  canonical Graph *candidates* that no execution path resolves (ADR-082926-65bf):
  ``require_template`` refuses them and unversioned ``store.get`` ignores them;
* every reused Graph is produced by the real ``GraphTemplate.instantiate``
  (fresh node identities, `TemplateProvenance` carried onto the Graph).

No network, no PostgreSQL, no product code changes: this bench exists to
produce the GRADUATE/INCUBATE/REJECT/WATCH disposition, not to ship an
induction pipeline.

What it addresses from the issue, mechanically:

* clustering by task structure — every successful Run's snapshot is reduced to
  a kind-level structural signature (sorted kinds + sorted kind-level edges),
  the isomorphism class of the topology; Runs cluster by that signature;
* anti-overfitting — a signature is inducted only with >= ``--min-support``
  successes across >= ``--min-instances`` *distinct goal instances*; a
  structure that helped one task instance alone is an overfit trap and is
  refused;
* reuse vs from-scratch — a held-out goal stream is planned by three arms on
  common random numbers: a from-scratch budgeted search planner, naive reuse
  (always reuse the best-retrieved motif), and guarded reuse (identical plus a
  per-motif trailing-success quarantine fed by the same Run-completion
  feedback production already records). Reuse falls back to scratch whenever
  retrieval or validation fails; fallback successes feed the flywheel
  (--reindex-every re-mines every successful Run so far);
* planning latency/tokens — a documented token-equivalent cost model (the
  shipped planning seam is `LLMDagSynthesizer`: one synthesis round-trip per
  candidate, prompt fixed, completion roughly linear in graph size). Scratch
  pays per candidate explored; reuse pays retrieval + per-edit adaptation;
* edit distance — adaptation edits against the reused motif, plus the
  kind-level distance between the reused Graph and the from-scratch Graph for
  the same goal;
* transfer across task families — reuse hits whose motif never observed the
  goal's family, and those hits' success rate;
* stale-pattern failures — at ``--drift-at`` one family's latent success
  quietly tightens (unvalidated structures take a large penalty) while the
  stated goals do not change; pre-drift motifs for that family go stale. The
  two recovery mechanisms are measured separately: fast quarantine (guard)
  and slow re-mining (post-drift successes re-induct corrective motifs).

Usage:
    uv run python scripts/bench_graph_pattern_reuse.py [--corpus-runs 600]
        [--episodes 400] [--seeds 5] [--drift-at 200] [--output results.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "packages" / "maistro-core" / "src"))

from maistro.graph.definitions import Edge, Graph, GraphTemplate, Node
from maistro.graph.templates import (
    GraphTemplateNotFound,
    InMemoryGraphTemplateStore,
    require_template,
)
from maistro.graph.types import AgentRole
from maistro.runs.model import (
    AcceptedNodeOutcome,
    Attempt,
    AttemptResult,
    AttemptStatus,
    GraphSnapshot,
    NodeRun,
    Run,
    RunStatus,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable, Sequence

# ─── World definition ────────────────────────────────────────────────────────
#
# The node vocabulary is the shipped one (`AgentRole`, plus the pipeline kinds
# the shipped `DagSynthesizer` prompts for). A "structure" is the kind-level
# shape of a Graph: which kinds it contains and which kinds its edges connect.
# Instance identity (node ids, parameters) deliberately does not enter
# structures — that is what makes a motif a *pattern* rather than a replay.

KINDS: tuple[str, ...] = (
    AgentRole.SCOUT,
    AgentRole.CODER,
    AgentRole.REVIEWER,
    AgentRole.PLANNER,
    "llm.summarize",
    "transform.extract_field",
)

#: The planning cost model, in token-equivalent units. These are declared
#: parameters of the offline world, calibrated to the real cost drivers of the
#: shipped planning seam (`LLMDagSynthesizer.synthesize`: one LLM round-trip
#: whose prompt is the fixed `_SYNTH_SYSTEM_PROMPT` plus the objective, with
#: completion roughly linear in graph size; a search-based planner adds one
#: scoring call per candidate). They are echoed in every output payload so the
#: numbers cannot be mistaken for measurements of a live model.
SCRATCH_PROMPT_TOKENS = 850
SCRATCH_TOKENS_PER_NODE = 45
SCRATCH_TOKENS_PER_CANDIDATE = 60
RETRIEVE_TOKENS = 120
ADAPT_TOKENS_PER_EDIT = 90
#: Adaptation round-trips batch ~3 edits each (the latency proxy).
ADAPT_EDITS_PER_ROUNDTRIP = 3


@dataclass(frozen=True)
class GoalSpec:
    """What a caller states a Goal needs. The planners see only this."""

    family: str
    required: frozenset[str]
    orderings: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class Instance:
    """One task instance: a family goal plus its per-instance spec jitter."""

    instance_id: int
    spec: GoalSpec


@dataclass(frozen=True)
class Family:
    """A task family: its stated goal shape, structural variants, draw weights."""

    name: str
    base: GoalSpec
    #: Structures the corpus generator draws from (kind tuples). Deliberately
    #: heterogeneous — the pre-drift world mildly prefers lean structures, so
    #: the corpus carries validated and lean variants side by side.
    variants: tuple[tuple[str, ...], ...]
    weights: tuple[float, ...]
    #: Instance jitter: instance_id % len(jitter) selects which required kind
    #: (if any) the instance relaxes away. Empty for the drift family so its
    #: stale-pattern dynamics stay clean.
    jitter: tuple[str, ...] = ()


def _spec(
    family: str,
    required: tuple[str, ...],
    orderings: tuple[tuple[str, str], ...],
    drop: str | None = None,
) -> GoalSpec:
    kept = frozenset(required) - ({drop} if drop else set())
    return GoalSpec(
        family=family,
        required=kept,
        orderings=tuple(o for o in orderings if o[0] in kept and o[1] in kept),
    )


#: Four families with distinct stated goals. Only the drift family
#: (`data-extract`) states a goal that does NOT mention the reviewer — which
#: is what lets the latent validation tightening bite spec-satisfying
#: structures there without touching the stated requirements.
FAMILIES: tuple[Family, ...] = (
    Family(
        name="research-report",
        base=_spec(
            "research-report",
            ("scout", "llm.summarize", "reviewer"),
            ((AgentRole.SCOUT, "llm.summarize"), ("llm.summarize", AgentRole.REVIEWER)),
        ),
        variants=(
            ("scout", "llm.summarize", "reviewer"),
            ("scout", "planner", "llm.summarize", "reviewer"),
            ("scout", "llm.summarize"),
        ),
        weights=(0.55, 0.25, 0.20),
        jitter=("llm.summarize",),
    ),
    Family(
        name="code-change",
        base=_spec(
            "code-change",
            ("scout", "coder", "reviewer"),
            ((AgentRole.SCOUT, AgentRole.CODER), (AgentRole.CODER, AgentRole.REVIEWER)),
        ),
        variants=(
            ("scout", "coder", "reviewer"),
            ("scout", "planner", "coder", "reviewer"),
            ("scout", "coder"),
        ),
        weights=(0.55, 0.25, 0.20),
        jitter=("reviewer",),
    ),
    Family(
        name="data-extract",
        base=_spec("data-extract", ("transform.extract_field",), ()),
        variants=(
            ("transform.extract_field",),
            ("transform.extract_field", AgentRole.REVIEWER),
            ("scout", "transform.extract_field"),
        ),
        weights=(0.55, 0.30, 0.15),
    ),
    Family(
        name="triage",
        base=_spec("triage", ("scout", "reviewer"), ((AgentRole.SCOUT, AgentRole.REVIEWER),)),
        variants=(
            ("scout", "reviewer"),
            ("scout", "planner", "reviewer"),
            ("scout",),
        ),
        weights=(0.55, 0.25, 0.20),
        jitter=("reviewer",),
    ),
)

FAMILY_BY_NAME = {family.name: family for family in FAMILIES}

#: The drift: for one family, downstream validation quietly becomes mandatory
#: (a large latent penalty for unvalidated structures). The stated goal specs
#: do NOT change — a planner only feels this through outcomes.
DRIFT_FAMILY = "data-extract"
VALIDATED_BONUS = 0.05
DRIFT_VALIDATION_PENALTY = -0.38

BASE_SUCCESS = 0.30
COVERAGE_BONUS = 0.18
ORDERING_BONUS = 0.22
EXTRA_NODE_PENALTY = 0.07
PROB_FLOOR, PROB_CEIL = 0.02, 0.97

WORKSPACE = "ws-bench"
PROJECT = "pj-bench"
MOTIF_PROJECT = "pj-motifs"


# ─── Structures ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Structure:
    """The kind-level shape of a Graph: kinds + kind-level edges."""

    kinds: frozenset[str]
    edges: tuple[tuple[str, str], ...]

    @property
    def signature(self) -> str:
        """Canonical signature: the isomorphism class at kind level.

        Two Graphs built for two instances of one task family share a
        signature exactly when their topologies coincide once node identities
        are abstracted away. This is the clustering key that makes a motif a
        pattern rather than a replay of one Run.
        """
        kinds = ",".join(sorted(self.kinds))
        edges = ";".join(f"{a}->{b}" for a, b in sorted(self.edges))
        return f"[{kinds}]({edges})"

    def validated(self) -> bool:
        """Every producer kind has the reviewer downstream of it."""
        if AgentRole.REVIEWER not in self.kinds:
            return False
        return all(
            self.reaches(kind, AgentRole.REVIEWER)
            for kind in self.kinds
            if kind != AgentRole.REVIEWER
        )

    def reaches(self, src: str, dst: str) -> bool:
        if src == dst:
            return True
        adjacency: dict[str, list[str]] = {}
        for a, b in self.edges:
            adjacency.setdefault(a, []).append(b)
        seen = {src}
        frontier = [src]
        while frontier:
            node = frontier.pop()
            for nxt in adjacency.get(node, ()):
                if nxt == dst:
                    return True
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return False

    def orderings_satisfiable(self, spec: GoalSpec) -> bool:
        """The structure's edges can be topologized to honor spec orderings.

        A missing ordering *edge* is fine if a path exists; a cycle over an
        ordering pair is not.
        """
        combined = set(self.edges) | set(spec.orderings)
        nodes = set(self.kinds) | {kind for pair in combined for kind in pair}
        indegree = dict.fromkeys(nodes, 0)
        adjacency: dict[str, list[str]] = {node: [] for node in nodes}
        for a, b in combined:
            if a == b:
                return False
            adjacency[a].append(b)
            indegree[b] += 1
        ready = [node for node in nodes if indegree[node] == 0]
        seen = 0
        while ready:
            node = ready.pop()
            seen += 1
            for nxt in adjacency[node]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        return seen == len(nodes)

    def satisfies(self, spec: GoalSpec) -> bool:
        """Coverage + stated orderings, the part of validity the spec states."""
        if not spec.required <= self.kinds:
            return False
        return self.orderings_satisfiable(spec)


def _kind_order(kind: str) -> tuple[int, str]:
    """Canonical chain order for kinds not pinned by a stated ordering.

    The reviewer sorts last: validation runs after production. Without this,
    an alphabetical chain would put `reviewer` before `transform.extract_field`
    and no enumerated candidate could ever be a validated structure.
    """
    return (kind == AgentRole.REVIEWER, KINDS.index(kind) if kind in KINDS else len(KINDS), kind)


def chain_structure(kinds: Iterable[str], spec: GoalSpec) -> Structure:
    """Deterministic structure for a kind set: orderings first, then the rest.

    Edges honor every stated ordering pair (sharing endpoints where pairs
    chain); remaining kinds are appended in canonical order (reviewer last).
    The result is one chain, which keeps the search space's edge-sets
    comparable.
    """
    remaining = sorted(set(kinds))
    if not remaining:
        return Structure(frozenset(), ())
    sequence: list[str] = []
    placed: set[str] = set()
    for src, dst in spec.orderings:
        for kind in (src, dst):
            if kind in remaining and kind not in placed:
                sequence.append(kind)
                placed.add(kind)
    for kind in sorted(set(remaining) - placed, key=_kind_order):
        # Non-reviewer kinds insert before the first reviewer so validation
        # stays downstream of production; with no reviewer present they
        # append in canonical order (a reviewer itself lands last).
        insert_at = (
            sequence.index(AgentRole.REVIEWER)
            if (kind != AgentRole.REVIEWER and AgentRole.REVIEWER in sequence)
            else len(sequence)
        )
        sequence.insert(insert_at, kind)
        placed.add(kind)
    edges = tuple((sequence[i], sequence[i + 1]) for i in range(len(sequence) - 1))
    return Structure(frozenset(sequence), edges)


# ─── World truth ─────────────────────────────────────────────────────────────


def true_success_prob(structure: Structure, spec: GoalSpec, *, drifted: bool = False) -> float:
    """Latent success probability of a structure for a goal in this world.

    No planner sees this function — the world is felt only through simulated
    outcomes (and, in production terms, through Run records).
    """
    p = BASE_SUCCESS
    if spec.required:
        covered = len(structure.kinds & spec.required)
        p += COVERAGE_BONUS * covered / len(spec.required)
    if structure.satisfies(spec):
        p += ORDERING_BONUS
    if structure.validated():
        p += VALIDATED_BONUS
    elif drifted and spec.family == DRIFT_FAMILY:
        p += DRIFT_VALIDATION_PENALTY
    p -= EXTRA_NODE_PENALTY * max(0, len(structure.kinds) - len(spec.required))
    return min(PROB_CEIL, max(PROB_FLOOR, p))


# ─── The canonical seam: Runs over real execution-spine records ─────────────


def build_graph(structure: Structure, *, workspace_id: str, project_id: str) -> Graph:
    """Materialize a structure as a real canonical Graph."""
    node_ids = {kind: f"node-{kind}-{i}" for i, kind in enumerate(sorted(structure.kinds))}
    nodes = [
        Node(node_id=node_ids[kind], node_type=kind, name=kind, parameters={"position": i})
        for i, kind in enumerate(sorted(structure.kinds))
    ]
    edges = [
        Edge(edge_id=f"edge-{i}", from_node=node_ids[a], to_node=node_ids[b])
        for i, (a, b) in enumerate(sorted(structure.edges))
    ]
    return Graph(
        workspace_id=workspace_id,
        project_id=project_id,
        name="bench-graph",
        nodes=nodes,
        edges=edges,
    )


#: Fixed record timestamps. They never enter any metric — outcomes, costs and
#: counts are all draw-derived — so pinning them keeps the whole bench
#: reproducible instead of only its numbers.
_TS = datetime(2026, 1, 1, tzinfo=UTC)


def record_run(
    structure: Structure,
    *,
    success: bool,
    actor_principal_id: str,
    provenance: dict[str, Any],
) -> tuple[Run, list[NodeRun]]:
    """Record one Run over the canonical spine, exactly as the models demand.

    A successful Run completes every NodeRun through a terminal physical
    Attempt projected via AcceptedNodeOutcome; a failed Run fails exactly one
    NodeRun (no accepted outcome) and carries the Run-level error. NodeRuns
    are returned beside the Run because the canonical model keeps them as
    separate records — nothing execution-shaped is embedded in the Run.
    """
    run_id = uuid.uuid4().hex
    graph = build_graph(structure, workspace_id=WORKSPACE, project_id=PROJECT)
    snapshot = GraphSnapshot.from_graph(graph)
    if success:
        failed_node_id = None
    else:
        # The first producer in the chain is where the simulation failed.
        producer_kinds = sorted(structure.kinds - {AgentRole.REVIEWER})
        failed_node_id = (
            f"node-{producer_kinds[0]}-{sorted(structure.kinds).index(producer_kinds[0])}"
        )

    node_runs: list[NodeRun] = []
    for ordinal, node in enumerate(sorted(graph.nodes, key=lambda n: n.node_id), start=1):
        if failed_node_id is not None and node.node_id == failed_node_id:
            node_runs.append(
                NodeRun(
                    run_id=run_id,
                    node_id=node.node_id,
                    ordinal=ordinal,
                    status=RunStatus.FAILED,
                    finished_at=_TS,
                    error="simulated execution failure",
                )
            )
            continue
        node_run_id = uuid.uuid4().hex
        completed_attempt = Attempt(
            node_run_id=node_run_id,
            ordinal=1,
            status=AttemptStatus.COMPLETED,
            finished_at=_TS,
            result={"ok": True},
        )
        node_runs.append(
            NodeRun(
                node_run_id=node_run_id,
                run_id=run_id,
                node_id=node.node_id,
                ordinal=ordinal,
                status=RunStatus.COMPLETED,
                finished_at=_TS,
                accepted_outcome=AcceptedNodeOutcome(
                    node_run_id=node_run_id,
                    attempt_result=AttemptResult.from_attempt(completed_attempt),
                ),
                result={"ok": True},
            )
        )

    run = Run(
        run_id=run_id,
        workspace_id=WORKSPACE,
        project_id=PROJECT,
        graph=snapshot,
        status=RunStatus.COMPLETED if success else RunStatus.FAILED,
        actor_principal_id=actor_principal_id,
        finished_at=_TS,
        provenance=provenance,
        **({} if success else {"error": "simulated execution failure"}),
    )
    return run, node_runs


def run_episode(
    structure: Structure,
    spec: GoalSpec,
    instance_id: int,
    rng: random.Random,
    *,
    drifted: bool,
    record: bool,
) -> tuple[bool, Run | None]:
    """Execute one goal instance against the world's latent truth."""
    success = rng.random() < true_success_prob(structure, spec, drifted=drifted)
    if not record:
        return success, None
    run, _node_runs = record_run(
        structure,
        success=success,
        actor_principal_id="principal-bench",
        provenance={
            "goal_family": spec.family,
            "goal_instance": instance_id,
            "goal_signature": structure.signature,
        },
    )
    return success, run


# ─── Mining / induction ──────────────────────────────────────────────────────

#: Metadata key carrying the source evidence of an induced template. Deliberately
#: NOT `run_id`/`node_run_id`/`attempt_id`: those are execution identity
#: (RUNTIME_STATE_FIELDS, SPEC-081226-bb3a R12) and a template carrying them is
#: refused at construction. Mined templates cite evidence by aggregate, never
#: by execution identity.
SOURCES_KEY = "induction_sources"


@dataclass
class Motif:
    """One induced pattern: a structure plus its mined evidence."""

    structure: Structure
    support: int
    instances: set[int]
    families: set[str]
    inducted_pre_drift: bool = True

    @property
    def signature(self) -> str:
        return self.structure.signature


def structure_of(graph: Graph) -> Structure:
    """Reduce a materialized Graph to its kind-level structure."""
    id_to_kind = {node.node_id: node.node_type for node in graph.nodes}
    edges = tuple(sorted((id_to_kind[e.from_node], id_to_kind[e.to_node]) for e in graph.edges))
    return Structure(frozenset(id_to_kind.values()), edges)


def mine_motifs(
    runs: Sequence[Run],
    *,
    min_support: int,
    min_instances: int,
) -> dict[str, Motif]:
    """Cluster successful Runs by structure signature and induct motifs.

    Only successful Runs contribute (`Run.status == COMPLETED`). A signature
    needs `min_support` successes across `min_instances` DISTINCT goal
    instances — that second bar is the anti-overfitting guard: a structure
    that helped exactly one task instance says nothing about the next one.
    """
    clusters: dict[str, dict[str, Any]] = {}
    for run in runs:
        if run.status is not RunStatus.COMPLETED:
            continue
        structure = structure_of(run.graph.materialize())
        cluster = clusters.setdefault(
            structure.signature,
            {"structure": structure, "support": 0, "instances": set(), "families": set()},
        )
        cluster["support"] += 1
        cluster["instances"].add(int(run.provenance["goal_instance"]))
        cluster["families"].add(str(run.provenance["goal_family"]))
    motifs: dict[str, Motif] = {}
    for signature, cluster in clusters.items():
        if cluster["support"] < min_support or len(cluster["instances"]) < min_instances:
            continue
        motifs[signature] = Motif(
            structure=cluster["structure"],
            support=cluster["support"],
            instances=cluster["instances"],
            families=cluster["families"],
        )
    return motifs


async def induce_templates(
    motifs: dict[str, Motif],
    store: InMemoryGraphTemplateStore,
    *,
    workspace_id: str,
) -> list[GraphTemplate]:
    """Register each motif as a versioned canonical Graph candidate.

    `GraphTemplate.from_graph` snapshots the mined structure; the lifecycle is
    then flipped to ``candidate`` so the template is addressable by exact
    version for inspection but resolvable by NO execution path
    (ADR-082926-65bf) until a human-audited promotion. Reused Graphs therefore
    remain versioned canonical Graph candidates — the issue's deliverable
    constraint.
    """
    induced: list[GraphTemplate] = []
    for motif in motifs.values():
        graph = build_graph(motif.structure, workspace_id=workspace_id, project_id=MOTIF_PROJECT)
        # The template's human-readable record rides on the Graph's description
        # (from_graph snapshots it), so an inspector can audit what was mined
        # and from how much evidence without re-deriving the counts.
        graph = graph.model_copy(
            update={
                "description": (
                    f"Induced from successful Runs: support={motif.support}, "
                    f"distinct_instances={len(motif.instances)}, "
                    f"families={','.join(sorted(motif.families))}."
                )
            }
        )
        template = GraphTemplate.from_graph(graph, name=f"motif {motif.signature[:40]}")
        template = template.model_copy(
            update={
                "metadata": {
                    "induction": {
                        "support": motif.support,
                        "distinct_instances": sorted(motif.instances),
                        "families": sorted(motif.families),
                        "inducted_pre_drift": motif.inducted_pre_drift,
                    },
                    SOURCES_KEY: sorted(motif.families),
                }
            }
        )
        await store.put(template)
        await store.set_lifecycle(template.template_id, template.version, "candidate")
        induced.append(template)
    return induced


# ─── Planners ────────────────────────────────────────────────────────────────


@dataclass
class PlanResult:
    structure: Structure
    tokens: int
    roundtrips: int
    edits: int
    reused: bool
    motif: Motif | None
    fallback: bool


def _combinations(pool: list[str], k: int) -> list[tuple[str, ...]]:
    results: list[tuple[str, ...]] = []

    def walk(start: int, prefix: tuple[str, ...]) -> None:
        if len(prefix) == k:
            results.append(prefix)
            return
        for i in range(start, len(pool)):
            walk(i + 1, (*prefix, pool[i]))

    walk(0, ())
    return results


@dataclass
class ScratchPlanner:
    """Planning from scratch: budgeted enumeration scored by a heuristic.

    The heuristic is the planner's own model of the world — coverage, stated
    orderings, a validation preference, size parsimony — NOT
    `true_success_prob` (it cannot see latent drift). Each candidate costs one
    scoring round-trip. Deliberately stateless: nothing about past Goals
    influences a from-scratch plan.
    """

    budget: int = 60

    def plan(self, spec: GoalSpec) -> PlanResult:
        candidates = self._candidates(spec)
        explored = candidates[: self.budget]
        best = max(
            explored,
            key=lambda structure: (self._heuristic(structure, spec), structure.signature),
            default=chain_structure(spec.required, spec),
        )
        tokens = SCRATCH_PROMPT_TOKENS + SCRATCH_TOKENS_PER_CANDIDATE * len(explored)
        tokens += SCRATCH_TOKENS_PER_NODE * len(best.kinds)
        return PlanResult(
            structure=best,
            tokens=tokens,
            roundtrips=len(explored),
            edits=0,
            reused=False,
            motif=None,
            fallback=False,
        )

    def _heuristic(self, structure: Structure, spec: GoalSpec) -> float:
        covered = len(structure.kinds & spec.required) / max(1, len(spec.required))
        score = 0.9 * covered
        if structure.satisfies(spec):
            score += 0.5
        if structure.validated():
            score += 0.4
        score -= 0.15 * max(0, len(structure.kinds) - len(spec.required))
        return score

    def _candidates(self, spec: GoalSpec) -> list[Structure]:
        """Deterministic candidate enumeration over the kind vocabulary:
        supersets of the required kinds, smallest first, each as a chain."""
        required = set(spec.required)
        pool = [kind for kind in KINDS if kind not in required]
        out: list[Structure] = []
        for extra_count in range(0, 3):
            for extras in _combinations(pool, extra_count):
                out.append(chain_structure(required | set(extras), spec))
        return out


@dataclass
class ReusePlanner:
    """Retrieval + adaptation over the mined motif index, with scratch fallback.

    Retrieval ranks by kind overlap (Jaccard), then mined support, then size —
    the signals a production index would have without oracle knowledge of the
    goal's true structure. Adaptation edits only what the STATED spec demands
    (adds missing required kinds, re-chains per the stated orderings); it
    cannot see latent drift, which is exactly where stale patterns bite.
    """

    motifs: dict[str, Motif]
    scratch: ScratchPlanner
    retrieve_threshold: float = 0.5
    #: When set, retrieval skips any motif that observed the goal's own family
    #: — the forced-transfer probe: can a motif inducted on OTHER families
    #: still serve this goal after adaptation?
    exclude_own_family: bool = False
    #: signatures quarantined by the outcome guard (guarded mode only)
    quarantined: set[str] = field(default_factory=set)
    #: trailing outcomes per signature, for the guarded mode's quarantine
    trailing: dict[str, deque[bool]] = field(default_factory=dict)
    guard_window: int = 20
    guard_min: int = 8
    guard_threshold: float = 0.55

    def plan(self, spec: GoalSpec) -> PlanResult:
        motif = self._retrieve(spec)
        if motif is not None:
            adapted, edits = self._adapt(motif.structure, spec)
            if adapted is not None:
                return PlanResult(
                    structure=adapted,
                    tokens=RETRIEVE_TOKENS + ADAPT_TOKENS_PER_EDIT * edits,
                    roundtrips=1 + -(-edits // ADAPT_EDITS_PER_ROUNDTRIP),
                    edits=edits,
                    reused=True,
                    motif=motif,
                    fallback=False,
                )
        fallback = self.scratch.plan(spec)
        fallback.fallback = True
        return fallback

    def _retrieve(self, spec: GoalSpec) -> Motif | None:
        best: tuple[tuple[float, int, int], Motif] | None = None
        for motif in self.motifs.values():
            if motif.signature in self.quarantined:
                continue
            if self.exclude_own_family and spec.family in motif.families:
                continue
            overlap = len(motif.structure.kinds & spec.required)
            union = len(motif.structure.kinds | spec.required)
            similarity = overlap / union if union else 0.0
            if similarity < self.retrieve_threshold:
                continue
            key = (similarity, motif.support, -len(motif.structure.kinds))
            if best is None or key > best[0]:
                best = (key, motif)
        return best[1] if best else None

    def _adapt(self, structure: Structure, spec: GoalSpec) -> tuple[Structure | None, int]:
        """Adapt a motif to the stated spec; None when it cannot be made valid.

        Adaptation is deliberately narrow: it adds missing required kinds and
        re-chains to the stated orderings, and nothing else. It therefore
        cannot repair a *latent* requirement the spec does not name — the
        precise gap stale patterns exploit.
        """
        missing = sorted(spec.required - structure.kinds)
        kinds = set(structure.kinds) | set(missing)
        adapted = chain_structure(kinds, spec)
        if not adapted.satisfies(spec):
            return None, 0
        return adapted, len(missing)

    def observe(self, signature: str, success: bool) -> bool:
        """Feed one outcome back; returns True if the motif got quarantined.

        This is the guarded mode's only edge over naive reuse, and it uses the
        same evidence production already records: whether the Run completed.
        """
        window = self.trailing.setdefault(signature, deque(maxlen=self.guard_window))
        window.append(success)
        if (
            len(window) >= self.guard_min
            and sum(window) / len(window) < self.guard_threshold
            and signature not in self.quarantined
        ):
            self.quarantined.add(signature)
            return True
        return False


# ─── Experiment ──────────────────────────────────────────────────────────────


def _instance_spec(family: Family, instance: int) -> GoalSpec:
    drop = family.jitter[instance % len(family.jitter)] if family.jitter else None
    # Keep every instance satisfiable: never drop a kind an ordering needs.
    if drop and any(drop in pair for pair in family.base.orderings):
        drop = None
    return _spec(family.name, tuple(sorted(family.base.required)), family.base.orderings, drop=drop)


def generate_corpus(
    *,
    runs_count: int,
    seed: int,
    instance_base: int = 0,
) -> list[Run]:
    """Historical Runs across the four families, recorded on the real spine."""
    rng = random.Random(seed)
    runs: list[Run] = []
    for i in range(runs_count):
        family = FAMILIES[i % len(FAMILIES)]
        instance = instance_base + i // len(FAMILIES)
        spec = _instance_spec(family, instance)
        kinds = rng.choices(family.variants, weights=family.weights, k=1)[0]
        structure = chain_structure(kinds, spec)
        _success, run = run_episode(structure, spec, instance, rng, drifted=False, record=True)
        assert run is not None
        runs.append(run)
    return runs


def heldout_goals(*, episodes: int, instance_base: int, seed: int) -> list[Instance]:
    """The held-out goal stream: deterministic, disjoint instance ids."""
    rng = random.Random(seed + 10_000)
    goals: list[Instance] = []
    for i in range(episodes):
        family = FAMILIES[rng.randrange(len(FAMILIES))]
        goals.append(
            Instance(
                instance_id=instance_base + i,
                spec=_instance_spec(family, instance_base + i),
            )
        )
    return goals


@dataclass
class ArmStats:
    """Per-arm accumulators over the held-out stream."""

    planner: str
    episodes: int = 0
    successes: int = 0
    tokens: int = 0
    roundtrips: int = 0
    edits: list[int] = field(default_factory=list)
    #: kind-level |kinds △ scratch_kinds| per episode — the measured edit
    #: distance between what reuse produced and what from-scratch would build
    #: for the same goal (0 for the scratch arm by construction).
    divergence: list[int] = field(default_factory=list)
    reuse_hits: int = 0
    fallbacks: int = 0
    cross_family_hits: int = 0
    cross_family_successes: int = 0
    stale_failures: int = 0
    quarantines: int = 0

    def note(
        self,
        plan: PlanResult,
        *,
        success: bool,
        cross_family: bool,
        stale: bool,
        divergence: int = 0,
    ) -> None:
        self.episodes += 1
        self.successes += int(success)
        self.tokens += plan.tokens
        self.roundtrips += plan.roundtrips
        self.edits.append(plan.edits)
        self.divergence.append(divergence)
        if plan.reused:
            self.reuse_hits += 1
        if plan.fallback:
            self.fallbacks += 1
        if cross_family:
            self.cross_family_hits += 1
            self.cross_family_successes += int(success)
        if stale:
            self.stale_failures += 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "planner": self.planner,
            "episodes": self.episodes,
            "success_rate": round(self.success_rate, 4),
            "mean_tokens": round(self.mean_tokens, 1),
            "mean_roundtrips": round(self.mean_roundtrips, 2),
            "mean_adaptation_edits": round(self.mean_edits, 3),
            "mean_structure_divergence_vs_scratch": round(self.mean_divergence, 3),
            "reuse_hits": self.reuse_hits,
            "scratch_fallbacks": self.fallbacks,
            "cross_family_hits": self.cross_family_hits,
            "cross_family_success_rate": round(
                self.cross_family_successes / self.cross_family_hits, 4
            )
            if self.cross_family_hits
            else None,
            "stale_attributable_failures": self.stale_failures,
            "guard_quarantines": self.quarantines,
        }

    @property
    def success_rate(self) -> float:
        return self.successes / self.episodes if self.episodes else 0.0

    @property
    def mean_tokens(self) -> float:
        return self.tokens / self.episodes if self.episodes else 0.0

    @property
    def mean_roundtrips(self) -> float:
        return self.roundtrips / self.episodes if self.episodes else 0.0

    @property
    def mean_edits(self) -> float:
        return sum(self.edits) / len(self.edits) if self.edits else 0.0

    @property
    def mean_divergence(self) -> float:
        return sum(self.divergence) / len(self.divergence) if self.divergence else 0.0


def _reindex(
    all_runs: list[Run],
    indices: dict[str, dict[str, Motif]],
    stores: dict[str, InMemoryGraphTemplateStore],
    planners: dict[str, ReusePlanner],
    *,
    episode_index: int,
    drift_at: int,
    min_support: int,
    min_instances: int,
) -> None:
    """The flywheel: re-mine every successful Run so far into the index.

    New signatures carry ``inducted_pre_drift=False`` after the drift point, so
    stale attribution can tell pre-drift patterns from corrective ones. Both
    reuse arms share one evidence pool; the guard is what differentiates them.
    """
    fresh = mine_motifs(all_runs, min_support=min_support, min_instances=min_instances)
    for name, store in stores.items():
        for motif in fresh.values():
            if motif.signature not in indices[name]:
                motif.inducted_pre_drift = episode_index < drift_at
                indices[name][motif.signature] = motif
        asyncio.run(induce_templates(indices[name], store, workspace_id=WORKSPACE))
        planners[name].motifs = indices[name]


def run_seed(
    seed: int,
    *,
    corpus_runs: int,
    episodes: int,
    drift_at: int,
    reindex_every: int,
    min_support: int,
    min_instances: int,
    budget: int,
) -> dict[str, Any]:
    """One seed: corpus → induction → held-out stream (naive / guarded / scratch).

    Common random numbers: all three arms execute the same goal instance with
    the same execution draw, so an identical structure yields an identical
    outcome and "reuse failed where scratch would have succeeded" is a crisp
    attribution, not noise.
    """
    scratch = ScratchPlanner(budget=budget)
    planners: dict[str, ReusePlanner] = {}
    stores: dict[str, InMemoryGraphTemplateStore] = {}
    indices: dict[str, dict[str, Motif]] = {}
    initial = mine_motifs(
        generate_corpus(runs_count=corpus_runs, seed=seed),
        min_support=min_support,
        min_instances=min_instances,
    )
    for name in ("reuse-naive", "reuse-guarded"):
        store = InMemoryGraphTemplateStore()
        asyncio.run(induce_templates(initial, store, workspace_id=WORKSPACE))
        stores[name] = store
        indices[name] = dict(initial)
        planners[name] = ReusePlanner(motifs=indices[name], scratch=scratch)
    # The forced-transfer probe: same index, but retrieval may only serve a
    # goal from motifs that never observed its family. Shares the naive
    # index object, so re-indexing updates it in place.
    planners["reuse-transfer"] = ReusePlanner(
        motifs=indices["reuse-naive"], scratch=scratch, exclude_own_family=True
    )

    arms = {
        "scratch": ArmStats("scratch"),
        "reuse-naive": ArmStats("reuse-naive"),
        "reuse-guarded": ArmStats("reuse-guarded"),
        "reuse-transfer": ArmStats("reuse-transfer"),
    }
    all_runs = generate_corpus(runs_count=corpus_runs, seed=seed)
    goals = heldout_goals(episodes=episodes, instance_base=10**6, seed=seed)
    checkpoints: list[dict[str, Any]] = []

    for index, goal in enumerate(goals):
        drifted = index >= drift_at
        episode_seed = random.Random(seed).randrange(2**31) ^ index

        # One shared from-scratch plan (all fallbacks and the scratch arm).
        scratch_plan = scratch.plan(goal.spec)
        exec_rng = random.Random(episode_seed)
        scratch_success = exec_rng.random() < true_success_prob(
            scratch_plan.structure, goal.spec, drifted=drifted
        )

        for name, planner in planners.items():
            plan = planner.plan(goal.spec)
            # Common random numbers: same draw for the same structure.
            arm_rng = random.Random(episode_seed)
            success = arm_rng.random() < true_success_prob(
                plan.structure, goal.spec, drifted=drifted
            )
            cross = plan.motif is not None and goal.spec.family not in plan.motif.families
            stale = (
                drifted
                and plan.motif is not None
                and plan.motif.inducted_pre_drift
                and not success
                and scratch_success
            )
            arms[name].note(
                plan,
                success=success,
                cross_family=cross,
                stale=stale,
                divergence=len(
                    plan.structure.kinds.symmetric_difference(scratch_plan.structure.kinds)
                ),
            )
            if name == "reuse-guarded" and plan.motif is not None:
                if planner.observe(plan.motif.signature, success):
                    arms[name].quarantines += 1
                # The flywheel's feedback: record the Run outcome production
                # would record. Successful fallbacks widen the corpus too.
                if success:
                    run, _ = record_run(
                        plan.structure,
                        success=True,
                        actor_principal_id="principal-bench",
                        provenance={
                            "goal_family": goal.spec.family,
                            "goal_instance": goal.instance_id,
                            "goal_signature": plan.structure.signature,
                        },
                    )
                    all_runs.append(run)

        arms["scratch"].note(
            scratch_plan,
            success=scratch_success,
            cross_family=False,
            stale=False,
            divergence=0,
        )

        # The flywheel: periodic re-mining over every successful Run so far.
        if reindex_every > 0 and (index + 1) % reindex_every == 0:
            _reindex(
                all_runs,
                indices,
                stores,
                planners,
                episode_index=index,
                drift_at=drift_at,
                min_support=min_support,
                min_instances=min_instances,
            )

        if index in (drift_at - 1, drift_at, episodes - 1) or index % 100 == 0:
            checkpoints.append(
                {
                    "episode": index,
                    "drifted": drifted,
                    "scratch_success": scratch_success,
                    "reuse_naive_quarantined": len(planners["reuse-naive"].quarantined),
                    "reuse_guarded_quarantined": len(planners["reuse-guarded"].quarantined),
                }
            )

    return {
        "seed": seed,
        "drift_at": drift_at,
        "episodes": episodes,
        "motifs_inducted_initial": len(initial),
        "motifs_inducted_final": {name: len(motifs) for name, motifs in indices.items()},
        "arms": {name: stats.as_dict() for name, stats in arms.items()},
        "inspectability": inspectability(indices, stores),
        "checkpoints": checkpoints,
    }


def inspectability(
    indices: dict[str, dict[str, Motif]],
    stores: dict[str, InMemoryGraphTemplateStore],
) -> dict[str, Any]:
    """Deterministic inspectability/trust proxies for the induced library.

    The issue asks whether reused patterns stay human-inspectable. Proxies:
    motif size (smaller topologies are cheaper to review), documentation
    coverage (induction writes a description naming support/instances/
    families), provenance (every reused Graph must carry TemplateProvenance
    via the real `instantiate`, citing the exact version hash), and the
    candidate-only lifecycle (nothing mined is executable until an audited
    promotion — `require_template`, the execution door, must refuse).
    """
    report: dict[str, Any] = {}
    for name, motifs in indices.items():
        if not motifs:
            report[name] = None
            continue
        sizes = [len(motif.structure.kinds) for motif in motifs.values()]
        store = stores[name]
        templates = asyncio.run(store.list_for_workspace(WORKSPACE))
        documented = sum(1 for template in templates if template.description.strip())
        provenance_ok = True
        for template in templates:
            graph = template.instantiate(project_id=MOTIF_PROJECT)
            source = graph.source_template
            provenance_ok = provenance_ok and source is not None
            if source is not None:
                provenance_ok = provenance_ok and source.template_hash == template.content_hash
        try:
            if templates:
                asyncio.run(require_template(store, templates[0].template_id))
            execution_door_closed = False
        except GraphTemplateNotFound:
            execution_door_closed = bool(templates)
        report[name] = {
            "motifs": len(motifs),
            "mean_motif_nodes": round(sum(sizes) / len(sizes), 2),
            "max_motif_nodes": max(sizes),
            "documented_fraction": round(documented / len(templates), 3) if templates else 0.0,
            "provenance_on_instantiate": provenance_ok,
            "all_candidates_not_active": all(
                asyncio.run(store.lifecycle_of(t.template_id, t.version)) == "candidate"
                for t in templates
            ),
            "execution_door_closed": execution_door_closed,
        }
    return report


# ─── Aggregation ─────────────────────────────────────────────────────────────


def aggregate(per_seed: list[dict[str, Any]]) -> dict[str, Any]:
    """Mean ± std across seeds for every headline number."""
    summary: dict[str, Any] = {}
    for arm in per_seed[0]["arms"]:
        rows = [seed["arms"][arm] for seed in per_seed]
        summary[arm] = {
            "success_rate": _mean_std([r["success_rate"] for r in rows]),
            "mean_tokens": _mean_std([r["mean_tokens"] for r in rows]),
            "mean_roundtrips": _mean_std([r["mean_roundtrips"] for r in rows]),
            "mean_adaptation_edits": _mean_std([r["mean_adaptation_edits"] for r in rows]),
            "stale_attributable_failures": _mean_std(
                [float(r["stale_attributable_failures"]) for r in rows]
            ),
            "guard_quarantines": _mean_std([float(r["guard_quarantines"]) for r in rows]),
            "cross_family_hits": _mean_std([float(r["cross_family_hits"]) for r in rows]),
        }
    return summary


def _mean_std(values: list[float]) -> dict[str, float]:
    n = len(values)
    mean = sum(values) / n
    if n < 2:
        return {"mean": round(mean, 4), "std": 0.0}
    var = sum((value - mean) ** 2 for value in values) / (n - 1)
    return {"mean": round(mean, 4), "std": round(var**0.5, 4)}


def verdict(summary: dict[str, Any]) -> str:
    """The disposition the measured numbers support — stated, not assumed.

    The bar for INCUBATE: reuse must cut planning cost without a success
    regression, and the guard must bound stale-pattern damage. Anything less
    is WATCH. Nothing here can GRADUATE (production adoption needs the normal
    architecture gates and an owning milestone), and REJECT would need reuse
    to fail its own hypothesis outright.
    """
    naive, guarded, scratch = summary["reuse-naive"], summary["reuse-guarded"], summary["scratch"]
    cost_win = scratch["mean_tokens"]["mean"] - guarded["mean_tokens"]["mean"] > 0
    guard_bounds = guarded["success_rate"]["mean"] >= scratch["success_rate"]["mean"] - 0.05
    stale_bounded = (
        guarded["stale_attributable_failures"]["mean"]
        <= naive["stale_attributable_failures"]["mean"]
    )
    if cost_win and guard_bounds and stale_bounded:
        return "INCUBATE"
    return "WATCH"


# ─── CLI ─────────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--corpus-runs", type=int, default=600)
    parser.add_argument("--episodes", type=int, default=400)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--drift-at", type=int, default=200)
    parser.add_argument("--reindex-every", type=int, default=50)
    parser.add_argument("--min-support", type=int, default=3)
    parser.add_argument("--min-instances", type=int, default=2)
    parser.add_argument("--budget", type=int, default=60)
    parser.add_argument("--output", type=str, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    per_seed = [
        run_seed(
            seed,
            corpus_runs=args.corpus_runs,
            episodes=args.episodes,
            drift_at=args.drift_at,
            reindex_every=args.reindex_every,
            min_support=args.min_support,
            min_instances=args.min_instances,
            budget=args.budget,
        )
        for seed in range(args.seeds)
    ]
    summary = aggregate(per_seed)
    payload = {
        "issue": 929,
        "research": "M8-D5 Graph pattern induction and reuse across Goals",
        "cost_model": {
            "scratch_prompt_tokens": SCRATCH_PROMPT_TOKENS,
            "scratch_tokens_per_node": SCRATCH_TOKENS_PER_NODE,
            "scratch_tokens_per_candidate": SCRATCH_TOKENS_PER_CANDIDATE,
            "retrieve_tokens": RETRIEVE_TOKENS,
            "adapt_tokens_per_edit": ADAPT_TOKENS_PER_EDIT,
        },
        "world": {
            "families": [family.name for family in FAMILIES],
            "drift_family": DRIFT_FAMILY,
            "drift_validation_penalty": DRIFT_VALIDATION_PENALTY,
            "validated_bonus": VALIDATED_BONUS,
        },
        "config": {
            "corpus_runs": args.corpus_runs,
            "episodes": args.episodes,
            "seeds": args.seeds,
            "drift_at": args.drift_at,
            "reindex_every": args.reindex_every,
            "min_support": args.min_support,
            "min_instances": args.min_instances,
            "budget": args.budget,
        },
        "summary": summary,
        "verdict": verdict(summary),
        "per_seed": per_seed,
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text)
    print(_render_table(summary, payload["verdict"]))
    return 0


def _render_table(summary: dict[str, Any], disposition: str) -> str:
    lines = [
        "#929 M8-D5 Graph-pattern induction/reuse bench",
        f"disposition: {disposition}",
        f"{'arm':<15} {'success':>9} {'tokens':>9} {'r.trips':>8} {'edits':>7} "
        f"{'stale-f':>8} {'quarant':>8}",
    ]
    for arm in ("scratch", "reuse-naive", "reuse-guarded"):
        row = summary[arm]
        lines.append(
            f"{arm:<15} {row['success_rate']['mean']:>9.4f} {row['mean_tokens']['mean']:>9.1f} "
            f"{row['mean_roundtrips']['mean']:>8.2f} {row['mean_adaptation_edits']['mean']:>7.3f} "
            f"{row['stale_attributable_failures']['mean']:>8.1f} "
            f"{row['guard_quarantines']['mean']:>8.1f}"
        )
    return "\n".join(lines)


if __name__ == "__main__":
    sys.exit(main())
