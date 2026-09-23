"""Acceptance coverage for canonical username claims (#1061)."""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from models.schemas import HiveUser
from services.model_store import JsonStore, ModelStore
from services.username_registry import (
    CLAIM_SCHEMA_VERSION,
    UsernameAllocationError,
    UsernameRegistry,
    UsernameTakenError,
    _claim_record,
    normalize_username,
)


def _user(user_id: str, username: str) -> HiveUser:
    return HiveUser(
        id=user_id,
        username=username,
        password_hash="unused",
        role="user",
        is_active=True,
        permissions=[],
        created_at=datetime.now(UTC),
    )


def test_many_case_variants_have_one_winner_on_shared_persistence(tmp_path) -> None:
    """Two independent writers race the same indexed identity."""
    from maistro.state import PersistedStore, State

    db = tmp_path / "username-race.db"
    states = [State(db), State(db)]
    persisted = [PersistedStore(state) for state in states]
    for store in persisted:
        store.initialize()
    registries = [
        UsernameRegistry(
            ModelStore("users", HiveUser, persisted=store),
            JsonStore("username_claims", persisted=store),
        )
        for store in persisted
    ]
    for registry in registries:
        registry._users.initialize()
        registry._claims.initialize()

    barrier = threading.Barrier(32)
    outcomes: list[bool] = []
    outcomes_lock = threading.Lock()

    def race(index: int) -> None:
        username = ("Alice" if index % 2 else "ALICE") + ("_" if index % 4 == 0 else "")
        # The underscore variants are deliberately different names; all
        # requests for the same claim are the case variants without it.
        username = username.rstrip("_")
        try:
            barrier.wait(timeout=10)
            registries[index % 2].create_users([_user(f"race-{index}", username)])
        except UsernameTakenError:
            won = False
        else:
            won = True
        with outcomes_lock:
            outcomes.append(won)

    threads = [threading.Thread(target=race, args=(index,)) for index in range(32)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)
    assert sum(outcomes) == 1

    reopened = ModelStore("users", HiveUser, persisted=persisted[0])
    reopened.initialize()
    assert len(reopened) == 1
    assert len(persisted[0].list_all_raw("username_claims")) == 1
    assert registries[0].resolve("aLiCe") is not None
    for state in states:
        state.close()


def test_allocator_calls_storage_atomic_claim_seam(tmp_path) -> None:
    """A scan-then-write mutation cannot satisfy the allocation contract."""
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "atomic-seam.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    atomic = Mock(wraps=persisted.put_raw_with_unique_claims)
    persisted.put_raw_with_unique_claims = atomic
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )
    registry.create_users([_user("atomic", "Alice")])

    atomic.assert_called_once()
    assert persisted.get_raw("username_claims", "username:alice") is not None
    assert persisted.get_raw("users", "atomic") is not None
    state.close()


def test_registry_rollback_releases_claim_and_account_together(tmp_path) -> None:
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "rollback-registry.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    users = ModelStore("users", HiveUser, persisted=persisted)
    claims = JsonStore("username_claims", persisted=persisted)
    registry = UsernameRegistry(users, claims)
    account = _user("rollback", "RetryName")
    registry.create_users([account])
    registry.rollback_users([account])

    assert persisted.get_raw("username_claims", "username:retryname") is None
    assert persisted.get_raw("users", "rollback") is None
    registry.create_users([_user("retry", "retryname")])
    state.close()


def test_atomic_allocation_rolls_back_claim_when_user_insert_fails(tmp_path) -> None:
    """A failed account write does not consume the username claim."""
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "rollback.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    persisted.put_raw("users", "existing", _user("existing", "existing").model_dump_json())
    state.flush()

    with pytest.raises(RuntimeError, match="atomic username allocation failed"):
        persisted.put_raw_with_unique_claims(
            [("username_claims", "username:retry", '{"status":"active"}')],
            [("users", "existing", _user("existing", "retry").model_dump_json())],
        )
    assert persisted.get_raw("username_claims", "username:retry") is None
    state.close()


