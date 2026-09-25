"""InMemoryUserModelStore: revision lineage, owner isolation, tombstones (#1047)."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from maistro.memory.user_model import (
    FactState,
    InMemoryUserModelStore,
    RevisionConflictError,
    TombstonedLineageError,
    UserModelFact,
    fact_key,
)
from maistro.protocols.memory import UserModelStore


def _fact(owner: str, statement: str, **overrides: object) -> UserModelFact:
    lineage = fact_key(owner, "preference", statement)
    base = UserModelFact(
        lineage_id=lineage,
        revision=1,
        supersedes=None,
        owner_user_id=owner,
        kind="preference",
        statement=statement,
    )
    return dataclasses.replace(base, **overrides)  # type: ignore[arg-type]


def test_store_satisfies_protocol() -> None:
    assert isinstance(InMemoryUserModelStore(), UserModelStore)


def test_fact_key_is_owner_bound_and_normalized() -> None:
    assert fact_key("u1", "preference", "Likes  Cameras") == fact_key(
        "u1", "preference", "likes cameras"
    )
    assert fact_key("u1", "preference", "likes cameras") != fact_key(
        "u2", "preference", "likes cameras"
    )


def test_fact_rejects_malformed_values() -> None:
    with pytest.raises(ValueError, match="owner_user_id"):
        _fact("", "x")
    with pytest.raises(ValueError, match="confidence"):
        _fact("u1", "x", confidence=1.5)
    with pytest.raises(ValueError, match="revision"):
        _fact("u1", "x", revision=0)
    with pytest.raises(ValueError, match="supersedes"):
        _fact("u1", "x", revision=2)
    now = datetime.now(UTC)
    with pytest.raises(ValueError, match="valid_until"):
        _fact("u1", "x", valid_from=now, valid_until=now - timedelta(days=1))


async def test_append_and_read_current_revision() -> None:
    store = InMemoryUserModelStore()
    first = _fact("u1", "likes cameras")
    await store.append_revision(first)
    second = dataclasses.replace(
        first, fact_id="f2", revision=2, supersedes=first.fact_id, confidence=0.8
    )
    await store.append_revision(second)

    current = await store.current(first.lineage_id)
    assert current is not None
    assert current.fact_id == "f2"
    history = await store.history(first.lineage_id)
    assert [f.revision for f in history] == [1, 2]
    assert await store.current("missing") is None


async def test_append_rejects_out_of_order_revision() -> None:
    store = InMemoryUserModelStore()
    first = _fact("u1", "likes cameras")
    await store.append_revision(first)
    with pytest.raises(RevisionConflictError):
        await store.append_revision(first)
    stale = dataclasses.replace(first, fact_id="f3", revision=2, supersedes="not-current")
    with pytest.raises(RevisionConflictError):
        await store.append_revision(stale)
    foreign = dataclasses.replace(
        first, fact_id="f4", revision=2, supersedes=first.fact_id, owner_user_id="u2"
    )
    with pytest.raises(RevisionConflictError):
        await store.append_revision(foreign)


async def test_list_for_user_never_returns_other_owner_facts() -> None:
    store = InMemoryUserModelStore()
    await store.append_revision(_fact("alice", "likes cameras"))
    await store.append_revision(_fact("bob", "likes cameras"))

    bob = await store.list_for_user("bob")
    assert [f.owner_user_id for f in bob] == ["bob"]
    assert await store.list_for_user("") == []
    assert await store.list_for_user("carol") == []


async def test_tombstone_hides_lineage_purges_content_and_blocks_recreation() -> None:
    store = InMemoryUserModelStore()
    fact = _fact("u1", "likes cameras")
    await store.append_revision(fact)

    tomb = await store.tombstone(fact.lineage_id, acting_user_id="u1", reason="user deleted")

    assert tomb.state is FactState.TOMBSTONED
    assert tomb.statement == ""
    assert tomb.correction is not None
    assert tomb.correction.corrected_by == "u1"
    assert await store.is_tombstoned(fact.lineage_id)
    assert await store.list_for_user("u1") == []
    assert [f.statement for f in await store.history(fact.lineage_id)] == [""]
    with pytest.raises(TombstonedLineageError):
        await store.append_revision(fact)


async def test_tombstone_unknown_or_foreign_lineage_is_refused() -> None:
    store = InMemoryUserModelStore()
    fact = _fact("u1", "likes cameras")
    await store.append_revision(fact)
    with pytest.raises(KeyError):
        await store.tombstone("missing", acting_user_id="u1", reason="x")
    with pytest.raises(PermissionError):
        await store.tombstone(fact.lineage_id, acting_user_id="u2", reason="x")
    assert not await store.is_tombstoned(fact.lineage_id)
