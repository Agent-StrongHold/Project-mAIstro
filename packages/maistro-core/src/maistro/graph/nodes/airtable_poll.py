"""`airtable.poll` — read records from an Airtable base + table.

Optional `since_iso` filter uses Airtable's `LAST_MODIFIED_TIME()` formula
so the daily-status DAG can pull only "last 24h" records.

PAT is passed in by the caller (Hive cred store), not the env.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.http import shared_client

from . import register_node
from .base import BaseNode, NodeContext


class AirtablePollIn(BaseModel):
    pat: str
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
        "Read recently-modified records from an Airtable base + table. "
        "Token comes from the Hive credential store at runtime."
    )

    async def _execute(self, inputs: AirtablePollIn, ctx: NodeContext) -> AirtablePollOut:
        params: dict[str, Any] = {
            "pageSize": inputs.page_size,
            "sort[0][field]": inputs.sort_field,
            "sort[0][direction]": inputs.sort_direction,
        }
        if inputs.since_iso:
            params["filterByFormula"] = f"IS_AFTER(LAST_MODIFIED_TIME(), '{inputs.since_iso}')"

        async with shared_client(timeout=inputs.timeout_s) as client:
            resp = await client.get(
                f"https://api.airtable.com/v0/{inputs.base_id}/{inputs.table}",
                headers={"Authorization": f"Bearer {inputs.pat}"},
                params=params,
            )

        if resp.status_code == 401:
            raise PermissionError("airtable_auth_failed status=401")
        if resp.status_code == 403:
            raise PermissionError("airtable_forbidden status=403")
        if resp.status_code >= 400:
            raise RuntimeError(f"airtable_http_error status={resp.status_code}")

        data = resp.json()
        records = [
            AirtableRecord(
                id=r.get("id", ""),
                fields=r.get("fields", {}) or {},
                created_time=r.get("createdTime", "") or "",
            )
            for r in data.get("records", [])
        ]
        return AirtablePollOut(
            records=records,
            count=len(records),
            base_id=inputs.base_id,
            table=inputs.table,
        )
