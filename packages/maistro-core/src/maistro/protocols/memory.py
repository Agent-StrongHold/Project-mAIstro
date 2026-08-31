"""Memory protocols: learnings, episodic, extraction, outcomes, sessions, audit."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from maistro.constants import THUMB_LIMIT, THUMB_WINDOW_DAYS
from maistro.types.memory import REINFORCE_DELTA

if TYPE_CHECKING:
    from datetime import datetime

    from maistro.types.memory import (
        DecaySweep,
        EpisodicMemory,
        Learning,
        Outcome,
        SkillMutation,
    )
    from maistro.types.security import AuditEntry


@runtime_checkable
class LearningStore(Protocol):
    """Self-improving memory from tool call patterns."""

    async def store(self, learning: Learning) -> int:
        """Store a learning, dedup against existing. Returns learning ID."""
        ...

    async def find_relevant(
        self,
        user_text: str,
        *,
        agent_id: str | None = None,
        org_id: str = "",
        max_results: int = 10,
    ) -> list[Learning]:
        """Find learnings relevant to the user's message."""
        ...

    async def mark_used(self, learning_ids: list[int]) -> None:
        """Increment hit_count for used learnings."""
        ...

    async def produced_by(self, run_id: str, *, org_id: str = "") -> list[Learning]:
        """Return the learnings one Run produced.

        The read that makes producer provenance worth recording. A learning is a
        correction the system applies to future work, so when one turns out to
        be wrong the first question is which execution taught it -- and until
        #709 nothing could answer it. Scoped like every other read here: an
        `org_id` filters, and a blank one matches only rows that have none.
        """
        ...

    async def mark_outcome(
        self, learning_ids: list[int], success: bool, *, org_id: str = ""
    ) -> None:
        """Record whether each injected learning was followed by a successful request."""
        ...

    async def check_auto_promotions(
        self, threshold: int = 5, *, org_id: str = ""
    ) -> list[Learning]:
        """Promote learnings that have been hit enough times."""
        ...

    async def get_promoted(
        self, task_type: str | None = None, *, org_id: str = ""
    ) -> list[Learning]:
        """Get promoted learnings for system prompt injection."""
        ...

    async def list_all(self, org_id: str = "", limit: int = 200) -> list[Learning]:
        """List learnings for an org (candidate enumeration for promotion/admin)."""
        ...


