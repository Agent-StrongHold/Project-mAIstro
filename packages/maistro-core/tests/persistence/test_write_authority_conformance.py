"""Two-actor write-authority authorization across every memory backend (#390).

ADR-057's enforcement matrix, run against the *real* store classes — in-memory,
SQLite and PostgreSQL — not just the pure gate: for every store and every
backend, an undeclared mode refuses to mutate (fail-closed, ``SPEC-062126-6a31``),
an agent-actor write under ``SYSTEM_MANAGED`` is denied and leaves no partial
durable state, and a system actor writes under every mode. Same three-backend
rule as ``test_backend_conformance``: a backend that skips is a backend not
proven, so PostgreSQL skips only when no server is configured (see conftest).
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.memory.exposure import (
    Actor,
    MemoryExposureMode,
    MemoryUndeclaredModeError,
    MemoryWriteDenied,
)
from maistro.memory.outcomes import InMemoryOutcomeStore
from maistro.types.memory import EpisodicMemory, Learning, MemoryScope, Outcome

pytest.importorskip("aiosqlite")
import aiosqlite

from .conftest import postgres_dsn

assert postgres_dsn is not None  # imported for the skip contract, not called here

#: (backend, declared mode) — None is the fail-closed undeclared case.
_AUTHORITIES = [
    ("memory", None),
    ("memory", MemoryExposureMode.SYSTEM_MANAGED),
    ("memory", MemoryExposureMode.AGENT_MANAGED),
    ("sqlite", None),
    ("sqlite", MemoryExposureMode.SYSTEM_MANAGED),
    ("sqlite", MemoryExposureMode.AGENT_MANAGED),
    ("postgres", None),
    ("postgres", MemoryExposureMode.SYSTEM_MANAGED),
    ("postgres", MemoryExposureMode.AGENT_MANAGED),
]


async def _sqlite_conn() -> aiosqlite.Connection:
    return await aiosqlite.connect(":memory:")


def _learning(**overrides: Any) -> Learning:
    fields: dict[str, Any] = {
        "learning": "roll back before redeploying",
        "trigger_keys": ["deploy"],
        "tool_name": "shell",
        "org_id": "org-authority",
        "agent_id": "artificer",
    }
    fields.update(overrides)
    return Learning(**fields)


def _memory(**overrides: Any) -> EpisodicMemory:
    fields: dict[str, Any] = {
        "content": "the deploy script lives in bin/deploy",
        "org_id": "org-authority",
        "agent_id": "artificer",
        "scope": MemoryScope.ORGANIZATION,
    }
    fields.update(overrides)
    return EpisodicMemory(**fields)


def _outcome(**overrides: Any) -> Outcome:
    fields: dict[str, Any] = {
        "task_type": "chat",
        "model_used": "test-model",
        "org_id": "org-authority",
        "agent_id": "artificer",
    }
    fields.update(overrides)
    return Outcome(**fields)


@pytest.fixture(params=_AUTHORITIES, ids=lambda p: f"{p[0]}-{p[1]}")
async def learning_store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    """Yield ``(store, declared mode)`` for every backend/authority pair."""
    backend, mode = request.param
    if backend == "memory":
        from maistro.memory.learnings.store import InMemoryLearningStore

        yield InMemoryLearningStore(exposure_mode=mode), mode
        return
    if backend == "sqlite":
        from maistro.persistence.sqlite_learnings import SqliteLearningStore

        conn = await _sqlite_conn()
        store = SqliteLearningStore(conn, exposure_mode=mode)
        await store.ensure_schema()
        try:
            yield store, mode
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_learnings import PgLearningStore

    store = PgLearningStore(pg_pool, exposure_mode=mode)
    await store.ensure_schema()
    yield store, mode


@pytest.fixture(params=_AUTHORITIES, ids=lambda p: f"{p[0]}-{p[1]}")
async def episodic_store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    backend, mode = request.param
    if backend == "memory":
        from maistro.memory.episodic.store import InMemoryEpisodicStore

        yield InMemoryEpisodicStore(exposure_mode=mode), mode
        return
    if backend == "sqlite":
        from maistro.persistence.sqlite_episodic import SqliteEpisodicStore

        conn = await _sqlite_conn()
        store = SqliteEpisodicStore(conn, exposure_mode=mode)
        await store.ensure_schema()
        try:
            yield store, mode
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_episodic import PgEpisodicStore

    store = PgEpisodicStore(pg_pool, exposure_mode=mode)
    await store.ensure_schema()
    yield store, mode


@pytest.fixture(params=_AUTHORITIES, ids=lambda p: f"{p[0]}-{p[1]}")
async def outcome_store(request: pytest.FixtureRequest, pg_pool: Any) -> Any:
    backend, mode = request.param
    if backend == "memory":
        yield InMemoryOutcomeStore(exposure_mode=mode), mode
        return
    if backend == "sqlite":
        from maistro.persistence.sqlite_outcomes import SqliteOutcomeStore

        conn = await _sqlite_conn()
        store = SqliteOutcomeStore(conn, exposure_mode=mode)
        await store.ensure_schema()
        try:
            yield store, mode
        finally:
            await conn.close()
        return
    if pg_pool is None:
        pytest.skip("MAISTRO_TEST_PG_DSN is not set")
    from maistro.persistence.pg_outcomes import PgOutcomeStore

    yield PgOutcomeStore(pg_pool, exposure_mode=mode), mode


def _only_mode(mode: Any, wanted: MemoryExposureMode | None) -> None:
    if mode is not wanted:
        pytest.skip(f"matrix case only for {wanted!r}")


# ── learnings: write + promote authority ─────────────────────────


async def test_undeclared_learning_store_refuses_every_mutation(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, None)
    with pytest.raises(MemoryUndeclaredModeError):
        await store.store(_learning(), actor=Actor.SYSTEM)
    with pytest.raises(MemoryUndeclaredModeError):
        await store.check_auto_promotions(actor=Actor.SYSTEM)
    assert await store.list_all() == []


async def test_agent_learning_write_under_system_managed_denied_and_state_untouched(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    with pytest.raises(MemoryWriteDenied):
        await store.store(_learning(), actor=Actor.AGENT)
    # No partial durable state: the denial preceded provenance, dedup and SQL.
    assert await store.list_all(org_id="org-authority") == []


async def test_agent_learning_write_under_agent_managed_persists(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, MemoryExposureMode.AGENT_MANAGED)
    await store.store(_learning(), actor=Actor.AGENT)
    listed = await store.list_all(org_id="org-authority")
    assert len(listed) == 1
    assert listed[0].learning == "roll back before redeploying"


async def test_system_learning_write_under_system_managed_succeeds(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    await store.store(_learning(), actor=Actor.SYSTEM)
    assert len(await store.list_all(org_id="org-authority")) == 1


async def test_agent_promotion_under_system_managed_denied_and_statuses_unchanged(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    learning_id = await store.store(_learning(), actor=Actor.SYSTEM)
    with pytest.raises(MemoryWriteDenied):
        await store.check_auto_promotions(threshold=0, org_id="org-authority", actor=Actor.AGENT)
    listed = await store.list_all(org_id="org-authority")
    assert [lr.status for lr in listed if lr.id == learning_id] == ["active"]


async def test_agent_promotion_under_agent_managed_promotes(
    learning_store: Any,
) -> None:
    store, mode = learning_store
    _only_mode(mode, MemoryExposureMode.AGENT_MANAGED)
    # The M4-B3 evidence contract (ADR-100126-5445) applies on every promotion
    # path, this conformance harness included: the candidate carries the source
    # Run and measured confidence any promotion requires, so this test isolates
    # exactly the ADR-057 authority decision.
    await store.store(_learning(run_id="run-authority", confidence=1.0), actor=Actor.AGENT)
    promoted = await store.check_auto_promotions(
        threshold=0, org_id="org-authority", actor=Actor.AGENT
    )
    assert len(promoted) == 1


# ── episodic: write authority ────────────────────────────────────


async def test_undeclared_episodic_store_refuses_every_write(
    episodic_store: Any,
) -> None:
    store, mode = episodic_store
    _only_mode(mode, None)
    with pytest.raises(MemoryUndeclaredModeError):
        await store.store(_memory(), actor=Actor.SYSTEM)
    assert await store.list_by_scope() == []


async def test_agent_episodic_write_under_system_managed_denied(
    episodic_store: Any,
) -> None:
    store, mode = episodic_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    with pytest.raises(MemoryWriteDenied):
        await store.store(_memory(), actor=Actor.AGENT)
    assert await store.list_by_scope() == []


async def test_agent_episodic_write_under_agent_managed_persists(
    episodic_store: Any,
) -> None:
    store, mode = episodic_store
    _only_mode(mode, MemoryExposureMode.AGENT_MANAGED)
    stored = await store.store(_memory(), actor=Actor.AGENT)
    listed = await store.list_by_scope(org_id="org-authority")
    assert [m.memory_id for m in listed] == [stored]


async def test_system_episodic_write_under_system_managed_succeeds(
    episodic_store: Any,
) -> None:
    store, mode = episodic_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    await store.store(_memory(), actor=Actor.SYSTEM)
    assert len(await store.list_by_scope(org_id="org-authority")) == 1


# ── outcomes: two actors on one record path ──────────────────────


async def test_undeclared_outcome_store_refuses_every_record(
    outcome_store: Any,
) -> None:
    store, mode = outcome_store
    _only_mode(mode, None)
    with pytest.raises(MemoryUndeclaredModeError):
        await store.record(_outcome(), actor=Actor.SYSTEM)


async def test_agent_outcome_record_under_system_managed_denied(
    outcome_store: Any,
) -> None:
    store, mode = outcome_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    with pytest.raises(MemoryWriteDenied):
        await store.record(_outcome(), actor=Actor.AGENT)
    assert await store.list_outcomes(org_id="org-authority") == []


async def test_agent_outcome_record_under_agent_managed_persists(
    outcome_store: Any,
) -> None:
    store, mode = outcome_store
    _only_mode(mode, MemoryExposureMode.AGENT_MANAGED)
    await store.record(_outcome(), actor=Actor.AGENT)
    listed = await store.list_outcomes(org_id="org-authority")
    assert len(listed) == 1


async def test_system_outcome_record_under_system_managed_succeeds(
    outcome_store: Any,
) -> None:
    store, mode = outcome_store
    _only_mode(mode, MemoryExposureMode.SYSTEM_MANAGED)
    await store.record(_outcome(), actor=Actor.SYSTEM)
    assert len(await store.list_outcomes(org_id="org-authority")) == 1
