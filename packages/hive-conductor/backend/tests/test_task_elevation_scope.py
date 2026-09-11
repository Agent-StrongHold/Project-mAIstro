"""Task-scoped elevation is not a session-wide union (#1239).

The pre-fix contract stored grants per task id but *checked* them against a
session-wide union (`get_current_user` merged every task's permissions into
one flat `elevated_permissions` list), and accepted any string as a task id.
One elevation therefore covered every later request for the session's whole
seven-day lifetime — for a task id nothing would ever revoke. This file pins
the repaired contract:

- a grant answers only a request that names the very task it was issued for
  (`X-Elevated-Task`), and only while it is unexpired;
- an expired grant stops answering immediately, is pruned from the session,
  and a legacy grant with no recorded bound reads as expired (fail closed);
- task ids are syntax-validated at elevation time, so a client cannot mint
  grants under ids shaped to escape the revocation and header paths;
- the TTL comes from `elevation_grant_ttl_seconds` (ADR-028 time-boxed
  delegation, ADR-068 §D short-TTL elevation grant).

Every route-level test drives the real `main:app` + `AuthMiddleware` stack via
`TestClient`, matching this suite's convention (test_api.py, test_ws_auth.py).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from routes import auth as auth_routes
from starlette.websockets import WebSocketDisconnect

POLICY_VIOLATION = 1008


@pytest.fixture
def preserved_sessions():
    """Keep the shared session store clean across tests (test_session_purge pattern)."""
    import copy

    import stores

    snapshot = copy.deepcopy(dict(stores.sessions.items()))
    yield
    stores.sessions.clear()
    for key, value in snapshot.items():
        stores.sessions[key] = value


def _member_client(permissions: list[str], uid: str, password: str = "pw") -> TestClient:
    """A logged-in user holding exactly `permissions`, assigned (not elevated)."""
    import stores
    from main import app

    from maistro.security.passwords import hash_password

    stores.users[uid] = stores.users._model_class(
        id=uid,
        username=uid,
        password_hash=hash_password(password),
        role="user",
        is_active=True,
        permissions=permissions,
        created_at=datetime.now(UTC),
    )
    c = TestClient(app)
    r = c.post("/v1/auth/login", json={"username": uid, "password": password})
    assert r.status_code == 200, r.text
    return c


def _elevate(c: TestClient, password: str, permissions: list[str], task_id: str) -> dict[str, Any]:
    r = c.post(
        "/v1/auth/elevate",
        json={"password": password, "permissions": permissions, "task_id": task_id},
    )
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.usefixtures("preserved_sessions")
class TestGrantAnswersOnlyForItsOwnTask:
    """The flattening failure mode: one task's grant must not cover the session."""

    def test_grant_for_task_a_is_403_when_request_names_task_b(self) -> None:
        c = _member_client(["config.write"], "tscope-a")
        _elevate(c, "pw", ["config.write"], "task-a")

        r_other = c.put(
            "/v1/settings",
            json={"temperature": 0.5},
            headers={"X-Elevated-Task": "task-b"},
        )
        assert r_other.status_code == 403, (
            "a grant for task-a must not authorize a request acting under task-b"
        )

    def test_grant_is_403_when_request_names_no_task(self) -> None:
        c = _member_client(["config.write"], "tscope-b")
        _elevate(c, "pw", ["config.write"], "task-a")

        r_unnamed = c.put("/v1/settings", json={"temperature": 0.5})
        assert r_unnamed.status_code == 403, (
            "without a named task there is no grant to satisfy the check — "
            "the pre-#1239 union would have passed this request"
        )

    def test_grant_still_answers_for_the_task_it_was_issued_for(self) -> None:
        c = _member_client(["config.write"], "tscope-c")
        _elevate(c, "pw", ["config.write"], "task-a")

        r = c.put(
            "/v1/settings",
            json={"temperature": 0.5},
            headers={"X-Elevated-Task": "task-a"},
        )
        assert r.status_code == 200, r.text

    def test_second_task_elevation_does_not_widen_the_first(self) -> None:
        """Two live grants must not collapse into one union at check time."""
        c = _member_client(["config.write", "agents.delete"], "tscope-d")
        _elevate(c, "pw", ["config.write"], "task-a")
        _elevate(c, "pw", ["agents.delete"], "task-b")

        r_mixed = c.put(
            "/v1/settings",
            json={"temperature": 0.5},
            headers={"X-Elevated-Task": "task-b"},
        )
        assert r_mixed.status_code == 403, "task-b's grant carries no config.write"

        r_own = c.delete("/v1/agents/x", headers={"X-Elevated-Task": "task-b"})
        assert r_own.status_code != 403

    def test_whoami_union_is_display_only(self) -> None:
        """whoami may show the union of live grants, but checking ignores it."""
        c = _member_client(["config.write"], "tscope-e")
        _elevate(c, "pw", ["config.write"], "task-a")
        who = c.get("/v1/auth/whoami").json()["user"]
        assert who["elevated_permissions"] == ["config.write"]
        assert who["elevated_grants"]["task-a"]["permissions"] == ["config.write"]

        # ...while the unnamed request stays denied anyway.
        assert c.put("/v1/settings", json={"temperature": 0.5}).status_code == 403


