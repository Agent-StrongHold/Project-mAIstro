"""Authorized administrative strike recovery (#1172)."""

from __future__ import annotations

from maistro.security.sentinel.audit import InMemoryAuditLog
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.policy import Sentinel
from maistro.security.strike_recovery import StrikeRecoveryService  # type: ignore[import-not-found]
from maistro.security.strikes import InMemoryStrikeTracker
from maistro.security.warden.detector import Warden


def _service(audit: InMemoryAuditLog) -> StrikeRecoveryService:
    actions = tuple(
        f"{StrikeRecoveryService.ACTION}.{operation}"
        for operation in ("unlock", "enable", "remove_strikes")
    )
    permissions = {action: frozenset({"admin"}) for action in actions}
    tiers = {(action, "admin"): Tier.ADMIN for action in actions}
    sentinel = Sentinel(warden=Warden(), permission_table=permissions, tier_policy=tiers)
    return StrikeRecoveryService(tracker=InMemoryStrikeTracker(), sentinel=sentinel, audit_log=audit)


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
