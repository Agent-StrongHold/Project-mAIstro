"""Canonical, case-insensitive Hive username allocation and lookup.

The users table is keyed by random user ids, so it cannot itself enforce
username uniqueness. This module owns the separate username index. Persistent
account creation uses one SQLite transaction that inserts the unique claim and
the user row together; the index is consequently not a best-effort cache.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, cast

from models.schemas import HiveUser

CLAIM_STORE = "username_claims"
CLAIM_SCHEMA_VERSION = 1


class UsernameAllocationError(RuntimeError):
    """The configured persistence layer could not complete an allocation."""


class UsernameTakenError(UsernameAllocationError):
    """The canonical username claim belongs to another identity."""


_LOCK = threading.RLock()


def normalize_username(username: str) -> str:
    """Return the identity key, independent of presentation casing."""
    return username.strip().casefold()


def claim_key(username: str) -> str:
    return f"username:{normalize_username(username)}"


def _claim_record(username: str, user_id: str) -> dict[str, Any]:
    return {
        "schema_version": CLAIM_SCHEMA_VERSION,
        "status": "active",
        "normalized_username": normalize_username(username),
        "username": username,
        "user_id": user_id,
        "created_at": datetime.now(UTC).isoformat(),
    }


def _valid_claim(record: object) -> bool:
    return (
        isinstance(record, dict)
        and record.get("schema_version") == CLAIM_SCHEMA_VERSION
        and record.get("status") in {"active", "quarantined"}
        and isinstance(record.get("normalized_username"), str)
    )


class UsernameRegistry:
    """Operate on a users ModelStore and its canonical claim JsonStore."""

    def __init__(self, users: Any, claims: Any) -> None:
        self._users = users
        self._claims = claims

    def _durable_user(self, user_id: str) -> HiveUser | None:
        user = cast(HiveUser | None, self._users.get(user_id))
        if user is not None:
            return user
        backend = getattr(self._users, "_persisted", None)
        getter = getattr(backend, "get", None)
        if not callable(getter):
            return None
        user = cast(HiveUser | None, getter("users", user_id, HiveUser))
        if user is not None:
            self._users._data[user_id] = user
        return user

    def _all_users(self) -> list[HiveUser]:
        users = list(self._users.values())
        backend = getattr(self._users, "_persisted", None)
        lister = getattr(backend, "list_all", None)
        if callable(lister):
            durable = lister("users", HiveUser)
            by_id = {user.id: user for user in users}
            by_id.update({user.id: user for user in durable})
            users = list(by_id.values())
            self._users._data.update(by_id)
        return users

    def _refresh_claim(self, key: str) -> object | None:
        record = self._claims.get(key)
        backend = getattr(self._claims, "_persisted", None)
        getter = getattr(backend, "get_raw", None)
        if record is None and callable(getter):
            raw = getter(CLAIM_STORE, key)
            if raw is not None:
                try:
                    record = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    # Keep a corrupt durable key visibly occupied. Replacing
                    # it through a read/delete/write sequence would reopen the
                    # race this index exists to close.
                    record = {"status": "corrupt"}
                self._claims._data[key] = record
        return cast(object | None, record)

    def is_claimed(self, username: str) -> bool:
        """Return true for active, quarantined, or corrupt indexed records.

        A corrupt index is treated as occupied so registration cannot silently
        create a second identity while an operator is repairing the record.
        """
        return self._refresh_claim(claim_key(username)) is not None

    def resolve(self, username: str) -> HiveUser | None:
        """Resolve through the canonical index, never by first matching row."""
        key = claim_key(username)
        record = self._refresh_claim(key)
        if not _valid_claim(record) or not isinstance(record, dict):
            return None
        if record.get("status") != "active":
            return None
        if record.get("normalized_username") != normalize_username(username):
            return None
        user_id = record.get("user_id")
        if not isinstance(user_id, str):
            return None
        user = self._durable_user(user_id)
        if user is None or normalize_username(user.username) != normalize_username(username):
            return None
        return user

    def _legacy_candidates(self, normalized: str) -> list[HiveUser]:
        return [
            user for user in self._all_users() if normalize_username(user.username) == normalized
        ]

    def migrate_legacy_claims(self) -> None:
        """Index unique legacy rows and quarantine duplicate historical rows."""
        grouped: dict[str, list[HiveUser]] = {}
        for user in self._all_users():
            grouped.setdefault(normalize_username(user.username), []).append(user)
        for normalized, candidates in grouped.items():
            key = f"username:{normalized}"
            if self._refresh_claim(key) is not None:
                continue
            ordered = sorted(candidates, key=lambda user: user.id)
            if len(ordered) == 1:
                record = _claim_record(ordered[0].username, ordered[0].id)
            else:
                record = {
                    "schema_version": CLAIM_SCHEMA_VERSION,
                    "status": "quarantined",
                    "normalized_username": normalized,
                    "candidate_user_ids": [user.id for user in ordered],
                    "reason": "duplicate historical username",
                }
            self._claims.put_if_absent(key, record)

    def _reject_existing_claims(self, claims: list[tuple[str, str, str]]) -> None:
        existing = [self._refresh_claim(key) for _, key, _ in claims]
        stale = [
            record
            for record in existing
            if isinstance(record, dict)
            and record.get("status") == "active"
            and isinstance(record.get("user_id"), str)
            and self._durable_user(record["user_id"]) is None
        ]
        if any(record is not None for record in existing) and not all(
            record in stale for record in existing if record is not None
        ):
            raise UsernameTakenError("username is already claimed")
        if stale and getattr(self._users, "_persisted", None) is not None:
            # A durable user deletion is not currently an exposed product
            # operation. Refuse a stale durable claim rather than replacing
            # it through a non-atomic delete/reinsert sequence.
            raise UsernameTakenError("username claim needs operator repair")

    def _write_batch(
        self,
        claims: list[tuple[str, str, str]],
        records: list[tuple[str, str, str]],
        batch: list[HiveUser],
    ) -> None:
        backend = getattr(self._users, "_persisted", None)
        atomic = getattr(backend, "put_raw_with_unique_claims", None)
        if backend is not None:
            if not callable(atomic):
                raise UsernameAllocationError(
                    "configured persistence cannot atomically allocate usernames"
                )
            if not atomic(claims, records):
                for _, key, _ in claims:
                    self._refresh_claim(key)
                raise UsernameTakenError("username is already claimed")
            return

        # Memory mode has one process-wide critical section. Durable
        # deployments always take the transaction path above.
        for _, key, _ in claims:
            if self._claims.get(key) is not None:
                raise UsernameTakenError("username is already claimed")
        for (_, key, raw), user in zip(claims, batch, strict=True):
            self._claims._data[key] = json.loads(raw)
            self._users._data[user.id] = user

    def create_users(self, users: Iterable[HiveUser]) -> None:
        """Create one or more users with their claims as one durable unit."""
        batch = list(users)
        if not batch:
            raise ValueError("at least one user is required")
        normalized = [normalize_username(user.username) for user in batch]
        if len(set(normalized)) != len(normalized):
            raise UsernameTakenError("duplicate usernames in account allocation")

        claims = [
            (CLAIM_STORE, f"username:{name}", json.dumps(_claim_record(user.username, user.id)))
            for name, user in zip(normalized, batch, strict=True)
        ]
        records = [("users", user.id, user.model_dump_json()) for user in batch]

        with _LOCK:
            self._reject_existing_claims(claims)
            self._write_batch(claims, records, batch)
            for (_, key, raw), user in zip(claims, batch, strict=True):
                self._claims._data[key] = json.loads(raw)
                self._users._data[user.id] = user

    def _rollback_durable(
        self,
        claims: list[tuple[str, str, str]],
        records: list[tuple[str, str]],
    ) -> None:
        backend = getattr(self._users, "_persisted", None)
        atomic = getattr(backend, "delete_raw_with_unique_claims", None)
        if not callable(atomic):
            raise UsernameAllocationError(
                "configured persistence cannot atomically roll back usernames"
            )
        if not atomic(claims, records):
            raise UsernameAllocationError("username rollback did not match its accounts")

    def _rollback_memory(self, batch: list[HiveUser], claims: list[tuple[str, str, str]]) -> None:
        for _, key, expected_id in claims:
            record = self._claims.get(key)
            if not isinstance(record, dict) or record.get("user_id") != expected_id:
                raise UsernameAllocationError("username rollback did not match its accounts")
        if any(self._users.get(user.id) is None for user in batch):
            raise UsernameAllocationError("username rollback account is missing")
        for _, key, _ in claims:
            self._claims._data.pop(key, None)
        for user in batch:
            self._users._data.pop(user.id, None)

    def rollback_users(self, users: Iterable[HiveUser]) -> None:
        """Remove accounts and claims after a later setup step fails.

        The durable backend verifies each claim still belongs to the supplied
        user ids before deleting either side. A rollback that cannot prove that
        ownership fails closed, leaving the durable claim and account for
        operator reconciliation rather than releasing a live username.
        """
        batch = list(users)
        if not batch:
            return
        claims = [(CLAIM_STORE, claim_key(user.username), user.id) for user in batch]
        records = [("users", user.id) for user in batch]
        with _LOCK:
            if getattr(self._users, "_persisted", None) is not None:
                self._rollback_durable(claims, records)
                for _, key, _ in claims:
                    self._claims._data.pop(key, None)
                for user in batch:
                    self._users._data.pop(user.id, None)
            else:
                self._rollback_memory(batch, claims)

    def migrate_or_index_one(self, username: str) -> None:
        """Index a legacy row encountered after startup migration."""
        normalized = normalize_username(username)
        key = f"username:{normalized}"
        if self._refresh_claim(key) is not None:
            return
        candidates = self._legacy_candidates(normalized)
        if not candidates:
            return
        ordered = sorted(candidates, key=lambda user: user.id)
        if len(ordered) == 1:
            record = _claim_record(ordered[0].username, ordered[0].id)
        else:
            record = {
                "schema_version": CLAIM_SCHEMA_VERSION,
                "status": "quarantined",
                "normalized_username": normalized,
                "candidate_user_ids": [user.id for user in ordered],
                "reason": "duplicate historical username",
            }
        self._claims.put_if_absent(key, record)


def _default_registry() -> UsernameRegistry:
    import stores

    return UsernameRegistry(stores.users, stores.username_claims)


def migrate_legacy_claims() -> None:
    _default_registry().migrate_legacy_claims()


def resolve(username: str) -> HiveUser | None:
    registry = _default_registry()
    registry.migrate_or_index_one(username)
    return registry.resolve(username)


def is_claimed(username: str) -> bool:
    registry = _default_registry()
    registry.migrate_or_index_one(username)
    return registry.is_claimed(username)


def create_users(users: Iterable[HiveUser]) -> None:
    _default_registry().create_users(users)


def rollback_users(users: Iterable[HiveUser]) -> None:
    _default_registry().rollback_users(users)
