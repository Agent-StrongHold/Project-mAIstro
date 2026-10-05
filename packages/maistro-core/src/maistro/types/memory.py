"""Memory types: learnings, episodic memory, tiers, scopes.

The 7-tier episodic memory system with bounded weights.
Key insight: REGRET weight cannot drop below 0.6 — structurally unforgettable.

Merged from maistro.memory.types + upstream types.memory.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class MemoryTier(StrEnum):
    """Episodic memory confidence tiers with increasing weight bounds."""

    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    OPINION = "opinion"
    LESSON = "lesson"
    REGRET = "regret"
    AFFIRMATION = "affirmation"
    WISDOM = "wisdom"


WEIGHT_BOUNDS: dict[MemoryTier, tuple[float, float]] = {
    MemoryTier.OBSERVATION: (0.1, 0.5),
    MemoryTier.HYPOTHESIS: (0.2, 0.6),
    MemoryTier.OPINION: (0.3, 0.8),
    MemoryTier.LESSON: (0.5, 0.9),
    MemoryTier.REGRET: (0.6, 1.0),
    MemoryTier.AFFIRMATION: (0.6, 1.0),
    MemoryTier.WISDOM: (0.9, 1.0),
}

INHERITANCE_PRIORITY: dict[MemoryTier, int] = {
    MemoryTier.OBSERVATION: 1,
    MemoryTier.HYPOTHESIS: 2,
    MemoryTier.OPINION: 3,
    MemoryTier.LESSON: 4,
    MemoryTier.REGRET: 5,
    MemoryTier.AFFIRMATION: 5,
    MemoryTier.WISDOM: 6,
}

REINFORCE_DELTA: float = 0.05
CONTRADICT_DELTA: float = 0.05

# Decay + reinforcement dynamics (ADR-080 part A / SPEC-240).
DEFAULT_DECAY_RATE: float = 0.01  # weight lost per hour at decay_rate=1.0
BOOST_RATE: float = 1.5  # weight multiplier on thumbs-up
DROP_RATE: float = 0.5  # weight multiplier on thumbs-down
SLOW_DECAY: float = 0.5  # decay_rate multiplier on thumbs-up
FAST_DECAY: float = 2.0  # decay_rate multiplier on thumbs-down
WISDOM_PROMOTE_THRESHOLD: int = 5  # reinforcement_count to promote -> WISDOM
REGRET_DEMOTE_THRESHOLD: int = 5  # contradiction_count to demote -> REGRET

# Learning pipeline dynamics (ADR-100126-8c2d / EPIC M4-B). A validated learning cannot
# sit below the validation floor -- the Gauntlet accepted its evidence -- and
# failure knowledge decays slowest: an anti-pattern cost a real failure to
# learn, and forgetting it re-buys that failure (the Learning-side mirror of
# REGRET's structural 0.6 floor).
DEFAULT_LEARNING_CONFIDENCE: float = 0.5
VALIDATED_CONFIDENCE_FLOOR: float = 0.6
ANTI_PATTERN_CONFIDENCE_FLOOR: float = 0.6
EMPIRICAL_HALF_LIFE_DAYS: float = 30.0
ANTI_PATTERN_HALF_LIFE_DAYS: float = 120.0


class EpistemicType(StrEnum):
    """How a learning claims to know what it says (M4-B3).

    A learning is a *claim*, not a truth: two learnings with identical text can
    deserve different treatment depending on where the claim came from. The
    type is explicit on the record so retrieval and ranking can weight a
    measured correction above a plausible-sounding distillation instead of
    treating them as interchangeable strings.

    Correspondence with the episodic tiers (MEMORY_TIER -> epistemic reading):
    OBSERVATION/HYPOTHESIS -> OBSERVED/INFERRED, LESSON -> TESTED,
    WISDOM -> REPORTED. The tiers grade confidence *weight* for episodic
    memory; this enum grades *justification* for learnings. They answer
    different questions and neither derives from the other.
    """

    #: Measured from an actual run or outcome (fail->succeed correction, tool telemetry).
    OBSERVED = "observed"
    #: Validated by an evaluation against a real execution.
    TESTED = "tested"
    #: Derived by reasoning or LLM distillation — plausible, not yet validated.
    INFERRED = "inferred"
    #: A claim about what *would* have happened; true only if an evaluation later confirms it.
    COUNTERFACTUAL = "counterfactual"
    #: Imported/asserted from an external source (e.g. CoinSwarm wisdom JSON).
    REPORTED = "reported"
    # Pipeline-epistemics members (#117/#121, ADR-100126-8c2d), reconciled with
    # M4-B3's ladder above: EMPIRICAL is the default for captured tool
    # corrections (the "observed" reading under a pipeline name), INFERENTIAL
    # marks RCA-derived diagnosis, ANTI_PATTERN marks failure knowledge that
    # decays slowest because forgetting it re-buys the failure.
    #: Observed fail->succeed (or first-try success) correction from tool history.
    EMPIRICAL = "empirical"
    #: RCA-derived diagnosis: inferred cause, not directly observed.
    INFERENTIAL = "inferential"
    #: Failure knowledge: what to stop doing. Retained near-permanently (#121).
    ANTI_PATTERN = "anti_pattern"


#: Retrieval bonus added to the keyword score in `find_relevant` (M4-B3). All
#: values are < 1.0 so the epistemic type reorders *ties* — it can never let a
#: less relevant learning outrank a more relevant one, which keeps the
#: established keyword-count ordering intact.
EPISTEMIC_BONUS: dict[EpistemicType, float] = {
    EpistemicType.TESTED: 0.4,
    EpistemicType.OBSERVED: 0.3,
    EpistemicType.REPORTED: 0.2,
    EpistemicType.INFERRED: 0.1,
    EpistemicType.COUNTERFACTUAL: 0.0,
    # Pipeline members mirror their M4-B3 readings: EMPIRICAL ranks as the
    # observation it is, INFERENTIAL as the inference it is, and an anti-pattern
    # (asserted failure knowledge) ranks beside REPORTED until a gauntlet
    # validates it.
    EpistemicType.EMPIRICAL: 0.3,
    EpistemicType.INFERENTIAL: 0.1,
    EpistemicType.ANTI_PATTERN: 0.2,
}


class LearningStage(StrEnum):
    """Knowledge-stage ladder over a Learning record (M4-B1 / ADR-103).

    The four semantic states between local execution memory and reusable
    institutional knowledge, in ascending order:

    - ``MEMORY`` — execution/agent-local remembered evidence/context. The
      record was captured with its producer provenance but has not been
      asserted as a reusable claim.
    - ``LEARNING`` — a claim inferred from that evidence: the correction a
      later execution is allowed to consider.
    - ``VALIDATED`` — a claim that survived independent evaluation. Whoever
      or whatever evaluated it is recorded in ``Learning.validated_by``; the
      evaluator is not the producer of the claim.
    - ``REPERTOIRE`` — validated learning explicitly promoted for reuse in
      shared knowledge. Promotion flips ``status`` to ``promoted`` so every
      existing promoted-only reader keeps working.

    Not a runtime: the ladder is fields on the one ``Learning`` record plus
    the transition functions in :mod:`maistro.memory.learnings.lifecycle`.
    A stage is metadata about knowledge, and it never grants permissions or
    execution authority — the Sentinel never reads it (ADR-103).
    """

    MEMORY = "memory"
    LEARNING = "learning"
    VALIDATED = "validated"
    REPERTOIRE = "repertoire"


#: Position of each stage on the ladder. Transitions are forward-only and
#: single-step; the lifecycle functions derive both rules from this map.
LEARNING_STAGE_ORDER: dict[LearningStage, int] = {
    LearningStage.MEMORY: 0,
    LearningStage.LEARNING: 1,
    LearningStage.VALIDATED: 2,
    LearningStage.REPERTOIRE: 3,
}


class MemoryScope(StrEnum):
    """Memory visibility scopes — hierarchical from broadest to narrowest."""

    GLOBAL = "global"
    ORGANIZATION = "organization"
    TEAM = "team"
    USER = "user"
    AGENT = "agent"
    SESSION = "session"


# Broadest-to-narrowest rank (ADR-013/068 axes); higher rank = broader scope.
# Used by ADR-080 part C's can_read/propose_widen scope comparisons.
SCOPE_RANK: dict[MemoryScope, int] = {
    MemoryScope.GLOBAL: 5,
    MemoryScope.ORGANIZATION: 4,
    MemoryScope.TEAM: 3,
    MemoryScope.USER: 2,
    MemoryScope.AGENT: 1,
    MemoryScope.SESSION: 0,
}


@dataclass(frozen=True)
class DecaySweep:
    """Outcome of one pass of periodic decay over an episodic store (SPEC-080126-9e42).

    ``scanned`` counts live (non-deleted) entries considered, ``decayed`` counts
    entries whose weight actually moved, ``at_floor`` counts entries already
    resting on their tier floor (the "structurally unforgettable" set).
    """

    scanned: int = 0
    decayed: int = 0
    at_floor: int = 0


@dataclass
class Learning:
    """A self-improving correction learned from tool call patterns."""

    category: str = "general"
    trigger_keys: list[str] = field(default_factory=list)
    learning: str = ""
    tool_name: str = ""
    source_query: str = ""
    org_id: str = ""
    team_id: str = ""
    agent_id: str | None = None
    user_id: str | None = None
    scope: MemoryScope = MemoryScope.AGENT
    hit_count: int = 0
    status: str = "active"
    id: int | None = None
    rca_category: str | None = None
    rca_prevention: str = ""
    success_after_use: int = 0
    failure_after_use: int = 0
    # Producer provenance (#709). Blank rather than absent because these are
    # dataclass fields with string siblings; the stores write blank as SQL NULL,
    # so "no execution was in scope" stays distinguishable from "a Run with no
    # id". Filled from the ambient execution context at write time when the
    # caller does not name them.
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
    # Epistemic qualification (M4-B3 / ADR-100126-b3c7, reconciled with the
    # pipeline epistemics #117/#121 ADR-100126-8c2d). `run_id` above names
    # the one Run that *produced* the text; `evidence_run_ids` names every Run
    # whose outcome *supports* the claim — a list, because consolidation and
    # rewording merge rows while their supporting executions accumulate. A
    # learning with neither list nor producer has no validation evidence and
    # cannot be promoted, no matter how it reads. EMPIRICAL is the default
    # epistemic type: a captured tool correction is measured until reclassified.
    epistemic_type: EpistemicType = EpistemicType.EMPIRICAL
    #: Contexts where the claim is known to hold (CoinSwarm wisdom's `excels_in`).
    works_when: list[str] = field(default_factory=list)
    #: Contexts where the claim failed or must not be applied (`avoid_in`).
    avoid_in: list[str] = field(default_factory=list)
    #: 0..1 belief strength, decayed toward the epistemic floor over time.
    #: `None` means unmeasured — which blocks promotion, because "no one
    #: measured" and "perfectly confident" must not read as the same record
    #: (the rule ADR-083026-a91e set for metrics). A fresh row starts at
    #: DEFAULT_LEARNING_CONFIDENCE, below the promotion floor.
    confidence: float | None = DEFAULT_LEARNING_CONFIDENCE
    evidence_run_ids: list[str] = field(default_factory=list)
    #: Evaluation records that scored the claim; the only evidence a
    #: COUNTERFACTUAL claim can be promoted on.
    evaluation_ids: list[str] = field(default_factory=list)
    #: Where this learning applies, e.g. {"task_types": ["deploy"], "tools": ["bash"]}.
    applicability: dict[str, list[str]] = field(default_factory=dict)
    reinforcement_count: int = 0
    contradiction_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    #: Last reinforcement instant; the decay clock anchors here, not created_at.
    last_confirmed_at: datetime | None = None
    # Knowledge-stage ladder (M4-B1 / ADR-103) with the pipeline epistemics
    # (#117/#121, ADR-100126-8c2d). `stage` is the knowledge pipeline position;
    # `status` stays the read surface (`promoted`-only readers keep working).
    # They move together only where they must: committing a learning to the
    # repertoire sets status="promoted" so those readers keep working.
    # `validated_by`/`promoted_by` name the actor of the corresponding
    # transition — blank means "never happened", never a fabricated default.
    stage: LearningStage = LearningStage.MEMORY
    #: Gauntlet provenance (#118): which independent validator accepted, and when.
    validated_by: str = ""
    validated_at: datetime | None = None
    #: Promotion actor (ADR-103): who committed the validated claim for reuse.
    promoted_by: str = ""
    #: Supersession links (#120). Both rows survive: institutional knowledge is
    # retained, so later Runs can ask what used to be believed.
    supersedes: int | None = None
    superseded_by: int | None = None


@dataclass
class Outcome:
    """The outcome of a completed request — tracks task completion rate.

    `input_tokens` and `output_tokens` are a **sum over the provider calls of
    one turn**, not one call's usage: a ReAct loop making four calls produces
    one Outcome with one pair. Which call was expensive, and which model served
    which step, needs a per-call record — that is the Invocation, and nothing
    constructs one yet (#55, and ADR-083026-aba1 for why this record says so).
    """

    #: The request this outcome came out of, or "" when none was in scope.
    #: Before migration 028 this field carried the *session* id: the one
    #: production writer passed `session_id` into it, and there was no
    #: `session_id` field to pass it to. Rows from before that revision may
    #: therefore hold either, which is why they are not backfilled -- there is
    #: no way to tell which a given historical row meant (ADR-083026-56ee).
    request_id: str = ""
    #: The conversation this outcome came out of, or "" when it came out of
    #: none. A session is not a request and not a Run; it is the axis
    #: `ExecutionContext` names `session_id` (ADR-083026-1cb1), and it now has
    #: a field of its own rather than borrowing one that means something else.
    session_id: str = ""
    task_type: str = ""
    model_used: str = ""
    provider: str = ""
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    success: bool = True
    error_type: str = ""
    response_time_ms: int = 0
    org_id: str = ""
    team_id: str = ""
    user_id: str = ""
    agent_id: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    #: How many of the turn's provider calls returned a `usage` object.
    #: `None` when the writer did not count — a row written before this
    #: existed, or a producer that does not know. Without it,
    #: `input_tokens = 0` reads as "free" and "nobody reported" at once, and
    #: the strategies spelled `usage.get("prompt_tokens", 0)` so both really
    #: did land as `0`. `0 over 3 reporting calls` and `0 over 0` are
    #: different facts (ADR-083026-aba1, #717; the same rule
    #: ADR-083026-a91e set for node metrics).
    usage_reported_calls: int | None = None
    charged_microchips: int = 0
    pricing_version: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None
    # Phase 2 additions — per-project memory + per-DAG telemetry. Defaults
    # keep existing callers byte-identical; new code passes these so
    # get_experience_context can return a project-scoped failure narrative
    # without polluting another project's learning loop.
    project_id: str = ""
    dag_id: str = ""
    dag_run_id: str = ""
    node_id: str = ""
    # For Phase 5/6 optimizer signals — extended outcomes the user-thumbs
    # widget + eval-judge can land on this same record without needing a
    # parallel store.
    thumb: str = ""  # "" | "up" | "down"
    thumb_comment: str = ""
    eval_judge_score: float | None = None  # 0..100 if eval-judge ran
    # Canonical producer provenance (#709). `dag_id`/`dag_run_id`/`node_id`
    # above stay: they name a real hive-conductor object the Conductor UI reads,
    # and ADR-019 puts that identity on the product side. These name the
    # canonical Run/NodeRun/Attempt the DAG run executes as (#143, #223, #697),
    # which is what the router's scoring and the optimizer's fitness are
    # actually evidence from.
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""


@dataclass
class SkillMutation:
    """Record of a skill being rewritten from a promoted learning."""

    skill_name: str = ""
    learning_id: int = 0
    old_prompt_hash: str = ""
    new_prompt_hash: str = ""
    mutation_type: str = "system_prompt_update"
    org_id: str = ""
    team_id: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    id: int | None = None


@dataclass
class EpisodicMemory:
    """A single episodic memory in the 7-tier weighted system."""

    #: Minted when the caller does not supply one. It used to default to `""`,
    #: and `TuringMemoryBridge.store_episode` constructs an `EpisodicMemory`
    #: without an id — so every episode shared one. The in-memory store appended
    #: them all and only the ids were wrong; the durable stores upsert on this
    #: column, which turned the same gap into each episode overwriting the last
    #: (Codex, #710).
    memory_id: str = field(default_factory=lambda: uuid4().hex)
    tier: MemoryTier = MemoryTier.OBSERVATION
    content: str = ""
    weight: float = 0.3
    org_id: str = ""
    team_id: str = ""
    agent_id: str | None = None
    user_id: str | None = None
    scope: MemoryScope = MemoryScope.AGENT
    project_id: str = ""
    source: str = ""
    #: `Any`, not `str`: `TuringMemoryBridge.store_episode` declares
    #: `context: dict[str, Any]` and passes it straight through, and the
    #: in-memory store keeps what it was handed. The annotation said `str` while
    #: the only producer sent numbers and nested objects, so a durable store
    #: reading it back faithfully would have contradicted the type, and one
    #: coercing to `str` would have contradicted the other store (Codex, #710).
    context: dict[str, Any] = field(default_factory=dict)
    reinforcement_count: int = 0
    contradiction_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted: bool = False
    decay_rate: float = DEFAULT_DECAY_RATE
    # ADR-080 part C: explicit cross-scope/cross-agent shareability marker.
    shared: bool = False
    # ADR-080 part B: contradiction review queue marker (never auto-resolved).
    flagged_for_review: bool = False
    # Producer provenance (#64). #709 left this table alone because nothing
    # wrote it: its only store held a dict, and columns with nothing behind
    # them are the unbacked durability claim this repo keeps removing. #710
    # then made the stores durable, which is the condition #709 named for
    # coming back. Blank means no execution was in scope; the stores fill it
    # from the ambient context when the caller does not name one.
    run_id: str = ""
    node_run_id: str = ""
    attempt_id: str = ""
