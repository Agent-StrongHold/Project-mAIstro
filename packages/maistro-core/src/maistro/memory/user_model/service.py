"""The one user-model service: every caller goes through this (#1047).

The Workspace Agent runtime and the HTTP API both call :class:`UserModelService`
-- the service owns owner checks, auditing and provenance, so no surface can
grow its own read/write path for user-model facts and no UI-only owner can
appear. A caller supplies the authenticated canonical user id as
``acting_user_id``; a lineage owned by someone else is indistinguishable from
a missing one (KeyError) on every per-lineage operation.

Promotion is deliberately not a service method: ``promote_evidence`` is the
one consolidation door, used directly by the Dreaming/consolidation side of
the same store and audit log this service holds, so there is exactly one
write path into the model and one read path out of it.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.memory.user_model.promotion import (
    ContradictionFn,
    _Auditor,
    _owned_head,
    correct_fact,
    forget_fact,
)
from maistro.memory.user_model.retrieval import RecallQuery, ScoredFact, recall
from maistro.memory.user_model.types import Correction, UserModelFact, new_fact_id

if TYPE_CHECKING:
    from maistro.protocols.memory import AuditLog, UserModelStore

__all__ = ["UserModelService"]


@dataclass(frozen=True)
class UserModelService:
    """Durable user-model reads and owner writes, shared by Agent and API."""

    store: UserModelStore
    audit_log: AuditLog
    contradiction_fn: ContradictionFn | None = None

    async def facts(self, acting_user_id: str) -> list[UserModelFact]:
        """The owner's current facts: "what does MAIstro believe about me"."""
        return await self.store.list_for_user(acting_user_id)

    async def history(self, lineage_id: str, *, acting_user_id: str) -> list[UserModelFact]:
        """Full revision lineage with provenance; foreign lineages look missing."""
        await _owned_head(
            self.store,
            lineage_id,
            _Auditor(self.audit_log, acting_user_id),
            "inspect",
        )
        return await self.store.history(lineage_id)

    async def correct(
        self,
        lineage_id: str,
        *,
        acting_user_id: str,
        statement: str,
        reason: str,
    ) -> UserModelFact:
        """Owner correction; appends a provenance-bearing revision."""
        return await correct_fact(
            lineage_id,
            acting_user_id=acting_user_id,
            statement=statement,
            reason=reason,
            store=self.store,
            audit_log=self.audit_log,
        )

    async def forget(self, lineage_id: str, *, acting_user_id: str, reason: str) -> UserModelFact:
        """Owner deletion; tombstones so no stale graph can recreate the fact."""
        return await forget_fact(
            lineage_id,
            acting_user_id=acting_user_id,
            reason=reason,
            store=self.store,
            audit_log=self.audit_log,
        )

    async def mark_not_reusable(
        self, lineage_id: str, *, acting_user_id: str, reason: str
    ) -> UserModelFact:
        """Owner marks a fact private/non-reusable: kept, but never surfaced again.

        The lineage stays ACTIVE (the fact is still believed true), so this is
        a shareability decision, not a correction or a deletion; recall gates
        on ``reusable`` before it scores.
        """
        auditor = _Auditor(self.audit_log, acting_user_id)
        head = await _owned_head(self.store, lineage_id, auditor, "mark_private")
        now = datetime.now(UTC)
        revision = dataclasses.replace(
            head,
            fact_id=new_fact_id(),
            revision=head.revision + 1,
            supersedes=head.fact_id,
            reusable=False,
            last_observed=now,
            correction=Correction(corrected_by=acting_user_id, reason=reason, corrected_at=now),
        )
        return await auditor.write(self.store, "mark_private", [revision])

    async def recall_for_task(self, query: RecallQuery) -> list[ScoredFact]:
        """Relevance-gated recall for one task; see ``retrieval`` for the rule."""
        return await recall(self.store, query)
