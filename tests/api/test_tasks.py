"""Tests for task API endpoints.

Evidence: The task API contract is defined in the plan — POST returns 202,
GET returns task status, DELETE cancels, and the response schema follows
the TaskResponse model.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from maistro_server.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


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


class TestListTasks:
    def test_list_returns_paginated(self, client: TestClient) -> None:
        response = client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        assert "items" in data
        assert "count" in data
        assert isinstance(data["items"], list)


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
