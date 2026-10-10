"""M8-D3 research harness — observation-driven replanning after surprises.

Issue #927 (leaf of epic #903 M8-D, initiative #879). Hypothesis under study:
explicit replanning from current Run evidence after a tool failure, changed
state, or new constraint improves Goal completion versus blindly continuing an
original plan.

This module is a RESEARCH ARTIFACT, not product code. It implements the
measurement machinery the #927 benchmark procedure demands — a deterministic
task-graph world, the issue's six surprise injections (unavailable provider,
changed artifact, failed tool, denied capability, stale assumption, newly
satisfied subgoal), the three policies (no-replan, local repair, full replan),
and the issue's full measure list (goal recovery rate, duplicated work,
invalidated-work reuse, cost, latency, oscillation/replan loops, correctness
of preserved provenance) — so the real experiment is reproducible the moment a
corpus of representative Goal executions exists. The synthetic fixtures below
are deterministic, hand-checked validations of the accounting and the policy
mechanics; they are NOT experimental results and must never be quoted as
evidence about real MAIstro workloads.

Canonical seams this benchmark models (measurement only — nothing here reads
or writes them):

- Durable canonical execution ``Goal -> Graph -> Run -> NodeRun -> Attempt``
  lives in ``packages/maistro-core/src/maistro/graph/durable_runs/``; this
  harness models one sequential NodeRun spine over declared tasks. It is not
  an executor and never becomes a second execution authority.
- The no-replan policy is the canonical today-shape: attempt-in-place retry
  under a budget, mirroring ``execute_with_resilience`` (``graph/executor``,
  ``RetryBudget`` + ``ResiliencePolicyStore``) — the plan is never revised and
  the world is never re-observed.
- Steering in the shipped system is human guidance (``graph/steering.py``),
  not observation-driven replanning; no shipped seam re-synthesizes a Graph
  from Run evidence today. That absence is exactly what this leaf evaluates.
- Provenance mirrors the canonical rule that promotion must not retroactively
  falsify derivation (``graph/definitions.py``, ``TemplateProvenance`` /
  ``PROVENANCE_METADATA_KEY``): every produced output records the artifact
  versions it consumed, and a completion walk flags any shipped output whose
  recorded derivation no longer matches the world.
- Budgets fail loudly with the budget named rather than truncating silently,
  mirroring ``graph/policies.py`` (``resolve_max_cycles`` semantics): retry
  exhaustion, ``NoViablePlan``, ``ReplanBudgetExhausted``, and
  ``ReplanOscillationExhausted`` are recorded outcomes, never silent drops.

Accounting rules (stated because they decide every number):

- Every attempt pays its task's cost and duration in full, failed or not —
  sunk spend is never hidden. Each attempt is one world action; surprise
  deltas fire after N completed actions.
- A repair wait is also one world action: an explicit observation point that
  advances the clock (so a scheduled recovery can land) without executing a
  task, and it pays nothing.
- A blind attempt on a subgoal the world already satisfied is duplicated
  work, and every retry of that attempt is duplicated work too.
- Each replan pays the planner's cost and latency, failed replans included.
- Skips pay nothing; a task whose subgoal the world already satisfied and
  whose artifact is current is reused, not re-executed.
- Provider availability is judged at attempt time (outages are transient —
  the canonical retry budget is the right first response); tool health,
  capability grants, and plan assumptions are pre-checked before spend by
  observation-aware policies. The blind policy pre-checks nothing.
- Blind (no-replan) execution consumes the artifact version that is current
  at attempt time and never re-reads the world afterwards, so a later
  external revision can falsify its recorded derivation retroactively.
- An oscillation replan is one that re-derives the same plan structure as the
  previous plan; consecutive ones trip a loud loop guard.

Trust boundary (the epic contract, enforced by construction):

- Every number produced here is ADVISORY EVIDENCE. Nothing reads or writes a
  Goal, a Run authority, a NodeRun store, or a capability/Warden/HITL control.
  The module imports no maistro module at all, so it cannot become an
  authority by accident (M8 guardrails 1-2). Production adoption of any
  replanning policy found here routes to the canonical Goal/Graph owner per
  the epic exit — never through this harness.
- Capability denial is modeled as an authority decision: observation-aware
  policies never attempt a task whose capability grant is absent, and no
  policy may work a denial away by retrying. Blind re-attempts against a
  denial are counted (``denied_reattempts``) as a trust-boundary measure.
- Records are frozen: measurements cannot be mutated into authorization
  after the fact.

The experiment record and terminal disposition live in
``docs/research/927-observation-driven-replanning.md``.
"""

from __future__ import annotations

import ast
import dataclasses
import inspect
import sys
import types
from collections import Counter, deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum, auto

import pytest

#: Explicit evidence-only contract marker. Asserted by a test so it cannot
#: silently rot; nothing outside this module may treat M8-D3 output as
#: authorization. Execution authority remains the durable Goal/Graph/Run spine.
EVIDENCE_ONLY = True

#: Cost and latency of one planner invocation (one replan), in the same units
#: as task attempts. Every replan pays both; failed replans pay too (sunk).
PLANNER_COST_UNITS = 1
PLANNER_LATENCY_MS = 50


# ---------------------------------------------------------------------------
# Surprise taxonomy — the issue's six controlled injections
# ---------------------------------------------------------------------------


class SurpriseKind(StrEnum):
    """The six surprise classes the #927 experiment injects."""

    PROVIDER_UNAVAILABLE = auto()
    ARTIFACT_CHANGED = auto()
    TOOL_FAILED = auto()
    CAPABILITY_DENIED = auto()
    ASSUMPTION_INVALIDATED = auto()
    SUBGOAL_SATISFIED = auto()


@dataclass(frozen=True)
class ProviderAvailability:
    """PROVIDER_UNAVAILABLE: a required provider goes down (or recovers)."""

    at_action: int
    provider: str
    up: bool

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.PROVIDER_UNAVAILABLE


@dataclass(frozen=True)
class ArtifactRevised:
    """ARTIFACT_CHANGED: an artifact is externally revised to a new version."""

    at_action: int
    artifact: str
    new_version: int

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.ARTIFACT_CHANGED


@dataclass(frozen=True)
class ToolHealth:
    """TOOL_FAILED: a required tool becomes unhealthy (or heals)."""

    at_action: int
    tool: str
    healthy: bool

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.TOOL_FAILED


@dataclass(frozen=True)
class CapabilityGrant:
    """CAPABILITY_DENIED: an authority revokes (or restores) a capability."""

    at_action: int
    capability: str
    granted: bool

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.CAPABILITY_DENIED


@dataclass(frozen=True)
class AssumptionTruth:
    """ASSUMPTION_INVALIDATED: a plan assumption stops holding (or holds)."""

    at_action: int
    assumption: str
    holding: bool

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.ASSUMPTION_INVALIDATED


@dataclass(frozen=True)
class SubgoalEvent:
    """SUBGOAL_SATISFIED: the world completes a subgoal outside the Run.

    The externally produced artifact arrives at ``artifact_version``; an
    observation-aware policy may reuse it instead of duplicating the work.
    """

    at_action: int
    subgoal: str
    artifact: str
    artifact_version: int

    @property
    def kind(self) -> SurpriseKind:
        return SurpriseKind.SUBGOAL_SATISFIED


WorldDelta = (
    ProviderAvailability
    | ArtifactRevised
    | ToolHealth
    | CapabilityGrant
    | AssumptionTruth
    | SubgoalEvent
)


