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


def _entry(
    action: str,
    acting_user_id: str,
    *,
    verdict: str = "allowed",
    detail: str = "",
    memory: EpisodicMemory | None = None,
    workspace_id: str = "",
) -> AuditEntry:
    return AuditEntry(
        boundary=AUDIT_BOUNDARY,
        action=action,
        verdict=verdict,
        user_id=acting_user_id,
        detail=detail,
        org_id=memory.org_id if memory else "",
        team_id=memory.team_id if memory else "",
        agent_id=(memory.agent_id or "") if memory else "",
        project_id=memory.project_id if memory else "",
        run_id=memory.run_id if memory else "",
        workspace_id=workspace_id,
    )


def _revision_detail(fact: UserModelFact) -> str:
    return f"lineage={fact.lineage_id} revision={fact.revision}"


async def _refuse(
    audit_log: AuditLog,
    error: PromotionRefusedError,
    acting_user_id: str,
    memory: EpisodicMemory,
    workspace_id: str,
) -> PromotionRefusedError:
    await audit_log.log(
        _entry(
            "promote",
            acting_user_id,
            verdict="denied",
            detail=f"refused={type(error).__name__} memory={memory.memory_id}",
            memory=memory,
            workspace_id=workspace_id,
        )
    )
    return error


def _refusal(memory: EpisodicMemory, acting_user_id: str) -> PromotionRefusedError | None:
    if not acting_user_id or memory.user_id != acting_user_id:
        return CrossUserPromotionError(
            "promoting another user's memory needs SPEC-242 consent, not self-consent"
        )
    if memory.deleted or not memory.content.strip():
        return PromotionRefusedError("deleted or empty memory cannot become a fact")
    if SCOPE_RANK[memory.scope] > SCOPE_RANK[MemoryScope.USER]:
        return PromotionRefusedError(
            f"{memory.scope} memory is shared beyond one user and cannot be self-promoted"
        )
    return None


async def _matching_head(
    store: UserModelStore, lineage_id: str, owner: str, kind: str, statement: str
) -> UserModelFact | None:
    head = await store.current(lineage_id)
    if head is not None:
        return head
    wanted = normalize_statement(statement)
    for fact in await store.list_for_user(owner):
        if fact.kind == kind and normalize_statement(fact.statement) == wanted:
            return fact
    return None


async def _contradicted(
    store: UserModelStore, owner: str, kind: str, statement: str, fn: ContradictionFn | None
) -> list[UserModelFact]:
    if fn is None:
        return []
    return [
        fact
        for fact in await store.list_for_user(owner)
        if fact.kind == kind and fact.state is FactState.ACTIVE and fn(fact.statement, statement)
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
    revision; evidence that ``contradiction_fn`` says contradicts an active
    fact puts that fact under review with a new revision instead of
    overwriting it. Refusals are audited as denied and raised.
    """
    refusal = _refusal(memory, acting_user_id)
    if refusal is not None:
        raise await _refuse(audit_log, refusal, acting_user_id, memory, workspace_id)
    lineage_id = fact_key(acting_user_id, kind, memory.content)
    if await store.is_tombstoned(lineage_id):
        raise await _refuse(
            audit_log, TombstonedLineageError(lineage_id), acting_user_id, memory, workspace_id
        )
    head = await _matching_head(store, lineage_id, acting_user_id, kind, memory.content)
    if (
        head is not None
        and head.correction is not None
        and normalize_statement(head.statement) != normalize_statement(memory.content)
    ):
        raise await _refuse(
            audit_log, StaleEvidenceError(lineage_id), acting_user_id, memory, workspace_id
        )
    now = datetime.now(UTC)
    ref = EvidenceRef(
        workspace_id=workspace_id,
        project_id=memory.project_id,
        memory_id=memory.memory_id,
        run_id=memory.run_id,
        artifact_id=artifact_id,
    )
    action = "promote"
    if head is not None:
        fact = _next_revision(
            head,
            ref,
            now,
            last_reinforced=now,
            confidence=min(1.0, head.confidence + REINFORCE_STEP),
        )
        writes = [fact]
    else:
        contradicted = await _contradicted(
            store, acting_user_id, kind, memory.content, contradiction_fn
        )
        if contradicted:
            action = "flag_for_review"
            writes = [
                _next_revision(f, ref, now, state=FactState.UNDER_REVIEW) for f in contradicted
            ]
        else:
            writes = [
                UserModelFact(
                    lineage_id=lineage_id,
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
            ]
    for fact in writes:
        await audit_log.log(
            _entry(
                action,
                acting_user_id,
                detail=f"{_revision_detail(fact)} memory={memory.memory_id}",
                memory=memory,
                workspace_id=workspace_id,
            )
        )
        await store.append_revision(fact)
    return writes[0]


async def _owned_head(
    store: UserModelStore, lineage_id: str, acting_user_id: str, action: str, audit_log: AuditLog
) -> UserModelFact:
    head = await store.current(lineage_id)
    if head is None:
        raise KeyError(lineage_id)
    if not acting_user_id or head.owner_user_id != acting_user_id:
        await audit_log.log(
            _entry(action, acting_user_id, verdict="denied", detail=f"lineage={lineage_id}")
        )
        raise PermissionError(f"only the owner may {action} a user-model fact")
    if await store.is_tombstoned(lineage_id):
        raise TombstonedLineageError(lineage_id)
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
    head = await _owned_head(store, lineage_id, acting_user_id, "correct", audit_log)
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
    await audit_log.log(_entry("correct", acting_user_id, detail=_revision_detail(fact)))
    return await store.append_revision(fact)


async def forget_fact(
    lineage_id: str,
    *,
    acting_user_id: str,
    reason: str,
    store: UserModelStore,
    audit_log: AuditLog,
) -> UserModelFact:
    """Tombstone an owner's fact so no stale evidence can recreate it."""
    await _owned_head(store, lineage_id, acting_user_id, "forget", audit_log)
    await audit_log.log(_entry("forget", acting_user_id, detail=f"lineage={lineage_id}"))
    return await store.tombstone(lineage_id, acting_user_id=acting_user_id, reason=reason)