@pytest.mark.usefixtures("preserved_sessions")
class TestGrantDoesNotOutliveItsBound:
    """The 'indefinite' half: a grant dies at its expiry even with no revocation."""

    def test_expired_grant_stops_answering_and_is_pruned(self) -> None:
        import stores

        c = _member_client(["config.write"], "tscope-f")
        task_id = "never-revoked-task"
        _elevate(c, "pw", ["config.write"], task_id)

        # An id no mission will ever complete used to hold its grant for the
        # session's whole lifetime. Simulate the clock passing the recorded
        # bound — the exact state `_active_grants` must treat as dead.
        session_id = c.cookies.get("hive_session")
        assert session_id and session_id in stores.sessions
        stored = stores.sessions[session_id]["elevated_grants"][task_id]
        stored["expires_at"] = datetime.now(UTC) - timedelta(seconds=1)

        who = c.get("/v1/auth/whoami").json()["user"]
        assert who["elevated_tasks"] == [], "expired grant must not be reported live"

        r = c.put(
            "/v1/settings",
            json={"temperature": 0.5},
            headers={"X-Elevated-Task": task_id},
        )
        assert r.status_code == 403, "expired grant must not authorize anything"

        # ...and the dead grant is gone from the store, not merely filtered:
        # a prune-shaped read is what keeps it from ever resurrecting.
        assert stores.sessions[session_id]["elevated_grants"] == {}

    def test_legacy_unbounded_list_grant_reads_as_expired(self) -> None:
        """Pre-TTL sessions stored bare permission lists — fail closed on them."""
        import stores

        c = _member_client(["config.write"], "tscope-g")
        session_id = c.cookies.get("hive_session")
        assert session_id
        stores.sessions[session_id] = {
            **stores.sessions[session_id],
            "elevated_grants": {"old-task": ["config.write"]},
        }

        sess = stores.sessions[session_id]
        assert auth_routes._active_grants(sess) == {}

        who = c.get("/v1/auth/whoami").json()["user"]
        assert who["elevated_tasks"] == []
        r = c.put(
            "/v1/settings",
            json={"temperature": 0.5},
            headers={"X-Elevated-Task": "old-task"},
        )
        assert r.status_code == 403

    def test_ttl_setting_bounds_the_recorded_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The grant's bound comes from `elevation_grant_ttl_seconds`."""
        from config import get_settings

        real = get_settings()

        class _ShortTtl:
            elevation_grant_ttl_seconds = 120

            def __getattr__(self, name: str) -> Any:
                return getattr(real, name)

        monkeypatch.setattr(auth_routes, "get_settings", lambda: _ShortTtl())

        c = _member_client(["config.write"], "tscope-h")
        data = _elevate(c, "pw", ["config.write"], "ttl-task")
        recorded = datetime.fromisoformat(data["expires_at"])
        ahead = (recorded - datetime.now(UTC)).total_seconds()
        assert 119 <= ahead <= 121, f"expected ~120s bound, recorded {ahead:.1f}s"


@pytest.mark.usefixtures("preserved_sessions")
class TestTaskIdValidation:
    """Unvalidated task ids were the revocation escape hatch (#1239)."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "",
            "   ",
            "a" * 129,
            "task id with spaces",
            "task\nid",
            "task;id",
            "task/id",
            "task?id=1",
            "tab\tid",
            "é-task",
        ],
    )
    def test_malformed_task_ids_are_422(self, bad_id: str) -> None:
        c = _member_client([], "tscope-i")
        r = c.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": [], "task_id": bad_id},
        )
        assert r.status_code == 422, f"{bad_id!r} should be rejected"

    @pytest.mark.parametrize(
        "good_id",
        ["t-1", "settings-edit-temperature-1760000000", "a" * 128, "mission_42:x.y", "TASK-9"],
    )
    def test_well_formed_task_ids_are_accepted(self, good_id: str) -> None:
        c = _member_client([], "tscope-j")
        r = c.post(
            "/v1/auth/elevate",
            json={"password": "pw", "permissions": [], "task_id": good_id},
        )
        assert r.status_code == 200, r.text

    def test_elevation_binds_the_grant_under_the_validated_id(self) -> None:
        c = _member_client(["config.write"], "tscope-k")
        data = _elevate(c, "pw", ["config.write"], "bind-task")
        assert data["task_id"] == "bind-task"
        who = c.get("/v1/auth/whoami").json()["user"]
        assert who["elevated_tasks"] == ["bind-task"]
        assert who["elevated_grants"]["bind-task"]["expires_at"] == data["expires_at"]


@pytest.mark.usefixtures("preserved_sessions")
class TestWebSocketGateIsTaskScoped:
    """The dag-run socket takes the same task-scoped contract (#1239)."""

    def _dag_writer(self, uid: str) -> TestClient:
        c = _member_client(["dags.write"], uid)
        _elevate(c, "pw", ["dags.write"], "dag-task-1")
        return c

    def _assert_policy_close(self, client: TestClient, path: str) -> None:

        with (
            pytest.raises(WebSocketDisconnect) as exc,
            client.websocket_connect(path) as ws,
        ):
            ws.receive_json()
        assert exc.value.code == POLICY_VIOLATION, (
            f"expected close {POLICY_VIOLATION} but got {exc.value.code}"
        )

    def test_socket_denied_without_a_named_task(self) -> None:
        c = self._dag_writer("tscope-ws-a")
        self._assert_policy_close(c, "/v1/ws/dags/no-such-dag/run")

    def test_socket_denied_for_another_tasks_grant(self) -> None:
        c = self._dag_writer("tscope-ws-b")
        self._assert_policy_close(c, "/v1/ws/dags/no-such-dag/run?elevated_task=other-task")

    def test_socket_passes_gate_for_its_own_task(self) -> None:
        c = self._dag_writer("tscope-ws-c")
        # With no such DAG the route accepts, reports, and closes normally —
        # reaching "dag not found" is the proof the permission gate passed.
        with c.websocket_connect("/v1/ws/dags/no-such-dag/run?elevated_task=dag-task-1") as ws:
            msg = ws.receive_json()
        assert msg == {"error": "dag not found"}