# ---------------------------------------------------------------------------
# World model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WorldObservation:
    """A frozen snapshot of the world a policy may re-observe."""

    providers_up: frozenset[str] = frozenset()
    tools_healthy: frozenset[str] = frozenset()
    granted_capabilities: frozenset[str] = frozenset()
    assumptions_holding: frozenset[str] = frozenset()
    satisfied_subgoals: frozenset[str] = frozenset()
    artifact_versions: Mapping[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # A frozen record must not expose a mutable mapping through the frozen
        # shell: wrap whatever the caller handed us (dict or proxy) in a
        # read-only proxy over a copy, so a scenario base cannot be revised
        # in place and skew later benchmark invocations.
        object.__setattr__(
            self, "artifact_versions", types.MappingProxyType(dict(self.artifact_versions))
        )


class World:
    """Deterministic world clock: deltas fire after N completed actions.

    An action is one task attempt (successful or failed). Observations are
    free and instantaneous — re-observing never advances the world. This is
    the injection surface for the issue's controlled surprises.
    """

    def __init__(self, base: WorldObservation, deltas: Sequence[WorldDelta]) -> None:
        for delta in deltas:
            if delta.at_action < 0:
                raise ValueError(f"delta at negative action: {delta!r}")
        self._providers = set(base.providers_up)
        self._tools = set(base.tools_healthy)
        self._capabilities = set(base.granted_capabilities)
        self._assumptions = set(base.assumptions_holding)
        self._satisfied = set(base.satisfied_subgoals)
        self._versions = dict(base.artifact_versions)
        self._external: dict[str, str] = {}
        self._pending = sorted(deltas, key=lambda d: d.at_action)
        self._fired = 0

    def apply_completed(self, completed_actions: int) -> None:
        """Fire every delta scheduled at or before ``completed_actions``."""
        while (
            self._fired < len(self._pending)
            and self._pending[self._fired].at_action <= completed_actions
        ):
            self._fire(self._pending[self._fired])
            self._fired += 1

    def _fire(self, delta: WorldDelta) -> None:
        """Apply one surprise to the world state."""
        if isinstance(delta, ProviderAvailability):
            self._mark(self._providers, delta.provider, delta.up)
        elif isinstance(delta, ToolHealth):
            self._mark(self._tools, delta.tool, delta.healthy)
        elif isinstance(delta, CapabilityGrant):
            self._mark(self._capabilities, delta.capability, delta.granted)
        elif isinstance(delta, AssumptionTruth):
            self._mark(self._assumptions, delta.assumption, delta.holding)
        elif isinstance(delta, ArtifactRevised):
            self._versions[delta.artifact] = delta.new_version
        else:
            self._satisfied.add(delta.subgoal)
            # The event's declared version always applies — a repeated
            # external completion re-versions an artifact the run (or an
            # earlier event) already produced; ``setdefault`` would hide the
            # external change from provenance and reuse accounting.
            self._versions[delta.artifact] = delta.artifact_version
            self._external[delta.subgoal] = delta.artifact

    @staticmethod
    def _mark(target: set[str], name: str, present: bool) -> None:
        if present:
            target.add(name)
        else:
            target.discard(name)

    def observe(self) -> WorldObservation:
        return WorldObservation(
            providers_up=frozenset(self._providers),
            tools_healthy=frozenset(self._tools),
            granted_capabilities=frozenset(self._capabilities),
            assumptions_holding=frozenset(self._assumptions),
            satisfied_subgoals=frozenset(self._satisfied),
            artifact_versions=types.MappingProxyType(dict(self._versions)),
        )

    def external_artifact(self, subgoal: str) -> str | None:
        """Name of the artifact an external subgoal event delivered."""
        return self._external.get(subgoal)

    def register_production(self, artifact: str, version: int) -> None:
        """Record a production: the emitted version is now current.

        An external revision fired by a later delta still wins, because the
        engine registers the production before the post-attempt world sync.
        """
        self._versions[artifact] = version


# ---------------------------------------------------------------------------
# Tasks, goal, outputs, provenance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    """One unit of canonical work (one NodeRun shape in the modeled spine).

    Requirements are checked against the current observation; ``alternates``
    are the substitute task ids a full replan may choose when the primary
    task's requirements cannot be met. Cost/latency are per attempt; failed
    attempts pay in full (sunk), mirroring honest accounting.
    """

    id: str
    satisfies_subgoal: str
    produces_artifact: str
    requires_provider: str | None = None
    requires_tool: str | None = None
    requires_capability: str | None = None
    requires_assumption: str | None = None
    reads_artifact: str | None = None
    alternates: tuple[str, ...] = ()
    cost_units: int = 1
    duration_ms: int = 100


@dataclass(frozen=True)
class Goal:
    """Terminal condition of the modeled Run: one required artifact."""

    artifact: str


@dataclass(frozen=True)
class OutputRecord:
    """Provenance record of one produced artifact version.

    ``derived_from`` maps each consumed artifact to the version that was
    read; ``required_assumption`` names the plan assumption the output
    depends on. The completion walk judges these against the live world —
    the canonical rule that derivation must not be retroactively falsified.
    """

    artifact: str
    emitted_version: int
    produced_by: str
    derived_from: Mapping[str, int] = field(default_factory=dict)
    required_assumption: str | None = None


@dataclass(frozen=True)
class Scenario:
    """A surprise injection schedule over a fixed base world."""

    name: str
    surprise_classes: tuple[SurpriseKind, ...]
    base: WorldObservation
    deltas: tuple[WorldDelta, ...]


class FailureKind(StrEnum):
    """Why a task could not proceed, named for the audit row."""

    MISSING_INPUT = auto()
    PROVIDER_UNAVAILABLE = auto()
    TOOL_FAILED = auto()
    CAPABILITY_DENIED = auto()
    ASSUMPTION_VIOLATED = auto()
    STALE_INPUT = auto()


@dataclass(frozen=True)
class GiveUp:
    """A loud terminal outcome with the reason named (never a silent drop)."""

    reason: str


@dataclass(frozen=True)
class _Check:
    """Outcome of one precondition check or attempt judgment."""

    failure: FailureKind | None = None
    stale_link: str | None = None


# ---------------------------------------------------------------------------
# Policy definitions
# ---------------------------------------------------------------------------


class Policy(StrEnum):
    """The three policies the #927 experiment compares."""

    NO_REPLAN = auto()
    LOCAL_REPAIR = auto()
    FULL_REPLAN = auto()


#: Retry budget per node for every policy — the canonical in-place retry shape
#: (initial attempt + ``RETRY_BUDGET`` retries) before repair/replan triggers.
RETRY_BUDGET = 1

#: Requeue passes local repair may spend per invalidated producer when the
#: world keeps moving; beyond that the repair is declared exhausted.
MAX_REQUEUE_PASSES = 2

#: Consecutive oscillating replans (same structure) before the replan loop
#: guard stops a policy loudly with the budget named.
MAX_CONSECUTIVE_OSCILLATIONS = 10


# ---------------------------------------------------------------------------
# Provenance walk and deterministic planner (used by FULL_REPLAN)
# ---------------------------------------------------------------------------


def chain_violations(
    record: OutputRecord,
    outputs: Mapping[str, OutputRecord],
    world_versions: Mapping[str, int],
    obs: WorldObservation,
    *,
    stop_at_first: bool = False,
) -> tuple[str, ...]:
    """Walk a derivation chain and name every retroactively falsified edge.

    A violation is a consumed artifact version no longer current, an emitted
    version superseded by an external revision, or a required plan assumption
    that no longer holds. This is the issue's provenance-correctness measure.
    """
    violations: list[str] = []
    seen: set[str] = set()
    stack = [record]
    while stack:
        node = stack.pop()
        if node.artifact in seen:
            continue
        seen.add(node.artifact)
        if node.emitted_version != world_versions.get(node.artifact):
            violations.append(
                f"{node.artifact}: emitted v{node.emitted_version},"
                f" world has v{world_versions.get(node.artifact)}"
            )
        if (
            node.required_assumption is not None
            and node.required_assumption not in obs.assumptions_holding
        ):
            violations.append(
                f"{node.artifact}: assumption {node.required_assumption!r} no longer holds"
            )
        for consumed, version in node.derived_from.items():
            if world_versions.get(consumed) != version:
                violations.append(
                    f"{node.artifact}: consumed {consumed}@v{version},"
                    f" world has v{world_versions.get(consumed)}"
                )
            consumed_record = outputs.get(consumed)
            if consumed_record is not None:
                stack.append(consumed_record)
        if stop_at_first and violations:
            return tuple(violations)
    return tuple(violations)


def _requirements_violated(
    task: Task,
    obs: WorldObservation,
    *,
    provider: bool,
    assumption: bool,
) -> FailureKind | None:
    """Resource requirements of ``task`` judged against ``obs``.

    ``provider`` selects whether provider availability participates: the
    pre-check excludes it (outages are transient; the retry budget is the
    right first response), while attempt-time judgment includes it.
    ``assumption`` selects plan assumptions: the blind policy never judges
    them — executing through a false assumption is the integrity hazard this
    benchmark exists to expose.
    """
    if (
        provider
        and task.requires_provider is not None
        and task.requires_provider not in obs.providers_up
    ):
        return FailureKind.PROVIDER_UNAVAILABLE
    if task.requires_tool is not None and task.requires_tool not in obs.tools_healthy:
        return FailureKind.TOOL_FAILED
    if (
        task.requires_capability is not None
        and task.requires_capability not in obs.granted_capabilities
    ):
        return FailureKind.CAPABILITY_DENIED
    if (
        assumption
        and task.requires_assumption is not None
        and task.requires_assumption not in obs.assumptions_holding
    ):
        return FailureKind.ASSUMPTION_VIOLATED
    return None


def _output_current(
    artifact: str,
    outputs: Mapping[str, OutputRecord],
    world_versions: Mapping[str, int],
    obs: WorldObservation,
) -> bool:
    """Whether a cached output exists and its derivation still holds."""
    record = outputs.get(artifact)
    if record is None:
        return False
    if record.emitted_version != world_versions.get(artifact):
        return False
    return not chain_violations(record, outputs, world_versions, obs, stop_at_first=True)


def _first_viable_producer(
    artifact: str,
    obs: WorldObservation,
    catalog: Sequence[Task],
    outputs: Mapping[str, OutputRecord],
    world_versions: Mapping[str, int],
    resolve,
    by_id: Mapping[str, Task],
) -> Task | None:
    """First viable producer of ``artifact`` under ``obs``, via declared alternates.

    The preferred producer is the first catalog task that produces the
    artifact; fallbacks are exactly the substitute ids it declares in
    ``alternates``. Tasks that merely share the output artifact but were
    never declared are not considered, so a replan cannot credit an
    undeclared structural recovery. A subgoal claimed satisfied externally
    without a current artifact cannot have its producer skipped. Input
    artifacts recurse through ``resolve``.
    """
    producers = [t for t in catalog if t.produces_artifact == artifact]
    if not producers:
        return None
    candidates = (producers[0], *(by_id[alt] for alt in producers[0].alternates))
    for task in candidates:
        # Mirrors the engine's redundant-work check: skip an externally
        # satisfied subgoal only when its artifact is current. A stale
        # artifact must fall through so the producer re-derives it —
        # ``resolve`` only reaches producer lookup for non-current
        # artifacts, which is exactly when regeneration is required.
        if task.satisfies_subgoal in obs.satisfied_subgoals and _output_current(
            task.produces_artifact, outputs, world_versions, obs
        ):
            continue
        if _requirements_violated(task, obs, provider=True, assumption=True) is not None:
            continue
        if task.reads_artifact is not None and not resolve(task.reads_artifact):
            continue
        return task
    return None


def _validate_alternates(catalog: Sequence[Task], by_id: Mapping[str, Task]) -> None:
    """Reject catalogs whose declared alternates do not name a same-artifact
    producer: a fallback that produces something else would fabricate a plan
    that never satisfies the goal."""
    for task in catalog:
        for alt in task.alternates:
            alternate = by_id.get(alt)
            if alternate is None:
                raise ValueError(f"task {task.id!r} names unknown alternate {alt!r}")
            if alternate.produces_artifact != task.produces_artifact:
                raise ValueError(
                    f"task {task.id!r} names alternate {alt!r} producing "
                    f"{alternate.produces_artifact!r}, not {task.produces_artifact!r}"
                )


def synthesize_plan(
    goal: Goal,
    obs: WorldObservation,
    catalog: Sequence[Task],
    outputs: Mapping[str, OutputRecord],
    world_versions: Mapping[str, int],
) -> tuple[Task, ...] | None:
    """Deterministically re-derive a plan for ``goal`` from the observation.

    Prefers the primary producer over its declared alternates (catalog
    order), skips tasks
    whose subgoal is already satisfied with a current artifact, and treats
    stale cached outputs as absent so invalidated work is re-derived. Returns
    ``None`` when no viable derivation exists — a loud NoViablePlan outcome,
    never a fabricated plan.
    """
    by_id = {t.id: t for t in catalog}
    if len(by_id) != len(catalog):
        raise ValueError("duplicate task ids in catalog")
    _validate_alternates(catalog, by_id)
    plan: list[Task] = []
    resolved: set[str] = set()
    in_progress: set[str] = set()

    def resolve(artifact: str) -> bool:
        if artifact in resolved:
            return True
        if artifact in in_progress:
            raise ValueError(f"cycle resolving artifact {artifact!r}")
        in_progress.add(artifact)
        try:
            if _output_current(artifact, outputs, world_versions, obs):
                resolved.add(artifact)
                return True
            producer = _first_viable_producer(
                artifact, obs, catalog, outputs, world_versions, resolve, by_id
            )
            if producer is None:
                return False
            plan.append(producer)
            resolved.add(artifact)
            return True
        finally:
            in_progress.discard(artifact)

    return tuple(plan) if resolve(goal.artifact) else None


# ---------------------------------------------------------------------------
# Engine — one sequential NodeRun spine under a policy
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExecutedTask:
    """Audit row for one task pass (execution, failure, or skip)."""

    task_id: str
    attempts: int
    ok: bool
    failure: FailureKind | None
    duplicated: bool


@dataclass(frozen=True)
class PolicyMeasurement:
    """Frozen per-(policy, scenario) measurement — one benchmark row."""

    policy: Policy
    scenario: str
    surprise_classes: tuple[SurpriseKind, ...]
    completed: bool
    recovered: bool
    provenance_violations: tuple[str, ...]
    duplicated_work_units: int
    reuse_units: int
    total_cost_units: int
    total_latency_ms: int
    attempts: int
    replans: int
    oscillation_replans: int
    denied_reattempts: int
    gave_up: GiveUp | None


def _precheck(
    task: Task,
    obs: WorldObservation,
    outputs: Mapping[str, OutputRecord],
    world_versions: Mapping[str, int],
) -> _Check:
    """Observation-aware precondition check (skipped entirely by NO_REPLAN).

    Provider availability is deliberately absent: outages are transient and
    the canonical retry budget is the right first response, so a provider
    surprise surfaces at attempt time where the budget lives.
    """
    violated = _requirements_violated(task, obs, provider=False, assumption=True)
    if violated is not None:
        return _Check(violated)
    if task.reads_artifact is not None:
        record = outputs.get(task.reads_artifact)
        if record is None:
            return _Check(FailureKind.MISSING_INPUT)
        if chain_violations(record, outputs, world_versions, obs, stop_at_first=True):
            return _Check(FailureKind.STALE_INPUT, stale_link=task.reads_artifact)
    return _Check()


def _attempt_judgment(
    task: Task,
    obs: WorldObservation,
    outputs: Mapping[str, OutputRecord],
    *,
    observation_aware: bool,
) -> _Check:
    """Judge one attempt against the world.

    The blind policy never judges plan assumptions (it executes through them
    — the integrity hazard this benchmark exists to expose) and never sees
    stale derivation chains (it consumes whatever version is current).
    """
    violated = _requirements_violated(task, obs, provider=True, assumption=observation_aware)
    if violated is not None:
        return _Check(violated)
    if task.reads_artifact is not None and task.reads_artifact not in outputs:
        return _Check(FailureKind.MISSING_INPUT)
    return _Check()


class _Action(StrEnum):
    """Outcome of one task pass for the engine's control flow."""

    NEXT = auto()
    RESTART = auto()


class _SpineEngine:
    """One sequential NodeRun spine executing a policy over a scenario.

    The three policies share this spine and differ only at the four decision
    points: the redundant-subgoal check, the precondition check, the attempt
    loop's transient judgment, and the repair/replan trigger after exhaustion.
    NO_REPLAN is blind at all four (it only ever retries in place); LOCAL_REPAIR
    re-observes and patches in place; FULL_REPLAN re-derives the remaining plan.
    """

    def __init__(
        self,
        policy: Policy,
        scenario: Scenario,
        goal: Goal,
        catalog: Sequence[Task],
        *,
        retry_budget: int,
        max_replans: int | None,
        max_consecutive_oscillations: int,
        planner_cost: int,
        planner_latency_ms: int,
        max_requeue_passes: int,
    ) -> None:
        self.policy = policy
        self.scenario_name = scenario.name
        self.surprise_classes = scenario.surprise_classes
        self.goal = goal
        self.catalog = catalog
        self.by_id = {t.id: t for t in catalog}
        self.observation_aware = policy is not Policy.NO_REPLAN
        self.retry_budget = retry_budget
        self.max_replans = max_replans
        self.max_consecutive_oscillations = max_consecutive_oscillations
        self.planner_cost = planner_cost
        self.planner_latency_ms = planner_latency_ms
        self.max_requeue_passes = max_requeue_passes
        self.world = World(scenario.base, scenario.deltas)
        self.outputs: dict[str, OutputRecord] = {}
        self.sync(0)  # fire any at_action == 0 deltas before initial planning
        self.attempts = 0
        self.clock = 0  # world-action clock: attempts + observation waits
        self.cost = 0
        self.latency = 0
        self.replans = 0
        self.oscillation_replans = 0
        self.consecutive_oscillations = 0
        self.denied_reattempts = 0
        self.duplicated = 0
        self.reuse = 0
        self.executed: list[ExecutedTask] = []
        self.requeue_passes: Counter[str] = Counter()
        self.gave_up: GiveUp | None = None
        self.last_retry_exhaustion: GiveUp | None = None
        self.last_plan_ids: tuple[str, ...] | None = None
        self.next_plan: list[Task] = []

    # -- world interaction ------------------------------------------------

    def sync(self, completed_actions: int) -> None:
        """Fire due deltas and refresh the observation snapshot."""
        self.world.apply_completed(completed_actions)
        self.state = self.world.observe()

    def inject_external(self) -> None:
        """Materialize externally delivered artifacts into the output cache.

        Only observation-aware policies ever look at the cache; the blind
        policy re-derives everything itself and never notices the delivery.
        """
        for subgoal in self.state.satisfied_subgoals:
            artifact_name = self.world.external_artifact(subgoal)
            if artifact_name is None or artifact_name in self.outputs:
                continue
            version = self.state.artifact_versions.get(artifact_name)
            if version is not None:
                self.outputs[artifact_name] = OutputRecord(
                    artifact=artifact_name,
                    emitted_version=version,
                    produced_by="external",
                )

    def record_output(self, task: Task) -> None:
        """Emit the task's output from the versions current right now.

        Called BEFORE the post-attempt world sync, so an external revision
        landing on the same action supersedes the fresh output — the world
        wins, and the stale chain is detected downstream.
        """
        derived: dict[str, int] = {}
        if task.reads_artifact is not None:
            consumed = self.state.artifact_versions.get(task.reads_artifact)
            if consumed is None or task.reads_artifact not in self.outputs:
                raise ValueError(f"attempt succeeded but input {task.reads_artifact!r} missing")
            derived[task.reads_artifact] = consumed
        existing = self.outputs.get(task.produces_artifact)
        emitted = 1 if existing is None else existing.emitted_version + 1
        self.outputs[task.produces_artifact] = OutputRecord(
            artifact=task.produces_artifact,
            emitted_version=emitted,
            produced_by=task.id,
            derived_from=derived,
            required_assumption=task.requires_assumption,
        )
        self.world.register_production(task.produces_artifact, emitted)

    # -- triggers -----------------------------------------------------------

    def _audit(self, audit: ExecutedTask | None) -> None:
        if audit is not None:
            self.executed.append(audit)

    def full_replan(self, audit: ExecutedTask | None) -> None:
        """Trigger one full replan (budgeted, loop-guarded)."""
        if self.max_replans is not None and self.replans >= self.max_replans:
            self.gave_up = GiveUp("replan-budget-exhausted")
            self._audit(audit)
            return
        new_plan = synthesize_plan(
            self.goal, self.state, self.catalog, self.outputs, self.state.artifact_versions
        )
        self.replans += 1
        self.cost += self.planner_cost
        self.latency += self.planner_latency_ms
        if new_plan is None:
            self.gave_up = GiveUp("no-viable-plan")
            self._audit(audit)
            return
        ids = tuple(t.id for t in new_plan)
        if ids == self.last_plan_ids:
            self.oscillation_replans += 1
            self.consecutive_oscillations += 1
            if self.consecutive_oscillations >= self.max_consecutive_oscillations:
                self.gave_up = GiveUp("replan-oscillation-exhausted")
                self._audit(audit)
                return
        else:
            self.consecutive_oscillations = 0
        self.last_plan_ids = ids
        self._audit(audit)
        self.next_plan.extend(new_plan)

    # -- task-pass phases ---------------------------------------------------

    def _redundant(self, task: Task) -> _Action | None:
        """Redundant-subgoal check (observation-aware policies only): the
        world satisfied this subgoal and a current artifact exists."""
        if not self.observation_aware:
            return None
        current = (
            task.satisfies_subgoal in self.state.satisfied_subgoals
            and task.produces_artifact in self.outputs
            and self.outputs[task.produces_artifact].emitted_version
            == self.state.artifact_versions.get(task.produces_artifact)
        )
        if not current:
            return None
        self.reuse += 1
        if self.policy is Policy.FULL_REPLAN:
            self.full_replan(ExecutedTask(task.id, 0, True, None, False))
            return _Action.RESTART
        self.executed.append(ExecutedTask(task.id, 0, True, None, False))
        return _Action.NEXT

    def _stale(self, task: Task, queue: deque[Task], pre: _Check) -> _Action:
        """Observation-driven response to invalidated work: full replan
        re-synthesizes; local repair re-derives exactly the invalidated
        producer, and the consumer re-checks right after it."""
        assert pre.stale_link is not None
        stale_record = self.outputs[pre.stale_link]
        if self.policy is Policy.FULL_REPLAN:
            self.full_replan(None)
            return _Action.RESTART
        producer_id = stale_record.produced_by
        producer = self.by_id.get(producer_id)
        if producer is None or self.requeue_passes[producer_id] >= self.max_requeue_passes:
            self.gave_up = GiveUp(f"local-repair-exhausted:{pre.failure.value}")
            return _Action.RESTART
        self.requeue_passes[producer_id] += 1
        queue.appendleft(task)
        queue.appendleft(producer)
        return _Action.NEXT

    def _precondition_phase(
        self, task: Task, queue: deque[Task], pre: _Check, failure_obs: WorldObservation
    ) -> _Action:
        if pre.failure is FailureKind.STALE_INPUT:
            return self._stale(task, queue, pre)
        if pre.failure is FailureKind.MISSING_INPUT:
            self.gave_up = GiveUp(f"missing-input:{task.reads_artifact}")
            return _Action.RESTART
        if pre.failure is FailureKind.CAPABILITY_DENIED:
            # Denial is an authority decision: never re-attempted, never
            # retried into submission. Full replan may still look for a
            # differently-authorized path.
            self.executed.append(ExecutedTask(task.id, 0, False, pre.failure, False))
            if self.policy is Policy.FULL_REPLAN:
                self.full_replan(None)
            else:
                self.gave_up = GiveUp("capability-denied")
            return _Action.RESTART
        # Tool / assumption: spend one wait action — an explicit observation
        # point that advances the world clock without executing the task — so
        # a transient failure's scheduled recovery can land, then requeue only
        # if the observation changed since this pass began; otherwise give up
        # — or, for full replan, re-derive the remaining plan.
        if self.requeue_passes[task.id] < self.max_requeue_passes:
            self.clock += 1
            self.sync(self.clock)
            if self.state != failure_obs:
                self.requeue_passes[task.id] += 1
                queue.appendleft(task)
                return _Action.NEXT
        self.executed.append(ExecutedTask(task.id, 0, False, pre.failure, False))
        if self.policy is Policy.FULL_REPLAN:
            self.full_replan(None)
            return _Action.RESTART
        self.gave_up = GiveUp(f"local-repair-exhausted:{pre.failure.value}")
        return _Action.RESTART

    def _attempt_phase(
        self, task: Task, blind_duplicate: bool
    ) -> tuple[bool, int, FailureKind | None]:
        """Attempt loop: initial attempt + in-place retries. Every attempt
        pays full cost/latency whether it succeeds or not (sunk spend), and
        a blind duplicate is counted per attempt, not per pass."""
        task_attempts = 0
        outcome = _Check()
        for _ in range(self.retry_budget + 1):
            outcome = _attempt_judgment(
                task, self.state, self.outputs, observation_aware=self.observation_aware
            )
            self.attempts += 1
            self.clock += 1
            task_attempts += 1
            if blind_duplicate:
                self.duplicated += 1  # every retry of satisfied work duplicates too
            self.cost += task.cost_units
            self.latency += task.duration_ms
            if outcome.failure is None:
                self.record_output(task)
                self.sync(self.clock)
                self.executed.append(
                    ExecutedTask(task.id, task_attempts, True, None, blind_duplicate)
                )
                return True, task_attempts, None
            if outcome.failure is FailureKind.CAPABILITY_DENIED and task_attempts > 1:
                self.denied_reattempts += 1
            self.sync(self.clock)
        return False, task_attempts, outcome.failure

    def _exhausted(
        self,
        task: Task,
        queue: deque[Task],
        last_failure: FailureKind,
        failure_obs: WorldObservation,
        task_attempts: int,
        blind_duplicate: bool,
    ) -> _Action:
        """Repair/replan trigger after attempt exhaustion."""
        audit = ExecutedTask(task.id, task_attempts, False, last_failure, blind_duplicate)
        if self.policy is Policy.NO_REPLAN:
            self.executed.append(audit)
            # The blind policy never revises its plan, so the spine keeps
            # walking; carry the exhaustion so the measurement can name the
            # budget that blocked the goal instead of dropping it silently.
            self.last_retry_exhaustion = GiveUp(f"retry-budget-exhausted:{last_failure.value}")
            return _Action.NEXT
        if self.policy is Policy.LOCAL_REPAIR:
            if last_failure is FailureKind.CAPABILITY_DENIED:
                self.executed.append(audit)
                self.gave_up = GiveUp("capability-denied")
                return _Action.RESTART
            if self.state != failure_obs and self.requeue_passes[task.id] < self.max_requeue_passes:
                self.requeue_passes[task.id] += 1
                queue.appendleft(task)
                return _Action.NEXT
            self.executed.append(audit)
            self.gave_up = GiveUp(f"local-repair-exhausted:{last_failure.value}")
            return _Action.RESTART
        self.full_replan(audit)
        return _Action.RESTART

    def _task_pass(self, task: Task, queue: deque[Task]) -> _Action:
        """Run one pass of one task under the policy."""
        failure_obs = self.state  # snapshot at this pass's start
        if self.observation_aware:
            self.inject_external()
        redundant = self._redundant(task)
        if redundant is not None:
            return redundant
        pre = (
            _precheck(task, self.state, self.outputs, self.state.artifact_versions)
            if self.observation_aware
            else _Check()
        )
        if pre.failure is not None:
            return self._precondition_phase(task, queue, pre, failure_obs)
        # The blind policy cannot see that the world already satisfied this
        # task's subgoal, so its execution here is duplicated work.
        blind_duplicate = (
            not self.observation_aware and task.satisfies_subgoal in self.state.satisfied_subgoals
        )
        ok, task_attempts, last_failure = self._attempt_phase(task, blind_duplicate)
        if ok:
            return _Action.NEXT
        return self._exhausted(
            task, queue, last_failure, failure_obs, task_attempts, blind_duplicate
        )

    # -- top level -----------------------------------------------------------

    def run(self) -> PolicyMeasurement:
        """Execute the spine to completion and return the frozen row."""
        plan = synthesize_plan(
            self.goal, self.state, self.catalog, self.outputs, self.state.artifact_versions
        )
        if plan is None:
            self.gave_up = GiveUp("no-viable-plan")
            plan = ()
        self.last_plan_ids = tuple(t.id for t in plan) if plan else None
        while (plan or self.next_plan) and self.gave_up is None:
            queue: deque[Task] = deque(plan)
            plan = ()
            while queue and self.gave_up is None:
                if self._task_pass(queue.popleft(), queue) is _Action.RESTART:
                    break
            if self.next_plan and self.gave_up is None:
                plan = tuple(self.next_plan)
                self.next_plan.clear()
        return self._final_measurement()

    def _final_measurement(self) -> PolicyMeasurement:
        self.world.apply_completed(self.clock)
        final_state = self.world.observe()
        goal_record = self.outputs.get(self.goal.artifact)
        violations: tuple[str, ...] = ()
        completed = False
        if goal_record is not None and self.gave_up is None:
            completed = True
            violations = chain_violations(
                goal_record, self.outputs, final_state.artifact_versions, final_state
            )
        gave_up = self.gave_up
        if not completed and gave_up is None and self.last_retry_exhaustion is not None:
            gave_up = self.last_retry_exhaustion
        return PolicyMeasurement(
            policy=self.policy,
            scenario=self.scenario_name,
            surprise_classes=self.surprise_classes,
            completed=completed,
            recovered=completed and not violations,
            provenance_violations=violations,
            duplicated_work_units=self.duplicated,
            reuse_units=self.reuse,
            total_cost_units=self.cost,
            total_latency_ms=self.latency,
            attempts=self.attempts,
            replans=self.replans,
            oscillation_replans=self.oscillation_replans,
            denied_reattempts=self.denied_reattempts,
            gave_up=gave_up,
        )


def measure(
    policy: Policy,
    scenario: Scenario,
    goal: Goal,
    catalog: Sequence[Task],
    *,
    retry_budget: int = RETRY_BUDGET,
    max_replans: int | None = None,
    max_consecutive_oscillations: int = MAX_CONSECUTIVE_OSCILLATIONS,
    planner_cost: int = PLANNER_COST_UNITS,
    planner_latency_ms: int = PLANNER_LATENCY_MS,
    max_requeue_passes: int = MAX_REQUEUE_PASSES,
) -> PolicyMeasurement:
    """Execute ``scenario`` under ``policy`` and return the frozen row."""
    if not catalog:
        raise ValueError("empty task catalog")
    if retry_budget < 0:
        raise ValueError("retry budget must be >= 0")
    if max_replans is not None and max_replans < 0:
        raise ValueError("replan budget must be >= 0")
    if max_requeue_passes < 0:
        raise ValueError("requeue budget must be >= 0")
    if max_consecutive_oscillations < 0:
        raise ValueError("oscillation budget must be >= 0")
    by_id = {t.id: t for t in catalog}
    if len(by_id) != len(catalog):
        raise ValueError("duplicate task ids in catalog")
    for task in catalog:
        for alt in task.alternates:
            if alt not in by_id:
                raise ValueError(f"task {task.id!r} names unknown alternate {alt!r}")
    engine = _SpineEngine(
        policy,
        scenario,
        goal,
        catalog,
        retry_budget=retry_budget,
        max_replans=max_replans,
        max_consecutive_oscillations=max_consecutive_oscillations,
        planner_cost=planner_cost,
        planner_latency_ms=planner_latency_ms,
        max_requeue_passes=max_requeue_passes,
    )
    return engine.run()


# ---------------------------------------------------------------------------
# Aggregation and dominance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyAggregate:
    """Per-policy roll-up over a scenario suite."""

    policy: Policy
    scenarios: int
    recovered: int
    clean_recovered: int
    dirty_completions: int
    total_cost_units: int
    total_latency_ms: int
    total_attempts: int
    total_replans: int
    total_oscillation_replans: int
    total_duplicated_work: int
    total_reuse: int
    total_denied_reattempts: int

    @property
    def recovery_rate(self) -> float:
        return self.recovered / self.scenarios

    @property
    def clean_recovery_rate(self) -> float:
        return self.clean_recovered / self.scenarios


def aggregate(rows: Sequence[PolicyMeasurement]) -> tuple[PolicyAggregate, ...]:
    """Roll rows up per policy; first-seen policy order preserved."""
    order: list[Policy] = []
    grouped: dict[Policy, list[PolicyMeasurement]] = {}
    for row in rows:
        if row.policy not in grouped:
            order.append(row.policy)
            grouped[row.policy] = []
        grouped[row.policy].append(row)
    aggs: list[PolicyAggregate] = []
    for policy in order:
        rs = grouped[policy]
        aggs.append(
            PolicyAggregate(
                policy=policy,
                scenarios=len(rs),
                recovered=sum(r.recovered for r in rs),
                clean_recovered=sum(r.recovered and not r.provenance_violations for r in rs),
                dirty_completions=sum(r.completed and bool(r.provenance_violations) for r in rs),
                total_cost_units=sum(r.total_cost_units for r in rs),
                total_latency_ms=sum(r.total_latency_ms for r in rs),
                total_attempts=sum(r.attempts for r in rs),
                total_replans=sum(r.replans for r in rs),
                total_oscillation_replans=sum(r.oscillation_replans for r in rs),
                total_duplicated_work=sum(r.duplicated_work_units for r in rs),
                total_reuse=sum(r.reuse_units for r in rs),
                total_denied_reattempts=sum(r.denied_reattempts for r in rs),
            )
        )
    return tuple(aggs)


def dominates(a: PolicyAggregate, b: PolicyAggregate) -> bool:
    """Whether policy ``a`` dominates ``b`` on the fixture suite.

    Dominance requires at least as many clean recoveries, no more cost, and
    at least one strict advantage. Provenance-clean recovery is the value
    axis — a dirty completion is not a recovery for this purpose.
    """
    at_least = a.clean_recovered >= b.clean_recovered and a.total_cost_units <= b.total_cost_units
    strict = a.clean_recovered > b.clean_recovered or a.total_cost_units < b.total_cost_units
    return at_least and strict


# ---------------------------------------------------------------------------
# Shared fixture: base world, catalog, goal
# ---------------------------------------------------------------------------

BASE_OBS = WorldObservation(
    providers_up=frozenset({"llm-a"}),
    tools_healthy=frozenset({"tool-x", "tool-y"}),
    granted_capabilities=frozenset({"cap-net", "cap-batch"}),
    assumptions_holding=frozenset({"schema-v2"}),
)

T_DRAFT = Task(
    id="draft",
    satisfies_subgoal="draft",
    produces_artifact="draft",
    requires_provider="llm-a",
    cost_units=2,
    duration_ms=100,
)
T_REVIEW = Task(
    id="review",
    satisfies_subgoal="review",
    produces_artifact="review",
    requires_provider="llm-a",
    requires_assumption="schema-v2",
    reads_artifact="draft",
    alternates=("review-manual",),
    cost_units=2,
    duration_ms=100,
)
T_REVIEW_MANUAL = Task(
    id="review-manual",
    satisfies_subgoal="review",
    produces_artifact="review",
    requires_tool="tool-y",
    reads_artifact="draft",
    cost_units=3,
    duration_ms=150,
)
T_PUBLISH = Task(
    id="publish",
    satisfies_subgoal="publish",
    produces_artifact="final",
    requires_tool="tool-x",
    requires_capability="cap-net",
    reads_artifact="review",
    alternates=("publish-batch",),
    cost_units=2,
    duration_ms=100,
)
T_PUBLISH_BATCH = Task(
    id="publish-batch",
    satisfies_subgoal="publish",
    produces_artifact="final",
    requires_tool="tool-y",
    requires_capability="cap-batch",
    reads_artifact="review",
    cost_units=3,
    duration_ms=150,
)

CATALOG = (T_DRAFT, T_REVIEW, T_REVIEW_MANUAL, T_PUBLISH, T_PUBLISH_BATCH)
GOAL = Goal(artifact="final")
POLICIES = (Policy.NO_REPLAN, Policy.LOCAL_REPAIR, Policy.FULL_REPLAN)


def _scenario(name: str, classes: tuple[SurpriseKind, ...], *deltas: WorldDelta) -> Scenario:
    return Scenario(name=name, surprise_classes=classes, base=BASE_OBS, deltas=deltas)


#: A — provider outage mid-Run, transient (recovers after action 3).
SCN_PROVIDER = _scenario(
    "provider-outage",
    (SurpriseKind.PROVIDER_UNAVAILABLE,),
    ProviderAvailability(1, "llm-a", up=False),
    ProviderAvailability(3, "llm-a", up=True),
)
#: B — the draft artifact is externally revised after review consumed it.
SCN_ARTIFACT = _scenario(
    "artifact-changed",
    (SurpriseKind.ARTIFACT_CHANGED,),
    ArtifactRevised(2, "draft", 2),
)
#: C — the publish tool fails permanently; the batch alternate is viable.
SCN_TOOL = _scenario(
    "tool-failed",
    (SurpriseKind.TOOL_FAILED,),
    ToolHealth(2, "tool-x", healthy=False),
)
#: C2 — the world violates a requirement before the Run even starts (the
#: delta is scheduled at action 0): initial planning must see it, so an
#: observation-aware policy refuses to spend instead of recovering cleanly
#: from a surprise that already happened. One-task catalog, one artifact.
SCN_SOLO_TOOL_DOWN = _scenario(
    "tool-down-at-start",
    (SurpriseKind.TOOL_FAILED,),
    ToolHealth(0, "tool-x", healthy=False),
)
#: H — the publish tool is already down when publish's pass begins and
#: recovers mid-Run (precheck-time transient; only reachable through the
#: precondition phase's wait-and-observe requeue).
SCN_TOOL_TRANSIENT = _scenario(
    "tool-transient",
    (SurpriseKind.TOOL_FAILED,),
    ToolHealth(1, "tool-x", healthy=False),
    ToolHealth(3, "tool-x", healthy=True),
)
#: D — the capability family is revoked; no alternate is grantable.
SCN_CAPABILITY = _scenario(
    "capability-denied",
    (SurpriseKind.CAPABILITY_DENIED,),
    CapabilityGrant(2, "cap-net", granted=False),
    CapabilityGrant(2, "cap-batch", granted=False),
)
#: E — the review assumption is invalidated; a manual alternate exists.
SCN_ASSUMPTION = _scenario(
    "assumption-invalidated",
    (SurpriseKind.ASSUMPTION_INVALIDATED,),
    AssumptionTruth(1, "schema-v2", holding=False),
)
#: F — the world satisfies the review subgoal outside the Run.
SCN_SUBGOAL = _scenario(
    "subgoal-satisfied",
    (SurpriseKind.SUBGOAL_SATISFIED,),
    SubgoalEvent(1, "review", "review", 1),
)
#: F2 — the review subgoal is satisfied outside the Run while the provider
#: review needs is down: the blind policy burns its full retry budget on the
#: already-satisfied subgoal, so duplicated work must count per attempt, not
#: per pass.
SCN_SUBGOAL_OUTAGE = _scenario(
    "subgoal-satisfied-provider-outage",
    (SurpriseKind.SUBGOAL_SATISFIED, SurpriseKind.PROVIDER_UNAVAILABLE),
    SubgoalEvent(1, "review", "review", 1),
    ProviderAvailability(1, "llm-a", up=False),
    ProviderAvailability(4, "llm-a", up=True),
)
#: G — hot world: the draft artifact is revised after every action.
SCN_HOT_WORLD = _scenario(
    "hot-world",
    (SurpriseKind.ARTIFACT_CHANGED,),
    ArtifactRevised(1, "draft", 2),
    ArtifactRevised(2, "draft", 3),
    ArtifactRevised(3, "draft", 4),
    ArtifactRevised(4, "draft", 5),
    ArtifactRevised(5, "draft", 6),
)

CORE_SCENARIOS = (
    SCN_PROVIDER,
    SCN_ARTIFACT,
    SCN_TOOL,
    SCN_CAPABILITY,
    SCN_ASSUMPTION,
    SCN_SUBGOAL,
)


def run_benchmark() -> tuple[tuple[PolicyMeasurement, ...], tuple[PolicyAggregate, ...]]:
    """The core 6-surprise x 3-policy fixture benchmark (deterministic)."""
    rows = tuple(
        measure(policy, scenario, GOAL, CATALOG)
        for scenario in CORE_SCENARIOS
        for policy in POLICIES
    )
    return rows, aggregate(rows)


# ---------------------------------------------------------------------------
# Contract tests: evidence-only, frozen records, no maistro imports
# ---------------------------------------------------------------------------


def test_advisory_only_marker_is_true() -> None:
    assert EVIDENCE_ONLY is True


def test_records_are_frozen() -> None:
    for record in (
        PolicyMeasurement,
        PolicyAggregate,
        ExecutedTask,
        OutputRecord,
        Scenario,
        Task,
        Goal,
    ):
        assert record.__dataclass_params__.frozen  # type: ignore[attr-defined]
        for verb in ("apply", "execute", "route", "authorize", "replan"):
            assert not callable(getattr(record, verb, None))


def test_outputs_are_measurements_not_actions() -> None:
    row = measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, CATALOG)
    assert isinstance(row, PolicyMeasurement)
    assert row.gave_up is None or isinstance(row.gave_up, GiveUp)


