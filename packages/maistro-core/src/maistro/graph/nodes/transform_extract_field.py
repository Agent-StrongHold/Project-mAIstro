"""`transform.extract_field` — pull a single field from each item in a list.

Pure data transform; no I/O. Used by the daily-status DAG to lift summaries
out of Jira issues, names out of Airtable records, etc.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext


class ExtractFieldIn(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list, description="Records to pull from")
    field_path: str = Field(description="Dot-path within each record (e.g. 'fields.summary')")
    default: Any = Field(default=None, description="Value to use when field is missing")


class ExtractFieldOut(BaseModel):
    values: list[Any] = Field(default_factory=list)
    count: int = 0


@register_node
class TransformExtractFieldNode(BaseNode[ExtractFieldIn, ExtractFieldOut]):
    kind: ClassVar[str] = "transform.extract_field"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = ExtractFieldIn
    output_schema: ClassVar[type[BaseModel]] = ExtractFieldOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Extract field"
    description: ClassVar[str] = (
        "Pull a single field (dot-path) out of every item in a list. Pure data, no LLM."
    )

    async def _execute(self, inputs: ExtractFieldIn, ctx: NodeContext) -> ExtractFieldOut:
        path_parts = [p for p in inputs.field_path.split(".") if p]
        values: list[Any] = []
        for item in inputs.items:
            cur: Any = item
            for part in path_parts:
                cur = cur.get(part) if isinstance(cur, dict) else getattr(cur, part, None)
                if cur is None:
                    break
            values.append(cur if cur is not None else inputs.default)
        return ExtractFieldOut(values=values, count=len(values))
