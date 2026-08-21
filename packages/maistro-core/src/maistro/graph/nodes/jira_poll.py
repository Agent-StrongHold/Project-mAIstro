"""`jira.poll` — query Jira via JQL and return the issue list.

Supports two Atlassian backends:
- **on-prem Jira Server** (Jira Data Center / Server v9 at jira.example.com).
  Uses the on-prem REST v2 API + per-request `Authorization: Bearer <PAT>`.
- **Atlassian Cloud** (any *.atlassian.net). Uses REST v3 + Basic Auth
  (email + API token) if ATLASSIAN_EMAIL is set; otherwise Bearer PAT.

The node never reads PATs from env — they live in the encrypted Hive
credential store. The caller injects the resolved PAT via `pat` so this
module stays purely "given these inputs, query Jira" and is testable
without the credential store.
"""

from __future__ import annotations

import logging
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, Field

from maistro.http import shared_client

from . import register_node
from .base import BaseNode, NodeContext

logger = logging.getLogger("maistro.nodes.jira")


class JiraPollIn(BaseModel):
    base_url: str = Field(description="e.g. https://jira.example.com or https://acme.atlassian.net")
    jql: str = Field(
        description="JQL query (e.g. assignee=currentUser() AND resolution=Unresolved)"
    )
    pat: str = Field(description="Personal access token — never logged")
    flavor: Literal["server", "cloud"] = "server"
    email: str | None = Field(default=None, description="Required only for cloud Basic auth")
    max_results: int = Field(default=20, ge=1, le=100)
    fields: list[str] = Field(default_factory=lambda: ["summary", "status", "updated", "issuetype"])
    timeout_s: float = 8.0


class JiraIssue(BaseModel):
    key: str
    summary: str = ""
    status: str = ""
    updated: str = ""
    issuetype: str = ""
    url: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, description="Full fields blob")


class JiraPollOut(BaseModel):
    issues: list[JiraIssue] = Field(default_factory=list)
    count: int = 0
    base_url: str = ""
    flavor: Literal["server", "cloud"] = "server"


@register_node
class JiraPollNode(BaseNode[JiraPollIn, JiraPollOut]):
    kind: ClassVar[str] = "jira.poll"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = JiraPollIn
    output_schema: ClassVar[type[BaseModel]] = JiraPollOut
    cost_hint: ClassVar[float] = 1.0
    idempotent: ClassVar[bool] = True  # GET is idempotent
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Jira: query (JQL)"
    description: ClassVar[str] = (
        "Run a JQL search against on-prem Jira Server Jira or Atlassian Cloud. "
        "PAT is supplied at runtime from the Hive credential store; never "
        "stored in the DAG definition."
    )

    async def _execute(self, inputs: JiraPollIn, ctx: NodeContext) -> JiraPollOut:
        base = inputs.base_url.rstrip("/")
        api_path = "/rest/api/2/search" if inputs.flavor == "server" else "/rest/api/3/search"

        headers: dict[str, str] = {"Accept": "application/json"}
        auth: tuple[str, str] | None = None
        if inputs.flavor == "server":
            headers["Authorization"] = f"Bearer {inputs.pat}"
        else:
            if inputs.email:
                auth = (inputs.email, inputs.pat)
            else:
                headers["Authorization"] = f"Bearer {inputs.pat}"

        params: dict[str, str | int] = {
            "jql": inputs.jql,
            "maxResults": inputs.max_results,
            "fields": ",".join(inputs.fields),
        }

        async with shared_client(timeout=inputs.timeout_s) as client:
            resp = await client.get(f"{base}{api_path}", params=params, headers=headers, auth=auth)

        if resp.status_code == 401:
            # Surface auth failures with a stable error code the optimizer can
            # react to (lowering trust on this edge, re-prompting for PAT).
            raise PermissionError(f"jira_auth_failed status=401 base={base}")
        if resp.status_code == 403:
            raise PermissionError(f"jira_forbidden status=403 base={base}")
        if resp.status_code >= 400:
            raise RuntimeError(f"jira_http_error status={resp.status_code} base={base}")

        data = resp.json()
        issues: list[JiraIssue] = []
        for it in data.get("issues", []):
            key = it.get("key", "")
            fields_blob = it.get("fields", {}) or {}
            status_field = fields_blob.get("status") or {}
            issuetype_field = fields_blob.get("issuetype") or {}
            issues.append(
                JiraIssue(
                    key=key,
                    summary=str(fields_blob.get("summary") or "")[:240],
                    status=str(status_field.get("name") or ""),
                    updated=str(fields_blob.get("updated") or ""),
                    issuetype=str(issuetype_field.get("name") or ""),
                    url=f"{base}/browse/{key}",
                    raw=fields_blob,
                )
            )
        return JiraPollOut(
            issues=issues,
            count=len(issues),
            base_url=base,
            flavor=inputs.flavor,
        )
