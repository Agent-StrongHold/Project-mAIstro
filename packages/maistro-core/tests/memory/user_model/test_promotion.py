"""Same-user self-consented promotion of episodic evidence into the user model (#1047)."""

from __future__ import annotations

import dataclasses

import pytest

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.user_model import (
    CrossUserPromotionError,
    FactState,
    InMemoryUserModelStore,
    PromotionRefusedError,
    StaleEvidenceError,
    TombstonedLineageError,
    correct_fact,
    fact_key,
    forget_fact,
    promote_evidence,
)
from maistro.security.sentinel.audit import InMemoryAuditLog


def _memory(user_id: str | None, content: str, **kw: object) -> EpisodicMemory:
    fields: dict[str, object] = {
        "tier": MemoryTier.OPINION,
        "content": content,
        "user_id": user_id,
        "agent_id": "agent-1",
        "scope": MemoryScope.AGENT,
        "project_id": "proj-a",
        "run_id": "run-1",
    }
    fields.update(kw)
    return EpisodicMemory(**fields)  # type: ignore[arg-type]


def _never(_old: str, _new: str) -> bool:
    return False


def _always(_old: str, _new: str) -> bool:
    return True


async def test_same_user_promotion_audits_once_and_yields_active_fact() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    memory = _memory("alice", "prefers mirrorless cameras")

    fact = await promote_evidence(
        memory, acting_user_id="alice", store=store, audit_log=audit, workspace_id="ws-a"
    )

    assert fact.state is FactState.ACTIVE
    assert fact.owner_user_id == "alice"
    assert fact.revision == 1
    assert fact.lineage_id == fact_key("alice", "preference", memory.content)
    ref = fact.evidence[0]
    assert (ref.workspace_id, ref.project_id, ref.memory_id, ref.run_id) == (
        "ws-a",
        "proj-a",
        memory.memory_id,
        "run-1",
    )
    entries = await audit.get_entries(user_id="alice")
    assert len(entries) == 1
    entry = entries[0]
    assert (entry.boundary, entry.action, entry.verdict) == (
        "user_model",
        "promote",
        "allowed",
    )
    assert memory.content not in entry.detail
    assert [f.fact_id for f in await store.list_for_user("alice")] == [fact.fact_id]


async def test_promoting_another_users_memory_is_refused_and_audited() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()

    with pytest.raises(CrossUserPromotionError):
        await promote_evidence(
            _memory("alice", "prefers mirrorless cameras"),
            acting_user_id="bob",
            store=store,
            audit_log=audit,
        )

    assert await store.list_for_user("alice") == []
    assert await store.list_for_user("bob") == []
    denied = await audit.get_entries(user_id="bob")
    assert [e.verdict for e in denied] == ["denied"]


@pytest.mark.parametrize(
    ("user_id", "acting"),
    [(None, ""), ("", ""), (None, "bob")],
)
async def test_unowned_memory_or_blank_actor_is_refused(user_id: str | None, acting: str) -> None:
    with pytest.raises(CrossUserPromotionError):
        await promote_evidence(
            _memory(user_id, "x"),
            acting_user_id=acting,
            store=InMemoryUserModelStore(),
            audit_log=InMemoryAuditLog(),
        )


@pytest.mark.parametrize(
    ("content", "overrides"),
    [
        ("prefers primes", {"scope": MemoryScope.TEAM}),
        ("prefers primes", {"deleted": True}),
        ("   ", {}),
    ],
)
async def test_non_promotable_memory_is_refused(content: str, overrides: dict[str, object]) -> None:
    store = InMemoryUserModelStore()
    with pytest.raises(PromotionRefusedError):
        await promote_evidence(
            _memory("alice", content, **overrides),
            acting_user_id="alice",
            store=store,
            audit_log=InMemoryAuditLog(),
        )
    assert await store.list_for_user("alice") == []


