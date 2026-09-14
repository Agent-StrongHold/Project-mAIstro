class TestCapabilitySnapshot:
    def test_admin_role_is_effective_without_task_elevation(self, admin_client):
        body = admin_client.get("/v1/auth/capabilities").json()
        assert body["role"] == "admin"
        assert body["surfaces"]["rsi"]["effective"] is True
        assert body["capabilities"]["config.write"]["reason"] == "admin role"

    def test_zero_permission_user_gets_live_explainable_policy(self, authed_client):
        response = authed_client.get("/v1/auth/capabilities")
        assert response.status_code == 200
        body = response.json()
        assert response.headers["cache-control"] == "no-store"
        assert body["role"] == "user"
        from services.authorization import required_permission

        assert body["surfaces"]["settings"]["permission"] == required_permission(
            "PATCH", "/v1/settings"
        )
        assert body["surfaces"]["credentials"]["permission"] == required_permission(
            "PUT", "/v1/credentials"
        )
        assert body["surfaces"]["integrations"]["permission"] == required_permission(
            "POST", "/v1/mcp/servers"
        )
        assert body["surfaces"]["rsi"]["permission"] == required_permission("GET", "/v1/rsi/status")
        assert body["surfaces"]["rsi"]["permission"] == "rsi.execute"
        assert body["surfaces"]["rsi"]["effective"] is False
        assert body["capabilities"]["rsi.execute"]["reason"] == "permission not assigned"

    def test_assignment_and_task_elevation_change_effective_policy(
        self, admin_client, authed_client
    ):
        import stores
        from routes.auth import revoke_task_elevation

        assignment = admin_client.patch(
            "/v1/auth/users/user/permissions", json={"permissions": ["rsi.execute"]}
        )
        assert assignment.status_code == 200
        try:
            assigned = authed_client.get("/v1/auth/capabilities").json()
            assert assigned["capabilities"]["rsi.execute"]["assigned"] is True
            assert assigned["capabilities"]["rsi.execute"]["effective"] is False
            assert assigned["capabilities"]["rsi.execute"]["can_elevate"] is True

            elevated = authed_client.post(
                "/v1/auth/elevate",
                json={
                    "password": "testpass",
                    "permissions": ["rsi.execute"],
                    "task_id": "cap-test",
                },
            )
            assert elevated.status_code == 200, elevated.text
            live = authed_client.get("/v1/auth/capabilities").json()
            assert live["capabilities"]["rsi.execute"]["effective"] is True
            assert "cap-test" in live["elevated_tasks"]

            session_id = authed_client.cookies.get("hive_session")
            assert session_id is not None
            session = stores.sessions[str(session_id)]
            stores.sessions[str(session_id)] = {
                **session,
                "elevated_grant_expires": {"cap-test": "2000-01-01T00:00:00+00:00"},
            }
            expired = authed_client.get("/v1/auth/capabilities").json()
            assert expired["capabilities"]["rsi.execute"]["effective"] is False

            re_elevated = authed_client.post(
                "/v1/auth/elevate",
                json={
                    "password": "testpass",
                    "permissions": ["rsi.execute"],
                    "task_id": "cap-test",
                },
            )
            assert re_elevated.status_code == 200, re_elevated.text
            revoke_task_elevation(str(session_id), "cap-test")
            revoked = authed_client.get("/v1/auth/capabilities").json()
            assert revoked["capabilities"]["rsi.execute"]["effective"] is False
        finally:
            stores.users["user"] = stores.users["user"].model_copy(update={"permissions": []})


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
