"""`airtable.poll` - read records through the governed capability egress."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.pm_polling import (
    AIRTABLE_POLL_CAPABILITY,
    AirtablePollRequest,
    invoke_airtable_poll,
)

from . import register_node
from .base import BaseNode, NodeContext


class AirtablePollIn(BaseModel):
    binding_id: str = Field(
        description="Pre-authorized Airtable Binding for this workspace/project"
    )
    base_id: str = Field(description="Airtable base id, e.g. appXXXXXXXXXXXXXX")
    table: str = Field(description="Table name (URL-encoded as needed)")
    since_iso: str | None = Field(
        default=None,
        description="ISO timestamp; only return records modified after this",
    )
    sort_field: str = Field(default="Last modified time")
    sort_direction: str = Field(default="desc")
    page_size: int = Field(default=20, ge=1, le=100)
    timeout_s: float = 8.0


class AirtableRecord(BaseModel):
    id: str
    fields: dict[str, Any] = Field(default_factory=dict)
    created_time: str = ""


class AirtablePollOut(BaseModel):
    records: list[AirtableRecord] = Field(default_factory=list)
    count: int = 0
    base_id: str = ""
    table: str = ""


@register_node
class AirtablePollNode(BaseNode[AirtablePollIn, AirtablePollOut]):
    kind: ClassVar[str] = "airtable.poll"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = AirtablePollIn
    output_schema: ClassVar[type[BaseModel]] = AirtablePollOut
    cost_hint: ClassVar[float] = 1.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Airtable: poll table"
    description: ClassVar[str] = (
        "Read records through a pre-authorized Airtable capability Binding. "
        "Credentials are resolved from the Binding's credential references."
    )

    def __init__(self, *, effect_context: CapabilityEffectContext | None = None) -> None:
        self._effects = effect_context or default_effect_context()

    async def _execute(self, inputs: AirtablePollIn, ctx: NodeContext) -> AirtablePollOut:
        if not inputs.binding_id.strip():
            raise BindingNotFound(
                "airtable.poll requires a pre-authorized Binding before any request"
            )
        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=AIRTABLE_POLL_CAPABILITY,
        )
        invocation = await invoke_airtable_poll(
            self._effects,
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=f"airtable.poll.records:{inputs.base_id}:{inputs.table}:{inputs.since_iso or ''}",
            request=AirtablePollRequest(
                base_id=inputs.base_id,
                table=inputs.table,
                since_iso=inputs.since_iso,
                sort_field=inputs.sort_field,
                sort_direction=inputs.sort_direction,
                page_size=inputs.page_size,
            ),
            timeout_s=inputs.timeout_s,
        )
        data = invocation.result if isinstance(invocation.result, dict) else {}
        records = [
            AirtableRecord(
                id=record.get("id", ""),
                fields=record.get("fields", {}) or {},
                created_time=record.get("createdTime", "") or "",
            )
            for record in data.get("records", [])
        ]
        return AirtablePollOut(
            records=records,
            count=len(records),
            base_id=inputs.base_id,
            table=inputs.table,
        )
