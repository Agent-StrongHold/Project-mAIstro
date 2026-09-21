"""PersistedStore — dict-like persistence over SQLite via State.

These tests define the contract for a key-value store that serializes
Pydantic models to JSON and persists them through the State module's
singleton writer.
"""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel, Field


class SampleModel(BaseModel):
    id: str
    name: str
    value: int = 0
    tags: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class NestedModel(BaseModel):
    id: str
    title: str
    items: list[SampleModel] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


@pytest.fixture()
def state_with_store(tmp_path: Path):
    from maistro.state import PersistedStore, State

    db_path = tmp_path / "state.db"
    state = State(db_path=str(db_path))
    store = PersistedStore(state)
    store.initialize()
    yield state, store
    state.close()


class TestPutAndGet:
    def test_put_then_get_returns_model(self, state_with_store) -> None:
        state, store = state_with_store
        model = SampleModel(id="k1", name="test", value=42)
        store.put("items", "k1", model)
        state.flush()

        result = store.get("items", "k1", SampleModel)
        assert result is not None
        assert result.id == "k1"
        assert result.name == "test"
        assert result.value == 42

    def test_get_missing_key_returns_none(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.get("items", "nonexistent", SampleModel) is None

    def test_get_from_empty_store_returns_none(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.get("anything", "anykey", SampleModel) is None


class TestListAll:
    def test_list_all_returns_all_items(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "a", SampleModel(id="a", name="alpha"))
        store.put("items", "b", SampleModel(id="b", name="beta"))
        store.put("items", "c", SampleModel(id="c", name="gamma"))
        state.flush()

        results = store.list_all("items", SampleModel)
        assert len(results) == 3
        by_id = {r.id: r for r in results}
        assert by_id["a"].name == "alpha"
        assert by_id["b"].name == "beta"
        assert by_id["c"].name == "gamma"

    def test_list_all_empty_store(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.list_all("items", SampleModel) == []

    def test_list_all_respects_store_name(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("store_a", "k1", SampleModel(id="k1", name="a"))
        store.put("store_b", "k1", SampleModel(id="k1", name="b"))
        state.flush()

        a_items = store.list_all("store_a", SampleModel)
        b_items = store.list_all("store_b", SampleModel)
        assert len(a_items) == 1
        assert len(b_items) == 1
        assert a_items[0].name == "a"
        assert b_items[0].name == "b"


class TestDelete:
    def test_delete_removes_item(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="test"))
        state.flush()

        store.delete("items", "k1")
        state.flush()

        assert store.get("items", "k1", SampleModel) is None

    def test_delete_missing_key_is_noop(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "present", SampleModel(id="present", name="kept"))
        state.flush()
        store.delete("items", "nonexistent")
        state.flush()

        assert store.get("items", "present", SampleModel) == SampleModel(id="present", name="kept")


class TestContains:
    def test_contains_returns_true_for_existing(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="test"))
        state.flush()

        assert store.contains("items", "k1") is True

    def test_contains_returns_false_for_missing(self, state_with_store) -> None:
        _, store = state_with_store
        assert store.contains("items", "missing") is False


class TestOverwrite:
    def test_put_same_key_overwrites(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="first", value=1))
        state.flush()

        store.put("items", "k1", SampleModel(id="k1", name="second", value=2))
        state.flush()

        result = store.get("items", "k1", SampleModel)
        assert result is not None
        assert result.name == "second"
        assert result.value == 2

    def test_list_all_count_after_overwrite(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("items", "k1", SampleModel(id="k1", name="first"))
        store.put("items", "k1", SampleModel(id="k1", name="second"))
        state.flush()

        assert len(store.list_all("items", SampleModel)) == 1


class TestComplexModel:
    def test_nested_model_roundtrip(self, state_with_store) -> None:
        state, store = state_with_store
        now = datetime.now(UTC)
        model = NestedModel(
            id="n1",
            title="complex",
            items=[
                SampleModel(id="s1", name="sub1", tags=["a", "b"]),
                SampleModel(id="s2", name="sub2", meta={"x": 1}),
            ],
            created_at=now,
        )
        store.put("nested", "n1", model)
        state.flush()

        result = store.get("nested", "n1", NestedModel)
        assert result is not None
        assert result.title == "complex"
        assert len(result.items) == 2
        assert result.items[0].tags == ["a", "b"]
        assert result.items[1].meta == {"x": 1}


class TestPersistenceAcrossRestart:
    def test_data_survives_close_and_reopen(self, tmp_path: Path) -> None:
        from maistro.state import PersistedStore, State

        db_path = tmp_path / "state.db"

        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()
        store.put("items", "k1", SampleModel(id="k1", name="persisted", value=99))
        state.flush()
        state.close()

        state2 = State(db_path=str(db_path))
        store2 = PersistedStore(state2)
        store2.initialize()
        result = store2.get("items", "k1", SampleModel)
        state2.close()

        assert result is not None
        assert result.name == "persisted"
        assert result.value == 99


class TestConcurrentWrites:
    def test_many_threads_writing_same_store(self, state_with_store) -> None:
        state, store = state_with_store
        errors: list[Exception] = []

        def write_item(idx: int) -> None:
            try:
                store.put("items", f"k{idx}", SampleModel(id=f"k{idx}", name=f"item-{idx}"))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=write_item, args=(i,)) for i in range(100)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        state.flush()
        assert len(errors) == 0

        results = store.list_all("items", SampleModel)
        assert len(results) == 100


class TestMultipleStores:
    def test_different_stores_isolated(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("missions", "m1", SampleModel(id="m1", name="mission"))
        store.put("agents", "a1", SampleModel(id="a1", name="agent"))
        state.flush()

        missions = store.list_all("missions", SampleModel)
        agents = store.list_all("agents", SampleModel)
        assert len(missions) == 1
        assert len(agents) == 1
        assert missions[0].name == "mission"
        assert agents[0].name == "agent"

    def test_delete_from_one_store_doesnt_affect_other(self, state_with_store) -> None:
        state, store = state_with_store
        store.put("missions", "k1", SampleModel(id="k1", name="mission"))
        store.put("agents", "k1", SampleModel(id="k1", name="agent"))
        state.flush()

        store.delete("missions", "k1")
        state.flush()

        assert store.get("missions", "k1", SampleModel) is None
        assert store.get("agents", "k1", SampleModel) is not None


class TwoFieldModel(BaseModel):
    """A model with two candidate unique fields, for testing multi-field claims."""

    id: str
    name: str
    email: str


class TestPutModelUnique:
    """PersistedStore.put_model_unique (#1248/#1259) — the transactional upsert
    that keeps a record's durable uniqueness claim(s) consistent with its row.

    The claim table (``unique_fields``) is normalized-value keyed per
    (store_name, field_name); a write that would collide with a claim held by
    a *different* record key is rejected before either table is touched.
    """

    def test_new_record_claims_the_field_and_persists(self, state_with_store) -> None:
        state, store = state_with_store
        model = SampleModel(id="u1", name="alice")

        assert store.put_model_unique("users", "u1", model, ("name",)) is True

        got = store.get("users", "u1", SampleModel)
        assert got is not None
        assert got.name == "alice"

        reader = state.open_reader()
        try:
            row = reader.execute(
                "SELECT record_key FROM unique_fields "
                "WHERE store_name = ? AND field_name = ? AND normalized_value = ?",
                ("users", "name", "alice"),
            ).fetchone()
        finally:
            reader.close()
        assert row is not None
        assert row[0] == "u1"

    def test_resaving_the_same_key_updates_without_conflict(self, state_with_store) -> None:
        """The claim belongs to the row's own key, so re-upserting it is not
        a collision (`existing[0] != key` is False) — it takes the DELETE +
        re-INSERT path and still lands the new field values."""
        state, store = state_with_store
        store.put_model_unique("users", "u1", SampleModel(id="u1", name="alice"), ("name",))

        assert (
            store.put_model_unique(
                "users", "u1", SampleModel(id="u1", name="alice", value=7), ("name",)
            )
            is True
        )

        got = store.get("users", "u1", SampleModel)
        assert got.value == 7
        reader = state.open_reader()
        try:
            count = reader.execute(
                "SELECT COUNT(*) FROM unique_fields WHERE store_name = ? AND record_key = ?",
                ("users", "u1"),
            ).fetchone()[0]
        finally:
            reader.close()
        assert count == 1

    def test_second_key_with_same_normalized_value_is_rejected(self, state_with_store) -> None:
        state, store = state_with_store
        store.put_model_unique("users", "u1", SampleModel(id="u1", name="alice"), ("name",))

        # Casefold-equal, not identical — the claim compares normalized values.
        rejected = store.put_model_unique(
            "users", "u2", SampleModel(id="u2", name="Alice"), ("name",)
        )

        assert rejected is False
        assert store.get("users", "u2", SampleModel) is None
        reader = state.open_reader()
        try:
            count = reader.execute(
                "SELECT COUNT(*) FROM unique_fields WHERE store_name = ? AND record_key = ?",
                ("users", "u2"),
            ).fetchone()[0]
        finally:
            reader.close()
        assert count == 0

    def test_second_unique_field_collision_also_rejects(self, state_with_store) -> None:
        """Every field in `unique_fields` is a separate claim; a collision on
        the second one is enough to refuse the whole write, and the first
        field's still-free value must not be claimed either (the loop returns
        before any INSERT)."""
        state, store = state_with_store
        store.put_model_unique(
            "users",
            "u1",
            TwoFieldModel(id="u1", name="alice", email="a@example.com"),
            ("name", "email"),
        )

        rejected = store.put_model_unique(
            "users",
            "u2",
            TwoFieldModel(id="u2", name="bob", email="a@example.com"),
            ("name", "email"),
        )

        assert rejected is False
        assert store.get("users", "u2", TwoFieldModel) is None
        reader = state.open_reader()
        try:
            row = reader.execute(
                "SELECT record_key FROM unique_fields "
                "WHERE store_name = ? AND field_name = ? AND normalized_value = ?",
                ("users", "name", "bob"),
            ).fetchone()
        finally:
            reader.close()
        # The `name` field was free, but must not have been claimed on a
        # write that was refused for the `email` collision.
        assert row is None

    def test_bad_field_name_surfaces_as_runtime_error(self, state_with_store) -> None:
        """An attribute error inside the writer thread's transaction is
        caught, rolled back, and re-raised on the calling thread — never
        left to hang or to silently drop the write."""
        _, store = state_with_store
        model = SampleModel(id="u1", name="alice")

        with pytest.raises(RuntimeError, match="unique model write failed"):
            store.put_model_unique("users", "u1", model, ("does_not_exist",))

        assert store.get("users", "u1", SampleModel) is None


class TestPutModelIfUnique:
    """PersistedStore.put_model_if_unique (#1248/#1259) — check-then-insert as
    one transaction, so two independent process writers cannot both publish a
    UUID-keyed record for the same field value (the registration race)."""

    def test_inserts_when_the_field_value_is_available(self, state_with_store) -> None:
        _, store = state_with_store

        assert (
            store.put_model_if_unique("users", "u1", SampleModel(id="u1", name="alice"), "name")
            is True
        )

        got = store.get("users", "u1", SampleModel)
        assert got is not None
        assert got.name == "alice"

    def test_rejects_when_the_field_value_is_already_claimed(self, state_with_store) -> None:
        _, store = state_with_store
        store.put_model_if_unique("users", "u1", SampleModel(id="u1", name="alice"), "name")

        rejected = store.put_model_if_unique(
            "users", "u2", SampleModel(id="u2", name="ALICE"), "name"
        )

        assert rejected is False
        assert store.get("users", "u2", SampleModel) is None

    def test_rejected_insert_leaves_the_original_record_untouched(self, state_with_store) -> None:
        _, store = state_with_store
        store.put_model_if_unique(
            "users", "u1", SampleModel(id="u1", name="alice", value=1), "name"
        )

        store.put_model_if_unique(
            "users", "u2", SampleModel(id="u2", name="alice", value=2), "name"
        )

        original = store.get("users", "u1", SampleModel)
        assert original.value == 1

    def test_kv_row_collision_after_a_successful_claim_surfaces_as_runtime_error(
        self, state_with_store
    ) -> None:
        """The claim insert and the kv_store insert are one transaction. If the
        claim insert succeeds (the field value is free) but the *key* already
        has a row in ``kv_store`` from outside this method (no ``ON CONFLICT``
        clause here, unlike ``put``), the second INSERT raises — and the whole
        transaction, claim included, must roll back rather than leave an
        orphaned claim with no matching record."""
        state, store = state_with_store
        # A pre-existing row for this key, written directly (bypassing the
        # unique-claim machinery) — the situation a migration or an older
        # code path could leave behind.
        store.put("users", "u1", SampleModel(id="u1", name="preexisting"))

        with pytest.raises(RuntimeError, match="unique model insert failed"):
            store.put_model_if_unique("users", "u1", SampleModel(id="u1", name="newclaim"), "name")

        # The row is unchanged, and the claim insert was rolled back with it.
        got = store.get("users", "u1", SampleModel)
        assert got.name == "preexisting"
        reader = state.open_reader()
        try:
            row = reader.execute(
                "SELECT record_key FROM unique_fields "
                "WHERE store_name = ? AND field_name = ? AND normalized_value = ?",
                ("users", "name", "newclaim"),
            ).fetchone()
        finally:
            reader.close()
        assert row is None
