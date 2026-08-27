from __future__ import annotations

from services.dashboard_safety import sanitize_dashboard_layout


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
