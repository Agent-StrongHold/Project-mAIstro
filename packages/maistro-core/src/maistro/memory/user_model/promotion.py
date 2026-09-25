"""Owner-only writes into the user model, each one audited (#1047).

Promoting a user's own Workspace- or Agent-scoped memory into their user model
is automatic self-consent with an audit entry (owner decision on #1047,
amending SPEC-242). Anything owned by someone else still needs a SPEC-242
ConsentTask, so it is refused here.

Every write is audited before it is appended, so a failing audit log blocks
the write rather than leaving an unaudited fact behind.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from maistro.memory.user_model.types import (
    Correction,
    CrossUserPromotionError,
    EvidenceRef,
    FactState,
    PromotionRefusedError,
    StaleEvidenceError,
    TombstonedLineageError,
    UserModelError,
    UserModelFact,
    fact_key,
    new_fact_id,
    normalize_statement,
)
from maistro.types.memory import SCOPE_RANK, MemoryScope
from maistro.types.security import AuditEntry

if TYPE_CHECKING:
    from maistro.protocols.memory import AuditLog, UserModelStore
    from maistro.types.memory import EpisodicMemory

AUDIT_BOUNDARY = "user_model"
REINFORCE_STEP = 0.1

ContradictionFn = Callable[[str, str], bool]


@dataclass(frozen=True)
class _Auditor:
    """Writes identifier-only audit entries for one acting user's attempt."""

    audit_log: AuditLog
    acting_user_id: str
    memory: EpisodicMemory | None = None
    workspace_id: str = ""

    async def record(self, action: str, detail: str, *, verdict: str = "allowed") -> None:
        memory = self.memory
        await self.audit_log.log(
            AuditEntry(
                boundary=AUDIT_BOUNDARY,
                action=action,
                verdict=verdict,
                user_id=self.acting_user_id,
                detail=detail if memory is None else f"{detail} memory={memory.memory_id}",
                org_id=memory.org_id if memory else "",
                team_id=memory.team_id if memory else "",
                agent_id=(memory.agent_id or "") if memory else "",
                project_id=memory.project_id if memory else "",
                run_id=memory.run_id if memory else "",
                workspace_id=self.workspace_id,
            )
        )

    async def refuse(self, action: str, error: Exception, detail: str = "") -> Exception:
        await self.record(
            action, f"refused={type(error).__name__} {detail}".strip(), verdict="denied"
        )
        return error

    async def write(
        self, store: UserModelStore, action: str, facts: list[UserModelFact]
    ) -> UserModelFact:
        """Audit then append each revision; a failed append is audited as denied."""
        for fact in facts:
            detail = f"lineage={fact.lineage_id} revision={fact.revision}"
            await self.record(action, detail)
            try:
                await store.append_revision(fact)
            except UserModelError as exc:
                raise await self.refuse(action, exc, detail) from None
        return facts[0]


def _refusal(memory: EpisodicMemory, acting_user_id: str) -> PromotionRefusedError | None:
    if not acting_user_id or memory.user_id != acting_user_id:
        return CrossUserPromotionError(
            "promoting another user's memory needs SPEC-242 consent, not self-consent"
        )
    if memory.deleted or memory.flagged_for_review or not memory.content.strip():
        return PromotionRefusedError("deleted, disputed or empty memory cannot become a fact")
    if SCOPE_RANK[memory.scope] > SCOPE_RANK[MemoryScope.USER]:
        return PromotionRefusedError(
            f"{memory.scope} memory is shared beyond one user and cannot be self-promoted"
        )
    return None


async def _stale_or_tombstoned(
    store: UserModelStore, key: str, statement: str
) -> PromotionRefusedError | None:
    if await store.is_tombstoned(key):
        return TombstonedLineageError("the owner deleted this fact")
    head = await store.current(key)
    if (
        head is not None
        and head.correction is not None
        and normalize_statement(head.statement) != normalize_statement(statement)
    ):
        return StaleEvidenceError("the owner corrected this fact")
    return None


def _seen(fact: UserModelFact, memory_id: str) -> bool:
    return any(ref.memory_id == memory_id for ref in fact.evidence)


async def _contradicted(
    store: UserModelStore, owner: str, statement: str, fn: ContradictionFn | None
) -> list[UserModelFact]:
    if fn is None:
        return []
    return [
        fact
        for fact in await store.list_for_user(owner)
        if fact.state in (FactState.ACTIVE, FactState.UNDER_REVIEW)
        and fn(fact.statement, statement)
    ]


