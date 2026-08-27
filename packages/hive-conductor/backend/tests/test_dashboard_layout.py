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

    def test_strips_generic_request_primitives_from_widget_config(self, authed_client: Any) -> None:
        hostile = {
            "widgets": [
                {
                    "id": "evil",
                    "type": "custom",
                    "title": "evil",
                    "size": "2",
                    "config": {
                        "endpoint": "/v1/admin/users",
                        "method": "DELETE",
                        "params": {"all": "1"},
                        "headers": {"X-Evil": "1"},
                        "body": {"confirm": True},
                        "source": "metrics",
                        "metric": "latency",
                    },
                }
            ]
        }
        assert authed_client.put("/v1/dashboard/layout", json=hostile).status_code == 200
        config = authed_client.get("/v1/dashboard/layout").json()["widgets"][0]["config"]
        for key in ("endpoint", "method", "params", "headers", "body"):
            assert key not in config
        assert config["source"] == "metrics"
        assert config["metric"] == "latency"

    def test_strips_generic_request_primitives_inside_tabs(self, authed_client: Any) -> None:
        hostile = {
            "tabs": [
                {
                    "name": "Overview",
                    "widgets": [
                        {
                            "id": "evil-tab",
                            "type": "custom",
                            "title": "evil",
                            "size": "2",
                            "config": {"endpoint": "/v1/settings", "method": "PUT"},
                        }
                    ],
                }
            ]
        }
        assert authed_client.put("/v1/dashboard/layout", json=hostile).status_code == 200
        config = authed_client.get("/v1/dashboard/layout").json()["tabs"][0]["widgets"][0]["config"]
        assert "endpoint" not in config
        assert "method" not in config
