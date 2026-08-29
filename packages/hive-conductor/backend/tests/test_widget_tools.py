"""Tests for the dashboard widget tools in services/chat_completion.py.

The real chat tools are create_dashboard_widget (adds a widget to the
user's layout) and suggest_widgets (searches the verified widget config
library). There is no widget-removal tool — widgets are removed by
overwriting the layout via PUT /v1/dashboard/layout.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _mock_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JIRA_SERVER_URL", "https://jira.example.com")
    monkeypatch.setenv("TESTING", "1")


class TestCreateDashboardWidgetTool:
    @pytest.mark.asyncio
    async def test_returns_created_widget(self) -> None:
        from services.chat_completion import _tool_create_dashboard_widget

        result = await _tool_create_dashboard_widget(
            {"type": "kpi", "title": "My KPI", "size": "2", "config": {"field": "active_agents"}},
            user_id="u1",
            jira_pat=None,
        )
        assert result["created"] is True
        assert result["widget_id"].startswith("w-")
        assert result["type"] == "kpi"
        assert result["title"] == "My KPI"

    @pytest.mark.asyncio
    async def test_uses_defaults(self) -> None:
        from services.chat_completion import _tool_create_dashboard_widget

        result = await _tool_create_dashboard_widget({}, user_id="u1", jira_pat=None)
        assert result["title"] == "New Widget"
        assert result["type"] == "kpi"
        assert result["size"] == "2"

    @pytest.mark.asyncio
    async def test_adds_widget_to_user_layout(self) -> None:
        from services import dashboard_layouts
        from services.chat_completion import _tool_create_dashboard_widget

        result = await _tool_create_dashboard_widget(
            {"type": "kpi", "title": "Layout Check"}, user_id="u-layout", jira_pat=None
        )
        layout = dashboard_layouts.load("u-layout").layout
        widgets = layout["tabs"][layout["activeTab"]]["widgets"]
        assert any(w["id"] == result["widget_id"] for w in widgets)

    @pytest.mark.asyncio
    async def test_creates_named_tab(self) -> None:
        from services import dashboard_layouts
        from services.chat_completion import _tool_create_dashboard_widget

        await _tool_create_dashboard_widget(
            {"type": "kpi", "title": "First"}, user_id="u-tabs", jira_pat=None
        )
        result = await _tool_create_dashboard_widget(
            {"type": "kpi", "title": "Second", "tab": "Ops"}, user_id="u-tabs", jira_pat=None
        )
        assert result["tab"] == "Ops"
        tabs = dashboard_layouts.load("u-tabs").layout["tabs"]
        ops = next(t for t in tabs if t["name"] == "Ops")
        assert any(w["title"] == "Second" for w in ops["widgets"])


class TestSuggestWidgetsTool:
    @pytest.mark.asyncio
    async def test_returns_verified_configs(self) -> None:
        from services.chat_completion import _tool_suggest_widgets

        result = await _tool_suggest_widgets({}, user_id="u1", jira_pat=None)
        assert result["total_matches"] > 0
        assert 1 <= len(result["configs"]) <= 5
        for cfg in result["configs"]:
            assert {"title", "type", "size", "config"} <= cfg.keys()

    @pytest.mark.asyncio
    async def test_filters_by_source(self) -> None:
        from services.chat_completion import _tool_suggest_widgets

        result = await _tool_suggest_widgets({"source": "jira"}, user_id="u1", jira_pat=None)
        assert result["total_matches"] > 0
        assert all(c["type"] == "jira" for c in result["configs"])

    @pytest.mark.asyncio
    async def test_unknown_source_matches_nothing(self) -> None:
        from services.chat_completion import _tool_suggest_widgets

        result = await _tool_suggest_widgets({"source": "bogus"}, user_id="u1", jira_pat=None)
        assert result["total_matches"] == 0
        assert result["configs"] == []


class TestToolRegistry:
    def test_create_dashboard_widget_registered(self) -> None:
        from services.chat_completion import _TOOL_HANDLERS, _tool_create_dashboard_widget

        assert _TOOL_HANDLERS["create_dashboard_widget"] is _tool_create_dashboard_widget

    def test_suggest_widgets_registered(self) -> None:
        from services.chat_completion import _TOOL_HANDLERS, _tool_suggest_widgets

        assert _TOOL_HANDLERS["suggest_widgets"] is _tool_suggest_widgets

    def test_dashboard_edit_scope_uses_real_tools(self) -> None:
        from services.chat_completion import get_scoped_tools

        names = [t["function"]["name"] for t in get_scoped_tools("dashboard_edit")]
        assert "create_dashboard_widget" in names
        assert "suggest_widgets" in names


@pytest.mark.ac("SPEC-082926-3b80/AC-2")
@pytest.mark.asyncio
async def test_a_widget_that_could_not_be_saved_is_not_reported_as_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The chat tool used to write inside `except Exception: pass` and return
    `{"created": True}` regardless — so a user was told a widget existed when
    nothing had been stored (#340)."""
    from services import dashboard_layouts
    from services.chat_completion import _tool_create_dashboard_widget

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise dashboard_layouts.LayoutPersistenceError("the store refused the write")

    monkeypatch.setattr(dashboard_layouts, "save", refuse)

    result = await _tool_create_dashboard_widget(
        {"type": "kpi", "title": "Doomed"}, user_id="u-refused", jira_pat=None
    )

    assert result["created"] is False
    assert "not saved" in result["error"]


@pytest.mark.ac("SPEC-082926-3b80/AC-3")
@pytest.mark.asyncio
async def test_a_widget_with_no_principal_is_refused_rather_than_pooled() -> None:
    """`user_id or "dev"` put every unidentified caller's widget in one layout."""
    from services.chat_completion import _tool_create_dashboard_widget

    result = await _tool_create_dashboard_widget(
        {"type": "kpi", "title": "Homeless"}, user_id="", jira_pat=None
    )

    assert result["created"] is False
    assert "principal" in result["error"]
