"""Conformance of the durable PostgreSQL user-model store (#1047).

Runs the same protocol cases the in-memory twin satisfies in
``test_store.py`` against the real system of record, plus the restart case:
a *new* store instance over the same database reads back what the previous
one wrote. Skipped unless ``MAISTRO_TEST_PG_DSN`` names a migrated
PostgreSQL (CI starts the service and runs ``alembic upgrade head`` first),
like the other backend-parametrized conformance suites.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from maistro.memory.user_model import (
    FactState,
    PostgresUserModelStore,
    RevisionConflictError,
    TombstonedLineageError,
    UserModelFact,
    fact_key,
)
from maistro.memory.user_model.promotion import promote_evidence
from maistro.memory.user_model.service import UserModelService
from maistro.memory.user_model.types import Correction
from maistro.protocols.memory import UserModelStore
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.testing.postgres import postgres_dsn

pytestmark = [
    pytest.mark.skipif(postgres_dsn() == "", reason="no MAISTRO_TEST_PG_DSN configured"),
]


def _factory() -> async_sessionmaker:
    engine = create_async_engine(postgres_dsn())
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
async def store() -> PostgresUserModelStore:
    """A store over a database; each test starts from empty tables."""
    factory = _factory()
    async with factory() as session, session.begin():
        await session.execute(sql_text("DELETE FROM user_model_statement_keys"))
        await session.execute(sql_text("DELETE FROM user_model_facts"))
    return PostgresUserModelStore(factory)


def _fact(owner: str, statement: str, revision: int = 1, **kw: object) -> UserModelFact:
    fields: dict[str, object] = {
        "lineage_id": f"lin-{owner}-{revision}-{abs(hash(statement)) % 10**8}",
        "revision": revision,
        "supersedes": None if revision == 1 else f"prev-{revision - 1}",
        "owner_user_id": owner,
        "kind": "preference",
        "statement": statement,
    }
    fields.update(kw)
    return UserModelFact(**fields)  # type: ignore[arg-type]


async def test_store_satisfies_protocol(store: PostgresUserModelStore) -> None:
    assert isinstance(store, UserModelStore)


async def test_round_trips_every_field_through_durable_rows(
    store: PostgresUserModelStore,
) -> None:
    """Sensitivity, validity windows, correction and hints survive the row."""
    valid_until = datetime(2027, 1, 1, tzinfo=UTC)
    fact = _fact(
        "pg-alice",
        "round-trips every field",
        sensitivity="sensitive",
        valid_until=valid_until,
        persona_hints=("photography",),
        confidence=0.8,
    )
    fact = dataclasses.replace(
        fact,
        correction=Correction(corrected_by="pg-alice", reason="seeded"),
        evidence=(),
    )
    await store.append_revision(fact)

    read_back = await store.current(fact.lineage_id)
    assert read_back == fact
    assert read_back is not None
    assert read_back.sensitivity.value == "sensitive"
    assert read_back.valid_until == valid_until
    assert read_back.persona_hints == ("photography",)
    assert read_back.correction is not None
    assert read_back.correction.reason == "seeded"


async def test_out_of_order_revision_is_refused(store: PostgresUserModelStore) -> None:
    lineage = "lin-pg-order"
    head = await store.append_revision(_fact("pg-alice", "order check", lineage_id=lineage))
    with pytest.raises(RevisionConflictError):
        await store.append_revision(
            dataclasses.replace(
                _fact("pg-alice", "order check", lineage_id=lineage),
                fact_id="wrong-order",
                revision=head.revision + 2,
                supersedes=head.fact_id,
            )
        )


async def test_list_for_user_is_owner_scoped(store: PostgresUserModelStore) -> None:
    await store.append_revision(_fact("pg-alice", "alice only fact"))
    await store.append_revision(_fact("pg-bob", "alice only fact"))

    assert [f.owner_user_id for f in await store.list_for_user("pg-alice")] == ["pg-alice"]
    assert [f.owner_user_id for f in await store.list_for_user("pg-bob")] == ["pg-bob"]
    assert await store.list_for_user("") == []


async def test_tombstone_purges_content_and_blocks_every_wording(
    store: PostgresUserModelStore,
) -> None:
    lineage = "lin-pg-tomb"
    head = await store.append_revision(_fact("pg-alice", "secret camera wish", lineage_id=lineage))
    await store.append_revision(
        dataclasses.replace(
            _fact("pg-alice", "wants a new secret camera", lineage_id=lineage),
            fact_id="rev2",
            revision=2,
            supersedes=head.fact_id,
        )
    )

    tomb = await store.tombstone(lineage, acting_user_id="pg-alice", reason="user asked to forget")
    assert tomb.state is FactState.TOMBSTONED
    assert tomb.statement == ""
    assert tomb.correction is not None and tomb.correction.reason == "user asked to forget"

    # Content revisions are gone from the record.
    history = await store.history(lineage)
    assert [rev.state for rev in history] == [FactState.TOMBSTONED]
    assert await store.is_tombstoned(lineage)
    # Both wordings the lineage ever held stay blocked, by lineage and by key.
    assert await store.is_tombstoned(fact_key("pg-alice", "secret camera wish"))
    assert await store.is_tombstoned(fact_key("pg-alice", "wants a new secret camera"))
    with pytest.raises(TombstonedLineageError):
        await store.append_revision(
            _fact("pg-alice", "secret camera wish", lineage_id="lin-pg-fresh")
        )
    # A foreign or unknown lineage still looks like a missing one.
    with pytest.raises(KeyError):
        await store.tombstone(lineage, acting_user_id="pg-bob", reason="not mine")
    await store.tombstone(lineage, acting_user_id="pg-alice", reason="idempotent")


async def test_fact_survives_a_store_restart(store: PostgresUserModelStore) -> None:
    """A new store instance over the same database reads back the fact."""
    await store.append_revision(_fact("pg-alice", "durable across restarts"))

    revived_store = PostgresUserModelStore(_factory())
    read_back = await revived_store.current(fact_key("pg-alice", "durable across restarts"))
    assert read_back is not None
    assert read_back.statement == "durable across restarts"


async def test_service_promotes_corrects_and_forgets_through_the_durable_twin(
    store: PostgresUserModelStore,
) -> None:
    from maistro.memory.types import EpisodicMemory, MemoryScope, MemoryTier

    audit = InMemoryAuditLog()
    service = UserModelService(store=store, audit_log=audit)
    memory = EpisodicMemory(
        tier=MemoryTier.OBSERVATION,
        content="prefers postgres-backed memory",
        user_id="pg-alice",
        agent_id="agent-1",
        scope=MemoryScope.AGENT,
        project_id="proj-a",
        run_id="run-1",
    )
    fact = await promote_evidence(
        memory,
        acting_user_id="pg-alice",
        store=store,
        audit_log=audit,
        workspace_id="ws-a",
    )
    assert fact.owner_user_id == "pg-alice"

    corrected = await service.correct(
        fact.lineage_id,
        acting_user_id="pg-alice",
        statement="prefers postgres-backed memory, confirmed",
        reason="user confirmed",
    )
    assert corrected.revision == 2

    await service.forget(fact.lineage_id, acting_user_id="pg-alice", reason="cleanup")
    assert await service.facts("pg-alice") == []
    with pytest.raises(TombstonedLineageError):
        await promote_evidence(
            memory,
            acting_user_id="pg-alice",
            store=store,
            audit_log=audit,
            workspace_id="ws-a",
        )
    # The audited promotions are in the log; the in-memory audit recorded them.
    assert await audit.get_entries(user_id="pg-alice")
