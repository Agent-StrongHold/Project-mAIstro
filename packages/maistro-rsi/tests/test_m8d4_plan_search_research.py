"""M8-D4 research harness — bounded beam/tree/MCTS-style search over candidate plans.

Issue #928 (leaf of epic #903, initiative #879, program #878). Hypothesis under study:
generating and evaluating multiple candidate plans before execution improves
difficult-Goal success enough to justify the added planning model calls compared with
one-shot planning.

What this module is
-------------------
The reproducible measurement machinery the #928 benchmark procedure demands, as a
test-suite-only research artifact (M8 guardrails 1-2). Candidate plans compile to
**canonical Graph candidates** — real ``maistro.graph.types.GraphConfig`` objects whose
DAG-file projection is checked by the production validator
(``maistro.graph.dag_validator.validate_dag``: registry-known kinds, entry
reachability, acyclicity, per-edge schema compatibility) — and are scored by an
independent rubric scorer before any outcome is consulted. The search is a pure
planner: it dispatches nothing, records nothing, spawns no Run, and registers no node.
A selected candidate would still reach execution through the existing canonical path
(durable Run dispatch of the compiled graph), so the search cannot become a second
runtime; a source-scan guard below pins that the machinery imports no execution or
persistence authority.

What it is not
--------------
No provider credentials exist in CI, so the planner is a deterministic fixture
proposer (seeded shuffle of a per-Goal option pool, billed tokens/latency per call)
and the execution outcome is a fixture oracle (executable candidate + required
capability coverage + width cap). Fixture numbers validate the *machinery* and expose
the search's structural economics; they are not evidence about real models. The
provider-backed experiment on a real difficult-Goal subset is the recorded
next-required-evidence of the research note
(``docs/research/928-bounded-plan-search.md``, INCUBATE).

Vocabulary honesty
------------------
Node kinds in the fixture pools are real registered kinds (``llm.summarize``,
``transform.*``, ``human.ask_question``, ``compliance.block``,
``dashboard.append_section``) plus one deliberately hallucinated kind (``auto.test``)
that the production registry rejects. The compiler wires static inputs for every
registered kind except ``human.ask_question`` — its question text is goal-dependent,
so a plan that clarifies mid-chain fails the real schema-compatibility check while
clarify-at-entry validates. Those are genuine validator findings, not simulated ones.
"""

from __future__ import annotations

import ast
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from maistro.graph.dag_validator import validate_dag
from maistro.graph.types import GraphConfig

# ---------------------------------------------------------------------------
# Canonical seams (production code under test) and fixture vocabulary
# ---------------------------------------------------------------------------

#: Real registered kinds the fixture planner may propose. ``transform.alias_keys``
#: declares no required inputs, so it composes with anything; every other wired
#: kind needs static inputs the compiler supplies from this table.
WIRED_KINDS: dict[str, dict[str, Any]] = {
    "llm.summarize": {"text": "$objective"},
    "transform.alias_keys": {},
    "transform.extract_field": {"field_path": "$objective"},
    "transform.format_markdown": {"template": "$objective"},
    "transform.filter_by_type": {"types": ["*"]},
    "compliance.block": {"rule_id": "$objective"},
    "dashboard.append_section": {"markdown": "$objective", "section_title": "$objective"},
}
#: Deliberately hallucinated kind: not registered, the validator must reject it.
HALLUCINATED_KIND = "auto.test"
#: Goal-dependent question text the plan compiler cannot fabricate: real schema
#: compatibility makes ``human.ask_question`` valid only as the entry node.
UNWIRED_KIND = "human.ask_question"

VOCABULARY: tuple[str, ...] = (*tuple(WIRED_KINDS), UNWIRED_KIND, HALLUCINATED_KIND)

#: Capability each kind contributes (fixture capability model for the oracle).
KIND_CAPABILITIES: dict[str, frozenset[str]] = {
    "llm.summarize": frozenset({"summarize"}),
    "transform.alias_keys": frozenset({"normalize"}),
    "transform.extract_field": frozenset({"extract"}),
    "transform.format_markdown": frozenset({"render"}),
    "transform.filter_by_type": frozenset({"filter"}),
    "human.ask_question": frozenset({"clarify"}),
    "compliance.block": frozenset({"gate"}),
    "dashboard.append_section": frozenset({"report"}),
    HALLUCINATED_KIND: frozenset(),
}

#: Estimated execution cost per kind (fixture estimate, measurement only — used by
#: the scorer's cost penalty and reported per candidate; never a runtime).
KIND_EST_EXEC_TOKENS: dict[str, int] = {
    "llm.summarize": 900,
    "transform.alias_keys": 50,
    "transform.extract_field": 300,
    "transform.format_markdown": 150,
    "transform.filter_by_type": 200,
    "human.ask_question": 10,
    "compliance.block": 50,
    "dashboard.append_section": 100,
    HALLUCINATED_KIND: 0,
}

# Proposal-call accounting constants: what one planner call costs. tokens =
# base + per_option * branching; latency is sequential (no parallelism credit).
PROPOSAL_CALL_TOKENS_BASE = 120
PROPOSAL_TOKENS_PER_OPTION = 40
PROPOSAL_CALL_MS_BASE = 30.0
PROPOSAL_MS_PER_OPTION = 12.0


# ---------------------------------------------------------------------------
# Candidate compilation — canonical Graph candidates + the real validator gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CandidateReport:
    """One compiled candidate plan: canonical GraphConfig + validator verdict."""

    steps: tuple[str, ...]
    graph_config: GraphConfig | None
    dag_findings: tuple[str, ...]
    executable: bool
    capabilities: frozenset[str]
    coverage_ratio: float
    score: float | None
    est_exec_tokens: int

    @property
    def is_valid(self) -> bool:
        return self.executable