def _maistro_import_roots(source: str) -> set[str]:
    """Top-level module roots ``source`` imports, across every import form.

    ``ast.ImportFrom.names`` holds the imported symbols, not the source
    module, and one ``ast.Import`` may bind several modules — both are
    handled here so the trust-boundary guard cannot be walked around by
    ``from maistro.graph import executor`` or ``import maistro.core, os``.
    Relative imports (``node.level > 0``) have no absolute root and
    attribute to the importing module itself.
    """
    roots: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = None if node.level else node.module
            if module is not None:
                roots.add(module.split(".")[0])
    return roots


def test_module_imports_no_maistro_module() -> None:
    assert "maistro" not in _maistro_import_roots(inspect.getsource(sys.modules[__name__]))


def test_import_guard_covers_every_import_form() -> None:
    assert _maistro_import_roots("from maistro.graph import executor") == {"maistro"}
    assert _maistro_import_roots("import maistro.core, os.path") == {"maistro", "os"}
    assert _maistro_import_roots("from . import sibling") == set()
    assert _maistro_import_roots("import collections.abc") == {"collections"}


def test_empty_catalog_and_bad_alternates_are_rejected() -> None:
    with pytest.raises(ValueError, match="empty task catalog"):
        measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, ())
    with pytest.raises(ValueError, match="duplicate task ids"):
        measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, (T_DRAFT, T_DRAFT))
    with pytest.raises(ValueError, match="unknown alternate"):
        measure(
            Policy.FULL_REPLAN,
            SCN_PROVIDER,
            GOAL,
            (T_DRAFT, dataclasses.replace(T_REVIEW, alternates=("ghost",))),
        )


