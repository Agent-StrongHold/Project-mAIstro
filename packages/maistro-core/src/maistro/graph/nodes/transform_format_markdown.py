"""`transform.format_markdown` — render a list of items + a template into Markdown.

The template is a literal Markdown string with `{field}` placeholders. Each
item in the input list produces one rendered row; the rows are joined with
newlines and prefixed with an optional `header`.

Pure data; no LLM. The format is intentionally simple — the LLM-driven
formatting variants live in `llm.summarize`.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext


class FormatMarkdownIn(BaseModel):
    items: list[dict[str, Any]] = Field(default_factory=list)
    template: str = Field(
        description=(
            "Per-item template with {field} placeholders. Use dot-path keys "
            "for nested fields (e.g. '- {key}: {fields.summary}')."
        )
    )
    header: str = Field(default="", description="Markdown text prepended once, before the rows")
    footer: str = Field(default="", description="Markdown text appended once, after the rows")
    empty_fallback: str = Field(default="_no items_", description="Text shown when items is empty")


class FormatMarkdownOut(BaseModel):
    markdown: str = ""
    rows_rendered: int = 0


@register_node
class TransformFormatMarkdownNode(BaseNode[FormatMarkdownIn, FormatMarkdownOut]):
    kind: ClassVar[str] = "transform.format_markdown"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = FormatMarkdownIn
    output_schema: ClassVar[type[BaseModel]] = FormatMarkdownOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Format Markdown"
    description: ClassVar[str] = (
        "Render a list of items into a Markdown block using a literal "
        "template. Pure data; for LLM-driven formatting use llm.summarize."
    )

    async def _execute(self, inputs: FormatMarkdownIn, ctx: NodeContext) -> FormatMarkdownOut:
        if not inputs.items:
            md = inputs.header + ("\n" if inputs.header else "") + inputs.empty_fallback
            if inputs.footer:
                md += "\n" + inputs.footer
            return FormatMarkdownOut(markdown=md, rows_rendered=0)

        rows: list[str] = []
        for item in inputs.items:
            try:
                rows.append(_render(inputs.template, item))
            except KeyError as exc:
                # Missing field — render placeholder so the user sees what's
                # absent rather than silently dropping the row.
                rows.append(f"{inputs.template} (missing: {exc.args[0]})")
        parts: list[str] = []
        if inputs.header:
            parts.append(inputs.header)
        parts.extend(rows)
        if inputs.footer:
            parts.append(inputs.footer)
        return FormatMarkdownOut(markdown="\n".join(parts), rows_rendered=len(rows))


def _render(template: str, item: dict[str, Any]) -> str:
    """Render a {placeholder}-style template against a dict that may have
    dot-path keys ('fields.summary')."""
    import re

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        parts = [p for p in key.split(".") if p]
        cur: Any = item
        for p in parts:
            cur = cur.get(p) if isinstance(cur, dict) else getattr(cur, p, None)
            if cur is None:
                return ""
        return str(cur)

    return re.sub(r"\{([^{}]+)\}", repl, template)
