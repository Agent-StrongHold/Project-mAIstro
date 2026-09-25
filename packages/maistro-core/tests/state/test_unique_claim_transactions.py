"""The atomic username-claim transactions behind canonical account allocation.

`put_raw_with_unique_claims` and `delete_raw_with_unique_claims` are the
storage seam #1061 builds on: a username claim and its user row must land in
one SQLite transaction, and a rollback must remove exactly the matching pair.
Hive-conductor exercises them through its username registry, but the contract
is the persistence layer's, so it is defined here against `PersistedStore`
directly — including every refusal path that leaves a partial allocation
undone.
"""

from __future__ import annotations

from typing import Any

import pytest

from maistro.state import PersistedStore, State


@pytest.fixture()
def persisted(tmp_path: Any):
    state = State(db_path=str(tmp_path / "claims.db"))
    store = PersistedStore(state)
    store.initialize()
    yield state, store
    state.close()


CLAIM = ("username_claims", "username:alice", '{"status": "active", "user_id": "u1"}')
# `delete_raw_with_unique_claims` reads the same triple as `(store, key,
# expected_owner_id)` — the owner check, not the payload.
DELAIM = ("username_claims", "username:alice", "u1")
RECORD = ("users", "u1", '{"id": "u1", "username": "Alice"}')


class TestPutRawWithUniqueClaims:
    def test_claims_and_records_land_together(self, persisted) -> None:
        state, store = persisted

        assert store.put_raw_with_unique_claims([CLAIM], [RECORD]) is True
        state.flush()
        assert store.get_raw("username_claims", "username:alice") is not None
        assert store.get_raw("users", "u1") is not None

    def test_empty_claims_or_records_is_refused(self, persisted) -> None:
        _, store = persisted

        with pytest.raises(ValueError, match="needs claims and records"):
            store.put_raw_with_unique_claims([], [RECORD])
        with pytest.raises(ValueError, match="needs claims and records"):
            store.put_raw_with_unique_claims([CLAIM], [])

    def test_lost_claim_race_refuses_and_writes_no_record(self, persisted) -> None:
        """A claim that already exists decides the race at the storage layer."""
        state, store = persisted
        store.put_raw(*CLAIM)
        state.flush()

        assert store.put_raw_with_unique_claims([CLAIM], [RECORD]) is False
        assert store.get_raw("users", "u1") is None, "the record must not outlive a lost claim"

    def test_failed_record_insert_rolls_back_the_claim(self, persisted) -> None:
        """A claim is never consumed by an account write that cannot land."""
        state, store = persisted
        store.put_raw(*RECORD)
        state.flush()

        with pytest.raises(RuntimeError, match="atomic username allocation failed"):
            store.put_raw_with_unique_claims([CLAIM], [RECORD])
        state.flush()
        assert store.get_raw("username_claims", "username:alice") is None

    def test_unrun_writer_times_out_instead_of_hanging(self, persisted, monkeypatch) -> None:
        state, store = persisted

        def _never(_fn: Any) -> None:
            return None

        monkeypatch.setattr(state, "submit", _never)
        with pytest.raises(TimeoutError, match="atomic username allocation"):
            store.put_raw_with_unique_claims([CLAIM], [RECORD], timeout=0.05)


class TestDeleteRawWithUniqueClaims:
    def test_removes_a_matching_claim_and_record(self, persisted) -> None:
        state, store = persisted
        store.put_raw_with_unique_claims([CLAIM], [RECORD])
        state.flush()

        assert store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")]) is True
        state.flush()
        assert store.get_raw("username_claims", "username:alice") is None
        assert store.get_raw("users", "u1") is None

    def test_refuses_when_the_claim_belongs_to_another_account(self, persisted) -> None:
        """A rollback may only release a claim that still names its owner."""
        state, store = persisted
        store.put_raw(
            "username_claims",
            "username:alice",
            '{"status": "active", "user_id": "someone-else"}',
        )
        state.flush()

        assert store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")]) is False
        assert store.get_raw("username_claims", "username:alice") is not None

    def test_refuses_a_missing_claim(self, persisted) -> None:
        _, store = persisted

        assert store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")]) is False

    def test_refuses_a_corrupt_claim_record(self, persisted) -> None:
        """An unreadable claim is operator territory, never a silent release."""
        state, store = persisted
        store.put_raw("username_claims", "username:alice", "{not json")
        state.flush()

        assert store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")]) is False
        assert store.get_raw("username_claims", "username:alice") == "{not json"

    def test_refuses_when_the_record_does_not_match(self, persisted) -> None:
        """Fewer deletions than requested means the pair already diverged."""
        state, store = persisted
        store.put_raw_with_unique_claims([CLAIM], [RECORD])
        # The account row is gone, but the claim remains: deleting "both" now
        # would report a clean rollback over a half-removed allocation.
        store.delete("users", "u1")
        state.flush()

        assert store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")]) is False
        assert store.get_raw("username_claims", "username:alice") is not None

    def test_empty_claims_or_records_is_refused(self, persisted) -> None:
        _, store = persisted

        with pytest.raises(ValueError, match="needs claims and records"):
            store.delete_raw_with_unique_claims([], [("users", "u1")])
        with pytest.raises(ValueError, match="needs claims and records"):
            store.delete_raw_with_unique_claims([DELAIM], [])

    def test_unrun_writer_times_out_instead_of_hanging(self, persisted, monkeypatch) -> None:
        state, store = persisted
        store.put_raw_with_unique_claims([CLAIM], [RECORD])

        def _never(_fn: Any) -> None:
            return None

        monkeypatch.setattr(state, "submit", _never)
        with pytest.raises(TimeoutError, match="atomic username rollback"):
            store.delete_raw_with_unique_claims([DELAIM], [("users", "u1")], timeout=0.05)