def _next_revision(
    head: UserModelFact, ref: EvidenceRef, now: datetime, **changes: object
) -> UserModelFact:
    return dataclasses.replace(
        head,
        fact_id=new_fact_id(),
        revision=head.revision + 1,
        supersedes=head.fact_id,
        evidence=(*head.evidence, ref),
        last_observed=now,
        **changes,  # type: ignore[arg-type]
    )


async def promote_evidence(
    memory: EpisodicMemory,
    *,
    acting_user_id: str,
    store: UserModelStore,
    audit_log: AuditLog,
    kind: str = "preference",
    workspace_id: str = "",
    artifact_id: str = "",
    contradiction_fn: ContradictionFn | None = None,
) -> UserModelFact:
    """Promote the acting user's own memory into their user model.

    New evidence starts a lineage; repeat evidence reinforces it with a new
    revision; evidence that ``contradiction_fn`` says contradicts a live fact
    puts that fact under review with a new revision instead of overwriting
    it. Replaying a memory already on record is a no-op. Refusals are audited
    as denied and raised.
    """
    auditor = _Auditor(audit_log, acting_user_id, memory, workspace_id)
    key = fact_key(acting_user_id, memory.content)
    refusal = _refusal(memory, acting_user_id) or await _stale_or_tombstoned(
        store, key, memory.content
    )
    if refusal is not None:
        raise await auditor.refuse("promote", refusal)
    now = datetime.now(UTC)
    ref = EvidenceRef(
        workspace_id=workspace_id,
        project_id=memory.project_id,
        memory_id=memory.memory_id,
        run_id=memory.run_id,
        artifact_id=artifact_id,
    )
    head = await store.current(key)
    if head is not None:
        if _seen(head, memory.memory_id):
            return head
        reinforced = _next_revision(
            head,
            ref,
            now,
            last_reinforced=now,
            confidence=min(1.0, head.confidence + REINFORCE_STEP),
        )
        return await auditor.write(store, "promote", [reinforced])
    contradicted = await _contradicted(store, acting_user_id, memory.content, contradiction_fn)
    if contradicted:
        fresh = [f for f in contradicted if not _seen(f, memory.memory_id)]
        if not fresh:
            return contradicted[0]
        flagged = [_next_revision(f, ref, now, state=FactState.UNDER_REVIEW) for f in fresh]
        return await auditor.write(store, "flag_for_review", flagged)
    fact = UserModelFact(
        lineage_id=new_fact_id(),
        revision=1,
        supersedes=None,
        owner_user_id=acting_user_id,
        kind=kind,
        statement=memory.content,
        evidence=(ref,),
        first_observed=now,
        last_observed=now,
        last_reinforced=now,
    )
    return await auditor.write(store, "promote", [fact])


async def _owned_head(
    store: UserModelStore, lineage_id: str, auditor: _Auditor, action: str
) -> UserModelFact:
    """The owner's current revision; a missing lineage and a foreign one look alike."""
    head = await store.current(lineage_id)
    if head is None or not auditor.acting_user_id or head.owner_user_id != auditor.acting_user_id:
        raise await auditor.refuse(action, KeyError(lineage_id), f"lineage={lineage_id}")
    if await store.is_tombstoned(lineage_id):
        raise await auditor.refuse(
            action, TombstonedLineageError(lineage_id), f"lineage={lineage_id}"
        )
    return head


async def correct_fact(
    lineage_id: str,
    *,
    acting_user_id: str,
    statement: str,
    reason: str,
    store: UserModelStore,
    audit_log: AuditLog,
) -> UserModelFact:
    """Append an owner-stated revision carrying correction provenance."""
    if not statement.strip():
        raise ValueError("a correction must state the corrected fact; use forget_fact to delete")
    auditor = _Auditor(audit_log, acting_user_id)
    head = await _owned_head(store, lineage_id, auditor, "correct")
    now = datetime.now(UTC)
    fact = dataclasses.replace(
        head,
        fact_id=new_fact_id(),
        revision=head.revision + 1,
        supersedes=head.fact_id,
        statement=statement,
        state=FactState.ACTIVE,
        confidence=1.0,
        last_observed=now,
        correction=Correction(corrected_by=acting_user_id, reason=reason, corrected_at=now),
    )
    return await auditor.write(store, "correct", [fact])


async def forget_fact(
    lineage_id: str,
    *,
    acting_user_id: str,
    reason: str,
    store: UserModelStore,
    audit_log: AuditLog,
) -> UserModelFact:
    """Tombstone an owner's fact so no stale evidence can recreate it."""
    auditor = _Auditor(audit_log, acting_user_id)
    head = await _owned_head(store, lineage_id, auditor, "forget")
    await auditor.record("forget", f"lineage={head.lineage_id}")
    return await store.tombstone(head.lineage_id, acting_user_id=acting_user_id, reason=reason)