def compile_candidate(steps: tuple[str, ...], goal: GoalSpec) -> CandidateReport:
    """Compile a plan (ordered node kinds) to a canonical candidate.

    The projection is the Hive DAGFile shape ``validate_dag`` documents:
    ``{nodes: [{id, kind, inputs}], edges: [{from_node, to_node}], entry_node}``.
    Static inputs are wired for every registered kind whose configuration the
    compiler can supply goal-independently; ``human.ask_question`` is left
    unwired (its question text is goal-dependent), so mid-chain clarify fails
    the real schema-compatibility check. A linear chain of distinct ids cannot
    cycle; duplicates surface as redundancy, not as validator cycles.
    """
    findings: list[str] = []
    graph_config: GraphConfig | None = None
    if not steps:
        findings.append("no_entry")
    else:
        node_specs = [
            {"id": f"step{i}", "kind": kind, "inputs": dict(WIRED_KINDS.get(kind, {}))}
            for i, kind in enumerate(steps)
        ]
        edges = [
            {"from_node": f"step{i}", "to_node": f"step{i + 1}"} for i in range(len(steps) - 1)
        ]
        dag: dict[str, Any] = {
            "nodes": node_specs,
            "edges": edges,
            "entry_node": "step0",
        }
        report = validate_dag(dag)
        findings = [f.code for f in report.findings if f.severity == "error"]
        try:
            graph_config = GraphConfig(
                nodes=[f"step{i}" for i in range(len(steps))],
                edges=[
                    {"from_role": f"step{i}", "to_role": f"step{i + 1}"}
                    for i in range(len(steps) - 1)
                ],
                entry="step0",
            )
        except Exception:  # pragma: no cover - pydantic rejects only malformed ids here
            findings.append("graph_config_rejected")
    capabilities = (
        frozenset().union(*(KIND_CAPABILITIES.get(kind, frozenset()) for kind in steps))
        if steps
        else frozenset()
    )
    required = goal.required
    coverage_ratio = len(capabilities & required) / len(required) if required else 1.0
    executable = bool(steps) and not findings and graph_config is not None
    est_tokens = sum(KIND_EST_EXEC_TOKENS.get(kind, 0) for kind in steps)
    return CandidateReport(
        steps=steps,
        graph_config=graph_config,
        dag_findings=tuple(findings),
        executable=executable,
        capabilities=capabilities,
        coverage_ratio=coverage_ratio,
        score=None,
        est_exec_tokens=est_tokens,
    )


# ---------------------------------------------------------------------------
# The oracle (ground truth for measurement) is NOT the scorer
# ---------------------------------------------------------------------------


def oracle_success(goal: GoalSpec, candidate: CandidateReport) -> bool:
    """Fixture ground truth: executable + all required capabilities + width cap.

    Measurement-only. A real study replaces this with observed Run outcomes on the
    executed candidate; nothing here executes anything.
    """
    return (
        candidate.executable
        and goal.required <= candidate.capabilities
        and len(candidate.steps) <= goal.max_width
    )


# ---------------------------------------------------------------------------
# Independent rubric scorer (the verifier/ranker under study)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScorerWeights:
    """Rubric weights for the independent plan scorer.

    The calibrated default rewards required-capability coverage, penalizes
    redundant steps and estimated execution cost. The adversarial and blind
    variants below exist to make verifier/ranker error measurable.
    """

    coverage: float = 100.0
    duplication: float = 30.0
    est_cost_per_token: float = 0.02

    def score(self, candidate: CandidateReport, goal: GoalSpec) -> float | None:
        if not candidate.executable:
            return None
        dup_ratio = (len(candidate.steps) - len(set(candidate.steps))) / len(candidate.steps)
        return (
            self.coverage * candidate.coverage_ratio
            - self.duplication * dup_ratio
            - self.est_cost_per_token * candidate.est_exec_tokens
        )


#: Ignores required coverage beyond 'clarify' — a miscalibrated ranker.
ADVERSARIAL_SCORER = ScorerWeights(coverage=0.0, duplication=30.0, est_cost_per_token=0.02)
#: Also blind to clarify: the scorer cannot rank at all.
BLIND_SCORER = ScorerWeights(coverage=0.0, duplication=0.0, est_cost_per_token=0.0)
CALIBRATED_SCORER = ScorerWeights()


# ---------------------------------------------------------------------------
# Goal fixtures: a difficult-Goal subset with per-Goal proposer pools
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GoalSpec:
    goal_id: str
    objective: str
    required: frozenset[str]
    pool: tuple[str, ...]
    depth: int = 4
    max_width: int = 4


def _goal(
    goal_id: str, objective: str, required: tuple[str, ...], pool: tuple[str, ...]
) -> GoalSpec:
    return GoalSpec(
        goal_id=goal_id,
        objective=objective,
        required=frozenset(required),
        pool=pool,
    )


#: Ten difficult Goals. Pools mix the required kinds with traps: the
#: hallucinated ``auto.test`` kind (any position invalidates the plan), filler
#: kinds that crowd out required capabilities under the width cap, and (for
#: clarify goals) the entry-only ``human.ask_question`` constraint.
GOAL_SUBSET: tuple[GoalSpec, ...] = (
    _goal(
        "g-01",
        "Ingest and summarize the quarterly report",
        ("summarize", "extract", "render"),
        (
            "llm.summarize",
            "transform.extract_field",
            "transform.format_markdown",
            "transform.alias_keys",
            HALLUCINATED_KIND,
            "compliance.block",
        ),
    ),
    _goal(
        "g-02",
        "Normalize the ledger and filter stale rows",
        ("extract", "normalize", "filter"),
        (
            "transform.extract_field",
            "transform.alias_keys",
            "transform.filter_by_type",
            "transform.format_markdown",
            "llm.summarize",
            "compliance.block",
        ),
    ),
    _goal(
        "g-03",
        "Clarify scope with the requester, then extract and render",
        ("clarify", "extract", "render"),
        (
            "human.ask_question",
            "transform.extract_field",
            "transform.format_markdown",
            "llm.summarize",
            HALLUCINATED_KIND,
            "transform.alias_keys",
        ),
    ),
    _goal(
        "g-04",
        "Gate the disclosure and report it",
        ("gate", "report", "summarize"),
        (
            "compliance.block",
            "dashboard.append_section",
            "llm.summarize",
            "transform.extract_field",
            "transform.filter_by_type",
            HALLUCINATED_KIND,
        ),
    ),
    _goal(
        "g-05",
        "Wide audit: extract, filter, render, normalize — nothing else",
        ("extract", "filter", "render", "normalize"),
        (
            "transform.extract_field",
            "transform.filter_by_type",
            "transform.format_markdown",
            "transform.alias_keys",
            "llm.summarize",
            HALLUCINATED_KIND,
        ),
    ),
    _goal(
        "g-06",
        "Ask the human, summarize, and append to the dashboard",
        ("clarify", "summarize", "report"),
        (
            "human.ask_question",
            "llm.summarize",
            "dashboard.append_section",
            "transform.extract_field",
            "compliance.block",
        ),
    ),
    _goal(
        "g-07",
        "Render the normalized pipeline output",
        ("render", "normalize"),
        (
            "transform.format_markdown",
            "transform.alias_keys",
            "transform.extract_field",
            "llm.summarize",
            "transform.filter_by_type",
        ),
    ),
    _goal(
        "g-08",
        "Full audit trail: summarize, extract, filter, report",
        ("summarize", "extract", "filter", "report"),
        (
            "llm.summarize",
            "transform.extract_field",
            "transform.filter_by_type",
            "dashboard.append_section",
            "transform.alias_keys",
            HALLUCINATED_KIND,
        ),
    ),
    _goal(
        "g-09",
        "Light normalization pass",
        ("normalize", "filter"),
        (
            "transform.alias_keys",
            "transform.filter_by_type",
            "transform.format_markdown",
            "llm.summarize",
            "transform.extract_field",
        ),
    ),
    _goal(
        "g-10",
        "Clarify, gate, filter, and render the finding",
        ("clarify", "gate", "filter", "render"),
        (
            "human.ask_question",
            "compliance.block",
            "transform.filter_by_type",
            "transform.format_markdown",
            "llm.summarize",
            HALLUCINATED_KIND,
        ),
    ),
)


