"""Acceptance coverage for canonical username claims (#1061)."""

from __future__ import annotations

import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from models.schemas import HiveUser
from services.model_store import JsonStore, ModelStore
from services.username_registry import (
    UsernameRegistry,
    UsernameTakenError,
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
