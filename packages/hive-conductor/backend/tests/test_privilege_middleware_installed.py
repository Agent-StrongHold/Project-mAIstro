"""The privilege boundary is installed on the real application (#63).

The disposition that named `main.py middleware registration` as the root for
the privilege middleware (and the agent/telemetry protocols) was open since M0:
the seam was written and never on the app. These tests pin the wiring the
disposition asked for — installed, and installed *inside* the authentication
boundary, because a path-level privilege check on an unknown principal is a
no-op wearing a middleware's clothes.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from main import app


def _middleware_index(cls: type) -> int:
    """Position of `cls` in `app.user_middleware`, outermost first.

    `add_middleware` inserts at index 0, so the recorded sequence is the
    request order: the first entry is the outermost wrapper and sees the
    request first.
    """
    names = [mw.cls.__name__ for mw in app.user_middleware]
    return names.index(cls.__name__)


def test_privilege_middleware_is_installed_on_the_app() -> None:
    from middleware.privilege import PrivilegeMiddleware

    assert "PrivilegeMiddleware" in [mw.cls.__name__ for mw in app.user_middleware]
    assert _middleware_index(PrivilegeMiddleware) >= 0


def test_privilege_runs_inside_the_authenticated_boundary() -> None:
    """Later in the outermost-first list, so `AuthMiddleware` wraps it: the
    principal is known by the time a privilege table entry could consult it."""
    from middleware.auth import AuthMiddleware
    from middleware.privilege import PrivilegeMiddleware

    assert _middleware_index(PrivilegeMiddleware) > _middleware_index(AuthMiddleware)


def test_the_empty_policy_table_passes_health_through() -> None:
    """The seam is installed, not activated: today it changes no response.

    No lifespan context (no `with`): running it would start and stop the
    process-global engine for one assertion, and the singleton's teardown
    leaves later tests without an engine — the same pollution
    `test_security_headers.py` avoids by using the plain client.
    """
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
