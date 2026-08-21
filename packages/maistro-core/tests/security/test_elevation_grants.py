"""Tests for elevation flows (SPEC-247 / ADR-068 §D)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from maistro.security._types import AuditEntry
from maistro.security.sentinel.authz_types import Principal, Tier
from maistro.security.sentinel.elevation import (
    InMemoryElevationStore,
    ScopedTwoFactorForHumanError,
    confirm_scoped_2fa,
    confirm_self_elevation,
    hash_args,
    request_scoped_2fa,
    request_self_elevation,
    store_grant_with_audit,
)
from maistro.security.sentinel.policy import Sentinel
from maistro.security.warden.detector import Warden


class _RecordingAuditLog:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


def test_self_elevation_grant_is_self_signed() -> None:
    challenge = request_self_elevation("u1", "delete_directory")

    grant = confirm_self_elevation(challenge, proof="opaque-proof")

    assert grant.kind == "self_elevation"
    assert grant.signed_by == "u1"
    assert grant.principal_id == "u1"


def test_request_scoped_2fa_rejects_human_principal() -> None:
    with pytest.raises(ScopedTwoFactorForHumanError):
        request_scoped_2fa(
            "u1", "owner-1", "delete_directory", {"path": "/x"}, principal_kind="human"
        )


def test_scoped_2fa_grant_bound_to_specific_args() -> None:
    request = request_scoped_2fa(
        "agent-1", "u1", "delete_directory", {"path": "/x"}, principal_kind="agent"
    )
    grant = confirm_scoped_2fa(request, owner_signature="opaque-sig")

    now = datetime.now(UTC)
    assert grant.is_valid(
        now=now, action_class="delete_directory", args_hash=hash_args({"path": "/x"})
    )
    assert not grant.is_valid(
        now=now, action_class="delete_directory", args_hash=hash_args({"path": "/y"})
    )


def test_expired_grant_fails_is_valid() -> None:
    challenge = request_self_elevation("u1", "delete_directory")
    granted_at = datetime.now(UTC) - timedelta(seconds=1000)
    grant = confirm_self_elevation(challenge, proof="x", now=granted_at, ttl_seconds=300)

    assert not grant.is_valid(now=datetime.now(UTC), action_class="delete_directory")


async def test_store_grant_with_audit_emits_audit_event() -> None:
    store = InMemoryElevationStore()
    audit_log = _RecordingAuditLog()
    challenge = request_self_elevation("u1", "delete_directory")
    grant = confirm_self_elevation(challenge, proof="x")

    await store_grant_with_audit(store, grant, audit_log)

    assert store.grants == [grant]
    assert len(audit_log.entries) == 1
    assert audit_log.entries[0].verdict == "granted"


async def test_sentinel_authorize_short_circuits_on_valid_grant() -> None:
    store = InMemoryElevationStore()
    sentinel = Sentinel(warden=Warden(), permission_table={}, elevation_store=store)
    principal = Principal(id="u1", kind="human", roles=(), scopes=())

    challenge = request_self_elevation("u1", "delete_directory")
    grant = confirm_self_elevation(challenge, proof="x")
    await store.store(grant)

    decision = await sentinel.authorize(
        "delete_directory", principal, reversibility="irreversible", within_budget=True
    )

    assert decision.tier == Tier.SELF_ELEVATION
    assert decision.needs == "none"
    assert decision.authorized is True


async def test_sentinel_authorize_without_grant_still_requires_elevation() -> None:
    store = InMemoryElevationStore()
    sentinel = Sentinel(warden=Warden(), permission_table={}, elevation_store=store)
    principal = Principal(id="u1", kind="human", roles=(), scopes=())

    decision = await sentinel.authorize(
        "delete_directory", principal, reversibility="irreversible", within_budget=True
    )

    assert decision.needs == "self_elevation"
