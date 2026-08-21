"""Node catalog + registry.

Public surface:
  - :func:`register_node(cls)` — decorator + plain registration for node kinds
  - :func:`get_node(kind)` — fetch a node class by its `kind` identifier
  - :func:`list_kinds()` — enumerate all registered kinds
  - :func:`catalog_json()` — serialize the catalog for the frontend palette
  - :func:`invoke_capability_effect()` — map governed capability approval into
    the canonical Graph pause/resume contract
  - :class:`Node`, :class:`BaseNode`, :class:`NodeContext`, :class:`NodeResult`
    (re-exported from :mod:`.base`)

Concrete node implementations import + register themselves at module import
time. Importing this package triggers the eager-import sweep so every kind
is available without callers having to discover modules manually.
"""

from __future__ import annotations

from typing import Any

from .base import (
    BaseNode,
    KindCategory,
    Node,
    NodeContext,
    NodeResult,
    now_utc,
    pause_until,
)
from .capability_effect import invoke_capability_effect

_REGISTRY: dict[str, type[BaseNode[Any, Any]]] = {}


def register_node(node_cls: type[BaseNode[Any, Any]]) -> type[BaseNode[Any, Any]]:
    """Register a node class by its `kind` identifier. Usable as a decorator.

    Raises ``ValueError`` on:
      - kind collision (cannot register two classes with the same kind)
      - missing required ClassVars (kind, input_schema, output_schema)
    """
    kind = getattr(node_cls, "kind", "") or ""
    if not kind:
        raise ValueError(f"{node_cls.__name__} missing required `kind` ClassVar")
    for required in ("input_schema", "output_schema"):
        if not hasattr(node_cls, required):
            raise ValueError(f"{node_cls.__name__} missing required `{required}` ClassVar")
    if kind in _REGISTRY and _REGISTRY[kind] is not node_cls:
        raise ValueError(
            f"Node kind collision: {kind!r} already registered to "
            f"{_REGISTRY[kind].__name__}, refusing to overwrite with {node_cls.__name__}"
        )
    _REGISTRY[kind] = node_cls
    return node_cls


def get_node(kind: str) -> type[BaseNode[Any, Any]]:
    """Look up a node class by kind. Raises ``KeyError`` if not registered."""
    if kind not in _REGISTRY:
        raise KeyError(
            f"No node registered for kind={kind!r}. "
            f"Available: {sorted(_REGISTRY.keys())[:10]}{'...' if len(_REGISTRY) > 10 else ''}"
        )
    return _REGISTRY[kind]


def list_kinds() -> list[str]:
    """Sorted list of all registered node kinds."""
    return sorted(_REGISTRY.keys())


def catalog_json() -> list[dict[str, Any]]:
    """Catalog serialized for the frontend palette.

    One entry per registered kind, ordered by category then kind, with the
    metadata the DagBuilder UI needs to render a draggable tile + the schemas
    it uses to validate edge connections.
    """
    entries: list[dict[str, Any]] = []
    for kind in list_kinds():
        cls = _REGISTRY[kind]
        entries.append(
            {
                "kind": cls.kind,
                "kind_category": cls.kind_category,
                "display_name": cls.display_name or cls.kind,
                "description": cls.description or "",
                "cost_hint": cls.cost_hint,
                "idempotent": cls.idempotent,
                "external_io": cls.external_io,
                "input_schema": _schema_summary(cls.input_schema),
                "output_schema": _schema_summary(cls.output_schema),
            }
        )
    entries.sort(key=lambda e: (e["kind_category"], e["kind"]))
    return entries


def _schema_summary(model_cls: type) -> dict[str, Any]:
    """Compact representation of a Pydantic schema for the frontend.

    Full JSON Schema is overkill for the palette tooltip; the UI only needs
    field name + type + required-ness for the wiring validator.
    """
    if not hasattr(model_cls, "model_fields"):
        return {"fields": []}
    fields = []
    for name, info in model_cls.model_fields.items():
        fields.append(
            {
                "name": name,
                "type": _annotation_str(info.annotation),
                "required": info.is_required(),
                "description": info.description or "",
            }
        )
    return {"name": model_cls.__name__, "fields": fields}


def _annotation_str(ann: Any) -> str:
    if ann is None:
        return "Any"
    name = getattr(ann, "__name__", None)
    if name:
        return str(name)
    return str(ann).replace("typing.", "")


def _import_node_modules() -> None:
    """Eagerly import every concrete node module so each self-registers.

    Done via ``importlib`` (not a top-level ``from . import ...``) because the
    concrete modules call :func:`register_node` at import time, so they must be
    imported only after this module's registry + ``register_node`` are defined.
    Keep this list flat + alphabetical so new kinds are obvious to add.
    """
    import importlib

    module_names = (
        "agent_delegate_remote",  # registers "agent.delegate_remote"
        "agent_spawn_harness",  # registers "agent.spawn_harness"
        "agent_synth_dag",  # registers "agent.synth_dag"
        "airtable_poll",  # registers "airtable.poll"
        "compliance_block",  # registers "compliance.block"
        "dashboard_append_section",  # registers "dashboard.append_section"
        "human_approve_draft",  # registers "human.approve_draft"
        "human_ask_question",  # registers "human.ask_question"
        "human_delegate_to_role",  # registers "human.delegate_to_role"
        "human_review_and_edit",  # registers "human.review_and_edit"
        "jira_poll",  # registers "jira.poll"
        "jira_wait_for_subtasks",  # registers "jira.wait_for_subtasks"
        "llm_summarize",  # registers "llm.summarize"
        "rsi_quota_pace_trigger",  # registers "rsi.quota_pace_trigger"
        "transform_alias_keys",  # registers "transform.alias_keys"
        "transform_extract_field",  # registers "transform.extract_field"
        "transform_filter_by_type",  # registers "transform.filter_by_type"
        "transform_format_markdown",  # registers "transform.format_markdown"
    )
    for name in module_names:
        importlib.import_module(f"{__name__}.{name}")


_import_node_modules()

__all__ = [
    "BaseNode",
    "KindCategory",
    "Node",
    "NodeContext",
    "NodeResult",
    "catalog_json",
    "get_node",
    "invoke_capability_effect",
    "list_kinds",
    "now_utc",
    "pause_until",
    "register_node",
]
