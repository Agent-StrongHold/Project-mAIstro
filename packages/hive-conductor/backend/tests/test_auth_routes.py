class TestPermissionAssignment:
    """The grant flow that makes harness.execute/rsi.execute obtainable.

    Codex P1 on #263: scoping /v1/rsi and /v1/harness without an assignment
    path made those features permanently 403 for the intended daily account —
    registration assigns permissions=[] and /elevate can only raise
    permissions the account already holds.
    """

    def test_admin_assigns_then_user_elevates_and_passes_the_scope_check(self, admin_client):
        import stores
        from middleware.auth import AuthMiddleware

        r = admin_client.patch(
            "/v1/auth/users/user/permissions",
            json={"permissions": ["rsi.execute"]},
        )
        assert r.status_code == 200
        assert r.json()["permissions"] == ["rsi.execute"]
        assert stores.users["user"].permissions == ["rsi.execute"]

        # The assigned-but-not-elevated state must NOT satisfy the middleware
        # check (elevation is task-scoped by design)...
        mw = AuthMiddleware(app=None)
        assigned_only = {"role": "user", "permissions": ["rsi.execute"], "elevated_permissions": []}
        assert mw._check_permission(assigned_only, "rsi.execute") is False

        # ...and the assigned+elevated state must satisfy it.
        elevated = {
            "role": "user",
            "permissions": ["rsi.execute"],
            "elevated_permissions": ["rsi.execute"],
        }
        assert mw._check_permission(elevated, "rsi.execute") is True

        # Restore for other tests (session-scoped store).
        stores.users["user"] = stores.users["user"].model_copy(update={"permissions": []})

    def test_non_admin_cannot_assign_permissions(self, authed_client):
        r = authed_client.patch(
            "/v1/auth/users/user/permissions",
            json={"permissions": ["rsi.execute"]},
        )
        assert r.status_code == 403

    def test_unknown_user_is_404(self, admin_client):
        r = admin_client.patch(
            "/v1/auth/users/ghost/permissions",
            json={"permissions": ["rsi.execute"]},
        )
        assert r.status_code == 404
