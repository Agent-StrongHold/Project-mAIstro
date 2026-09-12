from __future__ import annotations

import pytest
from services.dashboard_safety import (
    sanitize_dashboard_layout,
    sanitize_widget_config,
    widget_config_violations,
)


def test_generic_request_primitives_are_removed_from_top_level_widgets() -> None:
    layout = {
        "widgets": [
            {
                "id": "hostile",
                "type": "custom",
                "title": "Hostile",
                "config": {
                    "endpoint": "/v1/settings",
                    "method": "DELETE",
                    "params": {"x": "1"},
                    "headers": {"X-Evil": "1"},
                    "body": {"boom": True},
                    "credentials": "include",
                    "source": "metrics",
                    "metric": "latency",
                },
            }
        ]
    }
    safe = sanitize_dashboard_layout(layout)
    config = safe["widgets"][0]["config"]
    assert config == {"source": "metrics", "metric": "latency"}


def test_generic_request_primitives_are_removed_from_tab_widgets() -> None:
    layout = {
        "tabs": [
            {
                "name": "Overview",
                "widgets": [
                    {
                        "id": "hostile",
                        "type": "custom",
                        "title": "Hostile",
                        "config": {
                            "url": "https://evil.invalid",
                            "method": "POST",
                            "table": "Safe",
                        },
                    }
                ],
            }
        ]
    }
    safe = sanitize_dashboard_layout(layout)
    assert safe["tabs"][0]["widgets"][0]["config"] == {"table": "Safe"}


def test_sanitizer_is_idempotent_and_does_not_mutate_input() -> None:
    original = {
        "widgets": [
            {
                "id": "w",
                "type": "custom",
                "title": "W",
                "config": {"endpoint": "/v1/audit", "source": "airtable", "table": "T"},
            }
        ]
    }
    once = sanitize_dashboard_layout(original)
    twice = sanitize_dashboard_layout(once)
    assert twice == once
    assert original["widgets"][0]["config"]["endpoint"] == "/v1/audit"


# --------------------------------------------------------------------------- #
# #314 — strict declarative capability schema
# --------------------------------------------------------------------------- #


def test_model_authored_fields_are_limited_to_the_types_strict_schema() -> None:
    config = {
        "source": "airtable",
        "table": "Use Cases",
        "field": "Status",
        "max_records": "100",
        "theme": "ocean",
        "display": "donut",
        "refresh_minutes": 15,
    }
    assert sanitize_widget_config("custom", config) == config

    # kpi cannot carry the custom widget's data-selection fields
    kpi = sanitize_widget_config("kpi", {**config, "field": "ttft", "sub": "p50"})
    assert kpi == {
        "field": "ttft",
        "sub": "p50",
        "source": "airtable",
        "theme": "ocean",
        "display": "donut",
        "refresh_minutes": 15,
    }
    assert "table" not in kpi


def test_unknown_fields_are_rejected_rather_than_preserved() -> None:
    safe = sanitize_widget_config(
        "jira", {"project": "DEMO", "new_feature_field": "x", "endpoint": "/v1/settings"}
    )
    assert safe == {"project": "DEMO"}

    violations = widget_config_violations(
        "jira", {"project": "DEMO", "new_feature_field": "x", "endpoint": "/v1/settings"}
    )
    assert "endpoint: request configuration is not a widget field" in violations
    assert "new_feature_field: not a declarative field of widget type 'jira'" in violations


def test_scheme_traversal_and_encoded_bypasses_are_rejected() -> None:
    hostile = {
        "table": "../../etc/passwd",
        "source": "https://evil.invalid",
        "project": "%2e%2e%2fsecrets",
        "metric": "javascript:alert(1)",
        "field": "ok-field",
    }
    safe = sanitize_widget_config("custom", hostile)
    assert safe == {"field": "ok-field"}

    violations = widget_config_violations("custom", hostile)
    assert any(v.startswith("table:") for v in violations)
    assert any(v.startswith("source:") for v in violations)
    assert any(v.startswith("project:") for v in violations)
    assert any(v.startswith("metric:") for v in violations)


def test_non_primitive_shapes_do_not_survive() -> None:
    safe = sanitize_widget_config(
        "custom",
        {
            "table": "T",
            "breakdown": {"Dev": 5, "Nested": {"deep": object}},
            "records": [{"name": "a"}, {"table": "https://evil.invalid"}],
            "variables": [{"id": "v1", "label": "Pick", "options": ["a", "b"]}],
        },
    )
    assert safe == {
        "table": "T",
        "breakdown": {"Dev": 5},
        "records": [{"name": "a"}],
        "variables": [{"id": "v1", "label": "Pick", "options": ["a", "b"]}],
    }

    deep = current = {}
    for key in "abcdefghij":
        current[key] = {}
        current = current[key]
    current["leaf"] = "value"
    assert sanitize_widget_config("custom", {"breakdown": deep}) == {}


def test_widget_envelope_fields_are_constrained() -> None:
    layout = sanitize_dashboard_layout(
        {
            "widgets": [
                {
                    "id": "w",
                    "type": "kpi",
                    "title": "x" * 500,
                    "size": "99",
                    "rows": "12",
                    "config": {"field": "ttft"},
                }
            ]
        }
    )
    widget = layout["widgets"][0]
    assert widget["title"] == "x" * 120
    assert widget["size"] == "1"
    assert widget["rows"] == "1"


def test_free_text_fields_allow_formula_characters_but_not_traversal() -> None:
    formula = "{V2 Migration Status}='Next Candidates' AND OR()"
    assert sanitize_widget_config("custom", {"filter_formula": formula}) == {
        "filter_formula": formula
    }
    assert sanitize_widget_config("custom", {"jql_extra": 'text ~ "../etc"'}) == {}


async def test_chat_widget_tool_rejects_non_declarative_config() -> None:
    """The model-facing tool reports violations instead of saving a shell (#314)."""
    from services.chat_completion import _tool_create_dashboard_widget

    result = await _tool_create_dashboard_widget(
        {
            "title": "Hostile",
            "type": "custom",
            "config": {
                "endpoint": "/v1/settings",
                "method": "DELETE",
                "headers": {"X-Evil": "1"},
                "table": "../../secrets",
                "source": "airtable",
            },
        },
        "user-1",
        None,
    )
    assert result["created"] is False
    assert any("endpoint" in v for v in result["violations"])
    assert any("method" in v for v in result["violations"])
    assert any(v.startswith("table:") for v in result["violations"])

    ok = await _tool_create_dashboard_widget(
        {
            "title": "Pipeline",
            "type": "custom",
            "config": {"source": "airtable", "table": "Use Cases", "field": "Status"},
        },
        "user-1",
        None,
    )
    assert ok.get("created") is True


class TestDemoDashboardIdsStayInsideTheDemoDirectory:
    """`demo_id` is a URL segment that names a file (CodeQL py/path-injection)."""

    @pytest.mark.parametrize(
        "demo_id",
        ["../../../etc/passwd", "..", "demo/../../secret", "/etc/passwd", "a b", "x" * 65],
    )
    async def test_a_path_shaped_id_is_not_found(self, demo_id: str) -> None:
        from routes.dashboard_layout import get_demo_dashboard

        assert await get_demo_dashboard(demo_id) == {"error": "not found"}

    async def test_an_unknown_bare_id_is_not_found(self) -> None:
        from routes.dashboard_layout import get_demo_dashboard

        assert await get_demo_dashboard("no-such-demo") == {"error": "not found"}
