"""`jira.poll` - query Jira through the governed capability egress.

The node carries only JQL and result-shaping parameters. Jira endpoint
configuration and credentials belong to the Workspace/Project Binding.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field

from maistro.capabilities.binding_store import BindingNotFound
from maistro.capabilities.effect_context import CapabilityEffectContext, default_effect_context
from maistro.capabilities.pm_polling import (
    JIRA_POLL_CAPABILITY,
    JiraPollRequest,
    invoke_jira_poll,
)

from . import register_node
from .base import BaseNode, NodeContext


class JiraPollIn(BaseModel):
    binding_id: str = Field(description="Pre-authorized Jira Binding for this workspace/project")
    jql: str = Field(
        description="JQL query (e.g. assignee=currentUser() AND resolution=Unresolved)"
    )
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
    flavor: str = ""


@register_node
class JiraPollNode(BaseNode[JiraPollIn, JiraPollOut]):
    kind: ClassVar[str] = "jira.poll"
    kind_category: ClassVar = "sync.tool"
    input_schema: ClassVar[type[BaseModel]] = JiraPollIn
    output_schema: ClassVar[type[BaseModel]] = JiraPollOut
    cost_hint: ClassVar[float] = 1.0
    idempotent: ClassVar[bool] = True
    external_io: ClassVar[bool] = True
    display_name: ClassVar[str] = "Jira: query (JQL)"
    description: ClassVar[str] = (
        "Run a JQL search through the pre-authorized Jira capability Binding. "
        "Endpoint and credentials are supplied by Binding configuration."
    )

    def __init__(self, *, effect_context: CapabilityEffectContext | None = None) -> None:
        self._effects = effect_context or default_effect_context()

    async def _execute(self, inputs: JiraPollIn, ctx: NodeContext) -> JiraPollOut:
        if not inputs.binding_id.strip():
            raise BindingNotFound("jira.poll requires a pre-authorized Binding before any request")
        binding = await self._effects.bindings.resolve(
            inputs.binding_id,
            workspace_id=str(ctx.workspace_id or ""),
            project_id=str(ctx.project_id or ""),
            node_id=ctx.node_id,
            capability=JIRA_POLL_CAPABILITY,
        )
        request = JiraPollRequest(
            jql=inputs.jql,
            max_results=inputs.max_results,
            fields=tuple(inputs.fields),
        )
        invocation = await invoke_jira_poll(
            self._effects,
            binding=binding,
            run_id=ctx.run_id,
            node_run_id=ctx.node_run_id,
            attempt_id=ctx.attempt_id,
            effect_key=f"jira.poll.search:{inputs.jql}:{inputs.max_results}:{','.join(inputs.fields)}",
            request=request,
            timeout_s=inputs.timeout_s,
        )
        data = invocation.result if isinstance(invocation.result, dict) else {}
        base = str(binding.config.get("base_url", "")).rstrip("/")
        flavor = str(binding.config.get("flavor", "server"))
        issues: list[JiraIssue] = []
        for item in data.get("issues", []):
            key = item.get("key", "")
            fields_blob = item.get("fields", {}) or {}
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
        return JiraPollOut(issues=issues, count=len(issues), base_url=base, flavor=flavor)
