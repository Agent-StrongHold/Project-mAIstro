"""`transform.filter_by_type` — keep only items whose issuetype matches.

Used by the daily-status DAG to keep just Epics from a Jira poll result, or
just bugs from a Linear list, or only records of a certain kind from Airtable.
The "type" field path is configurable so it works across data sources.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext


class FilterByTypeIn(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    types: list[str] = Field(description="Type values to KEEP (case-insensitive)")
    type_path: str = Field(
        default="fields.issuetype.name",
        description="Dot-path within each item where the type lives",
    )
    case_sensitive: bool = False


class FilterByTypeOut(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    kept: int = 0
    dropped: int = 0


@register_node
class TransformFilterByTypeNode(BaseNode[FilterByTypeIn, FilterByTypeOut]):
    kind: ClassVar[str] = "transform.filter_by_type"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = FilterByTypeIn
    output_schema: ClassVar[type[BaseModel]] = FilterByTypeOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Filter by type"
    description: ClassVar[str] = (
        "Keep only items whose configured type field matches one of the "
        "allowed values. Pure data, no LLM."
    )

    async def _execute(self, inputs: FilterByTypeIn, ctx: NodeContext) -> FilterByTypeOut:
        allow = set(inputs.types) if inputs.case_sensitive else {t.lower() for t in inputs.types}
        path_parts = [p for p in inputs.type_path.split(".") if p]

        kept: list[dict[str, Any]] = []
        dropped = 0
        for item in inputs.items:
            cur: Any = item
            for part in path_parts:
                cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
                if cur is None:
                    break
            type_value: str | None = str(cur) if cur is not None else None
            check_value = (
                type_value if (inputs.case_sensitive or type_value is None) else type_value.lower()
            )
            if check_value is not None and check_value in allow:
                kept.append(item)
            else:
                dropped += 1
        return FilterByTypeOut(items=kept, kept=len(kept), dropped=dropped)