def test_registration_route_uses_atomic_allocator_not_scan_then_write() -> None:
    source = (Path(__file__).resolve().parents[1] / "routes" / "auth.py").read_text(
        encoding="utf-8"
    )
    register = source[source.index('@router.post("/register")') :]
    register = register[: register.index('@router.post("/login")')]

    assert "username_registry.create_users([user])" in register
    assert "stores.users[user_id] = user" not in register


def test_scan_then_write_mutation_loses_the_race() -> None:
    """Executed mutation: replace the atomic claim with scan-then-write.

    The issue's mutation criterion is that the suite fails if the atomic
    claim were replaced by the historical read-then-write shape. The
    mutated allocator below is exactly that shape — a claim scan followed
    by a random-id write with no storage-level constraint — driven through
    the same concurrent harness as
    `test_many_case_variants_have_one_winner_on_shared_persistence`. The
    barrier lands inside the check-to-write window, so the interleaving
    that concurrency hits in production is forced deterministically: every
    variant passes the scan before any of them writes. If the real
    allocator ever regressed to this shape, that test's `sum(outcomes)
    == 1` assertion would fail exactly the way this demonstration shows.
    """

    users = ModelStore("users", HiveUser)
    claims = JsonStore("username_claims")
    barrier = threading.Barrier(8)

    def mutated_scan_then_write(user: HiveUser) -> None:
        key = f"username:{user.username.strip().casefold()}"
        if key in claims:
            raise UsernameTakenError("username is already taken")
        # The window: every racer observes the name as free before any of
        # them persists, which is what the absent atomic claim permits.
        barrier.wait(timeout=10)
        claims[key] = {"status": "active", "user_id": user.id}
        users[user.id] = user

    outcomes: list[bool] = []
    outcomes_lock = threading.Lock()

    def race(index: int) -> None:
        try:
            mutated_scan_then_write(_user(f"mutant-{index}", "Alice" if index % 2 else "ALICE"))
        except UsernameTakenError:
            won = False
        else:
            won = True
        with outcomes_lock:
            outcomes.append(won)

    threads = [threading.Thread(target=race, args=(index,)) for index in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)
    assert all(not thread.is_alive() for thread in threads)

    # The mutation duplicated the identity: all eight case variants won,
    # eight distinct user rows share one canonical login name, and the
    # surviving claim points at whichever writer landed last — the exact
    # defect #1061 removes and the race harness above exists to detect.
    assert sum(outcomes) == 8
    assert len(users) == 8
    assert len({normalize_username(user.username) for user in users.values()}) == 1
    assert claims["username:alice"]["user_id"].startswith("mutant-")


def test_historical_duplicate_is_quarantined_not_winner_selected() -> None:
    users = ModelStore("users", HiveUser)
    claims = JsonStore("username_claims")
    users["b"] = _user("b", "Alice")
    users["a"] = _user("a", "alice")
    registry = UsernameRegistry(users, claims)

    registry.migrate_legacy_claims()

    assert claims["username:alice"]["status"] == "quarantined"
    assert registry.resolve("ALICE") is None
    with pytest.raises(UsernameTakenError):
        registry.create_users([_user("c", "Alice")])


def test_durable_loser_at_the_atomic_layer_is_refused(tmp_path) -> None:
    """A rival claim landing between the check and the txn still loses cleanly.

    `_reject_existing_claims` reads the durable index through this process's
    caches; a claim another process writes after that read is caught only by
    the storage-level primary-key insert. The wrapped backend below writes the
    rival's claim just before the transaction, which is exactly the
    between-check-and-txn window, and the loser must come back as
    UsernameTakenError having written no row of its own.
    """
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "atomic-loser.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    # The name is free when this writer checks — no claim exists yet.
    users = ModelStore("users", HiveUser, persisted=persisted)
    claims = JsonStore("username_claims", persisted=persisted)
    registry = UsernameRegistry(users, claims)
    real_atomic = persisted.put_raw_with_unique_claims

    def rival_lands_in_the_window(claims_arg, records_arg, **kwargs):
        # The rival's allocation lands durably after the check and before
        # this writer's own transaction; the atomic insert must refuse it.
        assert real_atomic(
            [("username_claims", "username:alice", json.dumps(_claim_record("AlicE", "rival")))],
            [("users", "rival", _user("rival", "AlicE").model_dump_json())],
        )
        return False

    persisted.put_raw_with_unique_claims = rival_lands_in_the_window  # type: ignore[method-assign]

    with pytest.raises(UsernameTakenError):
        registry.create_users([_user("loser", "alice")])

    assert persisted.get_raw("users", "loser") is None, "the loser must write no row"
    assert persisted.get_raw("users", "rival") is not None
    resolved = registry.resolve("ALICE")
    assert resolved is not None and resolved.id == "rival"
    state.close()