async def test_colliding_statements_stay_isolated_per_user() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    a = await promote_evidence(
        _memory("alice", "prefers mirrorless cameras"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
    )
    b = await promote_evidence(
        _memory("bob", "prefers mirrorless cameras"),
        acting_user_id="bob",
        store=store,
        audit_log=audit,
    )

    assert a.lineage_id != b.lineage_id
    assert [f.fact_id for f in await store.list_for_user("bob")] == [b.fact_id]
    assert [f.fact_id for f in await store.list_for_user("alice")] == [a.fact_id]


async def test_repeat_evidence_reinforces_with_new_revision() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    first = await promote_evidence(
        _memory("alice", "prefers primes"), acting_user_id="alice", store=store, audit_log=audit
    )
    second = await promote_evidence(
        _memory("alice", "Prefers  primes", project_id="proj-b"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
    )

    assert second.lineage_id == first.lineage_id
    assert (second.revision, second.supersedes) == (2, first.fact_id)
    assert second.state is FactState.ACTIVE
    assert second.first_observed == first.first_observed
    assert second.last_reinforced >= first.last_reinforced
    assert [r.project_id for r in second.evidence] == ["proj-a", "proj-b"]
    assert second.confidence > first.confidence


async def test_contradiction_moves_fact_under_review_without_overwrite() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    original = await promote_evidence(
        _memory("alice", "prefers primes"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
        contradiction_fn=_never,
    )

    reviewed = await promote_evidence(
        _memory("alice", "hates prime lenses"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
        contradiction_fn=_always,
    )

    assert reviewed.lineage_id == original.lineage_id
    assert reviewed.state is FactState.UNDER_REVIEW
    assert (reviewed.revision, reviewed.supersedes) == (2, original.fact_id)
    assert reviewed.statement == original.statement
    history = await store.history(original.lineage_id)
    assert history[0] == dataclasses.replace(original, state=FactState.SUPERSEDED)
    assert len(await store.list_for_user("alice")) == 1
    assert [e.action for e in await audit.get_entries(user_id="alice")] == [
        "flag_for_review",
        "promote",
    ]


async def test_correction_appends_revision_with_provenance() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    original = await promote_evidence(
        _memory("alice", "prefers primes"), acting_user_id="alice", store=store, audit_log=audit
    )

    corrected = await correct_fact(
        original.lineage_id,
        acting_user_id="alice",
        statement="prefers zooms for travel",
        reason="changed my kit",
        store=store,
        audit_log=audit,
    )

    assert (corrected.revision, corrected.supersedes) == (2, original.fact_id)
    assert corrected.state is FactState.ACTIVE
    assert corrected.statement == "prefers zooms for travel"
    assert corrected.correction is not None
    assert (corrected.correction.corrected_by, corrected.correction.reason) == (
        "alice",
        "changed my kit",
    )
    assert (await store.history(original.lineage_id))[0].statement == "prefers primes"

    with pytest.raises(StaleEvidenceError):
        await promote_evidence(
            _memory("alice", "prefers primes"),
            acting_user_id="alice",
            store=store,
            audit_log=audit,
        )
    with pytest.raises(PermissionError):
        await correct_fact(
            original.lineage_id,
            acting_user_id="bob",
            statement="x",
            reason="y",
            store=store,
            audit_log=audit,
        )
    with pytest.raises(KeyError):
        await correct_fact(
            "missing",
            acting_user_id="alice",
            statement="x",
            reason="y",
            store=store,
            audit_log=audit,
        )


async def test_tombstoned_fact_cannot_be_recreated_by_promotion() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    fact = await promote_evidence(
        _memory("alice", "prefers primes"), acting_user_id="alice", store=store, audit_log=audit
    )

    await forget_fact(
        fact.lineage_id, acting_user_id="alice", reason="forget this", store=store, audit_log=audit
    )

    with pytest.raises(TombstonedLineageError):
        await promote_evidence(
            _memory("alice", "prefers primes"),
            acting_user_id="alice",
            store=store,
            audit_log=audit,
        )
    with pytest.raises(TombstonedLineageError):
        await correct_fact(
            fact.lineage_id,
            acting_user_id="alice",
            statement="x",
            reason="y",
            store=store,
            audit_log=audit,
        )
    assert [e.action for e in await audit.get_entries(user_id="alice")] == [
        "promote",
        "forget",
        "promote",
    ]