def test_negative_budgets_are_rejected() -> None:
    with pytest.raises(ValueError, match="retry budget"):
        measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, CATALOG, retry_budget=-1)
    with pytest.raises(ValueError, match="replan budget"):
        measure(Policy.FULL_REPLAN, SCN_PROVIDER, GOAL, CATALOG, max_replans=-1)
    with pytest.raises(ValueError, match="requeue budget"):
        measure(Policy.LOCAL_REPAIR, SCN_TOOL, GOAL, CATALOG, max_requeue_passes=-1)
    with pytest.raises(ValueError, match="oscillation budget"):
        measure(Policy.FULL_REPLAN, SCN_HOT_WORLD, GOAL, CATALOG, max_consecutive_oscillations=-1)


def test_world_rejects_negative_delta_schedule() -> None:
    with pytest.raises(ValueError, match="negative action"):
        World(BASE_OBS, (ArtifactRevised(-1, "draft", 2),))


def test_planner_rejects_resolution_cycles() -> None:
    a = Task(id="a", satisfies_subgoal="a", produces_artifact="a", reads_artifact="b")
    b = Task(id="b", satisfies_subgoal="b", produces_artifact="b", reads_artifact="a")
    with pytest.raises(ValueError, match="cycle"):
        synthesize_plan(Goal(artifact="a"), BASE_OBS, (a, b), {}, {})


