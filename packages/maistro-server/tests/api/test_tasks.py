"""Tests for task API endpoints.

Evidence: The task API contract is defined in the plan — POST returns 202,
GET returns task status, DELETE cancels, and the response schema follows
the TaskResponse model.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro.tasks.queue import get_task_queue
from maistro_server.api.tasks import _owner_id
from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


class TestOwnerId:
    """Evidence: _owner_id falls back to the "dev" user when auth is disabled
    (RequireAuth yields None only in that path) and otherwise echoes the
    authenticated principal's user_id."""

    def test_none_auth_returns_dev(self) -> None:
        assert _owner_id(None) == "dev"


class TestCreateTask:
    def test_create_returns_202(self, client: TestClient) -> None:
        response = client.post(
            "/tasks",
            json={
                "description": "Add hello world endpoint",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        assert response.status_code == 202
        data = response.json()
        assert "task_id" in data
        assert data["status"] == "queued"

    def test_create_with_constraints(self, client: TestClient) -> None:
        response = client.post(
            "/tasks",
            json={
                "description": "Implement auth",
                "workspace": "/tmp/maistro-workspace/test",
                "tier": 3,
                "branch": "feature/auth",
                "constraints": ["Use bcrypt", "Add tests"],
            },
        )
        assert response.status_code == 202

    @pytest.mark.parametrize(
        "workspace",
        [
            "/etc",
            "/root/.ssh",
            "/tmp/maistro-workspace-evil/repo",
            "/repos_evil/project",
            "../../etc/passwd",
        ],
    )
    def test_create_rejects_disallowed_workspace(self, client: TestClient, workspace: str) -> None:
        response = client.post(
            "/tasks",
            json={
                "description": "Attempt hostile workspace",
                "workspace": workspace,
            },
        )
        assert response.status_code == 422
        assert response.json()["error"]["message"] == "Workspace path is not allowed"


class TestGetTask:
    def test_get_existing_task(self, client: TestClient) -> None:
        # Create first
        create_resp = client.post(
            "/tasks",
            json={
                "description": "Test task",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        task_id = create_resp.json()["task_id"]

        # Then retrieve
        get_resp = client.get(f"/tasks/{task_id}")
        assert get_resp.status_code == 200
        data = get_resp.json()
        assert data["task_id"] == task_id
        assert data["description"] == "Test task"
        assert data["status"] == "queued"

    def test_get_nonexistent_task(self, client: TestClient) -> None:
        response = client.get("/tasks/nonexistent")
        assert response.status_code == 404


class TestGetTaskResult:
    """Evidence: GET /tasks/{id}/result returns only the result section,
    404 if the task doesn't exist, and 404 (distinct detail) if the task
    exists but has not produced a result yet."""

    def test_nonexistent_task_returns_404(self, client: TestClient) -> None:
        response = client.get("/tasks/does-not-exist/result")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Task not found"

    def test_task_without_result_returns_404(self, client: TestClient) -> None:
        create_resp = client.post(
            "/tasks",
            json={
                "description": "No result yet",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        task_id = create_resp.json()["task_id"]

        response = client.get(f"/tasks/{task_id}/result")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Task has no result yet"

    def test_task_with_result_returns_result_body(self, client: TestClient) -> None:
        from maistro.tasks.models import TaskResult

        create_resp = client.post(
            "/tasks",
            json={
                "description": "Has result",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        task_id = create_resp.json()["task_id"]
        queue = get_task_queue()
        queue.set_result(task_id, TaskResult(files_changed=["a.py"], tests_passed=3))

        response = client.get(f"/tasks/{task_id}/result")
        assert response.status_code == 200
        data = response.json()
        assert data["files_changed"] == ["a.py"]
        assert data["tests_passed"] == 3


class TestCancelTask:
    def test_cancel_queued_task(self, client: TestClient) -> None:
        create_resp = client.post(
            "/tasks",
            json={
                "description": "Cancel me",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        task_id = create_resp.json()["task_id"]

        delete_resp = client.delete(f"/tasks/{task_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["cancelled"] is True

        # Verify status changed
        get_resp = client.get(f"/tasks/{task_id}")
        assert get_resp.json()["status"] == "cancelled"

    def test_cancel_nonexistent_task_returns_404(self, client: TestClient) -> None:
        response = client.delete("/tasks/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["message"] == "Task not found"

    def test_cancel_already_terminal_task_returns_400(self, client: TestClient) -> None:
        """Evidence: cancel() returns False once a task is already in a
        terminal state, which the route must map to 400, not 200."""
        create_resp = client.post(
            "/tasks",
            json={
                "description": "Already done",
                "workspace": "/tmp/maistro-workspace/test",
            },
        )
        task_id = create_resp.json()["task_id"]

        # First cancel succeeds (queued -> cancelled is a valid transition).
        first = client.delete(f"/tasks/{task_id}")
        assert first.status_code == 200

        # Second cancel on an already-terminal task must fail with 400.
        second = client.delete(f"/tasks/{task_id}")
        assert second.status_code == 400
        assert second.json()["error"]["message"] == "Cannot cancel task in current state"


class TestListTasks:
    def test_list_returns_paginated(self, client: TestClient) -> None:
        response = client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "count" in data
        assert isinstance(data["items"], list)

    @pytest.mark.parametrize("limit", [0, -1, 201])
    def test_list_rejects_out_of_range_limits(self, client: TestClient, limit: int) -> None:
        response = client.get(f"/tasks?limit={limit}")
        assert response.status_code == 422


class TestModelsEndpoint:
    """Evidence: Open WebUI reads /v1/models to populate model selector."""

    def test_models_returns_tier_list(self, client: TestClient) -> None:
        response = client.get("/v1/models")
        assert response.status_code == 200
        data = response.json()
        assert data["object"] == "list"
        model_ids = [m["id"] for m in data["data"]]
        assert "maistro-tier-1" in model_ids
        assert "maistro-tier-2" in model_ids
        assert "maistro-tier-3" in model_ids
        assert "maistro-tier-4" in model_ids

    def test_models_owned_by_maistro(self, client: TestClient) -> None:
        data = client.get("/v1/models").json()
        for model in data["data"]:
            assert model["owned_by"] == "maistro"
