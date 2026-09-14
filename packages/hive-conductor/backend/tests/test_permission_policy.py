"""The shared API/UI permission inventory is the setup authorization contract."""

from __future__ import annotations

from middleware.auth import _PROTECTED_OPS, AuthMiddleware
from routes.setup import _DEFAULT_DAILY_USER_PERMISSIONS
from services.permission_policy import (
    DAILY_USER_PERMISSIONS,
    PROTECTED_OPERATIONS,
    ROLE_PERMISSIONS,
    UI_MUTATIONS,
    protected_ops_by_method,
)


def test_middleware_is_generated_from_the_policy_source() -> None:
    assert protected_ops_by_method() == _PROTECTED_OPS
    assert len(PROTECTED_OPERATIONS) > len(_PROTECTED_OPS)


def test_daily_setup_role_covers_every_visible_protected_mutation() -> None:
    expected = sorted({operation.permission for operation in UI_MUTATIONS})
    assert expected == _DEFAULT_DAILY_USER_PERMISSIONS
    assert list(DAILY_USER_PERMISSIONS) == expected
    assert set(ROLE_PERMISSIONS["user"]) == set(expected)
    assert "config.write" not in expected
    assert "containers.control" not in expected


def test_elevation_is_required_after_assignment_for_each_daily_permission() -> None:
    middleware = AuthMiddleware(app=None)
    for permission in DAILY_USER_PERMISSIONS:
        assigned = {
            "role": "user",
            "permissions": list(DAILY_USER_PERMISSIONS),
            "elevated_permissions": [],
        }
        assert not middleware._check_permission(assigned, permission)
        assigned["elevated_permissions"] = [permission]
        assert middleware._check_permission(assigned, permission)


def test_admin_role_is_break_glass_without_copying_daily_permissions() -> None:
    assert ROLE_PERMISSIONS["admin"] == ("*",)
    assert AuthMiddleware(app=None)._check_permission({"role": "admin"}, "config.write")