def test_planner_returns_none_when_nothing_is_viable() -> None:
    dark = WorldObservation()  # nothing up, nothing granted
    assert synthesize_plan(GOAL, dark, CATALOG, {}, {}) is None


def test_planner_rederives_stale_externally_satisfied_artifact() -> None:
    """An external satisfaction does not shield a stale artifact.

    ``review`` was satisfied externally at v1, then the world revised it
    to v2: the cached output is no longer current, so the replanner must
    re-derive it through the primary producer (or a declared alternate)
    instead of reporting NoViablePlan.
    """
    outputs = {"review": OutputRecord(artifact="review", emitted_version=1, produced_by="external")}
    world = World(
        BASE_OBS, (SubgoalEvent(1, "review", "review", 1), ArtifactRevised(2, "review", 2))
    )
    world.apply_completed(2)
    obs = world.observe()
    assert "review" in obs.satisfied_subgoals
    assert obs.artifact_versions["review"] == 2
    assert _output_current("review", outputs, obs.artifact_versions, obs) is False
    plan = synthesize_plan(GOAL, obs, CATALOG, outputs, obs.artifact_versions)
    assert [t.id for t in plan] == ["draft", "review", "publish"]


def test_planner_only_reaches_declared_alternates() -> None:
    """A same-artifact producer not named in ``alternates`` is never a fallback.

    With ``schema-v2`` dropped, the primary ``review`` is not viable; the
    replanner must reach ``review-manual`` only because ``T_REVIEW`` declares
    it. An undeclared producer of the same artifact stays unreachable and
    the derivation fails loudly instead of crediting a phantom recovery.
    """
    no_schema = dataclasses.replace(BASE_OBS, assumptions_holding=frozenset())
    undeclared = Task(
        id="review-shadow",
        satisfies_subgoal="review",
        produces_artifact="review",
        requires_tool="tool-y",
        reads_artifact="draft",
    )
    primary = dataclasses.replace(T_REVIEW, alternates=())
    assert (
        synthesize_plan(
            GOAL, no_schema, (T_DRAFT, primary, undeclared, T_PUBLISH, T_PUBLISH_BATCH), {}, {}
        )
        is None
    )
    plan = synthesize_plan(GOAL, no_schema, CATALOG, {}, {})
    assert [t.id for t in plan] == ["draft", "review-manual", "publish"]