# ---------------------------------------------------------------------------
# Bounded search machinery: accounting, proposer, beam, MCTS-style, baseline
# ---------------------------------------------------------------------------


@dataclass
class _Ledger:
    """Mutable planning-call accounting; frozen into the report at the end."""

    max_proposal_calls: int
    proposal_calls: int = 0
    options_considered: int = 0
    tokens: int = 0
    latency_ms: float = 0.0

    @property
    def exhausted(self) -> bool:
        return self.proposal_calls >= self.max_proposal_calls

    def bill(self, options: int) -> None:
        self.proposal_calls += 1
        self.options_considered += options
        self.tokens += PROPOSAL_CALL_TOKENS_BASE + PROPOSAL_TOKENS_PER_OPTION * options
        self.latency_ms += PROPOSAL_CALL_MS_BASE + PROPOSAL_MS_PER_OPTION * options


@dataclass(frozen=True)
class Accounting:
    proposal_calls: int
    options_considered: int
    tokens: int
    latency_ms: float


@dataclass(frozen=True)
class BoundedSearchConfig:
    """Hard caps. Every knob here is a bound the search must respect exactly."""

    strategy: str = "beam"  # "beam" | "mcts"
    beam_width: int = 2
    branching: int = 5
    max_depth: int = 4
    max_proposal_calls: int = 64
    max_scored_candidates: int = 256
    mcts_iterations: int = 12
    mcts_explore: float = 1.414


#: One-shot planning analog: the planner never sees alternatives (branching=1)
#: and never revisits a choice (width=1). Bills exactly ``depth`` calls.
ONE_SHOT_CONFIG = BoundedSearchConfig(
    strategy="beam", beam_width=1, branching=1, max_proposal_calls=8
)


class FixtureProposer:
    """Deterministic stand-in for the planning model.

    Each call shuffles the Goal's option pool with a seed derived from the Goal
    id and the prefix, then offers the first ``branching`` options. Same
    (goal, prefix) always yields the same options; different prefixes explore
    the pool differently. Every call is billed.
    """

    def __init__(self, goal: GoalSpec, ledger: _Ledger, cfg: BoundedSearchConfig) -> None:
        self._goal = goal
        self._ledger = ledger
        self._cfg = cfg

    def propose(self, prefix: tuple[str, ...]) -> tuple[str, ...]:
        if self._ledger.exhausted:
            return ()
        rng = random.Random(f"{self._goal.goal_id}|{'>'.join(prefix)}")
        pool = list(self._goal.pool)
        rng.shuffle(pool)
        options = tuple(pool[: self._cfg.branching])
        self._ledger.bill(len(options))
        return options


class DegenerateProposer(FixtureProposer):
    """Every state offers the same single option — search cannot diversify."""

    def __init__(self, goal: GoalSpec, ledger: _Ledger, cfg: BoundedSearchConfig) -> None:
        super().__init__(goal, ledger, cfg)
        self._only = (self._goal.pool[0],)

    def propose(self, prefix: tuple[str, ...]) -> tuple[str, ...]:
        if self._ledger.exhausted:
            return ()
        self._ledger.bill(len(self._only))
        return self._only


@dataclass(frozen=True)
class SearchReport:
    strategy: str
    selected: CandidateReport
    final_beam: tuple[CandidateReport, ...]
    candidates: tuple[CandidateReport, ...]
    accounting: Accounting
    config: BoundedSearchConfig

    def success(self, goal: GoalSpec) -> bool:
        return oracle_success(goal, self.selected)

    @property
    def distinct_fraction(self) -> float:
        """Share of distinct plans among the final beam — the diversity measure."""
        if not self.final_beam:
            return 0.0
        return len({c.steps for c in self.final_beam}) / len(self.final_beam)

    @property
    def executable_fraction(self) -> float:
        if not self.candidates:
            return 0.0
        return sum(1 for c in self.candidates if c.executable) / len(self.candidates)


class _CandidateCache:
    """Compile+score memo shared by one search. Scores at most
    ``max_scored_candidates`` distinct plans — the scoring-budget cap. Once the
    cap binds, ``full`` is True and the search loops stop expanding."""

    def __init__(
        self,
        goal: GoalSpec,
        cfg: BoundedSearchConfig,
        weights: ScorerWeights,
    ) -> None:
        self._goal = goal
        self._cfg = cfg
        self._weights = weights
        self._by_steps: dict[tuple[str, ...], CandidateReport] = {}

    @property
    def full(self) -> bool:
        return len(self._by_steps) >= self._cfg.max_scored_candidates

    def get(self, steps: tuple[str, ...]) -> CandidateReport:
        if steps in self._by_steps:
            return self._by_steps[steps]
        candidate = compile_candidate(steps, self._goal)
        candidate = CandidateReport(
            **{
                **{f: getattr(candidate, f) for f in CandidateReport.__dataclass_fields__},
                "score": self._weights.score(candidate, self._goal),
            }
        )
        self._by_steps[steps] = candidate
        return candidate

    @property
    def complete(self) -> list[CandidateReport]:
        return [c for steps, c in self._by_steps.items() if len(steps) == self._goal.depth]

    @property
    def deepest(self) -> list[CandidateReport]:
        """Candidates of the greatest compiled length — the honest fallback when
        a tight scoring cap stopped the search before any complete plan."""
        if not self._by_steps:
            return []
        depth = max(len(steps) for steps in self._by_steps)
        return [c for c in self._by_steps.values() if len(c.steps) == depth]

    @property
    def all(self) -> list[CandidateReport]:
        """Every compiled candidate, prefixes included — what was searched."""
        return sorted(self._by_steps.values(), key=lambda c: (len(c.steps), c.steps))


