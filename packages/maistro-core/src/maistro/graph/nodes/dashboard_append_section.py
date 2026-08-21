"""`dashboard.append_section` — append a Markdown section to a named dashboard.

The dashboard itself is just an in-memory accumulator on the graph blackboard
(`blackboard.metadata['dashboard:<id>']`). Downstream code (the Daily Report
route) lifts the accumulated markdown when the DAG completes and renders it.

This keeps the node pure-ish: no external I/O; idempotent within a single
DAG run because the section title acts as a stable key.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from . import register_node
from .base import BaseNode, NodeContext


class DashboardAppendIn(BaseModel):
    dashboard_id: str = Field(default="default", description="Logical dashboard name")
    section_title: str = Field(description="Section heading text (used as the section key)")
    markdown: str = Field(description="Section body (already formatted)")
    order_hint: int = Field(
        default=0,
        description="Lower numbers render first; ties broken by insertion order",
    )


class DashboardAppendOut(BaseModel):
    dashboard_id: str
    section_id: str
    sections_total: int = 0


@register_node
class DashboardAppendSectionNode(BaseNode[DashboardAppendIn, DashboardAppendOut]):
    kind: ClassVar[str] = "dashboard.append_section"
    kind_category: ClassVar = "sync.transform"
    input_schema: ClassVar[type[BaseModel]] = DashboardAppendIn
    output_schema: ClassVar[type[BaseModel]] = DashboardAppendOut
    cost_hint: ClassVar[float] = 0.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = False
    display_name: ClassVar[str] = "Dashboard: append section"
    description: ClassVar[str] = (
        "Append a Markdown section under a named dashboard on the run "
        "blackboard. The Daily Report route lifts the accumulated sections."
    )

    async def _execute(self, inputs: DashboardAppendIn, ctx: NodeContext) -> DashboardAppendOut:
        bb_metadata = self._blackboard_metadata(ctx)
        key = f"dashboard:{inputs.dashboard_id}"
        dashboard: dict[str, Any] = bb_metadata.get(key) or {"sections": []}
        section_id = f"{inputs.dashboard_id}/{inputs.section_title}"

        # Upsert by section_id so re-running the same node doesn't duplicate.
        sections: list[dict[str, Any]] = list(dashboard.get("sections", []))
        for i, s in enumerate(sections):
            if s.get("id") == section_id:
                sections[i] = {
                    "id": section_id,
                    "title": inputs.section_title,
                    "markdown": inputs.markdown,
                    "order": inputs.order_hint,
                }
                break
        else:
            sections.append(
                {
                    "id": section_id,
                    "title": inputs.section_title,
                    "markdown": inputs.markdown,
                    "order": inputs.order_hint,
                }
            )

        dashboard["sections"] = sections
        bb_metadata[key] = dashboard
        return DashboardAppendOut(
            dashboard_id=inputs.dashboard_id,
            section_id=section_id,
            sections_total=len(sections),
        )

    @staticmethod
    def _blackboard_metadata(ctx: NodeContext) -> dict[str, Any]:
        """Return the writable metadata dict on the blackboard.

        If no blackboard is attached (unit tests, ad-hoc runs), fall back to
        ctx.metadata so the node still produces a valid result.
        """
        bb = ctx.blackboard
        if bb is None:
            return ctx.metadata
        if hasattr(bb, "metadata") and isinstance(bb.metadata, dict):
            return bb.metadata
        return ctx.metadata