def test_corrupt_durable_claim_is_occupied_and_fails_closed(tmp_path) -> None:
    """An unreadable index record is treated as taken, never overwritten."""
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "corrupt-claim.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    persisted.put_raw("username_claims", "username:broken", "{not json")
    state.flush()
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )

    assert registry.is_claimed("broken") is True
    assert registry.resolve("broken") is None
    with pytest.raises(UsernameTakenError):
        registry.create_users([_user("newcomer", "BROKEN")])
    assert persisted.get_raw("users", "newcomer") is None
    state.close()


def test_resolve_refuses_claims_that_do_not_name_the_account() -> None:
    """Only an active, schema-valid, name-matching claim resolves a user."""
    users = ModelStore("users", HiveUser)
    claims = JsonStore("username_claims")
    registry = UsernameRegistry(users, claims)

    # Wrong schema version: not a record this code may act on.
    claims["username:stale-schema"] = {
        "schema_version": CLAIM_SCHEMA_VERSION + 1,
        "status": "active",
        "normalized_username": "stale-schema",
        "user_id": "u1",
    }
    # Quarantined history: refuses to pick a winner.
    claims["username:quarantined"] = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "status": "quarantined",
        "normalized_username": "quarantined",
        "candidate_user_ids": ["a", "b"],
    }
    # The indexed name does not match the requested name.
    claims["username:mismatched"] = {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "status": "active",
        "normalized_username": "other-name",
        "user_id": "u3",
    }
    # A well-formed claim whose user row is gone resolves to nothing.
    claims["username:ghosted"] = _claim_record("ghosted", "missing-id")

    for name in ("STALE-SCHEMA", "quarantined", "Mismatched", "ghosted"):
        assert registry.resolve(name) is None, name


def test_stale_durable_claim_fails_closed_for_operator_repair(tmp_path) -> None:
    """A durable claim whose user row vanished is never silently re-allocated."""
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "stale-claim.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )
    registry.create_users([_user("vanished", "Lingering")])
    persisted.delete("users", "vanished")
    state.flush()

    fresh = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )
    with pytest.raises(UsernameTakenError, match="operator repair"):
        fresh.create_users([_user("successor", "lingering")])
    assert persisted.get_raw("users", "successor") is None
    state.close()


def test_migrate_legacy_claims_leaves_existing_claims_untouched() -> None:
    users = ModelStore("users", HiveUser)
    claims = JsonStore("username_claims")
    users["a"] = _user("a", "Alice")
    claims["username:alice"] = {"handwritten": True}
    registry = UsernameRegistry(users, claims)

    registry.migrate_legacy_claims()

    assert claims["username:alice"] == {"handwritten": True}


def test_migrate_or_index_one_quarantines_legacy_duplicates() -> None:
    users = ModelStore("users", HiveUser)
    claims = JsonStore("username_claims")
    users["b"] = _user("b", "Zara")
    users["a"] = _user("a", "zara")
    registry = UsernameRegistry(users, claims)

    registry.migrate_or_index_one("ZARA")

    record = claims["username:zara"]
    assert record["status"] == "quarantined"
    assert record["candidate_user_ids"] == ["a", "b"]
    assert registry.resolve("zara") is None


