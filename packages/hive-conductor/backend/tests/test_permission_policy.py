"""The shared API/UI permission inventory is the setup authorization contract."""

from __future__ import annotations

import pytest
from middleware.auth import _PROTECTED_OPS, AuthMiddleware
from routes.setup import _DEFAULT_DAILY_USER_PERMISSIONS
from services.permission_policy import (
    DAILY_USER_PERMISSIONS,
    PROTECTED_OPERATIONS,
    ROLE_PERMISSIONS,
    UI_MUTATIONS,
    permission_for_ui_action,
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


def test_every_advertised_ui_action_resolves_through_the_policy() -> None:
    """The elevation affordance resolves action names through the one policy.

    Each advertised UI mutation must round-trip to exactly its own permission;
    a resolver that guessed would let a renamed action silently grant whatever
    the caller liked.
    """
    for operation in UI_MUTATIONS:
        assert permission_for_ui_action(operation.action) == operation.permission


def test_an_unknown_ui_action_fails_closed_with_key_error() -> None:
    with pytest.raises(KeyError, match="unknown UI action"):
        permission_for_ui_action("grant admin forever")


@pytest.mark.parametrize(
    ("membership", "expected_status"),
    [("owner", 200), ("editor", 403), ("viewer", 403), ("nonmember", 404)],
)
def test_clean_setup_restore_requires_elevation_and_live_ownership(
    monkeypatch: pytest.MonkeyPatch, membership: str, expected_status: int
) -> None:
    """Real setup/login/restore APIs, never an all-permissions daily fixture."""
    import stores
    from fastapi.testclient import TestClient
    from main import app
    from models.schemas import HiveAccount as HiveUser
    from models.workspace import Workspace
    from services.model_store import JsonStore, ModelStore

    monkeypatch.setattr(stores, "users", ModelStore("users", HiveUser))
    monkeypatch.setattr(stores, "sessions", JsonStore("sessions"))
    monkeypatch.setattr(stores, "workspaces", ModelStore("workspaces", Workspace))
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)
    daily = TestClient(app)
    setup = daily.post(
        "/v1/setup/complete",
        json={
            "hardware_preset": "auto",
            "admin_username": "review-admin",
            "admin_password": "admin-password",
            "user_username": "review-daily",
            "user_password": "daily-password",
        },
    )
    assert setup.status_code == 200, setup.text
    login = daily.post(
        "/v1/auth/login", json={"username": "review-daily", "password": "daily-password"}
    )
    assert login.status_code == 200, login.text
    principal = daily.get("/v1/auth/whoami").json()["user"]
    assert principal["role"] == "user"
    assert principal["permissions"] == list(DAILY_USER_PERMISSIONS)
    assert "*" not in principal["permissions"]
    assert principal["elevated_permissions"] == []

    created = daily.post(
        "/v1/workspaces", json={"name": "Restore review", "persona_template_id": "personal"}
    )
    assert created.status_code == 201, created.text
    path = f"/v1/workspaces/{created.json()['id']}"
    denied = daily.patch(path, json={"active": False})
    assert denied.status_code == 403
    assert "workspaces.write" in denied.json()["detail"]
    elevated = daily.post(
        "/v1/auth/elevate",
        json={
            "password": "daily-password",
            "permissions": ["workspaces.write"],
            "task_id": "restore-review",
        },
    )
    assert elevated.status_code == 200, elevated.text
    archived = daily.patch(path, json={"active": False})
    assert archived.status_code == 200, archived.text
    assert archived.json()["active"] is False

    # The owner explicitly invites the separate break-glass account. It is
    # not implicitly a member, and it still cannot become the chat user.
    admin = TestClient(app)
    assert (
        admin.post(
            "/v1/auth/login", json={"username": "review-admin", "password": "admin-password"}
        ).status_code
        == 200
    )
    assert admin.get(path).status_code == 404
    assert admin.get("/v1/chat/sessions").status_code == 403
    invited = daily.post(f"{path}/members", json={"user_id": "admin", "role": "owner"})
    assert invited.status_code == 200, invited.text
    if membership == "nonmember":
        changed = admin.delete(f"{path}/members/user")
        assert changed.status_code == 200, changed.text
    elif membership != "owner":
        changed = admin.post(f"{path}/members", json={"user_id": "user", "role": membership})
        assert changed.status_code == 200, changed.text

    restored = daily.patch(path, json={"active": True})
    assert restored.status_code == expected_status, restored.text
    visible = admin.get(path)
    assert visible.status_code == 200
    assert visible.json()["active"] is (membership == "owner")
