"""Tests for routes/dashboard_layout.py — per-user widget layout persistence."""

from typing import Any


class TestDashboardLayout:
    def test_get_returns_layout(self, authed_client: Any) -> None:
        r = authed_client.get("/v1/dashboard/layout")
        assert r.status_code == 200
        data = r.json()
        assert "widgets" in data
        assert isinstance(data["widgets"], list)

    def test_put_saves_layout(self, authed_client: Any) -> None:
        layout = {"widgets": [{"id": "w1", "type": "stat-score", "title": "Score", "size": "md"}]}
        r = authed_client.put("/v1/dashboard/layout", json=layout)
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    def test_persists_across_gets(self, authed_client: Any) -> None:
        layout = {
            "widgets": [
                {"id": "a", "type": "agent-feed", "title": "Agents", "size": "lg"},
                {"id": "b", "type": "dag-list", "title": "DAGs", "size": "full"},
            ]
        }
        authed_client.put("/v1/dashboard/layout", json=layout)
        r = authed_client.get("/v1/dashboard/layout")
        assert len(r.json()["widgets"]) == 2

    def test_overwrites_previous(self, authed_client: Any) -> None:
        authed_client.put(
            "/v1/dashboard/layout",
            json={"widgets": [{"id": "old", "type": "stat-failed", "title": "Old", "size": "sm"}]},
        )
        authed_client.put(
            "/v1/dashboard/layout",
            json={"widgets": [{"id": "new", "type": "stat-running", "title": "New", "size": "sm"}]},
        )
        r = authed_client.get("/v1/dashboard/layout")
        assert len(r.json()["widgets"]) == 1
        assert r.json()["widgets"][0]["id"] == "new"
