"""M0 containment for model/persisted dashboard request configuration (#483)."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Generic request primitives are never valid dashboard configuration during M0.
# Fixed source widgets build their own server-owned URLs from declarative fields.
_FORBIDDEN_REQUEST_KEYS = frozenset(
    {
        "endpoint",
        "method",
        "params",
        "headers",
        "body",
        "url",
        "credentials",
    }
)


def _sanitize_widget(widget: Any) -> Any:
    if not isinstance(widget, dict):
        return widget
    clean = deepcopy(widget)
    config = clean.get("config")
    if isinstance(config, dict):
        clean["config"] = {k: v for k, v in config.items() if k not in _FORBIDDEN_REQUEST_KEYS}
    return clean


def sanitize_dashboard_layout(layout: Any) -> dict[str, Any]:
    """Strip generic HTTP request primitives from every persisted widget.

    The operation is deliberately idempotent and schema-tolerant so it can be
    applied to legacy/corrupt persisted state before returning it to the SPA.
    Unknown non-request fields are preserved for forward compatibility.
    """
    if not isinstance(layout, dict):
        return {"widgets": []}
    clean: dict[str, Any] = deepcopy(layout)
    widgets = clean.get("widgets")
    if isinstance(widgets, list):
        clean["widgets"] = [_sanitize_widget(widget) for widget in widgets]
    tabs = clean.get("tabs")
    if isinstance(tabs, list):
        safe_tabs: list[Any] = []
        for tab in tabs:
            if not isinstance(tab, dict):
                safe_tabs.append(tab)
                continue
            safe_tab = deepcopy(tab)
            tab_widgets = safe_tab.get("widgets")
            if isinstance(tab_widgets, list):
                safe_tab["widgets"] = [_sanitize_widget(widget) for widget in tab_widgets]
            safe_tabs.append(safe_tab)
        clean["tabs"] = safe_tabs
    return clean