def test_planner_rederives_stale_external_via_declared_alternate() -> None:
    """Same as above, but the primary producer lost its assumption, so the
    stale externally satisfied artifact is re-derived via ``review-manual``."""
    outputs = {"review": OutputRecord(artifact="review", emitted_version=1, produced_by="external")}
    world = World(
        BASE_OBS, (SubgoalEvent(1, "review", "review", 1), ArtifactRevised(2, "review", 2))
    )
    world.apply_completed(2)
    obs = world.observe()
    no_schema = dataclasses.replace(obs, assumptions_holding=frozenset())
    plan = synthesize_plan(GOAL, no_schema, CATALOG, outputs, no_schema.artifact_versions)
    assert [t.id for t in plan] == ["draft", "review-manual", "publish"]


def test_planner_rejects_alternates_producing_a_different_artifact() -> None:
    stray = Task(id="stray", satisfies_subgoal="stray", produces_artifact="other")
    bad = dataclasses.replace(T_REVIEW, alternates=("stray",))
    with pytest.raises(ValueError, match="not 'review'"):
        synthesize_plan(GOAL, BASE_OBS, (T_DRAFT, bad, stray, T_PUBLISH, T_PUBLISH_BATCH), {}, {})


# ---------------------------------------------------------------------------
# World-model tests
# ---------------------------------------------------------------------------