def _expand_level(
    beam: list[tuple[str, ...]],
    proposer: FixtureProposer,
    cache: _CandidateCache,
    ledger: _Ledger,
    cfg: BoundedSearchConfig,
) -> list[CandidateReport]:
    """One beam level: bill one proposal call per prefix, dedupe children, and
    compile+score up to the scoring cap (children past the cap are dropped,
    not scored)."""
    children: list[tuple[str, ...]] = []
    for prefix in beam:
        if ledger.exhausted or cache.full:
            break
        for kind in proposer.propose(prefix):
            children.append((*prefix, kind))
    scored: list[CandidateReport] = []
    for child in dict.fromkeys(children):
        if cache.full:
            break
        scored.append(cache.get(child))
    scored.sort(key=lambda c: (-(c.score if c.score is not None else float("-inf")), c.steps))
    return scored


def beam_plan_search(
    goal: GoalSpec,
    cfg: BoundedSearchConfig,
    weights: ScorerWeights = CALIBRATED_SCORER,
    proposer_cls: type[FixtureProposer] = FixtureProposer,
) -> SearchReport:
    """Bounded beam search over plan prefixes.

    Depth = plan length. Each level expands every beam prefix with one billed
    proposal call of ``branching`` options, dedupes children, ranks them with
    the independent scorer (invalid candidates rank last but never vanish, so
    the beam stays populated), and keeps ``beam_width`` prefixes. Total
    proposal calls <= ``max_depth * beam_width``; distinct scored candidates
    <= ``max_scored_candidates``. Selection is the best-scoring executable
    complete candidate in the final beam (best-scoring candidate overall if
    none executed, reported faithfully as a failure by ``oracle_success``).
    """
    effective_depth = min(cfg.max_depth, goal.depth)
    ledger = _Ledger(cfg.max_proposal_calls)
    cache = _CandidateCache(goal, cfg, weights)
    proposer = proposer_cls(goal, ledger, cfg)

    beam: list[tuple[str, ...]] = [()]
    final_beam: tuple[CandidateReport, ...] = ()
    for depth in range(effective_depth):
        scored = _expand_level(beam, proposer, cache, ledger, cfg)
        if not scored:
            break
        beam = [c.steps for c in scored[: cfg.beam_width]]
        if depth == effective_depth - 1:
            final_beam = tuple(scored[: cfg.beam_width])

    # Selection: the best-scoring candidate of the final beam; if the budget ran
    # out before the last level, the deepest compiled candidates (reported
    # faithfully — oracle_success will judge them against the full plan).
    if final_beam:
        selected_pool: list[CandidateReport] = list(final_beam)
    else:
        selected_pool = cache.deepest or [cache.get(())]
    selected = min(
        selected_pool,
        key=lambda c: (-(c.score if c.score is not None else float("-inf")), c.steps),
    )
    all_candidates = tuple(cache.all)
    return SearchReport(
        strategy="beam",
        selected=selected,
        final_beam=final_beam,
        candidates=all_candidates,
        accounting=Accounting(
            proposal_calls=ledger.proposal_calls,
            options_considered=ledger.options_considered,
            tokens=ledger.tokens,
            latency_ms=ledger.latency_ms,
        ),
        config=cfg,
    )


@dataclass
class _MctsNode:
    prefix: tuple[str, ...]
    parent: _MctsNode | None = None
    children: dict[str, _MctsNode] = field(default_factory=dict)
    untried: tuple[str, ...] = ()
    visits: int = 0
    reward_sum: float = 0.0

    @property
    def mean_reward(self) -> float:
        return self.reward_sum / self.visits if self.visits else 0.0

    def ucb1(self, explore: float) -> float:
        if self.visits == 0:
            return float("inf")
        parent_visits = self.parent.visits if self.parent is not None else self.visits
        return self.mean_reward + explore * (parent_visits**0.5) / (1 + self.visits) ** 0.5


def normalized_mcts_reward(candidate: CandidateReport) -> float:
    """Scorer verdict mapped to [0, 1] for UCB1 backpropagation."""
    if not candidate.executable:
        return 0.0
    dup_ratio = (len(candidate.steps) - len(set(candidate.steps))) / len(candidate.steps)
    return max(0.0, candidate.coverage_ratio - 0.3 * dup_ratio)


def _mcts_iteration(
    root: _MctsNode,
    goal: GoalSpec,
    cfg: BoundedSearchConfig,
    proposer: FixtureProposer,
    cache: _CandidateCache,
) -> None:
    """One UCB1 selection -> expansion -> greedy rollout -> backprop pass."""
    node = root
    path = [node]
    # Selection: descend fully expanded nodes by UCB1 (ties -> first child).
    while node.untried == () and node.children:
        node = max(node.children.values(), key=lambda n: n.ucb1(cfg.mcts_explore))
        path.append(node)
    # Expansion: bill one proposal call; add one new child.
    if node.untried == () and not node.children and not proposer._ledger.exhausted:
        node.untried = proposer.propose(node.prefix)
    if node.untried:
        kind = node.untried[0]
        node.untried = node.untried[1:]
        child = _MctsNode((*node.prefix, kind), parent=node)
        node.children[kind] = child
        node, path = child, [*path, child]
    # Rollout: greedy completion (first offered option) with billed calls.
    prefix = node.prefix
    while len(prefix) < goal.depth and not proposer._ledger.exhausted:
        options = proposer.propose(prefix)
        if not options:
            break
        prefix = (*prefix, options[0])
    reward = normalized_mcts_reward(cache.get(prefix))
    for n in path:
        n.visits += 1
        n.reward_sum += reward


def mcts_plan_search(
    goal: GoalSpec,
    cfg: BoundedSearchConfig,
    weights: ScorerWeights = CALIBRATED_SCORER,
    proposer_cls: type[FixtureProposer] = FixtureProposer,
) -> SearchReport:
    """Bounded MCTS-style search over the prefix tree (UCB1 + greedy rollouts).

    Selection descends by UCB1 through expanded nodes; expansion asks the
    proposer once per freshly visited node; the rollout completes the plan
    greedily (first offered option) with billed calls; the reward is the
    scorer's normalized verdict of the completed plan, backpropagated along
    the path. Bounded by ``mcts_iterations`` and the shared
    ``max_proposal_calls`` budget.
    """
    ledger = _Ledger(cfg.max_proposal_calls)
    cache = _CandidateCache(goal, cfg, weights)
    proposer = proposer_cls(goal, ledger, cfg)
    root = _MctsNode(())
    for _ in range(cfg.mcts_iterations):
        if ledger.exhausted or cache.full:
            break
        _mcts_iteration(root, goal, cfg, proposer, cache)

    complete = sorted(cache.complete, key=lambda c: c.steps)
    if not complete:  # tight scoring cap: report the deepest searched prefixes
        complete = sorted(cache.deepest, key=lambda c: c.steps)
    if not complete:  # pragma: no cover - iterations >= 1 always compiles something
        complete = [cache.get(())]
    ranked = sorted(
        complete,
        key=lambda c: (-(c.score if c.score is not None else float("-inf")), c.steps),
    )
    final_beam = tuple(ranked[: cfg.beam_width])
    return SearchReport(
        strategy="mcts",
        selected=ranked[0],
        final_beam=final_beam,
        candidates=tuple(complete),
        accounting=Accounting(
            proposal_calls=ledger.proposal_calls,
            options_considered=ledger.options_considered,
            tokens=ledger.tokens,
            latency_ms=ledger.latency_ms,
        ),
        config=cfg,
    )


