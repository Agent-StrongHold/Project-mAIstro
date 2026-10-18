"""Adversarial path-matching tests for AuthMiddleware (middleware/auth.py).

Two sibling-prefix-confusion bugs were found and fixed here:

1. ``_PUBLIC_PREFIXES`` used unguarded ``str.startswith()`` for
   ``"/v1/auth/login"`` and ``"/v1/auth/register"`` (no trailing "/"
   boundary). A sibling path that merely shared the prefix string (e.g.
   ``"/v1/auth/login-history"``) would silently bypass authentication
   entirely. Fixed via ``_matches_public_prefix`` (mirrors the analogous
   fix already applied to ``tools/sandbox/workspace.py``).
2. ``_required_permission`` used ``"/invoke" in path`` (substring anywhere)
   to exempt the autonomous agent-invoke action from permission gating.
   Any future route merely containing "/invoke" as a substring — not just
   the real trailing ``/{id}/invoke`` segment — would also lose its
   permission gate. Fixed to ``path.endswith("/invoke")``.

These tests drive the real ``main:app`` + ``AuthMiddleware`` stack via
``TestClient``, matching this file's established convention (see
test_api.py, test_capabilities_settings.py) rather than an isolated
synthetic app.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from main import app
from middleware.auth import (
    _PUBLIC_EXACT,
    _PUBLIC_PREFIXES,
    _PUBLIC_PREFIXES_LOOSE,
    _matches_public_prefix,
)


def _login(username: str = "testuser", password: str = "testpass") -> TestClient:
    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, f"login failed: {r.text}"
    return c


@pytest.fixture
def temp_route() -> Iterator[object]:
    """Register a synthetic GET route on the live app, removed after the test.

    Lets tests exercise AuthMiddleware.dispatch's real routing decision for
    sibling paths that don't correspond to any real handler, without
    permanently polluting the shared `app` singleton other test modules
    also import.
    """
    added: list[str] = []

    def _add(path: str) -> None:
        async def _handler() -> dict[str, bool]:
            return {"reached": True}

        app.add_api_route(path, _handler, methods=["GET"])
        added.append(path)

    yield _add

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) not in added]


class TestMatchesPublicPrefixBoundary:
    """Unit-level boundary grid for the helper itself."""

    @pytest.mark.parametrize(
        ("path", "prefix", "expected"),
        [
            ("/v1/setup/status", "/v1/setup/", True),
            ("/v1/setup/", "/v1/setup/", True),
            # The bare prefix itself (sans trailing slash) also matches —
            # mirrors workspace.py's _is_within_prefix, where the directory
            # root is "within" itself. No route is registered at exactly
            # this path, so it's not a security-relevant case either way.
            ("/v1/setup", "/v1/setup/", True),
            ("/v1/setupextra", "/v1/setup/", False),
            ("/health", "/health", True),
            ("/health/ready", "/health", True),
            ("/healthcheck-internal", "/health", False),
            ("/healthy", "/health", False),
            ("/v1/voice/intent", "/v1/voice/", True),
            ("/v1/voicemail", "/v1/voice/", False),
        ],
    )
    def test_boundary_grid(self, path: str, prefix: str, expected: bool) -> None:
        assert _matches_public_prefix(path, prefix) is expected


class TestSiblingPrefixConfusionRegressionLock:
    """Sibling routes that merely share a public-prefix string must still
    require auth — this is the live, exploitable half of the bug (only
    paths under /v1/ are auth-gated at all, so the bypass only mattered for
    /v1/auth/* siblings; /health siblings never reach the auth-gated branch
    since they aren't under /v1/, covered separately above)."""

    @pytest.mark.parametrize(
        "sibling_path",
        [
            "/v1/auth/login-history",
            "/v1/auth/loginXYZ",
            "/v1/auth/registerSomethingElse",
            "/v1/auth/registered",
        ],
    )
    def test_v1_auth_sibling_route_requires_auth(self, temp_route, sibling_path: str) -> None:
        temp_route(sibling_path)
        c = TestClient(app)
        r = c.get(sibling_path)
        assert r.status_code == 401
        assert r.json()["detail"] == "Authentication required"

    def test_legitimate_exact_login_path_still_bypasses(self) -> None:
        c = TestClient(app)
        # Public exact path bypasses auth — the middleware does not return 401.
        # We assert != 401 rather than == 405 because FastAPI's 404 vs 405
        # distinction for a wrong-method hit on a real route depends on
        # whether the router has finished building its internal method-not-
        # allowed table (an implementation detail; varies with initialisation
        # order in a shared-app test session).
        r = c.get("/v1/auth/login")
        assert r.status_code != 401

    def test_legitimate_exact_register_path_still_bypasses(self) -> None:
        c = TestClient(app)
        r = c.get("/v1/auth/register")
        assert r.status_code != 401


class TestPublicPathsStillWork:
    """No-regression grid: every entry that should remain public still does."""

    @pytest.mark.parametrize(
        "path",
        [
            "/",
            "/favicon.ico",
            "/v1/setup/status",
            "/v1/setup/presets",
            "/v1/auth/whoami",
            "/health",
            "/health/ready",
        ],
    )
    def test_public_path_does_not_401(self, path: str) -> None:
        c = TestClient(app)
        r = c.get(path)
        assert r.status_code != 401

    @pytest.mark.parametrize("path", ["/docs", "/openapi.json", "/redoc"])
    def test_loose_docs_paths_remain_public(self, path: str) -> None:
        c = TestClient(app)
        r = c.get(path)
        assert r.status_code == 200

    def test_v1_setup_checklist_not_confused_with_v1_setup_prefix(self) -> None:
        """ "/v1/setup-checklist" must NOT match the "/v1/setup/" prefix —
        confirms the boundary check doesn't over-match a real sibling route
        that happens to share a string prefix in the other direction."""
        c = TestClient(app)
        r = c.get("/v1/setup-checklist")
        assert r.status_code == 401


class TestUnauthenticatedProtectedPaths:
    def test_unprotected_v1_path_requires_auth(self) -> None:
        c = TestClient(app)
        r = c.get("/v1/tasks")
        assert r.status_code == 401

    def test_non_v1_unregistered_path_is_not_auth_gated(self, temp_route) -> None:
        """Paths outside /v1/ are never auth-gated by this middleware at
        all (by design — only /v1/* is gated), regression-locking that
        scope so a future change to the gating condition is caught."""
        temp_route("/not-versioned-at-all")
        c = TestClient(app)
        r = c.get("/not-versioned-at-all")
        assert r.status_code == 200


class TestInvokeSubstringCarveOutBoundary:
    """Regression lock for the "/invoke" substring -> endswith fix."""

    def test_real_agent_invoke_path_still_exempted_from_permission(self) -> None:
        c = _login()
        # No agents.write permission, no elevation — would 403 under
        # _PROTECTED_OPS POST "/v1/agents" if not exempted; the route itself
        # may 404 (PM POC mode) or 200, but it must not be a 403 from the
        # permission gate.
        r = c.post("/v1/agents/some-agent/invoke", json={})
        assert r.status_code != 403

    def test_hypothetical_invoke_substring_sibling_is_not_exempted(self, temp_route) -> None:
        """A path that merely *contains* "/invoke" but doesn't end with it
        must still be permission-gated (proves endswith, not `in`)."""
        temp_route("/v1/agents/invoke-history")
        c = _login()
        r = c.post("/v1/agents/invoke-history")
        assert r.status_code == 403

    def test_path_ending_in_invoke_suffix_without_separator_not_exempted(self, temp_route) -> None:
        """ "/v1/agentsinvoke" ends with "invoke" but not "/invoke" — must
        remain gated (and in fact doesn't match the "/v1/agents" prefix
        either, but this locks the endswith("/invoke") boundary itself)."""
        temp_route("/v1/agentsinvoke")
        c = _login()
        r = c.post("/v1/agentsinvoke")
        assert r.status_code in (401, 403, 404)
        assert r.status_code != 200


class TestProtectedOpsPermissionMatrix:
    """(method, prefix) x (no perm, perm w/o elevation, perm w/ elevation,
    admin bypass) grid against a representative slice of _PROTECTED_OPS."""

    def _writer(self, task_id: str, perms: list[str]) -> TestClient:
        from datetime import UTC, datetime

        import stores

        from maistro.security.passwords import hash_password

        uid = f"opsmatrix-{task_id}"
        stores.users[uid] = stores.users._model_class(
            id=uid,
            username=uid,
            password_hash=hash_password("pw"),
            role="user",
            is_active=True,
            permissions=perms,
            created_at=datetime.now(UTC),
        )
        c = TestClient(app)
        r = c.post("/v1/auth/login", json={"username": uid, "password": "pw"})
        assert r.status_code == 200, r.text
        return c

    def test_delete_agents_without_permission_is_403(self) -> None:
        c = self._writer("del-agents-1", perms=[])
        r = c.delete("/v1/agents/foo")
        assert r.status_code == 403

    def test_delete_agents_with_permission_but_no_elevation_is_403(self) -> None:
        c = self._writer("del-agents-2", perms=["agents.delete"])
        r = c.delete("/v1/agents/foo")
        assert r.status_code == 403

    def test_delete_agents_with_permission_and_elevation_passes_gate(self) -> None:
        c = self._writer("del-agents-3", perms=["agents.delete"])
        e = c.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": ["agents.delete"], "task_id": "t-del"},
        )
        assert e.status_code == 200, e.text
        r = c.delete("/v1/agents/foo")
        assert r.status_code != 403

    def test_admin_bypasses_permission_gate_entirely(self) -> None:
        c = TestClient(app)
        r = c.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
        assert r.status_code == 200, r.text
        r2 = c.delete("/v1/agents/foo")
        assert r2.status_code != 403

    def test_post_mcp_servers_requires_mcp_write_not_agents_write(self) -> None:
        """ "/v1/mcp/servers" is a longer, more specific POST entry than any
        "/v1/mcp" prefix — confirms dict iteration order/matching picks a
        sane permission rather than the wrong sibling key."""
        c = self._writer("mcp-srv-1", perms=["agents.write"])
        r = c.post("/v1/mcp/servers", json={})
        assert r.status_code == 403

    def test_patch_capabilities_requires_config_write(self) -> None:
        c = self._writer("cap-patch-1", perms=[])
        r = c.patch("/v1/capabilities/foo", json={})
        assert r.status_code == 403


class TestAdminBlockedFromChat:
    def test_admin_cannot_use_chat(self) -> None:
        c = TestClient(app)
        r = c.post("/v1/auth/login", json={"username": "testadmin", "password": "adminpass"})
        assert r.status_code == 200, r.text
        r2 = c.post("/v1/chat/message", json={"message": "hi"})
        assert r2.status_code == 403

    def test_regular_user_not_blocked_from_chat_path(self) -> None:
        c = _login()
        r = c.post("/v1/chat/message", json={"message": "hi"})
        assert r.status_code != 403


class TestMalformedAuthHeaders:
    def test_bearer_header_case_sensitive_prefix_not_matched(self) -> None:
        c = TestClient(app)
        r = c.get("/v1/tasks", headers={"Authorization": "bearer sometoken"})
        assert r.status_code == 401

    def test_bearer_header_with_garbage_token_returns_401_not_500(self) -> None:
        c = TestClient(app)
        r = c.get("/v1/tasks", headers={"Authorization": "Bearer " + "x" * 5000})
        assert r.status_code == 401

    def test_bearer_header_empty_token_returns_401(self) -> None:
        c = TestClient(app)
        r = c.get("/v1/tasks", headers={"Authorization": "Bearer "})
        assert r.status_code == 401

    def test_cookie_session_overrides_absent_header(self) -> None:
        c = _login()
        r = c.get("/v1/tasks", headers={"Authorization": "Bearer not-a-real-session"})
        # Cookie wins (checked first in _get_user); request still succeeds.
        assert r.status_code == 200

    def test_unknown_session_id_in_cookie_is_401(self) -> None:
        c = TestClient(app)
        c.cookies.set("hive_session", "not-a-real-session-id")
        r = c.get("/v1/tasks")
        assert r.status_code == 401


class TestOptionsMethodBypass:
    def test_options_request_bypasses_auth_on_protected_path(self) -> None:
        c = TestClient(app)
        r = c.options("/v1/tasks")
        assert r.status_code != 401


def test_public_prefixes_and_loose_prefixes_are_disjoint() -> None:
    """Sanity: the two prefix tuples shouldn't overlap entries, since they
    use different matching semantics — overlap would be ambiguous/dead code."""
    assert not set(_PUBLIC_PREFIXES) & set(_PUBLIC_PREFIXES_LOOSE)


def test_public_exact_entries_not_redundantly_in_boundary_prefixes() -> None:
    """ "/v1/auth/login" and "/v1/auth/register" were removed from
    _PUBLIC_PREFIXES (now redundant with _PUBLIC_EXACT) as part of the fix —
    lock that removal in so it isn't silently reintroduced."""
    assert "/v1/auth/login" not in _PUBLIC_PREFIXES
    assert "/v1/auth/register" not in _PUBLIC_PREFIXES
    assert "/v1/auth/login" in _PUBLIC_EXACT
    assert "/v1/auth/register" in _PUBLIC_EXACT


class TestInstallPreSetupWindow:
    """/v1/install/* is public only before first-run provisioning — the wizard
    runs when no account exists yet — and reverts to normal auth afterwards
    (same one-shot boundary as /v1/setup/complete's 409 guard)."""

    def test_install_requires_auth_once_setup_complete(self) -> None:
        # conftest seeds users, so setup is complete in the test app.
        c = TestClient(app)
        r = c.get("/v1/install/session")
        assert r.status_code == 401

    def test_install_public_before_setup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import routes.setup as setup_routes

        monkeypatch.setattr(setup_routes, "_is_setup_complete", lambda: False)
        c = TestClient(app)
        r = c.get("/v1/install/session")
        # 200 in a monorepo checkout; 503 only when maistro-bootstrap is not
        # adjacent. Never 401 — that's the regression this test pins.
        assert r.status_code in (200, 503)
        if r.status_code == 200:
            assert r.json()["kind"] == "maistro_install_session_template"

    def test_install_sibling_prefix_not_public_pre_setup(
        self, monkeypatch: pytest.MonkeyPatch, temp_route
    ) -> None:
        import routes.setup as setup_routes

        monkeypatch.setattr(setup_routes, "_is_setup_complete", lambda: False)
        temp_route("/v1/installers-catalog")
        c = TestClient(app)
        r = c.get("/v1/installers-catalog")
        assert r.status_code == 401