def test_world_fires_deltas_in_schedule_order_and_observations_are_free() -> None:
    world = World(
        BASE_OBS,
        (
            ProviderAvailability(2, "llm-a", up=False),
            ProviderAvailability(4, "llm-a", up=True),
        ),
    )
    world.apply_completed(1)
    assert "llm-a" in world.observe().providers_up
    world.apply_completed(3)
    assert "llm-a" not in world.observe().providers_up
    before = world.observe()
    assert world.observe() == before  # observing twice changes nothing
    world.apply_completed(4)
    assert "llm-a" in world.observe().providers_up


def test_subgoal_event_delivers_artifact_at_declared_version() -> None:
    world = World(BASE_OBS, (SubgoalEvent(1, "review", "review", 1),))
    world.apply_completed(1)
    obs = world.observe()
    assert "review" in obs.satisfied_subgoals
    assert obs.artifact_versions["review"] == 1
    assert world.external_artifact("review") == "review"


def test_subgoal_event_applies_its_declared_version_over_an_existing_one() -> None:
    """A repeated external completion re-versions the artifact it delivers.

    ``register_production`` had already moved the world to v1; the event
    declaring v2 must win, so provenance and reuse accounting observe the
    external change instead of a silently preserved old version.
    """
    world = World(BASE_OBS, (SubgoalEvent(2, "review", "review", 2),))
    world.register_production("review", 1)
    world.apply_completed(2)
    obs = world.observe()
    assert "review" in obs.satisfied_subgoals
    assert obs.artifact_versions["review"] == 2


def test_observation_versions_resist_in_place_mutation() -> None:
    """Frozen observations expose immutable version maps.

    ``WorldObservation`` is frozen, but a plain dict field stays mutable
    through the frozen shell: a caller could revise ``scenario.base``
    mid-benchmark and skew every later invocation. The mapping is stored
    behind a read-only proxy instead.
    """
    base = WorldObservation(artifact_versions={"draft": 1})
    scenario = Scenario(name="tamper", surprise_classes=(), base=base, deltas=())
    with pytest.raises(TypeError):
        scenario.base.artifact_versions["draft"] = 99  # type: ignore[index]
    world = World(scenario.base, scenario.deltas)
    obs = world.observe()
    assert obs.artifact_versions == {"draft": 1}
    with pytest.raises(TypeError):
        obs.artifact_versions["draft"] = 99  # type: ignore[index]
    assert world.observe() == obs


# ---------------------------------------------------------------------------
# Hand-checked per-surprise fixtures (exact units; synthetic, not evidence)
# ---------------------------------------------------------------------------


class TestNoReplanBlindBaseline:
    def test_provider_outage_is_not_recovered_and_blind_retries_burn_cost(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, CATALOG)
        assert row.recovered is False
        assert row.completed is False
        # The last blocked task (publish, missing input) names the budget
        # that exhausted — never a silent drop.
        assert row.gave_up is not None
        assert row.gave_up.reason == "retry-budget-exhausted:missing_input"
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (5, 10, 500)
        assert row.replans == 0

    def test_changed_artifact_completes_with_stale_provenance(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_ARTIFACT, GOAL, CATALOG)
        assert row.completed is True
        assert row.recovered is False
        # A completion is not an exhaustion: no give-up is fabricated.
        assert row.gave_up is None
        assert len(row.provenance_violations) == 2
        assert (row.attempts, row.total_cost_units) == (3, 6)

    def test_failed_tool_exhausts_retries_and_never_considers_alternates(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_TOOL, GOAL, CATALOG)
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "retry-budget-exhausted:tool_failed"
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (4, 8, 400)

    def test_denied_capability_is_retried_blindly_and_counted(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_CAPABILITY, GOAL, CATALOG)
        assert row.recovered is False
        assert row.denied_reattempts == 1
        assert row.gave_up is not None
        assert row.gave_up.reason == "retry-budget-exhausted:capability_denied"
        assert (row.attempts, row.total_cost_units) == (4, 8)

    def test_stale_assumption_ships_a_wrong_output(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_ASSUMPTION, GOAL, CATALOG)
        assert row.completed is True
        assert row.recovered is False
        assert len(row.provenance_violations) == 1
        assert "schema-v2" in row.provenance_violations[0]

    def test_satisfied_subgoal_is_reexecuted_as_duplicated_work(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_SUBGOAL, GOAL, CATALOG)
        assert row.recovered is True
        assert row.duplicated_work_units == 1
        assert row.reuse_units == 0
        assert row.gave_up is None
        assert (row.total_cost_units, row.total_latency_ms) == (6, 300)

    def test_blind_retries_of_a_satisfied_subgoal_count_per_attempt(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_SUBGOAL_OUTAGE, GOAL, CATALOG)
        assert row.completed is False
        # Review burns both blind attempts on an already-satisfied subgoal:
        # each attempt is duplicated work, not just the single pass.
        assert row.duplicated_work_units == 2
        assert row.attempts == 5
        assert row.gave_up is not None
        assert row.gave_up.reason == "retry-budget-exhausted:missing_input"


