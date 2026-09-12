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
        from datetime import UTC, datetime

        now = datetime.now(UTC)
        stores.missions["t1"] = stores.missions._model_class(
            id="t1",
            user_id="user",
            name="t1",
            description="t1",
            status="pending",
            priority="medium",
            created_at=now,
            updated_at=now,
        )

        # The assigned-but-not-elevated state must NOT satisfy the middleware
        # check (elevation is task-scoped by design)...
        mw = AuthMiddleware(app=None)
        assigned_only = {"role": "user", "permissions": ["rsi.execute"], "elevated_permissions": []}
        assert mw._check_permission(assigned_only, "rsi.execute", "t1") is False

        # ...and assigned + a valid grant FOR THE TASK THE REQUEST NAMES must
        # satisfy it (#1239 contract: the check consumes `elevated_grants`
        # against the named task, never a session-wide union).
        elevated = {
            "id": "user",
            "role": "user",
            "permissions": ["rsi.execute"],
            "elevated_permissions": ["rsi.execute"],
            "elevated_grants": {
                "t1": {"permissions": ["rsi.execute"], "expires_at": "9999-01-01T00:00:00+00:00"}
            },
        }
        assert mw._check_permission(elevated, "rsi.execute", "t1") is True
        # A grant for one task is invisible to a request naming another (the
        # pre-#1239 union would have passed this), and to one naming no task.
        assert mw._check_permission(elevated, "rsi.execute", "other-task") is False
        assert mw._check_permission(elevated, "rsi.execute", None) is False

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