def test_persistence_without_atomic_claims_refuses_allocation() -> None:
    """A backend that cannot run the claim transaction must not be used."""

    class LegacyBackend:
        """Reads work; the atomic allocation boundary is absent."""

        def get(self, _store, _key, _cls):
            return None

        def get_raw(self, _store, _key):
            return None

        def list_all(self, _store, _cls):
            return []

    backend = LegacyBackend()
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=backend),
        JsonStore("username_claims", persisted=backend),
    )

    with pytest.raises(UsernameAllocationError, match="cannot atomically allocate"):
        registry.create_users([_user("x", "Nona")])


def test_rollback_needs_the_atomic_delete_boundary(tmp_path, monkeypatch) -> None:
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "rollback-boundary.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )
    account = _user("keeper", "Boundary")
    registry.create_users([account])

    monkeypatch.setattr(persisted, "delete_raw_with_unique_claims", None)
    with pytest.raises(UsernameAllocationError, match="cannot atomically roll back"):
        registry.rollback_users([account])
    assert persisted.get_raw("users", "keeper") is not None
    state.close()


def test_rollback_refuses_when_the_claim_moved_to_another_owner(tmp_path) -> None:
    """A claim that no longer names the account is not this rollback's to free."""
    from maistro.state import PersistedStore, State

    state = State(tmp_path / "rollback-owner.db")
    persisted = PersistedStore(state)
    persisted.initialize()
    registry = UsernameRegistry(
        ModelStore("users", HiveUser, persisted=persisted),
        JsonStore("username_claims", persisted=persisted),
    )
    account = _user("owner", "ShiftName")
    registry.create_users([account])
    persisted.put_raw(
        "username_claims",
        "username:shiftname",
        json.dumps(_claim_record("ShiftName", "someone-else")),
    )
    state.flush()

    with pytest.raises(UsernameAllocationError, match="did not match"):
        registry.rollback_users([account])
    assert persisted.get_raw("username_claims", "username:shiftname") is not None
    state.close()


def test_empty_rollback_is_a_no_op() -> None:
    registry = UsernameRegistry(ModelStore("users", HiveUser), JsonStore("username_claims"))
    registry.rollback_users([])


def test_memory_write_batch_refuses_a_claim_that_appeared_in_its_window() -> None:
    """The memory path's own critical-section check inside `_write_batch`."""
    registry = UsernameRegistry(ModelStore("users", HiveUser), JsonStore("username_claims"))
    registry._claims._data["username:popped"] = {"status": "active"}

    with pytest.raises(UsernameTakenError):
        registry._write_batch(
            [("username_claims", "username:popped", json.dumps(_claim_record("Popped", "p1")))],
            [("users", "p1", _user("p1", "Popped").model_dump_json())],
            [_user("p1", "Popped")],
        )


def test_memory_rollback_verifies_claim_ownership_and_accounts() -> None:
    registry = UsernameRegistry(ModelStore("users", HiveUser), JsonStore("username_claims"))
    account = _user("m1", "Milo")

    # The claim names somebody else: not this rollback's pair.
    registry._claims._data["username:milo"] = {"status": "active", "user_id": "OTHER"}
    with pytest.raises(UsernameAllocationError, match="did not match"):
        registry._rollback_memory([account], [("username_claims", "username:milo", "m1")])

    # The claim matches but the account row is gone: refuse rather than half-delete.
    registry._claims._data["username:milo"] = {"status": "active", "user_id": "m1"}
    with pytest.raises(UsernameAllocationError, match="account is missing"):
        registry._rollback_memory([account], [("username_claims", "username:milo", "m1")])


def test_create_users_requires_a_batch_and_distinct_names() -> None:
    registry = UsernameRegistry(ModelStore("users", HiveUser), JsonStore("username_claims"))

    with pytest.raises(ValueError, match="at least one user"):
        registry.create_users([])
    with pytest.raises(UsernameTakenError, match="duplicate usernames"):
        registry.create_users([_user("x", "Dup"), _user("y", "dup")])