class TestLocalRepair:
    def test_transient_provider_outage_recovers_by_requeue(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_PROVIDER, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (5, 10, 500)
        assert row.replans == 0
        assert row.gave_up is None

    def test_precheck_tool_failure_waits_out_a_transient_outage(self) -> None:
        """A tool already down at precheck time still reaches its recovery.

        The precondition phase spends one wait action — an explicit
        observation point — so the scheduled ToolHealth recovery lands,
        the observation differs from the pass-start snapshot, and the task
        is requeued instead of given up on without advancing the world.
        """
        row = measure(Policy.LOCAL_REPAIR, SCN_TOOL_TRANSIENT, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert row.gave_up is None
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (3, 6, 300)
        assert row.replans == 0

    def test_zero_action_surprise_is_visible_before_the_first_attempt(self) -> None:
        """A delta scheduled at action 0 is world state before the Run starts.

        The world is synced before initial planning, so a one-task Run whose
        only requirement is already violated never attempts blind into the
        outage: initial synthesis refuses loudly under every policy — before
        any spend, and without recording a clean recovery from a surprise
        that had already happened.
        """
        solo = Task(
            id="solo", satisfies_subgoal="solo", produces_artifact="final", requires_tool="tool-x"
        )
        row = measure(Policy.LOCAL_REPAIR, SCN_SOLO_TOOL_DOWN, GOAL, (solo,))
        assert row.recovered is False
        assert row.attempts == 0
        assert row.replans == 0
        assert row.gave_up is not None
        assert row.gave_up.reason == "no-viable-plan"
        replan = measure(Policy.FULL_REPLAN, SCN_SOLO_TOOL_DOWN, GOAL, (solo,))
        assert replan.recovered is False
        assert (replan.attempts, replan.replans) == (0, 0)
        assert replan.gave_up is not None
        assert replan.gave_up.reason == "no-viable-plan"

    def test_changed_artifact_invalidates_exactly_the_stale_chain(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_ARTIFACT, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (5, 10, 500)

    def test_permanent_tool_failure_is_not_repairable_locally(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_TOOL, GOAL, CATALOG)
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "local-repair-exhausted:tool_failed"
        assert (row.attempts, row.total_cost_units) == (2, 4)

    def test_capability_denial_is_terminal_and_never_reattempted(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_CAPABILITY, GOAL, CATALOG)
        assert row.recovered is False
        assert row.denied_reattempts == 0
        assert row.gave_up is not None
        assert row.gave_up.reason == "capability-denied"
        assert (row.attempts, row.total_cost_units) == (2, 4)

    def test_stale_assumption_fails_without_shipping_a_wrong_output(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_ASSUMPTION, GOAL, CATALOG)
        assert row.recovered is False
        assert row.completed is False
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units) == (1, 2)

    def test_satisfied_subgoal_is_reused_not_duplicated(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_SUBGOAL, GOAL, CATALOG)
        assert row.recovered is True
        assert row.reuse_units == 1
        assert row.duplicated_work_units == 0
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (2, 4, 200)


class TestFullReplan:
    def test_transient_provider_outage_recovers_and_pays_the_planner(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_PROVIDER, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (5, 11, 550)
        assert (row.replans, row.oscillation_replans) == (1, 0)

    def test_changed_artifact_rederives_via_one_replan(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_ARTIFACT, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.total_cost_units, row.total_latency_ms) == (11, 550)
        # Same structure re-derived — corrective, not thrash: one replan.
        assert (row.replans, row.oscillation_replans) == (1, 1)

    def test_failed_tool_recovers_through_the_declared_alternate(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_TOOL, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (3, 8, 400)
        assert row.replans == 1

    def test_precheck_tool_failure_requeues_on_observed_recovery(self) -> None:
        """Full replan also waits and observes before spending the planner.

        When the wait exposes the scheduled recovery, the requeue resolves
        the surprise structurally-for-free; the planner is only paid when
        the observation did not change in the task's favor.
        """
        row = measure(Policy.FULL_REPLAN, SCN_TOOL_TRANSIENT, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (3, 6, 300)
        assert (row.replans, row.oscillation_replans) == (0, 0)

    def test_denied_capability_ends_in_a_loud_no_viable_plan(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_CAPABILITY, GOAL, CATALOG)
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "no-viable-plan"
        assert row.replans == 1
        assert row.denied_reattempts == 0
        assert (row.total_cost_units, row.total_latency_ms) == (5, 250)

    def test_stale_assumption_recovers_through_the_alternate_path(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_ASSUMPTION, GOAL, CATALOG)
        assert row.recovered is True
        assert row.provenance_violations == ()
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (3, 8, 400)
        assert row.replans == 1

    def test_satisfied_subgoal_is_dropped_by_the_replan(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_SUBGOAL, GOAL, CATALOG)
        assert row.recovered is True
        assert row.reuse_units == 1
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (2, 5, 250)
        assert row.replans == 1


# ---------------------------------------------------------------------------
# Benchmark-level results: recovery frontier and oscillation
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def benchmark() -> tuple[tuple[PolicyMeasurement, ...], tuple[PolicyAggregate, ...]]:
    return run_benchmark()


class TestBenchmarkFrontier:
    def test_every_surprise_class_times_every_policy_is_measured(
        self, benchmark: tuple[tuple[PolicyMeasurement, ...], tuple[PolicyAggregate, ...]]
    ) -> None:
        rows, _ = benchmark
        assert len(rows) == 18  # 6 surprises x 3 policies
        assert {(r.scenario, r.policy) for r in rows} == {
            (s.name, p) for s in CORE_SCENARIOS for p in POLICIES
        }

    def test_recovery_frontier_on_the_fixture_suite(
        self, benchmark: tuple[tuple[PolicyMeasurement, ...], tuple[PolicyAggregate, ...]]
    ) -> None:
        _, aggs = benchmark
        by_policy = {a.policy: a for a in aggs}
        blind = by_policy[Policy.NO_REPLAN]
        local = by_policy[Policy.LOCAL_REPAIR]
        full = by_policy[Policy.FULL_REPLAN]
        # Blind baseline: 1/6 recovered, and its 2 "completions" ship stale
        # derivations — exactly the hazard observation-driven replanning targets.
        assert (blind.recovered, blind.dirty_completions) == (1, 2)
        assert blind.total_denied_reattempts == 1
        # Local repair dominates the blind baseline: better clean recovery at
        # strictly lower total cost (the blind policy burns sunk retries).
        assert (local.clean_recovered, local.total_cost_units) == (3, 34)
        assert dominates(local, blind) is True
        # Full replan buys the two structural recoveries (tool substitution,
        # alternate assumption path) for ~41% more spend than local repair.
        assert (full.clean_recovered, full.total_cost_units) == (5, 48)
        assert dominates(full, local) is False
        assert (full.total_replans, full.total_oscillation_replans) == (6, 1)

    def test_benchmark_is_deterministic_across_invocations(self) -> None:
        assert run_benchmark() == run_benchmark()

    def test_dirty_completions_are_never_counted_as_recoveries(
        self, benchmark: tuple[tuple[PolicyMeasurement, ...], tuple[PolicyAggregate, ...]]
    ) -> None:
        rows, _ = benchmark
        for row in rows:
            if row.provenance_violations:
                assert row.recovered is False


class TestOscillationAndBudgets:
    def test_hot_world_thrashes_an_unbounded_replanner_then_recovers(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_HOT_WORLD, GOAL, CATALOG)
        assert row.recovered is True
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (8, 21, 1050)
        assert (row.replans, row.oscillation_replans) == (5, 5)

    def test_hot_world_is_stopped_loudly_by_the_oscillation_guard(self) -> None:
        row = measure(
            Policy.FULL_REPLAN, SCN_HOT_WORLD, GOAL, CATALOG, max_consecutive_oscillations=2
        )
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "replan-oscillation-exhausted"
        assert (row.replans, row.oscillation_replans) == (2, 2)
        assert (row.attempts, row.total_cost_units, row.total_latency_ms) == (2, 6, 300)

    def test_replan_budget_stops_the_replanner_loudly_with_the_budget_named(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_HOT_WORLD, GOAL, CATALOG, max_replans=2)
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "replan-budget-exhausted"

    def test_local_repair_thrash_is_bounded_by_requeue_passes(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_HOT_WORLD, GOAL, CATALOG)
        assert row.recovered is False
        assert row.gave_up is not None
        assert row.gave_up.reason == "local-repair-exhausted:stale_input"
        assert (row.attempts, row.total_cost_units) == (3, 6)

    def test_blind_policy_in_a_hot_world_ships_stale_derivations(self) -> None:
        row = measure(Policy.NO_REPLAN, SCN_HOT_WORLD, GOAL, CATALOG)
        assert row.completed is True
        assert row.recovered is False
        assert len(row.provenance_violations) == 2


class TestAccountingRules:
    def test_failed_attempts_pay_full_cost_and_latency(self) -> None:
        # Scenario A blind: t1 succeeds (1x2), t2 burns two failed attempts
        # (2x2), t3 burns two missing-input attempts (2x2): every attempt pays.
        row = measure(Policy.NO_REPLAN, SCN_PROVIDER, GOAL, CATALOG)
        assert row.total_cost_units == 5 * 2
        assert row.total_latency_ms == 5 * 100

    def test_replan_pays_even_when_it_finds_nothing(self) -> None:
        row = measure(Policy.FULL_REPLAN, SCN_CAPABILITY, GOAL, CATALOG)
        assert row.replans == 1
        assert row.total_cost_units == 4 + PLANNER_COST_UNITS
        assert row.total_latency_ms == 200 + PLANNER_LATENCY_MS

    def test_skips_pay_nothing_and_count_as_reuse(self) -> None:
        row = measure(Policy.LOCAL_REPAIR, SCN_SUBGOAL, GOAL, CATALOG)
        assert row.reuse_units == 1
        assert row.attempts == 2  # draft + publish; review skipped
        assert row.total_cost_units == 4

    def test_provenance_walk_flags_each_falsified_edge_once(self) -> None:
        review = OutputRecord(
            artifact="review",
            emitted_version=1,
            produced_by="review",
            derived_from={"draft": 1},
            required_assumption="schema-v2",
        )
        final = OutputRecord(
            artifact="final",
            emitted_version=1,
            produced_by="publish",
            derived_from={"review": 1},
        )
        stale_world = {"review": 1, "final": 1, "draft": 2}
        dark = WorldObservation(assumptions_holding=frozenset())
        draft = OutputRecord(artifact="draft", emitted_version=1, produced_by="draft")
        violations = chain_violations(
            final, {"draft": draft, "review": review, "final": final}, stale_world, dark
        )
        # review's consumed draft@1 link, review's assumption, and draft's
        # superseded emission — each named exactly once.
        assert len(violations) == 3
        assert len(set(violations)) == 3

    def test_clean_chain_has_no_violations(self) -> None:
        draft = OutputRecord(artifact="draft", emitted_version=2, produced_by="draft")
        review = OutputRecord(
            artifact="review",
            emitted_version=2,
            produced_by="review",
            derived_from={"draft": 2},
            required_assumption="schema-v2",
        )
        final = OutputRecord(
            artifact="final",
            emitted_version=1,
            produced_by="publish",
            derived_from={"review": 2},
        )
        world = {"draft": 2, "review": 2, "final": 1}
        obs = WorldObservation(assumptions_holding=frozenset({"schema-v2"}))
        assert (
            chain_violations(final, {"draft": draft, "review": review, "final": final}, world, obs)
            == ()
        )


class TestDominanceAndAggregation:
    def test_dominance_requires_clean_recovery_advantage_or_cost_parity(self) -> None:
        full = PolicyAggregate(Policy.FULL_REPLAN, 6, 5, 5, 0, 48, 2400, 20, 6, 1, 0, 1, 0)
        local = PolicyAggregate(Policy.LOCAL_REPAIR, 6, 3, 3, 0, 34, 1700, 17, 0, 0, 0, 1, 0)
        assert dominates(full, local) is False  # more recovery, but far more cost
        blind = PolicyAggregate(Policy.NO_REPLAN, 6, 1, 1, 2, 44, 2200, 22, 0, 0, 1, 0, 1)
        assert dominates(local, blind) is True  # better recovery AND cheaper

    def test_aggregate_preserves_policy_order_and_sums(self) -> None:
        rows = (
            measure(Policy.FULL_REPLAN, SCN_TOOL, GOAL, CATALOG),
            measure(Policy.NO_REPLAN, SCN_TOOL, GOAL, CATALOG),
            measure(Policy.FULL_REPLAN, SCN_ASSUMPTION, GOAL, CATALOG),
        )
        aggs = aggregate(rows)
        assert [a.policy for a in aggs] == [Policy.FULL_REPLAN, Policy.NO_REPLAN]
        assert aggs[0].scenarios == 2
        assert aggs[0].recovered == 2
        assert aggs[1].recovered == 0

    def test_recovery_rates_are_fractions_of_the_suite(self) -> None:
        _, aggs = run_benchmark()
        for a in aggs:
            assert a.recovery_rate == a.recovered / 6
            assert a.clean_recovery_rate == a.clean_recovered / 6