@runtime_checkable
class LearningExtractor(Protocol):
    """Extracts learnings from tool call histories. Pure function, no I/O."""

    def extract_corrections(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> list[Learning]:
        """Extract fail→succeed correction patterns."""
        ...

    def extract_positive_patterns(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> list[Learning]:
        """Extract first-try success patterns on ambiguous queries."""
        ...


@runtime_checkable
class EpisodicStore(Protocol):
    """7-tier episodic memory with weight-bounded tiers."""

    async def store(self, memory: EpisodicMemory) -> str:
        """Store a memory. Returns memory_id."""
        ...

    async def retrieve(
        self,
        query: str,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        limit: int = 5,
    ) -> list[EpisodicMemory]:
        """Retrieve relevant memories, scope-filtered."""
        ...

    async def reinforce(self, memory_id: str, delta: float = REINFORCE_DELTA) -> None:
        """Reinforce a memory (increase weight, clamped to tier ceiling)."""
        ...

    async def list_by_scope(
        self,
        *,
        agent_id: str | None = None,
        user_id: str | None = None,
        team_id: str | None = None,
        org_id: str | None = None,
        project_id: str | None = None,
        min_weight: float = 0.0,
        limit: int = 50,
    ) -> list[EpisodicMemory]:
        """Scope-filtered memories at or above min_weight, no content matching.

        `user_id` is one of the scope axes root CLAUDE.md decision 7 / ADR-068
        names (global -> org -> team -> user -> agent -> session), and
        `retrieve` above has always accepted it. It was missing here, so a
        caller that wanted the scoped set *without* content matching -- which is
        what a reranker wants -- could not express a user scope at all (#622).
        """
        ...


@runtime_checkable
class DecayableEpisodicStore(Protocol):
    """An :class:`EpisodicStore` that can apply periodic decay to itself.

    Split out from ``EpisodicStore`` so a store that cannot sweep (e.g. a
    read-only or remote projection) stays a valid ``EpisodicStore`` and the
    decay driver reports "no decayable store" loudly instead of crashing.
    """

    async def apply_decay(self, *, now: datetime | None = None) -> DecaySweep:
        """Apply one pass of time-based decay to every live memory.

        Returns what the sweep touched, so a driver can report it (SPEC-080126-9e42).
        """
        ...


@runtime_checkable
class OutcomeStore(Protocol):
    """Tracks request outcomes for task completion rate and experience-augmented prompts."""

    async def record(self, outcome: Outcome) -> int:
        """Record an outcome. Returns outcome ID."""
        ...

    async def get_task_completion_rate(
        self,
        task_type: str = "",
        days: int = 7,
    ) -> dict[str, Any]:
        """Get completion rate stats: {total, succeeded, failed, rate, by_model}."""
        ...

    async def get_experience_context(
        self,
        task_type: str,
        tool_name: str = "",
        limit: int = 5,
        org_id: str = "",
        project_id: str = "",
    ) -> str:
        """Get recent failure patterns as a prompt section for experience-augmented context."""
        ...

    async def get_usage_breakdown(
        self,
        group_by: str = "user_id",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Aggregate token usage grouped by a dimension (user_id, team_id, model_used)."""
        ...

    async def get_daily_timeseries(
        self,
        group_by: str = "",
        days: int = 7,
        org_id: str = "",
    ) -> list[dict[str, Any]]:
        """Daily token usage timeseries, optionally grouped by a dimension."""
        ...

    async def list_outcomes(
        self,
        task_type: str = "",
        days: int = 7,
        limit: int = 50,
    ) -> list[Outcome]:
        """List recent outcomes for admin inspection."""
        ...

    async def list_thumbs(
        self,
        *,
        dag_id: str = "",
        days: int = THUMB_WINDOW_DAYS,
        limit: int = THUMB_LIMIT,
        org_id: str = "",
    ) -> list[Outcome]:
        """Outcomes carrying a thumb, most recent first.

        The optimizer's user-satisfaction signal. It exists as a protocol
        method because the only reader used to be
        `getattr(store, "_outcomes", [])` -- a private list that
        `InMemoryOutcomeStore` has and the two durable stores do not, so
        wiring a durable store would have emptied the signal and raised
        nothing (#696).

        `dag_id` scoping keeps the reader's original rule: a thumb whose own
        `dag_id` is empty matches every DAG. Those are thumbs recorded before
        the attribution wire existed, and dropping them would discard real
        user feedback to tidy a filter.
        """
        ...


@runtime_checkable
class SkillMutationStore(Protocol):
    """Tracks skill mutations triggered by promoted learnings."""

    async def record(self, mutation: SkillMutation) -> int:
        """Record a skill mutation. Returns mutation ID."""
        ...

    async def list_mutations(self, limit: int = 50) -> list[SkillMutation]:
        """List recent mutations."""
        ...


@runtime_checkable
class RCAExtractor(Protocol):
    """Generates root cause analysis when tool loops exhaust max rounds."""

    async def extract_rca(
        self,
        user_text: str,
        tool_history: list[dict[str, Any]],
    ) -> Learning | None:
        """Diagnose why the tool loop failed. Returns a learning or None."""
        ...


@runtime_checkable
class SessionStore(Protocol):
    """Conversation history storage."""

    async def get_history(
        self,
        session_id: str,
        max_messages: int | None = None,
        ttl_seconds: int | None = None,
    ) -> list[dict[str, str]]:
        """Retrieve conversation history, pruning expired messages."""
        ...

    async def append_messages(
        self,
        session_id: str,
        messages: list[dict[str, str]],
        turn_id: str | None = None,
    ) -> None:
        """Append messages to session history, at most once per turn identity.

        `turn_id` names the turn the batch belongs to (ADR-083026-5fab). It is
        opaque to the store, and a batch appended under an identity already
        recorded for the session is a retry: nothing is written, nothing is
        raised. Omitting it leaves the append unchanged, which is what every
        caller that does not know it is retrying should do.
        """
        ...

    async def produced_runs(self, session_id: str) -> list[str]:
        """The canonical Runs that produced this session's turns, oldest first.

        The session-to-Run direction, which until ADR-083026-56ee existed only
        as a coincidence of one call site passing a Run id as an opaque turn
        identity. Distinct, and never blank: a turn appended with no execution
        in scope contributes nothing rather than an empty name.
        """
        ...

    async def delete_session(self, session_id: str) -> None:
        """Delete a session."""
        ...


@runtime_checkable
class ContextAssemblyPolicy(Protocol):
    """Assembles Level-1 storage types into Layer 0-4 LLM-prompt text (ADR-091)."""

    async def layer0(self, project_id: str) -> str:
        """Pinned project constraints text. Always included; drives KV cache key."""
        ...

    async def layer1(
        self,
        run_id: str,
        agent_id: str,
        session_id: str,
        query: str = "",
        budget_tokens: int | None = None,
    ) -> str:
        """Active task context: high-confidence episodic memories scoped to this agent.

        `query` and `budget_tokens` were added by #622. Without a query no
        implementation of this protocol can rank by relevance, so "high
        confidence" could only ever mean "above a weight floor, in store order";
        without the budget here, packing happens on joined text, where a whole
        memory is no longer a unit and ADR-091's always-include band cannot be
        honoured. Both default so an existing caller keeps its behaviour: no
        query means no ranking, and no budget means unbounded, not zero.
        """
        ...

    async def layer2(self, session_id: str, budget_tokens: int) -> str:
        """Compressed conversation history (SPEC-189 rolling window)."""
        ...

    async def layer3(self, project_id: str, n: int = 20, budget_tokens: int | None = None) -> str:
        """Project changelog: recent Outcome records + WISDOM-tier episodic memories."""
        ...

    async def layer4(self, project_id: str) -> str:
        """Knowledge graph context. Returns '' until implemented."""
        ...

    async def assemble(
        self,
        project_id: str,
        run_id: str,
        agent_id: str,
        session_id: str,
        budget_tokens: int,
        query: str = "",
    ) -> str:
        """Concatenate layers 0-4 in order, respecting budget_tokens total."""
        ...


@runtime_checkable
class AuditLog(Protocol):
    """Immutable audit log for boundary crossings."""

    async def log(self, entry: AuditEntry) -> None:
        """Record an audit entry."""
        ...

    async def get_entries(
        self,
        *,
        user_id: str | None = None,
        agent_id: str | None = None,
        org_id: str = "",
        limit: int = 100,
    ) -> list[AuditEntry]:
        """Retrieve audit entries with optional filtering."""
        ...
