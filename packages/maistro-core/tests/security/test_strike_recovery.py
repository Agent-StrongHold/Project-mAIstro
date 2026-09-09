"""Authorized administrative strike recovery (#1172)."""

from __future__ import annotations

import asyncio
from typing import Any

from maistro.security.pg_strikes import PgStrikeTracker  # type: ignore[import-not-found]
from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.strike_recovery import StrikeRecoveryService  # type: ignore[import-not-found]
from maistro.security.strikes import InMemoryStrikeTracker
from maistro.security.warden.detector import Warden


def _service(
    audit: InMemoryAuditLog,
    tracker: Any | None = None,
) -> StrikeRecoveryService:
    actions = tuple(
        f"{StrikeRecoveryService.ACTION}.{operation}"
        for operation in ("unlock", "enable", "remove_strikes")
    )
    permissions = {action: frozenset({"admin"}) for action in actions}
    tiers = {(action, "admin"): Tier.ADMIN for action in actions}
    sentinel = Sentinel(warden=Warden(), permission_table=permissions, tier_policy=tiers)
    return StrikeRecoveryService(
        tracker=tracker or InMemoryStrikeTracker(), sentinel=sentinel, audit_log=audit
    )


def _principal(user_id: str, *roles: str) -> Principal:
    return Principal(id=user_id, kind="human", roles=roles)


async def test_self_unlock_is_refused_and_audited() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="locked", flags=("x",))
    await service._tracker.record_violation(user_id="locked", flags=("x",))

    result = await service.unlock(_principal("locked", "admin"), "locked")

    assert result is None
    entries = await audit.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "denied"
    assert "actor_id=locked" in entries[0].detail
    assert "target_id=locked" in entries[0].detail
    assert "outcome=denied" in entries[0].detail
    locked = await service._tracker.get("locked")
    assert locked is not None and locked.is_locked is True


async def test_non_admin_unlock_is_refused_and_audited() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))

    result = await service.unlock(_principal("operator", "user"), "target")

    assert result is None
    entries = await audit.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "denied"
    assert "security.strikes.recover.unlock" in entries[0].detail
    locked = await service._tracker.get("target")
    assert locked is not None and locked.is_locked is True


async def test_authorized_unlock_is_scoped_and_audited() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="other", flags=("x",))
    await service._tracker.record_violation(user_id="other", flags=("x",))

    result = await service.unlock(_principal("operator", "admin"), "target")

    assert result is not None
    assert result.is_locked is False
    other = await service._tracker.get("other")
    assert other is not None and other.is_locked is True
    entries = await audit.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "granted"
    assert "actor_id=operator" in entries[0].detail
    assert "target_id=target" in entries[0].detail
    assert "outcome=granted" in entries[0].detail


async def test_authorized_enable_and_remove_strikes_match_tracker_lifecycle() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))

    admin = _principal("operator", "admin")
    enabled = await service.enable(admin, "target")
    removed = await service.remove_strikes(admin, "target")

    assert enabled is not None and enabled.disabled is False
    assert removed is not None and removed.strike_count == 0
    assert removed.scrutiny_level == "normal"
    assert [entry.verdict for entry in await audit.get_entries()] == ["granted", "granted"]


async def test_re_lock_after_authorized_unlock() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))

    unlocked = await service.unlock(_principal("operator", "admin"), "target")
    assert unlocked is not None and unlocked.is_locked is False

    relocked = await service._tracker.record_violation(user_id="target", flags=("x",))
    assert relocked.strike_count == 3
    assert relocked.disabled is True
    assert relocked.is_locked is True
    entries = await audit.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "granted"
    assert "action=security.strikes.recover.unlock" in entries[0].detail


async def test_concurrent_violations_and_unlock_have_deterministic_final_state() -> None:
    audit = InMemoryAuditLog()
    service = _service(audit)
    await service._tracker.record_violation(user_id="target", flags=("x",))
    await service._tracker.record_violation(user_id="target", flags=("x",))

    operations = [
        service._tracker.record_violation(user_id="target", flags=("x",)) for _ in range(5)
    ]
    operations.append(service.unlock(_principal("operator", "admin"), "target"))
    results = await asyncio.gather(*operations)

    final = await service._tracker.get("target")
    assert final is not None
    assert final.strike_count == 7
    assert final.disabled is True
    assert final.is_locked is True
    assert results[-1] is not None
    entries = await audit.get_entries()
    assert len(entries) == 1
    assert entries[0].verdict == "granted"


class _RecoveryTxn:
    async def __aenter__(self) -> _RecoveryTxn:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _RecoveryConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, tuple[Any, ...]]] = []
        self._fetchrow_results: list[dict[str, Any] | None] = []

    def queue_fetchrow(self, row: dict[str, Any] | None) -> None:
        self._fetchrow_results.append(row)

    async def fetchrow(self, query: str, *args: Any) -> dict[str, Any] | None:
        self.calls.append(("fetchrow", query, args))
        return self._fetchrow_results.pop(0) if self._fetchrow_results else None

    async def fetch(self, query: str, *args: Any) -> list[Any]:
        self.calls.append(("fetch", query, args))
        return []

    async def execute(self, query: str, *args: Any) -> None:
        self.calls.append(("execute", query, args))

    def transaction(self) -> _RecoveryTxn:
        return _RecoveryTxn()


class _RecoveryAcquire:
    def __init__(self, connection: _RecoveryConnection) -> None:
        self._connection = connection

    async def __aenter__(self) -> _RecoveryConnection:
        return self._connection

    async def __aexit__(self, *exc: Any) -> None:
        return None


class _RecoveryPool:
    def __init__(self, connection: _RecoveryConnection) -> None:
        self._connection = connection

    def acquire(self) -> _RecoveryAcquire:
        return _RecoveryAcquire(self._connection)


def _recovery_strike_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "user_id": "u1",
        "strike_count": 2,
        "scrutiny_level": "locked",
        "locked_until": None,
        "disabled": False,
        "last_violation_at": None,
        "last_appeal": "",
        "last_appeal_at": None,
    }
    row.update(overrides)
    return row


async def test_recovery_service_drives_pg_tracker_lifecycle() -> None:
    audit = InMemoryAuditLog()
    connection = _RecoveryConnection()
    connection.queue_fetchrow({"user_id": "u1"})
    connection.queue_fetchrow(_recovery_strike_row(scrutiny_level="elevated"))
    connection.queue_fetchrow({"user_id": "u1"})
    connection.queue_fetchrow(
        _recovery_strike_row(strike_count=0, scrutiny_level="normal", locked_until=None)
    )
    tracker = PgStrikeTracker(pool=_RecoveryPool(connection))
    service = _service(audit, tracker=tracker)

    admin = _principal("operator", "admin")
    unlocked = await service.unlock(admin, "u1")
    removed = await service.remove_strikes(admin, "u1")

    assert unlocked is not None
    assert unlocked.locked_until is None
    assert unlocked.is_locked is False
    assert removed is not None
    assert removed.strike_count == 0
    assert removed.scrutiny_level == "normal"
    entries = await audit.get_entries()
    assert len(entries) == 2
    assert [entry.verdict for entry in entries] == ["granted", "granted"]
    queries = [query for _, query, _ in connection.calls]
    assert any("locked_until = NULL" in query for query in queries)
    assert any(
        "GREATEST(0, strike_count - COALESCE($2, strike_count))" in query for query in queries
    )
