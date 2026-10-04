"""Relevance-gated recall from the user model (#1047).

Authorized access does not imply context injection: these tests pin the
structural zero (a fact with no task/persona/Workspace link scores exactly
0.0 and is never injected), the hard gates (review state, expiry,
non-reusability, sensitivity cap, confidence floor), and the fact that
Persona shapes ranking without ever changing whose facts a query can see.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier
from maistro.memory.user_model import (
    FactSensitivity,
    InMemoryUserModelStore,
    RecallQuery,
    UserModelFact,
    promote_evidence,
    recall,
    score_fact,
)
from maistro.security.sentinel.audit import InMemoryAuditLog

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


def _memory(user_id: str, content: str, **kw: object) -> EpisodicMemory:
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


async def _store_with(user: str, statement: str, **promote_kw: object) -> InMemoryUserModelStore:
    store = InMemoryUserModelStore()
    await promote_evidence(
        _memory(user, statement),
        acting_user_id=user,
        store=store,
        audit_log=InMemoryAuditLog(),
        **promote_kw,
    )
    return store


def _query(owner: str, task: str = "", **kw: object) -> RecallQuery:
    return RecallQuery(owner_user_id=owner, task_text=task, now=_NOW, **kw)  # type: ignore[arg-type]


async def test_task_relevant_fact_is_recalled_and_ranked_first() -> None:
    store = await _store_with("alice", "owns a Canon 7D camera body")

    scored = await recall(store, _query("alice", "set up tethered capture for my camera"))

    assert [item.fact.statement for item in scored] == ["owns a Canon 7D camera body"]
    assert scored[0].score > 0.0


async def test_unrelated_task_scores_structural_zero_and_is_not_injected() -> None:
    """The #1047 non-injection criterion, pinned as an exact structural zero.

    No overlap term, persona term or Workspace affinity exists, so no
    confidence or recency value can push the fact through: an unrelated task
    receives nothing without any tuning.
    """
    store = await _store_with("alice", "owns a Canon 7D camera body")
    fact = (await store.list_for_user("alice"))[0]

    unrelated = _query("alice", "refactor the payment parser module")
    assert score_fact(fact, unrelated) == 0.0
    assert await recall(store, unrelated) == []

    # The zero is structural, not tuned: a maximal-confidence twin of the
    # fact with the same observation stamps still scores zero for the
    # unrelated task.
    confident = UserModelFact(
        lineage_id=fact.lineage_id,
        revision=2,
        supersedes=fact.fact_id,
        owner_user_id="alice",
        kind=fact.kind,
        statement=fact.statement,
        confidence=1.0,
        first_observed=fact.first_observed,
        last_observed=fact.last_observed,
        last_reinforced=fact.last_reinforced,
    )
    assert score_fact(confident, unrelated) == 0.0


async def test_persona_hints_lift_relevant_facts_without_task_overlap() -> None:
    """A photography Persona surfaces camera facts the task text alone missed."""
    store = await _store_with(
        "alice", "owns a Canon 7D camera body", persona_hints=("photography", "camera gear")
    )
    fact = (await store.list_for_user("alice"))[0]

    blogger = _query(
        "alice",
        "draft the restaurant review",
        persona_hints=("photography", "camera", "lenses"),
    )
    assert score_fact(fact, blogger) > 0.0
    general = _query("alice", "draft the restaurant review")
    assert score_fact(fact, general) == 0.0


async def test_expired_fact_is_not_recalled() -> None:
    store = InMemoryUserModelStore()
    await store.append_revision(
        UserModelFact(
            lineage_id="lin-expired",
            revision=1,
            supersedes=None,
            owner_user_id="alice",
            kind="status",
            statement="lives in Austin",
            valid_from=_NOW - timedelta(days=400),
            valid_until=_NOW - timedelta(days=30),
        )
    )

    assert await recall(store, _query("alice", "austin weather today")) == []

    # Inside its window the same kind of fact recalls: expiry, not the
    # statement, kept the first one out.
    await store.append_revision(
        UserModelFact(
            lineage_id="lin-live",
            revision=1,
            supersedes=None,
            owner_user_id="alice",
            kind="status",
            statement="currently lives in Austin",
            valid_until=_NOW + timedelta(days=30),
        )
    )
    recalled = await recall(store, _query("alice", "austin"))
    assert [item.fact.lineage_id for item in recalled] == ["lin-live"]


async def test_sensitive_facts_need_an_explicit_surface_opt_in() -> None:
    store = InMemoryUserModelStore()
    await store.append_revision(
        UserModelFact(
            lineage_id="lin-health",
            revision=1,
            supersedes=None,
            owner_user_id="alice",
            kind="health",
            statement="takes metformin daily",
            sensitivity=FactSensitivity.SENSITIVE,
        )
    )

    assert await recall(store, _query("alice", "metformin prescription refill")) == []
    opted_in = _query(
        "alice", "metformin prescription refill", max_sensitivity=FactSensitivity.SENSITIVE
    )
    assert len(await recall(store, opted_in)) == 1


async def test_owner_marked_private_facts_are_never_surfaced() -> None:
    from maistro.memory.user_model.service import UserModelService

    store = await _store_with("alice", "owns a Canon 7D camera body")
    service = UserModelService(store=store, audit_log=InMemoryAuditLog())
    lineage = (await store.list_for_user("alice"))[0].lineage_id

    await service.mark_not_reusable(
        lineage, acting_user_id="alice", reason="keep this out of task context"
    )

    assert await recall(store, _query("alice", "which camera should I take")) == []
    # The fact is kept, not deleted: the owner still sees it in their model.
    kept = (await service.facts("alice"))[0]
    assert kept.statement == "owns a Canon 7D camera body"
    assert kept.reusable is False


async def test_confidence_floor_gates_low_confidence_facts() -> None:
    store = InMemoryUserModelStore()
    await store.append_revision(
        UserModelFact(
            lineage_id="lin-weak",
            revision=1,
            supersedes=None,
            owner_user_id="alice",
            kind="preference",
            statement="prefers dark mode terminals",
            confidence=0.2,
        )
    )

    assert (
        await recall(store, _query("alice", "dark mode terminal setup", min_confidence=0.5)) == []
    )
    assert (
        len(await recall(store, _query("alice", "dark mode terminal setup", min_confidence=0.1)))
        == 1
    )


async def test_reinforced_fact_outranks_an_unreinforced_twin() -> None:
    store = InMemoryUserModelStore()
    audit = InMemoryAuditLog()
    # Two independent observations of the same fact: the lineage is
    # reinforced, raising both its confidence and its recency stamp.
    await promote_evidence(
        _memory("alice", "owns a Canon 7D camera", run_id="run-1"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
    )
    fresh = await promote_evidence(
        _memory("alice", "owns a Canon 7D camera", run_id="run-2"),
        acting_user_id="alice",
        store=store,
        audit_log=audit,
    )
    assert fresh.revision == 2 and fresh.confidence > 0.5
    stale = UserModelFact(
        lineage_id="lin-stale",
        revision=1,
        supersedes=None,
        owner_user_id="alice",
        kind="possession",
        statement="has a Canon 7D camera",
        confidence=0.5,
        first_observed=_NOW - timedelta(days=120),
        last_observed=_NOW - timedelta(days=120),
        last_reinforced=_NOW - timedelta(days=120),
    )
    await store.append_revision(stale)

    scored = await recall(store, _query("alice", "canon camera"))
    assert [item.fact.lineage_id for item in scored] == [fresh.lineage_id, "lin-stale"]
    assert scored[0].score > scored[1].score


@pytest.mark.parametrize("owner,task", [("bob", "which camera should I take"), ("alice", "")])
async def test_recall_never_crosses_owners(owner: str, task: str) -> None:
    """Persona/task affinity cannot widen authorization to another owner."""
    store = await _store_with("alice", "owns a Canon 7D camera body")

    assert await recall(store, _query(owner, task)) == []
    assert await recall(store, _query("BOB", "owns a Canon 7D camera body")) == []


async def test_recall_order_is_deterministic() -> None:
    store = await _store_with("alice", "owns a Canon 7D camera body")
    await store.append_revision(
        UserModelFact(
            lineage_id="lin-lens",
            revision=1,
            supersedes=None,
            owner_user_id="alice",
            kind="possession",
            statement="owns a Canon 7D camera battery grip",
        )
    )

    first = await recall(store, _query("alice", "which camera body and grip"))
    second = await recall(store, _query("alice", "which camera body and grip"))
    assert len(first) == 2
    assert [item.fact.fact_id for item in first] == [item.fact.fact_id for item in second]
    assert [item.score for item in first] == [item.score for item in second]
