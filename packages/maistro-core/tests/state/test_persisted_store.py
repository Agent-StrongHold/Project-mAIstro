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

from maistro.state import PersistedStore, State


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

    def test_times_out_when_the_writer_never_runs_the_transaction(
        self, state_with_store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bounded like every other write in this module (`put_raw_if_absent`
        has the same `completed.wait(timeout=...)` guard): a writer that never
        drains the queue must not hang the caller forever."""
        state, store = state_with_store
        monkeypatch.setattr(state, "submit", lambda _fn: None)

        with pytest.raises(TimeoutError, match="timed out waiting for unique model write"):
            store.put_model_unique(
                "users", "u1", SampleModel(id="u1", name="alice"), ("name",), timeout=0.01
            )


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

    def test_times_out_when_the_writer_never_runs_the_transaction(
        self, state_with_store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bounded like every other write in this module: a writer that never
        drains the queue must not hang the caller forever."""
        state, store = state_with_store
        monkeypatch.setattr(state, "submit", lambda _fn: None)

        with pytest.raises(TimeoutError, match="timed out waiting for unique model insert"):
            store.put_model_if_unique(
                "users", "u1", SampleModel(id="u1", name="alice"), "name", timeout=0.01
            )


class UserLikeModel(BaseModel):
    """Stands in for hive-conductor's ``HiveUser`` — the field name (not just
    the store name) matters here, since the reconciliation warning and the
    DB-level index below both key off `$.username` specifically."""

    id: str
    username: str


def _write_raw_user(state: State, key: str, username: str) -> None:
    """Insert a `users` row straight into `kv_store`, bypassing every
    unique-claim code path — the shape of a pre-#1248 legacy write, and of a
    same-DB write from an old-version process during a rolling upgrade."""
    conn = state._writer
    assert conn is not None
    conn.execute(
        "INSERT INTO kv_store (store_name, key, value, updated_at) VALUES (?, ?, ?, ?)",
        ("users", key, f'{{"id": "{key}", "username": "{username}"}}', "2026-01-01T00:00:00Z"),
    )
    conn.commit()


class TestDuplicateUsernameMigrationReconciliation:
    """Codex review finding 2 (PR #1528): `kv_unique_fields_001`'s
    ``INSERT OR IGNORE`` claims a `unique_fields` row for only the first
    pre-existing `users` record it sees per normalized username, leaving
    every other duplicate active and unclaimed. `PersistedStore.initialize()`
    must surface that loudly rather than silently accept the ambiguity."""

    def test_unclaimed_legacy_duplicates_are_logged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        # Three pre-existing rows share one username — only the first can be
        # claimed by INSERT OR IGNORE's per-normalized-value primary key.
        _write_raw_user(state, "legacy-1", "duplicate")
        _write_raw_user(state, "legacy-2", "duplicate")
        _write_raw_user(state, "legacy-3", "Duplicate")  # casefold-equal too
        _write_raw_user(state, "legacy-4", "unique-one")

        with caplog.at_level("WARNING", logger="maistro.state"):
            store = PersistedStore(state)
            store.initialize()

        warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
        reconciliation_warnings = [w for w in warnings if "no durable uniqueness claim" in w]
        assert len(reconciliation_warnings) == 1
        message = reconciliation_warnings[0]
        assert "2 " in message  # two of the three duplicates are unclaimed
        assert "legacy-2" in message or "legacy-3" in message
        assert "legacy-4" not in message  # the unambiguous row is not flagged

        reader = state.open_reader()
        try:
            claimed = {
                row[0]
                for row in reader.execute(
                    "SELECT record_key FROM unique_fields "
                    "WHERE store_name = 'users' AND field_name = 'username'"
                ).fetchall()
            }
        finally:
            reader.close()
        # Exactly one of the three duplicates holds the claim; the other two
        # remain active, unclaimed rows in kv_store — the exact ambiguity the
        # warning exists to surface, not silently resolve on its own.
        assert len(claimed & {"legacy-1", "legacy-2", "legacy-3"}) == 1
        assert "legacy-4" in claimed
        state.close()

    def test_no_warning_when_usernames_are_unique(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        _write_raw_user(state, "u1", "alice")
        _write_raw_user(state, "u2", "bob")

        with caplog.at_level("WARNING", logger="maistro.state"):
            store = PersistedStore(state)
            store.initialize()

        assert not [r for r in caplog.records if "duplicate username" in r.message]
        state.close()

    def test_account_created_through_the_atomic_seam_is_not_flagged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """#1061's canonical claim IS a durable uniqueness claim.

        Account allocation writes the claim and the user row in one
        transaction and bypasses `put_model_unique`, so such a row holds no
        `unique_fields` row until its first password rehash. Warning about it
        on every restart told operators a healthy hive held an ambiguous
        duplicate — the false alarm the canonical-claim clause removes, while
        genuinely unclaimed rows stay loud.
        """
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        assert store.put_raw_with_unique_claims(
            [
                (
                    "username_claims",
                    "username:alice",
                    '{"schema_version": 1, "status": "active", '
                    '"normalized_username": "alice", "user_id": "u1"}',
                )
            ],
            [("users", "u1", '{"id": "u1", "username": "Alice"}')],
        )
        state.flush()

        with caplog.at_level("WARNING", logger="maistro.state"):
            PersistedStore(state).initialize()

        assert not [r for r in caplog.records if "duplicate username" in r.message]
        state.close()

    def test_only_rows_holding_no_durable_claim_are_flagged(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The warning names exactly the rows holding neither layer's claim.

        Pre-existing duplicate rows are written before the migrations apply
        (the rolling-upgrade shape). The backfill claims one of them in
        `unique_fields`, the canonical claim names the other — whichever row
        ends up holding NEITHER is the ambiguous one, and the only one the
        warning may name."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        _write_raw_user(state, "winner", "dupe")
        _write_raw_user(state, "loser", "DUPE")
        PersistedStore(state).put_raw(
            "username_claims",
            "username:dupe",
            '{"schema_version": 1, "status": "active", '
            '"normalized_username": "dupe", "user_id": "winner"}',
        )
        state.flush()

        with caplog.at_level("WARNING", logger="maistro.state"):
            PersistedStore(state).initialize()

        reader = state.open_reader()
        try:
            unique_fields_holder = reader.execute(
                "SELECT record_key FROM unique_fields "
                "WHERE store_name = 'users' AND field_name = 'username' "
                "AND normalized_value = 'dupe'"
            ).fetchone()
        finally:
            reader.close()
        claimed = {"winner", unique_fields_holder[0] if unique_fields_holder else None}
        expected = {"winner", "loser"} - claimed  # a canonically-named row is never flagged

        warnings = [r.message for r in caplog.records if "no durable uniqueness claim" in r.message]
        if expected == {"loser"}:
            assert len(warnings) == 1
            assert "loser" in warnings[0]
            assert "winner" not in warnings[0]
        else:
            # Both rows hold a durable claim (the canonical layer decides
            # login deterministically), so there is no ambiguity to surface.
            assert warnings == []
        state.close()

    def test_quarantined_and_crossed_claims_do_not_silence_the_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Only an ACTIVE claim naming the row suppresses it — a quarantined
        record or a claim pointing at another key leaves the row exactly as
        loud as before the canonical clause existed."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        PersistedStore(state).initialize()
        _write_raw_user(state, "q1", "zara")
        PersistedStore(state).put_raw(
            "username_claims",
            "username:zara",
            '{"schema_version": 1, "status": "quarantined", '
            '"normalized_username": "zara", "candidate_user_ids": ["q1"]}',
        )
        _write_raw_user(state, "crossed", "misty")
        PersistedStore(state).put_raw(
            "username_claims",
            "username:misty",
            '{"schema_version": 1, "status": "active", '
            '"normalized_username": "misty", "user_id": "someone-else"}',
        )
        state.flush()

        with caplog.at_level("WARNING", logger="maistro.state"):
            PersistedStore(state).initialize()

        warnings = [r.message for r in caplog.records if "no durable uniqueness claim" in r.message]
        assert len(warnings) == 1
        for flagged in ("q1", "crossed"):
            assert flagged in warnings[0], flagged
        state.close()

    def test_warning_persists_across_repeated_initialize_calls(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The warning is not a one-shot migration side effect — it must keep
        firing on every startup until an operator actually resolves the
        duplicates, or a fleet that never restarts would never see it again
        after the first boot post-upgrade."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        _write_raw_user(state, "legacy-1", "duplicate")
        _write_raw_user(state, "legacy-2", "duplicate")
        store = PersistedStore(state)

        store.initialize()
        with caplog.at_level("WARNING", logger="maistro.state"):
            store.initialize()

        assert [r for r in caplog.records if "duplicate username" in r.message]
        state.close()


class TestUsernameUniquenessDatabaseBoundary:
    """Codex review finding 4 (PR #1528): `unique_fields` only stops a writer
    that knows to consult it. During a rolling upgrade a still-running
    old-version process registers users through the generic `put()` path,
    which writes straight to `kv_store` without ever touching `unique_fields`
    — invisible to a new-version process's availability check. The
    `kv_users_username_unique_001` migration puts a real SQL UNIQUE index on
    `kv_store` itself, so it is enforced no matter which code path wrote the
    row."""

    def test_index_is_created_on_a_clean_database(self, tmp_path: Path) -> None:
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        store = PersistedStore(state)

        store.initialize()

        reader = state.open_reader()
        try:
            found = reader.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name = 'kv_store_users_username_unique'"
            ).fetchone()
            applied = reader.execute(
                "SELECT 1 FROM schema_migrations WHERE name = 'kv_users_username_unique_001'"
            ).fetchone()
        finally:
            reader.close()
        assert found is not None
        assert applied is not None
        state.close()

    def test_old_code_path_writing_a_duplicate_username_is_rejected_at_the_db(
        self, tmp_path: Path
    ) -> None:
        """Simulates the exact mixed-version scenario: a new-version process
        holds the `unique_fields` claim for "alice"; an old-version process
        (using the generic `put()` path, unaware `unique_fields` exists)
        tries to insert a *second*, differently-keyed row for "alice". The
        DB-level index must refuse it even though `put()` never consults
        `unique_fields`."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        assert store.put_model_unique(
            "users", "u1", UserLikeModel(id="u1", username="alice"), ("username",)
        )

        import sqlite3

        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint failed"):
            # `put`, not `put_model_unique` — the old-version code path, which
            # never checks `unique_fields` and has no special handling for
            # this: the DB-level index is what stops it, and `put()` simply
            # surfaces whatever the writer thread raised (#1238).
            store.put("users", "u2", UserLikeModel(id="u2", username="alice"))

        got = store.get("users", "u2", UserLikeModel)
        assert got is None
        state.close()

    def test_old_code_path_overwriting_its_own_row_to_a_free_username_still_works(
        self, tmp_path: Path
    ) -> None:
        """The index must not block the ordinary, non-colliding case: an
        old-version process updating its own row via `put()` to a username
        nobody else holds."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        store = PersistedStore(state)
        store.initialize()

        store.put("users", "u1", UserLikeModel(id="u1", username="alice"))
        store.put("users", "u1", UserLikeModel(id="u1", username="alice-renamed"))

        got = store.get("users", "u1", UserLikeModel)
        assert got is not None
        assert got.username == "alice-renamed"
        state.close()

    def test_preexisting_legacy_duplicates_degrade_gracefully_without_crashing(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """SQLite refuses to create a UNIQUE index over data that already
        violates it. `initialize()` must not let that abort startup — an
        operator who has not yet resolved the legacy duplicates should still
        get the application-level enforcement this DB already had, with a
        clear warning, not a crash."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        _write_raw_user(state, "legacy-1", "duplicate")
        _write_raw_user(state, "legacy-2", "duplicate")

        with caplog.at_level("WARNING", logger="maistro.state"):
            store = PersistedStore(state)
            store.initialize()  # must not raise

        assert any(
            "username-uniqueness index" in r.message
            for r in caplog.records
            if r.levelname == "WARNING"
        )
        reader = state.open_reader()
        try:
            found = reader.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name = 'kv_store_users_username_unique'"
            ).fetchone()
        finally:
            reader.close()
        assert found is None
        state.close()

    def test_index_is_created_once_legacy_duplicates_are_resolved(self, tmp_path: Path) -> None:
        """The migration is retried on every `initialize()`, so it self-heals
        the moment an operator resolves the duplicates and restarts."""
        db_path = tmp_path / "state.db"
        state = State(db_path=str(db_path))
        state.open_writer()
        state.run_migration(
            "kv_store_001",
            "CREATE TABLE IF NOT EXISTS kv_store "
            "(store_name TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, "
            "updated_at TEXT NOT NULL, PRIMARY KEY (store_name, key))",
        )
        _write_raw_user(state, "legacy-1", "duplicate")
        _write_raw_user(state, "legacy-2", "duplicate")
        store = PersistedStore(state)
        store.initialize()

        # Operator resolves it: remove the loser.
        conn = state._writer
        assert conn is not None
        conn.execute("DELETE FROM kv_store WHERE store_name = 'users' AND key = 'legacy-2'")
        conn.execute(
            "DELETE FROM unique_fields WHERE store_name = 'users' AND record_key = 'legacy-2'"
        )
        conn.commit()

        store.initialize()

        reader = state.open_reader()
        try:
            found = reader.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' "
                "AND name = 'kv_store_users_username_unique'"
            ).fetchone()
        finally:
            reader.close()
        assert found is not None
        state.close()