def run_search(
    goal: GoalSpec,
    cfg: BoundedSearchConfig,
    weights: ScorerWeights = CALIBRATED_SCORER,
    proposer_cls: type[FixtureProposer] = FixtureProposer,
) -> SearchReport:
    if cfg.strategy == "mcts":
        return mcts_plan_search(goal, cfg, weights, proposer_cls)
    return beam_plan_search(goal, cfg, weights, proposer_cls)


# ---------------------------------------------------------------------------
# Measurement utilities: uplift, sensitivity, diversity, verifier error,
# benchmark-overfitting probes
# ---------------------------------------------------------------------------


def success_rate(
    goals: tuple[GoalSpec, ...], cfg: BoundedSearchConfig, weights: ScorerWeights
) -> float:
    return sum(1 for g in goals if run_search(g, cfg, weights).success(g)) / len(goals)


def uplift(
    goals: tuple[GoalSpec, ...],
    cfg: BoundedSearchConfig,
    weights: ScorerWeights = CALIBRATED_SCORER,
) -> float:
    """Goal success of the search minus one-shot planning over the subset."""
    baseline = success_rate(goals, ONE_SHOT_CONFIG, weights)
    return success_rate(goals, cfg, weights) - baseline


def planning_cost(cfg: BoundedSearchConfig, goals: tuple[GoalSpec, ...]) -> Accounting:
    """Mean per-Goal planning accounting for a config over the subset."""
    reports = [run_search(g, cfg) for g in goals]
    n = len(reports)
    return Accounting(
        proposal_calls=round(sum(r.accounting.proposal_calls for r in reports) / n),
        options_considered=round(sum(r.accounting.options_considered for r in reports) / n),
        tokens=round(sum(r.accounting.tokens for r in reports) / n),
        latency_ms=round(sum(r.accounting.latency_ms for r in reports) / n, 3),
    )


def _oracle_key(goal: GoalSpec, c: CandidateReport) -> tuple[bool, float, int]:
    return (oracle_success(goal, c), c.coverage_ratio, -c.est_exec_tokens)


def top1_regret(goal: GoalSpec, cfg: BoundedSearchConfig, weights: ScorerWeights) -> int:
    """Verifier error at the decision that matters: did the scorer's pick beat the
    oracle's pick? 1 if a candidate in the searched set dominates the selected one
    under the oracle, else 0."""
    report = run_search(goal, cfg, weights)
    best = max(report.candidates, key=lambda c: _oracle_key(goal, c))
    if oracle_success(goal, report.selected):
        return 0
    return 1 if _oracle_key(goal, best) > _oracle_key(goal, report.selected) else 0


def kendall_tau(a: list[float], b: list[float]) -> float:
    """Kendall tau-b between two rankings (concordant minus discordant pairs,
    normalized by sqrt of the tie-corrected products)."""
    assert len(a) == len(b) and len(a) >= 2
    n = len(a)
    concordant = discordant = 0
    ties_a = ties_b = 0
    for i in range(n):
        for j in range(i + 1, n):
            da = (a[i] > a[j]) - (a[i] < a[j])
            db = (b[i] > b[j]) - (b[i] < b[j])
            if da == 0 and db == 0:
                ties_a += 1
                ties_b += 1
            elif da == 0:
                ties_a += 1
            elif db == 0:
                ties_b += 1
            elif da == db:
                concordant += 1
            else:
                discordant += 1
    denom = ((n * (n - 1) / 2 - ties_a) * (n * (n - 1) / 2 - ties_b)) ** 0.5
    if denom == 0:
        return 0.0
    return (concordant - discordant) / denom


def scorer_oracle_tau(goal: GoalSpec, cfg: BoundedSearchConfig, weights: ScorerWeights) -> float:
    """Rank agreement between the scorer and the oracle over the searched set."""
    report = run_search(goal, cfg, weights)

    def oracle_score(c: CandidateReport) -> float:
        success, coverage, neg_cost = _oracle_key(goal, c)
        return float(success) + coverage + neg_cost / 1000.0

    scorer_scores = [c.score if c.score is not None else float("-inf") for c in report.candidates]
    oracle_scores = [oracle_score(c) for c in report.candidates]
    return kendall_tau(scorer_scores, oracle_scores)


def mean_pairwise_jaccard_distance(beams: list[CandidateReport]) -> float:
    """Mean diversity (1 - Jaccard) across the given candidates' capability sets
    (pass the flattened final beams of the searched goals)."""
    from itertools import combinations

    pairs = list(combinations(range(len(beams)), 2))
    if not pairs:
        return 0.0
    total = 0.0
    for i, j in pairs:
        union = beams[i].capabilities | beams[j].capabilities
        inter = beams[i].capabilities & beams[j].capabilities
        total += 1.0 - (len(inter) / len(union) if union else 1.0)
    return total / len(pairs)


TUNING_GRID: tuple[tuple[int, int], ...] = (
    (1, 1),
    (1, 3),
    (2, 3),
    (2, 4),
    (3, 4),
    (3, 5),
)


def tune_width_branch(
    goals: tuple[GoalSpec, ...], grid: tuple[tuple[int, int], ...] = TUNING_GRID
) -> BoundedSearchConfig:
    """Pick (beam_width, branching) by uplift on the given goals — the honest
    protocol tunes on a tuning split only."""
    best_cfg = ONE_SHOT_CONFIG
    best_uplift = -float("inf")
    for width, branch in grid:
        cfg = BoundedSearchConfig(beam_width=width, branching=branch, max_depth=4)
        value = uplift(goals, cfg)
        if value > best_uplift:
            best_uplift, best_cfg = value, cfg
    return best_cfg


