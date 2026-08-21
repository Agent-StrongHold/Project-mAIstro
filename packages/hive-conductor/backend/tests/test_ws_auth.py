"""WebSocket handshake authentication (review finding C2).

`routes/ws.py` had no test file at all and no auth: `AuthMiddleware` subclasses
Starlette's `BaseHTTPMiddleware`, which only runs for `scope["type"] == "http"`,
so both sockets were reachable by anyone who could open a TCP connection —
including `/dags/{id}/run`, which *executes* the graph.

**Every rejection test asserts the close code, not just the exception type.**
That is load-bearing. `services/engine.iter_task_events` returns immediately
when no backend is configured (which is the case under `tests/conftest.py`), so
the pre-fix `/tasks` socket accepted the connection and then closed cleanly —
and `receive_json()` raised `WebSocketDisconnect(1000)`, satisfying a bare
`pytest.raises(WebSocketDisconnect)` exactly as a handshake rejection does. Two
tests here were originally written that way and passed against the unfixed code:
they asserted nothing. 1008 (RFC 6455 "policy violation") is only reachable via
`_authenticate`, so asserting on it is what makes these regression nets.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

POLICY_VIOLATION = 1008
NORMAL_CLOSURE = 1000


@pytest.fixture
def anon_client() -> TestClient:
    from main import app

    return TestClient(app)


def _assert_denied(client: TestClient, path: str, **kwargs: object) -> None:
    """Connect and require a *policy* close, not merely a disconnect.

    `pytest.raises` comes first here on purpose: the denial happens during the
    handshake, i.e. inside `websocket_connect.__enter__`, so it has to be inside
    the raises block to be caught at all. The acceptance controls below invert
    the order for the opposite reason.
    """
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        client.websocket_connect(path, **kwargs) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == POLICY_VIOLATION, (
        f"expected close {POLICY_VIOLATION} (denied) but got {exc.value.code}; "
        f"{NORMAL_CLOSURE} means the socket was accepted and closed normally, "
        "which is what the unfixed code did"
    )


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_task_stream_rejects_anonymous(anon_client: TestClient) -> None:
    _assert_denied(anon_client, "/v1/ws/tasks/any-task")


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_dag_run_stream_rejects_anonymous(anon_client: TestClient) -> None:
    """The higher-stakes of the two: this socket runs the DAG."""
    _assert_denied(anon_client, "/v1/ws/dags/whatever/run")


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_dag_run_stream_rejects_authenticated_user_without_permission(
    authed_client: TestClient,
) -> None:
    """Authentication alone is not enough.

    `POST /v1/dags` requires `dags.write` in `_PROTECTED_OPS`; the seeded
    `testuser` has `permissions=[]`. If the socket only checked identity, this
    plain user could run a graph over WebSocket that the HTTP route denies —
    an elevation bypass by protocol choice.
    """
    _assert_denied(authed_client, "/v1/ws/dags/whatever/run")


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_cross_site_origin_is_rejected(authed_client: TestClient) -> None:
    """Cross-site WebSocket hijacking.

    CORS does not apply to a WebSocket handshake, and while `SameSite=Lax`
    already stops browsers attaching the session cookie cross-site, the Origin
    check is the server-side half of that defence rather than a bet on cookie
    policy.
    """
    _assert_denied(
        authed_client,
        "/v1/ws/tasks/unknown-task",
        headers={"Origin": "https://evil.example"},
    )


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_task_stream_accepts_authenticated_user(authed_client: TestClient) -> None:
    """Control: the socket must still work for a legitimate caller.

    An unknown task id yields no events, so the server closes cleanly after
    accepting. Asserting the code is 1000 rather than 1008 is what distinguishes
    "authenticated and ran" from "denied" — without it, a blanket-deny
    `_authenticate` would satisfy this test too.
    """
    # connect OUTSIDE raises: a handshake denial must escape and fail this test,
    # not be absorbed as "well, it raised WebSocketDisconnect".
    with (
        authed_client.websocket_connect("/v1/ws/tasks/unknown-task") as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_dag_run_stream_accepts_admin(admin_client: TestClient) -> None:
    """Second control, for the gate the other tests only ever see deny.

    Without this, replacing the `dags.write` check with an unconditional deny
    would leave every DAG-socket test green while the feature was dead.
    """
    with (
        admin_client.websocket_connect("/v1/ws/dags/no-such-dag/run") as ws,
        pytest.raises(WebSocketDisconnect) as exc,
    ):
        assert ws.receive_json() == {"error": "dag not found"}
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE


@pytest.mark.contract("behavioral")
@pytest.mark.scope("integration")
def test_same_origin_is_allowed(authed_client: TestClient) -> None:
    """A same-origin page must not be rejected.

    The SPA is served by this very server (`DagBuilder.tsx` builds the socket
    URL from `location.host`), so its Origin equals the request's Host and CORS
    never applied to it. The first version of this check consulted only
    `cors_origins`, whose defaults cover localhost alone — which silently broke
    the DAG socket on every deployment reached by LAN IP or hostname, since
    those never needed `CORS_ORIGINS` set in the first place.
    """
    with (
        pytest.raises(WebSocketDisconnect) as exc,
        authed_client.websocket_connect(
            "/v1/ws/tasks/unknown-task",
            headers={"Origin": "http://192.0.2.1:8101", "Host": "192.0.2.1:8101"},
        ) as ws,
    ):
        ws.receive_json()
    assert exc.value.code == NORMAL_CLOSURE, (
        "a same-origin handshake must be allowed even though the origin is not in CORS_ORIGINS"
    )
