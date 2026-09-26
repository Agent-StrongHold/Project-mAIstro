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
        body = r.json()
        assert body["ok"] is True
        # The revision is what makes `expectedRevision` usable (#340): a client
        # that never sees one cannot claim one.
        assert body["revision"] == 1
        assert body["updatedAt"]

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


def _widget_ids(layout: dict[str, Any]) -> set[str]:
    ids = {w["id"] for w in layout.get("widgets", [])}
    for tab in layout.get("tabs", []):
        ids |= {w["id"] for w in tab.get("widgets", [])}
    return ids


def _ui_principal(authed_client: Any) -> str:
    """The key the UI's PUT stores under, so the Agent edits the same layout."""
    import stores

    r = authed_client.put(
        "/v1/dashboard/layout",
        json={"tabs": [{"name": "Overview", "widgets": []}], "activeTab": 0},
    )
    assert r.status_code == 200
    (principal,) = list(stores.dashboard_layouts.keys())
    return str(principal)


class TestAgentWidgetEditIsRevisionChecked:
    """#1048: the Agent's widget edit and a UI save must not silently erase each other."""

    def _ui_saves_between_read_and_write(
        self, authed_client: Any, monkeypatch: Any, times: int
    ) -> list[str]:
        from services import dashboard_layouts

        real_effective = dashboard_layouts.effective
        ui_ids: list[str] = []

        def effective_then_ui_save(principal: str) -> Any:
            record = real_effective(principal)
            if len(ui_ids) < times:
                ui_id = f"ui-{len(ui_ids)}"
                ui_ids.append(ui_id)
                layout = dict(record.layout)
                tabs = [dict(t) for t in layout.get("tabs", [])]
                tabs[0]["widgets"] = [
                    *tabs[0].get("widgets", []),
                    {"id": ui_id, "type": "stat-score", "title": "UI", "size": "sm"},
                ]
                r = authed_client.put(
                    "/v1/dashboard/layout", json={**layout, "tabs": tabs, "activeTab": 0}
                )
                assert r.status_code == 200
            return record

        monkeypatch.setattr(dashboard_layouts, "effective", effective_then_ui_save)
        return ui_ids

    def test_a_ui_save_during_the_agent_edit_is_kept(
        self, authed_client: Any, monkeypatch: Any
    ) -> None:
        import asyncio

        from services import dashboard_layouts
        from services.chat_completion import _tool_create_dashboard_widget

        principal = _ui_principal(authed_client)
        start = dashboard_layouts.load(principal).revision
        ui_ids = self._ui_saves_between_read_and_write(authed_client, monkeypatch, times=1)

        result = asyncio.run(
            _tool_create_dashboard_widget({"type": "kpi", "title": "Agent"}, principal, None)
        )

        assert result["created"] is True
        stored = dashboard_layouts.load(principal)
        ids = _widget_ids(stored.layout)
        assert ui_ids[0] in ids, "the UI's concurrent save was overwritten by the Agent"
        assert result["widget_id"] in ids
        assert stored.revision == start + 2
        served = authed_client.get("/v1/dashboard/layout").json()
        assert {ui_ids[0], result["widget_id"]} <= _widget_ids(served)

    def test_a_ui_that_keeps_saving_is_never_overwritten(
        self, authed_client: Any, monkeypatch: Any
    ) -> None:
        import asyncio

        from services import dashboard_layouts
        from services.chat_completion import _tool_create_dashboard_widget

        principal = _ui_principal(authed_client)
        ui_ids = self._ui_saves_between_read_and_write(authed_client, monkeypatch, times=99)

        result = asyncio.run(
            _tool_create_dashboard_widget({"type": "kpi", "title": "Agent"}, principal, None)
        )

        assert result["created"] is False
        assert "kept changing" in result["error"]
        ids = _widget_ids(dashboard_layouts.load(principal).layout)
        assert set(ui_ids) <= ids
        assert not any(i.startswith("w-") for i in ids)


def test_with_widget_appends_to_the_named_tab_without_mutating_the_input() -> None:
    from services.dashboard_layouts import with_widget

    widget = {"id": "w", "type": "kpi", "title": "T"}
    base = {"tabs": [{"name": "Ops", "widgets": [{"id": "a"}]}], "activeTab": 0}

    same_tab = with_widget(base, widget, "ops")
    new_tab = with_widget(base, widget, "Money")
    flat = with_widget({"widgets": [{"id": "a"}]}, widget, "")

    assert base["tabs"][0]["widgets"] == [{"id": "a"}]
    assert same_tab["tabs"][0]["widgets"] == [{"id": "a"}, widget]
    assert new_tab["tabs"][1] == {"name": "Money", "widgets": [widget]}
    assert flat == {
        "tabs": [{"name": "Overview", "widgets": [{"id": "a"}, widget]}],
        "activeTab": 0,
    }


def test_with_widget_falls_back_to_the_first_tab_when_active_tab_is_not_one() -> None:
    from services.dashboard_layouts import with_widget

    widget = {"id": "w", "type": "kpi", "title": "T"}
    tabs = [{"name": None, "widgets": []}, {"name": "B", "widgets": []}]

    for active in (5, -1, "1", None):
        result = with_widget({"tabs": tabs, "activeTab": active}, widget, "")
        assert result["tabs"][0]["widgets"] == [widget], active
        assert result["tabs"][1]["widgets"] == [], active
    named = with_widget({"tabs": tabs, "activeTab": 0}, widget, "b")
    assert named["tabs"][1]["widgets"] == [widget]
