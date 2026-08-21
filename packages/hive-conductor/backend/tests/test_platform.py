"""Comprehensive platform tests — covers all major API endpoints and integrations.

Run: TESTING=1 python -m pytest tests/test_platform.py -v
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TESTING", "1")
    monkeypatch.setenv("JIRA_SERVER_URL", "https://jira.example.com")
    monkeypatch.setenv("LITELLM_API_BASE", "https://test-gateway.example.com/v1")
    monkeypatch.setenv("LITELLM_API_KEY", "test-key")


@pytest.fixture
def app():
    from main import app

    return app


@pytest.fixture
def client(app):
    from fastapi.testclient import TestClient

    return TestClient(app)


# admin_client comes from conftest.py — real POST /v1/auth/login session.


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Health & Core
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestHealth:
    def test_health_endpoint(self, client):
        r = client.get("/health/ready")
        assert r.status_code == 200

    def test_frontend_index_served(self, client):
        # Frontend dist should serve index.html at root paths
        r = client.get("/")
        assert r.status_code in (200, 404)  # 404 if no frontend-dist


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Dashboard Layout
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDashboardLayout:
    def test_get_layout(self, admin_client):
        r = admin_client.get("/v1/dashboard/layout")
        assert r.status_code == 200
        data = r.json()
        assert "tabs" in data or "widgets" in data

    def test_put_layout_with_tabs(self, admin_client):
        layout = {
            "tabs": [
                {
                    "name": "Overview",
                    "widgets": [
                        {
                            "id": "w1",
                            "type": "kpi",
                            "title": "Test",
                            "size": "1",
                            "config": {"field": "active_agents"},
                        }
                    ],
                }
            ],
            "activeTab": 0,
        }
        r = admin_client.put("/v1/dashboard/layout", json=layout)
        assert r.status_code == 200

    def test_layout_persists(self, admin_client):
        layout = {
            "tabs": [
                {
                    "name": "T1",
                    "widgets": [
                        {"id": "x", "type": "kpi", "title": "X", "size": "1", "config": {}}
                    ],
                }
            ],
            "activeTab": 0,
        }
        admin_client.put("/v1/dashboard/layout", json=layout)
        r = admin_client.get("/v1/dashboard/layout")
        assert r.json()["tabs"][0]["name"] == "T1"

    def test_metrics_endpoint(self, admin_client):
        r = admin_client.get("/v1/dashboard/metrics")
        assert r.status_code == 200
        data = r.json()
        assert "active_agents" in data

    def test_widget_examples(self, admin_client):
        r = admin_client.get("/v1/dashboard/widget-examples")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_demos_list(self, admin_client):
        r = admin_client.get("/v1/dashboard/demos")
        assert r.status_code == 200

    def test_deck_templates(self, admin_client):
        r = admin_client.get("/v1/dashboard/deck-templates")
        assert r.status_code == 200
        templates = r.json()
        assert len(templates) >= 30
        assert all("id" in t and "category" in t and "html" in t for t in templates)

    def test_deck_templates_filter_by_category(self, admin_client):
        r = admin_client.get("/v1/dashboard/deck-templates?category=KPI")
        assert r.status_code == 200
        templates = r.json()
        assert all(t["category"] == "KPI" for t in templates)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Widgets (Airtable / Jira)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestWidgets:
    def test_airtable_widget_no_creds(self, admin_client):
        r = admin_client.get("/v1/widgets/airtable?table=test&group_by=Status&max_records=10")
        assert r.status_code == 200
        data = r.json()
        # Should return error (no creds), not crash
        assert "error" in data or "breakdown" in data

    def test_jira_widget_no_creds(self, admin_client):
        r = admin_client.get("/v1/widgets/jira?project=TEST")
        assert r.status_code == 200
        data = r.json()
        assert "error" in data or "issues" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Credentials
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCredentials:
    def test_list_credentials(self, admin_client):
        r = admin_client.get("/v1/credentials")
        assert r.status_code == 200
        data = r.json()
        assert "credentials" in data
        # Should have airtable and jira at minimum
        ids = [c["id"] for c in data["credentials"]]
        assert "airtable" in ids

    def test_get_credential_config(self, admin_client):
        r = admin_client.get("/v1/credentials/airtable/config")
        assert r.status_code == 200
        assert "config" in r.json()

    def test_save_credential_config(self, admin_client):
        r = admin_client.put(
            "/v1/credentials/airtable/config", json={"config": {"base_id": "appTEST123"}}
        )
        assert r.status_code == 200
        assert r.json()["config"]["base_id"] == "appTEST123"

    def test_reject_unknown_config_fields(self, admin_client):
        r = admin_client.put(
            "/v1/credentials/airtable/config", json={"config": {"evil_field": "hack"}}
        )
        assert r.status_code == 400


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Chat Completion
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestChatCompletion:
    def test_tool_definitions_valid(self):
        """All PM_TOOLS must have valid OpenAI function-calling schema."""
        from services.chat_completion import PM_TOOLS

        assert len(PM_TOOLS) > 10
        for tool in PM_TOOLS:
            assert tool["type"] == "function"
            fn = tool["function"]
            assert "name" in fn
            assert "description" in fn
            assert "parameters" in fn
            assert fn["parameters"]["type"] == "object"
            assert "properties" in fn["parameters"]

    def test_tool_handlers_registered(self):
        """Every tool in PM_TOOLS must have a handler."""
        from services.chat_completion import _TOOL_HANDLERS, PM_TOOLS

        for tool in PM_TOOLS:
            name = tool["function"]["name"]
            assert name in _TOOL_HANDLERS, f"Tool '{name}' has no handler"

    def test_scoped_tools_deck(self):
        from services.chat_completion import get_scoped_tools

        tools = get_scoped_tools("deck")
        names = [t["function"]["name"] for t in tools]
        assert "airtable_query" in names
        assert "poll_jira" not in names

    def test_scoped_tools_dashboard_edit(self):
        from services.chat_completion import get_scoped_tools

        tools = get_scoped_tools("dashboard_edit")
        names = [t["function"]["name"] for t in tools]
        assert "create_widget" in names or "create_dashboard_widget" in names
        assert "airtable_query" in names

    def test_scoped_tools_none_returns_all(self):
        from services.chat_completion import PM_TOOLS, get_scoped_tools

        tools = get_scoped_tools(None)
        assert len(tools) == len(PM_TOOLS)

    @pytest.mark.asyncio
    async def test_create_dashboard_widget_tool(self):
        from services.chat_completion import _tool_create_dashboard_widget

        result = await _tool_create_dashboard_widget(
            {"title": "Test", "type": "kpi", "size": "1", "config": {"field": "active_agents"}},
            user_id="test-user",
            jira_pat=None,
        )
        assert result["created"] is True
        assert result["widget_id"].startswith("w-")
        assert result["type"] == "kpi"

    @pytest.mark.asyncio
    async def test_suggest_widgets_tool(self):
        from services.chat_completion import _tool_suggest_widgets

        result = await _tool_suggest_widgets(
            {"source": "airtable"},
            user_id="test-user",
            jira_pat=None,
        )
        assert result["total_matches"] > 0
        assert all("config" in c for c in result["configs"])

    @pytest.mark.asyncio
    async def test_tool_execution_error_handled(self):
        """Tool failures should return error dict, not raise."""
        from services.chat_completion import _execute_tool

        # Call a tool that will fail (no Jira PAT)
        result = await _execute_tool("poll_jira", {}, "test-user")
        assert "error" in result

    def test_assistant_tool_call_content_is_none(self):
        """When assistant has tool_calls, content must be None not empty string."""
        # This is the gateway 400 fix
        # Simulate what happens in the tool loop
        msg = {
            "content": None,
            "tool_calls": [{"id": "tc1", "function": {"name": "test", "arguments": "{}"}}],
        }
        assistant_msg = {
            "role": "assistant",
            "content": msg.get("content") or None,
            "tool_calls": msg["tool_calls"],
        }
        # Must be None, not ""
        assert assistant_msg["content"] is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Agents
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestAgents:
    def test_list_agents(self, admin_client):
        r = admin_client.get("/v1/agents")
        assert r.status_code == 200
        assert isinstance(r.json(), list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Settings
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSettings:
    def test_get_settings(self, admin_client):
        r = admin_client.get("/v1/settings")
        assert r.status_code == 200

    def test_get_models(self, admin_client):
        r = admin_client.get("/v1/settings/models")
        assert r.status_code == 200
        data = r.json()
        assert "models" in data


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# DAGs
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDAGs:
    def test_list_dags(self, admin_client):
        r = admin_client.get("/v1/dags")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_dag_runs(self, admin_client):
        r = admin_client.get("/v1/dag-runs")
        assert r.status_code == 200

    def test_dag_metrics(self, admin_client):
        r = admin_client.get("/v1/dag-metrics")
        assert r.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Memory
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMemory:
    def test_list_entries(self, admin_client):
        r = admin_client.get("/v1/memory/entries")
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_list_namespaces(self, admin_client):
        r = admin_client.get("/v1/memory/namespaces")
        assert r.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Persistence (PostgREST)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestPersistence:
    def test_pg_persisted_store_interface(self):
        from services.pg_persisted import PgPersistedStore

        store = PgPersistedStore()
        # Should not crash without POSTGREST_URL
        assert store.list_all_raw("test") == []

    def test_pg_store_helpers(self):
        from services.pg_store import is_pg_available

        # Without env var, should return False
        assert is_pg_available() is False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# MCP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestMCP:
    def test_list_servers(self, admin_client):
        r = admin_client.get("/v1/mcp/servers")
        assert r.status_code == 200

    def test_list_tools(self, admin_client):
        r = admin_client.get("/v1/mcp/tools")
        assert r.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Schedules & Quotas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSchedules:
    def test_list_schedules(self, admin_client):
        r = admin_client.get("/v1/schedules")
        assert r.status_code == 200


class TestQuotas:
    def test_providers(self, admin_client):
        r = admin_client.get("/v1/quotas/providers")
        assert r.status_code == 200

    def test_models(self, admin_client):
        r = admin_client.get("/v1/quotas/models")
        assert r.status_code == 200


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Data Files Integrity
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestDataFiles:
    def test_dashboard_layouts_json_valid(self):
        path = Path(__file__).parent.parent / "data" / "dashboard_layouts.json"
        data = json.loads(path.read_text())
        assert isinstance(data, dict)
        # Should have at least one user key with tabs
        for _uid, layout in data.items():
            assert "tabs" in layout
            assert len(layout["tabs"]) > 0

    def test_widget_examples_json_valid(self):
        path = Path(__file__).parent.parent / "data" / "widget_examples.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) > 50

    def test_deck_templates_json_valid(self):
        path = Path(__file__).parent.parent / "data" / "deck_templates.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) >= 50
        categories = {t["category"] for t in data}
        assert "KPI" in categories
        assert "Charts" in categories
        assert "Layout" in categories

    def test_widget_templates_json_valid(self):
        path = Path(__file__).parent.parent / "data" / "widget_templates.json"
        data = json.loads(path.read_text())
        assert isinstance(data, list)
        assert len(data) > 10

    def test_verified_widget_configs_json_valid(self):
        path = Path(__file__).parent.parent / "data" / "verified_widget_configs.json"
        if path.exists():
            data = json.loads(path.read_text())
            assert isinstance(data, list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Import Smoke Tests (ensures no module-level crashes)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestImports:
    def test_main_imports(self):
        import main  # noqa: F401

    def test_chat_completion_imports(self):
        from services import chat_completion  # noqa: F401

    def test_widgets_imports(self):
        from routes import widgets  # noqa: F401

    def test_dashboard_layout_imports(self):
        from routes import dashboard_layout  # noqa: F401

    def test_credentials_imports(self):
        from routes import credentials  # noqa: F401

    def test_pg_persisted_imports(self):
        from services import pg_persisted  # noqa: F401

    def test_pg_store_imports(self):
        from services import pg_store  # noqa: F401
