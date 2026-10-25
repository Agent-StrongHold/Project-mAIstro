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
