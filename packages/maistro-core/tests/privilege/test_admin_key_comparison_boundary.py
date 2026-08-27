"""Behavioral regression for admin-key comparison boundaries (#322)."""

from __future__ import annotations

import maistro.privilege as privilege
from maistro.security.secret_equal import secret_equal as real_secret_equal


def test_every_privilege_admin_key_decision_uses_secret_equal(tmp_path, monkeypatch) -> None:
    """A direct equality mutation on any live admin decision must fail this test."""
    compared: list[tuple[str, str]] = []

    def recording_secret_equal(left: str, right: str) -> bool:
        compared.append((left, right))
        return real_secret_equal(left, right)

    monkeypatch.setattr(privilege, "secret_equal", recording_secret_equal)

    guard = privilege.PrivilegeGuard(data_dir=tmp_path)
    guard.initialize(admin_public_key="pk_admin", user_public_key="pk_user")

    request = privilege.ElevationRequest(
        user_public_key="pk_user",
        scope="shell:execute",
        justification="comparison-boundary test",
    )
    token = guard.propose_elevation(request)
    guard.admin_sign_elevation(token, admin_key="pk_admin")

    policy_id = guard.create_policy(
        admin_key="pk_admin",
        user_public_key="pk_user",
        scope="file:read:/data/*",
        description="comparison-boundary test",
    )

    assert guard.can_perform("pk_admin", "admin:settings:write") is True
    guard.revoke_policy(policy_id, admin_key="pk_admin")
    guard.rotate_admin_key(old_key="pk_admin", new_key="pk_admin_v2")

    assert compared == [
        ("pk_admin", "pk_admin"),  # admin_sign_elevation
        ("pk_admin", "pk_admin"),  # create_policy
        ("pk_admin", "pk_admin"),  # can_perform admin bypass
        ("pk_admin", "pk_admin"),  # revoke_policy
        ("pk_admin", "pk_admin"),  # rotate_admin_key
    ]
