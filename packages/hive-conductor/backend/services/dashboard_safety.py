"""Widget request containment for model- and user-authored dashboard config.

M0 containment (#483) stripped generic HTTP request primitives from persisted
widget configs. #314 tightens that blocklist into a strict declarative
allowlist: a widget config may only carry the fields its type can declaratively
express, with primitive values, bounded sizes, and no URL-scheme or
path-traversal payloads in fields that become request identifiers. The
renderer builds its own server-owned URLs from those fields, so no
model-authored configuration can ever describe a request — only what to ask
for, through a named server-side capability.

The sanitizer stays idempotent and schema-tolerant: it is applied to legacy
and corrupt persisted state before use (read, save, demo load), where
"migration" means the unsafe or unknown simply does not survive.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from urllib.parse import unquote

# Generic request primitives are never valid dashboard configuration. They are
# listed explicitly (rather than only via the allowlist) so a violation names
# what it saw — the model-facing tool reports these, and a future field that
# legitimately belongs in a config does not silently collide with them.
REQUEST_PRIMITIVE_KEYS = frozenset(
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

#: Fields every widget type may carry (presentation-only).
_COMMON_FIELDS = frozenset(
    {
        "refresh_minutes",
        "theme",
        "display",
        "target",
        "variables",
        "display_options",
    }
)

_KPI_FIELDS = frozenset({"field", "sub", "source"})

_JIRA_FIELDS = frozenset(
    {
        "project",
        "status",
        "days",
        "assignee",
        "jql_extra",
        "jira_display",
    }
)

#: The declarative data-selection fields a `custom` widget (and, via the
#: airtable-backed jira rendering, a `jira` widget) may carry. Every one of
#: these is consumed by a fixed server-side route, never by a generic fetch.
_CUSTOM_FIELDS = frozenset(
    {
        "source",
        "table",
        "filter_formula",
        "max_records",
        "field",
        "group_by",
        "display_field",
        "metric",
        "period",
        "query",
        "breakdown",
        "records",
        "count",
        "sub",
        # `project`/`status`/`days`... may ride on custom widgets migrated
        # from jira-typed ones; harmless declarative values either way.
        *_JIRA_FIELDS,
    }
)

#: The strict per-type schema. Unknown types get the `custom` set — the
#: renderer treats them as custom, so the boundary treats them as custom too.
WIDGET_CONFIG_CAPABILITIES: dict[str, frozenset[str]] = {
    "kpi": _KPI_FIELDS | _COMMON_FIELDS,
    "jira": _JIRA_FIELDS | _CUSTOM_FIELDS | _COMMON_FIELDS,
    "agent-orbs": _COMMON_FIELDS,
    "invocations": _COMMON_FIELDS,
    "cost-donut": _COMMON_FIELDS,
    "trace": _COMMON_FIELDS,
    "custom": _CUSTOM_FIELDS | _COMMON_FIELDS,
}

#: Fields whose values become identifiers or URL parameters server-side.
_IDENTIFIER_FIELDS = frozenset(
    {
        "source",
        "table",
        "project",
        "field",
        "group_by",
        "display_field",
        "metric",
        "period",
        "status",
        "assignee",
        "jira_display",
        "display",
        "theme",
        "sub",
    }
)

#: Fields that legitimately contain rich text (chat prompts, formulas, JQL).
#: Scheme characters are allowed here — they never name a destination — but
#: traversal payloads still are not.
_FREE_TEXT_FIELDS = frozenset({"query", "filter_formula", "jql_extra"})

MAX_STRING_LENGTH = 2048
_MAX_RECORD_ENTRIES = 500
_MAX_VALUE_DEPTH = 8

#: A URL scheme (`https://`, `data:`), a protocol-relative `//`, or a path
#: traversal `..` — matched on the raw and once-decoded value, so encoded
#: bypasses (`%2e%2e%2f`, `%3a%2f%2f`) are caught too.
_SCHEME_OR_TRAVERSAL = ("//", "..")


def _decoded_variants(value: str) -> list[str]:
    variants = [value]
    decoded = unquote(value)
    if decoded != value:
        variants.append(decoded)
    return variants


def _has_scheme(value: str) -> bool:
    head = value.split("/", 1)[0]
    return ":" in head


def _identifier_value_is_safe(field: str, value: str) -> bool:
    for variant in _decoded_variants(value):
        if any(marker in variant for marker in _SCHEME_OR_TRAVERSAL):
            return False
        if _has_scheme(variant):
            return False
    return True


def _free_text_value_is_safe(value: str) -> bool:
    return not any(marker in v for v in _decoded_variants(value) for marker in ("..",))


def _sanitize_string(field: str, value: str) -> str | None:
    if field in _IDENTIFIER_FIELDS and not _identifier_value_is_safe(field, value):
        return None
    if field in _FREE_TEXT_FIELDS and not _free_text_value_is_safe(value):
        return None
    return value[:MAX_STRING_LENGTH]


def _sanitize_mapping(value: dict[str, Any], depth: int) -> dict[str, Any] | None:
    clean: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or len(key) > MAX_STRING_LENGTH:
            continue
        item_clean = _sanitize_value(key, item, depth + 1)
        if item_clean is not None:
            clean[key] = item_clean
    return clean or None


def _sanitize_sequence(field: str, value: list[Any], depth: int) -> list[Any] | None:
    if len(value) > _MAX_RECORD_ENTRIES:
        value = value[:_MAX_RECORD_ENTRIES]
    clean_list: list[Any] = []
    for item in value:
        item_clean = _sanitize_value(field, item, depth + 1)
        if item_clean is not None:
            clean_list.append(item_clean)
    return clean_list or None


def _sanitize_value(field: str, value: Any, depth: int = 0) -> Any:
    """One allowlisted field's value, or the absence marker (None drops it).

    Values may nest — `breakdown`, `records`, and `variables` hold maps and
    lists — but only through primitives, never deeper than `_MAX_VALUE_DEPTH`,
    and every string is scheme/traversal-checked against its own key, so a
    hostile payload buried in a data map is judged where it sits.
    """
    if depth > _MAX_VALUE_DEPTH:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return _sanitize_string(field, value)
    if isinstance(value, dict):
        return _sanitize_mapping(value, depth)
    if isinstance(value, list):
        return _sanitize_sequence(field, value, depth)
    return None


def sanitize_widget_config(widget_type: Any, config: Any) -> dict[str, Any]:
    """The declarative subset of one widget config for its type.

    Unknown fields, request primitives, non-primitive shapes, oversized
    values, and scheme/traversal payloads do not survive. `None`-valued
    entries drop entirely rather than persisting as nulls.
    """
    if not isinstance(config, dict) or not isinstance(widget_type, str):
        return {}
    allowed = WIDGET_CONFIG_CAPABILITIES.get(widget_type, _CUSTOM_FIELDS | _COMMON_FIELDS)
    clean: dict[str, Any] = {}
    for key, value in config.items():
        if not isinstance(key, str) or key not in allowed:
            continue
        value_clean = _sanitize_value(key, value)
        if value_clean is not None:
            clean[key] = value_clean
    return clean


def widget_config_violations(widget_type: Any, config: Any) -> list[str]:
    """Why a config does not conform, named per field — for the model boundary.

    The chat tool reports these instead of silently saving a sanitized shell:
    #314 requires rejection, and a caller that is told which fields were
    rejected can produce a conforming config next turn.
    """
    if not isinstance(config, dict):
        return ["config must be an object"]
    violations: list[str] = []
    for key in sorted(config):
        if key in REQUEST_PRIMITIVE_KEYS:
            violations.append(f"{key}: request configuration is not a widget field")
        elif not isinstance(widget_type, str) or key not in (
            WIDGET_CONFIG_CAPABILITIES.get(widget_type, _CUSTOM_FIELDS | _COMMON_FIELDS)
        ):
            violations.append(f"{key}: not a declarative field of widget type {widget_type!r}")
        elif _sanitize_value(key, config[key]) is None:
            violations.append(f"{key}: value is not a declarative primitive or is unsafe")
    return violations


def _sanitize_widget(widget: Any) -> Any:
    if not isinstance(widget, dict):
        return widget
    clean = deepcopy(widget)
    clean["config"] = sanitize_widget_config(clean.get("type"), clean.get("config"))
    # `size`/`rows` drive layout only, but a hostile value here is still
    # model-authored configuration: constrain both to the grid the renderer
    # understands.
    if clean.get("size") not in ("1", "2", "3", "4", "5", "6"):
        clean["size"] = "1"
    if clean.get("rows") is not None and clean["rows"] not in ("1", "2", "3", "4"):
        clean["rows"] = "1"
    if not isinstance(clean.get("title"), str) or not clean["title"]:
        clean["title"] = str(clean.get("title") or "Widget")[:120]
    else:
        clean["title"] = clean["title"][:120]
    return clean


def sanitize_dashboard_layout(layout: Any) -> dict[str, Any]:
    """Constrain every persisted widget to its declarative capability set.

    Deliberately idempotent and schema-tolerant so it can be applied to
    legacy/corrupt persisted state before returning it to the SPA: this is
    the "validated/migrated before use" boundary for existing configs.
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