def leaky_tuned_uplift(goals: tuple[GoalSpec, ...]) -> float:
    """The overfitting trap: pick the best config *per Goal on the evaluation
    split itself* (oracle access), then report its mean success against the
    one-shot baseline. This is the inflated number a leaked protocol reports."""
    baseline = success_rate(goals, ONE_SHOT_CONFIG, CALIBRATED_SCORER)
    wins = 0
    for g in goals:
        best = max(
            success_rate(
                (g,), BoundedSearchConfig(beam_width=w, branching=b, max_depth=4), CALIBRATED_SCORER
            )
            for w, b in TUNING_GRID
            if (w, b) != (1, 1)
        )
        wins += int(best > 0)
    return wins / len(goals) - baseline


# ---------------------------------------------------------------------------
# Machinery-inertness guard: the search must not import an execution authority
# ---------------------------------------------------------------------------


def _module_imports() -> list[str]:
    source = Path(__file__).read_text(encoding="utf-8")
    modules: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
    return modules


FORBIDDEN_EXECUTION_IMPORT_PREFIXES = (
    "maistro.runs",
    "maistro.graph.executor",
    "maistro.graph.durable_runs",
    "maistro.graph.harness",
    "maistro.graph.harness_executor",
    "maistro_server",
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestCompileGate:
    """Candidate plans compile to canonical Graph candidates behind the real gate."""

    def test_valid_plan_compiles_to_canonical_graph_config(self):
        goal = GOAL_SUBSET[0]
        steps = ("human.ask_question", "transform.extract_field", "transform.alias_keys")
        candidate = compile_candidate(steps, goal)
        assert candidate.executable
        assert candidate.graph_config is not None
        assert isinstance(candidate.graph_config, GraphConfig)
        assert candidate.graph_config.entry == "step0"
        assert [str(n) for n in candidate.graph_config.nodes] == [
            "step0",
            "step1",
            "step2",
        ]
        assert candidate.dag_findings == ()

    def test_hallucinated_kind_is_rejected_by_the_production_registry(self):
        goal = GOAL_SUBSET[0]
        candidate = compile_candidate(
            ("transform.extract_field", HALLUCINATED_KIND, "transform.alias_keys"), goal
        )
        assert not candidate.executable
        assert "unknown_kind" in candidate.dag_findings
        # The canonical config is still built; the gate, not construction, binds.
        assert candidate.graph_config is not None

    def test_mid_chain_clarify_fails_real_schema_compatibility(self):
        goal = GOAL_SUBSET[2]
        wired = compile_candidate(
            ("transform.extract_field", "human.ask_question", "transform.alias_keys"), goal
        )
        assert not wired.executable
        assert "schema_mismatch" in wired.dag_findings
        # The same step is valid as the entry: no upstream edge to violate.
        entry_only = compile_candidate(
            ("human.ask_question", "transform.extract_field", "transform.alias_keys"), goal
        )
        assert entry_only.executable

    def test_empty_plan_has_no_entry_and_covers_nothing(self):
        goal = GOAL_SUBSET[0]
        candidate = compile_candidate((), goal)
        assert not candidate.executable
        assert "no_entry" in candidate.dag_findings
        assert candidate.capabilities == frozenset()
        assert candidate.coverage_ratio == 0.0

    def test_oracle_and_scorer_are_independent_instruments(self):
        """The oracle demands coverage; the scorer merely rewards it. A candidate
        with full coverage but a validator defect scores None and fails the oracle:
        neither instrument can substitute for the other."""
        goal = GOAL_SUBSET[0]
        broken_but_covering = compile_candidate(
            (
                "llm.summarize",
                "transform.extract_field",
                HALLUCINATED_KIND,
                "transform.format_markdown",
            ),
            goal,
        )
        assert goal.required <= broken_but_covering.capabilities
        assert not oracle_success(goal, broken_but_covering)
        assert CALIBRATED_SCORER.score(broken_but_covering, goal) is None


class TestBoundedSearch:
    """The bounds are structural: caps respected exactly, one-shot degenerates."""

    def test_caps_are_respected_exactly(self):
        goal = GOAL_SUBSET[4]
        cfg = BoundedSearchConfig(
            beam_width=2, branching=3, max_proposal_calls=8, max_scored_candidates=40
        )
        report = run_search(goal, cfg)
        assert report.accounting.proposal_calls <= cfg.max_proposal_calls
        assert report.accounting.proposal_calls <= 1 + (cfg.max_depth - 1) * cfg.beam_width
        assert len(report.candidates) <= cfg.max_scored_candidates
        assert len({c.steps for c in report.candidates}) == len(report.candidates)

    def test_tight_scoring_cap_reports_deepest_searched_prefixes(self):
        """A tight candidate cap must not fabricate unsearched plans: the report
        carries the deepest prefixes actually compiled."""
        goal = GOAL_SUBSET[0]
        cfg = BoundedSearchConfig(beam_width=2, branching=3, max_scored_candidates=10)
        report = run_search(goal, cfg)
        # The cap binds exactly: one candidate is compiled per scoring slot, and
        # the search stops cleanly at the deepest reached level.
        assert len(report.candidates) == cfg.max_scored_candidates
        assert report.selected.steps != ()
        deepest = max(len(c.steps) for c in report.candidates)
        assert len(report.selected.steps) == deepest

    def test_width_one_branching_one_is_exactly_one_shot(self):
        goal = GOAL_SUBSET[0]
        greedy = run_search(goal, ONE_SHOT_CONFIG)
        baseline = run_search(goal, ONE_SHOT_CONFIG)
        assert greedy.selected.steps == baseline.selected.steps
        # depth calls, one option each: the pinned one-shot accounting.
        assert greedy.accounting.proposal_calls == goal.depth
        assert greedy.accounting.options_considered == goal.depth
        assert greedy.accounting.tokens == goal.depth * (
            PROPOSAL_CALL_TOKENS_BASE + PROPOSAL_TOKENS_PER_OPTION
        )
        assert greedy.accounting.latency_ms == goal.depth * (
            PROPOSAL_CALL_MS_BASE + PROPOSAL_MS_PER_OPTION
        )

    def test_beam_accounting_is_pinned_and_sequential(self):
        goal = GOAL_SUBSET[0]
        cfg = BoundedSearchConfig(beam_width=2, branching=3)
        report = run_search(goal, cfg)
        # Root level bills one call; every deeper level bills one per beam member.
        calls = 1 + (cfg.max_depth - 1) * cfg.beam_width
        assert report.accounting.proposal_calls == calls
        assert report.accounting.options_considered == calls * cfg.branching
        assert report.accounting.tokens == calls * (
            PROPOSAL_CALL_TOKENS_BASE + PROPOSAL_TOKENS_PER_OPTION * cfg.branching
        )
        assert report.accounting.latency_ms == calls * (
            PROPOSAL_CALL_MS_BASE + PROPOSAL_MS_PER_OPTION * cfg.branching
        )

    def test_search_is_deterministic(self):
        goal = GOAL_SUBSET[7]
        cfg = BoundedSearchConfig(beam_width=2, branching=5)
        assert run_search(goal, cfg) == run_search(goal, cfg)
        mcts_cfg = BoundedSearchConfig(strategy="mcts")
        assert run_search(goal, mcts_cfg) == run_search(goal, mcts_cfg)

    def test_exhausted_budget_terminates_cleanly(self):
        goal = GOAL_SUBSET[3]
        cfg = BoundedSearchConfig(beam_width=2, branching=5, max_proposal_calls=2)
        report = run_search(goal, cfg)
        assert report.accounting.proposal_calls == 2
        # The report still carries whatever was compiled before the cap bound.
        assert report.selected.steps != ()

    def test_beam_never_returns_an_empty_selection(self):
        for goal in GOAL_SUBSET:
            report = run_search(goal, BoundedSearchConfig())
            assert report.selected is not None
            assert len(report.selected.steps) == goal.depth
            assert len(report.final_beam) <= BoundedSearchConfig().beam_width


class TestUplift:
    """The hypothesis cell: bounded search beats one-shot on the difficult subset."""

    def test_search_beats_one_shot_on_the_difficult_subset(self):
        rate_baseline = success_rate(GOAL_SUBSET, ONE_SHOT_CONFIG, CALIBRATED_SCORER)
        rate_beam = success_rate(
            GOAL_SUBSET, BoundedSearchConfig(beam_width=2, branching=5), CALIBRATED_SCORER
        )
        # Pinned at this fixture set: one-shot planning fails often enough that
        # bounded search pays for its extra calls.
        assert 0.0 < rate_baseline < 0.6, f"fixture drifted: baseline={rate_baseline}"
        assert rate_beam >= 0.9, f"fixture drifted: beam={rate_beam}"
        assert uplift(GOAL_SUBSET, BoundedSearchConfig(beam_width=2, branching=5)) > 0.3

    def test_search_strictly_costs_more_planning_than_one_shot(self):
        baseline_cost = planning_cost(ONE_SHOT_CONFIG, GOAL_SUBSET)
        beam_cost = planning_cost(BoundedSearchConfig(beam_width=2, branching=5), GOAL_SUBSET)
        assert beam_cost.proposal_calls > baseline_cost.proposal_calls
        assert beam_cost.tokens > baseline_cost.tokens
        assert beam_cost.latency_ms > baseline_cost.latency_ms
        # The pinned per-call economics: 4 calls x (120 + 40) vs 1 + 3x2 calls
        # x (120 + 40*5).
        assert baseline_cost.tokens == 4 * (PROPOSAL_CALL_TOKENS_BASE + PROPOSAL_TOKENS_PER_OPTION)
        assert beam_cost.tokens == (1 + 3 * 2) * (
            PROPOSAL_CALL_TOKENS_BASE + PROPOSAL_TOKENS_PER_OPTION * 5
        )

    def test_blind_scorer_earns_no_uplift_at_full_cost(self):
        """The dominance boundary: without a discriminating verifier, the full
        planning bill buys nothing the calibrated ranker wouldn't — uplift is a
        property of the scorer's discrimination, not of search alone."""
        cfg = BoundedSearchConfig(beam_width=2, branching=5)
        blind_uplift = uplift(GOAL_SUBSET, cfg, BLIND_SCORER)
        calibrated_uplift = uplift(GOAL_SUBSET, cfg, CALIBRATED_SCORER)
        assert blind_uplift < calibrated_uplift
        # The blind beam bills the same calls regardless of scorer quality.
        blind_report = run_search(GOAL_SUBSET[0], cfg, BLIND_SCORER)
        calibrated_report = run_search(GOAL_SUBSET[0], cfg, CALIBRATED_SCORER)
        assert blind_report.accounting.tokens == calibrated_report.accounting.tokens


class TestSensitivity:
    """Search depth/branching sensitivity: gains saturate while cost grows."""

    def test_success_is_not_decreasing_in_beam_width(self):
        one = success_rate(
            GOAL_SUBSET, BoundedSearchConfig(beam_width=1, branching=5), CALIBRATED_SCORER
        )
        three = success_rate(
            GOAL_SUBSET, BoundedSearchConfig(beam_width=3, branching=5), CALIBRATED_SCORER
        )
        assert three >= one

    def test_cost_strictly_increases_in_branching(self):
        cheap = planning_cost(BoundedSearchConfig(beam_width=2, branching=2), GOAL_SUBSET)
        rich = planning_cost(BoundedSearchConfig(beam_width=2, branching=5), GOAL_SUBSET)
        assert rich.tokens > cheap.tokens
        assert rich.latency_ms > cheap.latency_ms

    def test_gains_saturate_before_cost_does(self):
        """width 2 -> 3 adds (at most) marginal success while tokens keep climbing:
        the economics that bound a production deployment."""
        two = success_rate(
            GOAL_SUBSET, BoundedSearchConfig(beam_width=2, branching=5), CALIBRATED_SCORER
        )
        three = success_rate(
            GOAL_SUBSET, BoundedSearchConfig(beam_width=3, branching=5), CALIBRATED_SCORER
        )
        cost_two = planning_cost(BoundedSearchConfig(beam_width=2, branching=5), GOAL_SUBSET)
        cost_three = planning_cost(BoundedSearchConfig(beam_width=3, branching=5), GOAL_SUBSET)
        assert cost_three.tokens > cost_two.tokens
        assert three - two < 0.15  # saturation: the wide beam buys almost nothing


class TestDiversity:
    """Diversity of the candidate set is a search property, not an accident."""

    def test_degenerate_proposer_yields_no_diversity_and_no_gain(self):
        goal = GOAL_SUBSET[0]
        cfg = BoundedSearchConfig(beam_width=3, branching=2)
        report = run_search(goal, cfg, proposer_cls=DegenerateProposer)
        # Dedup collapses the beam to the single plan the proposer can offer.
        assert len({c.steps for c in report.final_beam}) == 1
        assert report.distinct_fraction == pytest.approx(1.0)
        baseline = run_search(goal, ONE_SHOT_CONFIG, proposer_cls=DegenerateProposer)
        assert oracle_success(goal, report.selected) == oracle_success(goal, baseline.selected)

    def test_normal_search_surfacing_distinct_candidates(self):
        goal = GOAL_SUBSET[0]
        report = run_search(goal, BoundedSearchConfig(beam_width=3, branching=5))
        assert report.distinct_fraction > 0.5
        assert report.executable_fraction > 0.0

    def test_mean_pairwise_jaccard_distance_spans_the_range(self):
        goal = GOAL_SUBSET[0]
        degenerate = list(
            run_search(
                goal,
                BoundedSearchConfig(beam_width=3, branching=2),
                proposer_cls=DegenerateProposer,
            ).candidates
        )
        normal = list(run_search(goal, BoundedSearchConfig(beam_width=3, branching=5)).candidates)
        degenerate_distance = mean_pairwise_jaccard_distance(degenerate)
        normal_distance = mean_pairwise_jaccard_distance(normal)
        for value in (degenerate_distance, normal_distance):
            assert 0.0 <= value <= 1.0
        # The degenerate candidate set carries one capability set; the normal
        # search surfaces candidates covering more of the vocabulary.
        assert normal_distance > degenerate_distance


class TestVerifierError:
    """Verifier/ranker error: scorer-vs-oracle agreement, regret, and its cost."""

    def test_calibrated_scorer_has_zero_top1_regret_on_the_subset(self):
        cfg = BoundedSearchConfig(beam_width=2, branching=5)
        regrets = [top1_regret(g, cfg, CALIBRATED_SCORER) for g in GOAL_SUBSET]
        assert sum(regrets) == 0

    def test_adversarial_scorer_incurs_real_regret(self):
        cfg = BoundedSearchConfig(beam_width=2, branching=5)
        calibrated = success_rate(GOAL_SUBSET, cfg, CALIBRATED_SCORER)
        adversarial = success_rate(GOAL_SUBSET, cfg, ADVERSARIAL_SCORER)
        assert adversarial < calibrated
        regrets = [top1_regret(g, cfg, ADVERSARIAL_SCORER) for g in GOAL_SUBSET]
        assert sum(regrets) > 0

    def test_rank_agreement_tracks_scorer_quality(self):
        cfg = BoundedSearchConfig(beam_width=2, branching=5)
        taus_calibrated = [scorer_oracle_tau(g, cfg, CALIBRATED_SCORER) for g in GOAL_SUBSET]
        taus_adversarial = [scorer_oracle_tau(g, cfg, ADVERSARIAL_SCORER) for g in GOAL_SUBSET]
        for tau in [*taus_calibrated, *taus_adversarial]:
            assert -1.0 <= tau <= 1.0
        assert sum(taus_calibrated) > sum(taus_adversarial)

    def test_kendall_tau_identities(self):
        assert kendall_tau([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == pytest.approx(1.0)
        assert kendall_tau([1.0, 2.0, 3.0], [3.0, 2.0, 1.0]) == pytest.approx(-1.0)
        assert kendall_tau([1.0, 2.0], [1.0, 1.0]) == 0.0  # fully tied second ranking


class TestMctsStyleSearch:
    """The MCTS-style variant obeys the same bounds and scoring discipline."""

    def test_mcts_respects_iteration_and_budget_caps(self):
        goal = GOAL_SUBSET[4]
        cfg = BoundedSearchConfig(
            strategy="mcts",
            mcts_iterations=6,
            beam_width=2,
            branching=3,
            max_proposal_calls=32,
        )
        report = run_search(goal, cfg)
        assert report.strategy == "mcts"
        assert report.accounting.proposal_calls <= cfg.max_proposal_calls
        assert len(report.selected.steps) == goal.depth

    def test_mcts_uplift_is_non_negative_on_the_subset(self):
        cfg = BoundedSearchConfig(strategy="mcts", mcts_iterations=12, branching=5)
        value = uplift(GOAL_SUBSET, cfg, CALIBRATED_SCORER)
        assert value >= 0.0

    def test_ucb1_spreads_visits_beyond_greedy(self):
        """With a discriminating reward, selection must visit more than the single
        greedy arm: the exploration term is doing work."""
        goal = GOAL_SUBSET[0]
        cfg = BoundedSearchConfig(strategy="mcts", mcts_iterations=16, branching=5)
        ledger = _Ledger(cfg.max_proposal_calls)
        cache = _CandidateCache(goal, cfg, CALIBRATED_SCORER)
        proposer = FixtureProposer(goal, ledger, cfg)
        root = _MctsNode(())
        for _ in range(cfg.mcts_iterations):
            _mcts_iteration(root, goal, cfg, proposer, cache)
        assert len(root.children) >= 2, "UCB1 never expanded past one arm"
        visited_children = sum(1 for c in root.children.values() if c.visits > 0)
        assert visited_children >= 2


class TestOverfitting:
    """Evidence-of-overfitting measures: honest tuning transfers; leaked tuning inflates."""

    def test_honest_tuning_split_transfers_to_eval_split(self):
        # Interleave so both splits mix hard and moderate goals.
        tuning, evaluation = GOAL_SUBSET[::2], GOAL_SUBSET[1::2]
        chosen = tune_width_branch(tuning)
        tuning_uplift = uplift(tuning, chosen)
        eval_uplift = uplift(evaluation, chosen)
        # The transfer gap is bounded: no fixture-split lottery.
        assert abs(tuning_uplift - eval_uplift) <= 0.35
        assert eval_uplift > 0.0

    def test_leaked_per_goal_tuning_inflates_measured_uplift(self):
        evaluation = GOAL_SUBSET[1::2]
        honest = uplift(evaluation, tune_width_branch(GOAL_SUBSET[:5]))
        leaked = leaky_tuned_uplift(evaluation)
        assert leaked >= honest


class TestEvidenceOnlyContract:
    """The search must not become a second runtime — pinned structurally."""

    def test_machinery_imports_no_execution_or_persistence_authority(self):
        modules = _module_imports()
        offenders = [
            m
            for m in modules
            for prefix in FORBIDDEN_EXECUTION_IMPORT_PREFIXES
            if m == prefix or m.startswith(prefix + ".")
        ]
        assert offenders == []

    def test_selected_candidate_is_data_not_a_dispatch(self):
        goal = GOAL_SUBSET[0]
        report = run_search(goal, BoundedSearchConfig())
        selected = report.selected
        # A plan artifact: kinds, the canonical GraphConfig, a score — nothing
        # addressable as a Run/NodeRun/Attempt.
        assert isinstance(selected.steps, tuple)
        assert isinstance(selected.graph_config, GraphConfig)
        assert isinstance(selected.score, float)
        assert not hasattr(selected, "run_id")
        assert not hasattr(selected, "execute")
        assert not hasattr(report, "execute")

    def test_search_registers_no_node_and_needs_no_store(self):
        import maistro.graph.nodes as nodes_pkg

        before = set(nodes_pkg.list_kinds())
        run_search(GOAL_SUBSET[1], BoundedSearchConfig())
        run_search(GOAL_SUBSET[1], BoundedSearchConfig(strategy="mcts"))
        assert set(nodes_pkg.list_kinds()) == before
