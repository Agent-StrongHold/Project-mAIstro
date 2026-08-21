"""HTTP client for mcp-atlassian (the MAISTRO on-prem Atlassian MCP).

Speaks streamable-HTTP MCP at `/mcp` (FastMCP convention). For v0 we
use a single-shot tools/call JSON-RPC POST — the streaming notification
channel isn't needed for synchronous tool invocations.

Per-request auth: PATs go in headers, never env. URLs come from env
(`ATLASSIAN_MCP_URL`, defaults to docker-compose service hostname).

Compatible with Cloud Rovo MCP post-migration: same headers, same JSON-RPC
shape; only the URL changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import httpx

from maistro.http import shared_client

_MAX_DESCRIPTION = 2000
_MAX_CONFLUENCE_CONTENT = 4000


class AtlassianMCPError(RuntimeError):
    """Raised when mcp-atlassian returns an error or is unreachable.

    Carries the same machine-readable fields as the MCP-tool-layer fail()
    dicts (error_code, recoverable, suggested_action) so callers can branch
    on them via the exception rather than parsing the message string.
    """

    def __init__(
        self,
        message: str,
        *,
        error_code: str = "atlassian_mcp_error",
        recoverable: bool = True,
        suggested_action: str = "Retry; if it persists, verify ATLASSIAN_MCP_URL and the PAT.",
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.recoverable = recoverable
        self.suggested_action = suggested_action


@dataclass(frozen=True)
class JiraIssue:
    key: str
    summary: str
    status: str = ""
    assignee: str | None = None
    issuetype: str = ""
    url: str | None = None
    description: str = ""
    labels: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class JiraSearchResult:
    issues: tuple[JiraIssue, ...]
    total: int
    jql: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "jql": self.jql,
            "total": self.total,
            "issues": [
                {
                    "key": i.key,
                    "summary": i.summary,
                    "status": i.status,
                    "assignee": i.assignee,
                    "issuetype": i.issuetype,
                    "url": i.url,
                    "labels": list(i.labels),
                }
                for i in self.issues
            ],
        }


@dataclass(frozen=True)
class ConfluencePage:
    id: str
    title: str
    space: str = ""
    url: str | None = None
    content: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "space": self.space,
            "url": self.url,
            "content": self.content,
        }


@dataclass(frozen=True)
class ConfluenceSearchResult:
    pages: tuple[ConfluencePage, ...]
    total: int
    query: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "total": self.total,
            "pages": [p.to_dict() for p in self.pages],
        }


def _resolve_mcp_url() -> str:
    return (
        os.environ.get("ATLASSIAN_MCP_URL")
        or os.environ.get("ATLASSIAN_SERVER_MCP_URL")
        or "http://atlassian-mcp:8000/mcp"
    )


def _extract_jira_summary(fields: dict[str, Any]) -> str:
    return str(fields.get("summary", "") if isinstance(fields, dict) else "")


def _extract_jira_status(fields: dict[str, Any]) -> str:
    status_obj = fields.get("status") if isinstance(fields, dict) else None
    status = status_obj.get("name") if isinstance(status_obj, dict) else (status_obj or "")
    return str(status or "")


def _extract_jira_assignee(fields: dict[str, Any]) -> str | None:
    assignee_obj = fields.get("assignee") if isinstance(fields, dict) else None
    assignee = assignee_obj.get("displayName") if isinstance(assignee_obj, dict) else assignee_obj
    return str(assignee) if assignee else None


def _extract_jira_issuetype(fields: dict[str, Any]) -> str:
    issuetype_obj = fields.get("issuetype") if isinstance(fields, dict) else None
    issuetype = (
        issuetype_obj.get("name") if isinstance(issuetype_obj, dict) else (issuetype_obj or "")
    )
    return str(issuetype or "")


def _extract_jira_url(d: dict[str, Any]) -> str | None:
    return str(d.get("self") or d.get("url") or "") or None


def _extract_jira_description(fields: dict[str, Any]) -> str:
    return str(fields.get("description", "") if isinstance(fields, dict) else "")[:_MAX_DESCRIPTION]


def _extract_jira_labels(fields: dict[str, Any]) -> tuple[str, ...]:
    labels = fields.get("labels", []) if isinstance(fields, dict) else []
    return tuple(str(lbl) for lbl in labels) if isinstance(labels, list) else ()


class AtlassianMCPClient:
    """v0 client for the on-prem MAISTRO Atlassian MCP.

    Methods take PATs as explicit arguments — callers fetch them from
    the per-user encrypted credential store (Hive Credentials nav). This
    keeps tokens off env/disk inside maistro-core itself.
    """

    def __init__(
        self,
        *,
        mcp_url: str | None = None,
        timeout: float = 60.0,
    ) -> None:
        self.mcp_url = (mcp_url or _resolve_mcp_url()).rstrip("/")
        self.timeout = timeout
        # Health probe endpoint is at /healthz on the same host (not under /mcp).
        # Derive the base URL by stripping a trailing /mcp segment if present.
        base = self.mcp_url
        if base.endswith("/mcp"):
            base = base[: -len("/mcp")]
        self.health_url = f"{base}/healthz"

    def _headers(self, jira_pat: str | None, confluence_pat: str | None) -> dict[str, str]:
        h: dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        # Split-header mode — per mcp-atlassian's UserTokenMiddleware. Both
        # products can be authed simultaneously in a single request.
        if jira_pat:
            h["X-Atlassian-Jira-Personal-Token"] = jira_pat
        if confluence_pat:
            h["X-Atlassian-Confluence-Personal-Token"] = confluence_pat
        return h

    async def healthz(self) -> dict[str, Any]:
        """Probe the MCP container (no auth required for /healthz)."""
        async with shared_client(timeout=self.timeout) as client:
            try:
                resp = await client.get(self.health_url)
            except httpx.HTTPError as exc:
                raise AtlassianMCPError(
                    f"healthz unreachable: {exc}",
                    error_code="atlassian_unreachable",
                    suggested_action="Check that the mcp-atlassian container is running and ATLASSIAN_MCP_URL is correct, then retry.",
                ) from exc
        if resp.status_code >= 400:
            raise AtlassianMCPError(
                f"healthz returned {resp.status_code}: {resp.text[:300]}",
                error_code="atlassian_http_error",
            )
        try:
            health: dict[str, Any] = resp.json()
            return health
        except ValueError:
            return {"status": resp.text}

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        jira_pat: str | None = None,
        confluence_pat: str | None = None,
    ) -> dict[str, Any]:
        """Invoke an MCP tool by name. Returns the parsed JSON result.

        Raises AtlassianMCPError on transport failure, HTTP error, or
        MCP-level error response.
        """
        body = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        async with shared_client(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    self.mcp_url,
                    json=body,
                    headers=self._headers(jira_pat, confluence_pat),
                )
            except httpx.HTTPError as exc:
                raise AtlassianMCPError(
                    f"MCP transport error for tool '{tool_name}': {exc}",
                    error_code="atlassian_unreachable",
                    suggested_action="Check that the mcp-atlassian container is running and ATLASSIAN_MCP_URL is correct, then retry.",
                ) from exc
        if resp.status_code >= 400:
            recoverable = resp.status_code not in (401, 403)
            suggested = (
                "Regenerate the PAT under Hive → Credentials and retry."
                if not recoverable
                else "Retry; if it persists, check mcp-atlassian's logs."
            )
            raise AtlassianMCPError(
                f"MCP '{tool_name}' returned {resp.status_code}: {resp.text[:500]}",
                error_code="atlassian_http_error",
                recoverable=recoverable,
                suggested_action=suggested,
            )
        try:
            payload = resp.json()
        except ValueError as exc:
            raise AtlassianMCPError(
                f"MCP '{tool_name}' returned non-JSON: {resp.text[:300]}",
                error_code="atlassian_invalid_response",
            ) from exc
        if "error" in payload:
            err = payload["error"]
            raise AtlassianMCPError(
                f"MCP '{tool_name}' error: {err.get('message', err)} (code={err.get('code', '?')})",
                error_code="atlassian_tool_error",
                suggested_action="Inspect the error message — e.g. invalid JQL or page id — adjust arguments and retry.",
            )
        result = payload.get("result", payload)
        return result if isinstance(result, dict) else {"raw": result}

    # ------------------------------------------------------------------
    # Convenience wrappers around the tools mcp-atlassian exposes.
    # Tool inputs/outputs match the MAISTRO repo's tool definitions in
    # src/mcp_atlassian/tools/{jira,confluence,health}.py.
    # ------------------------------------------------------------------

    async def jira_search_issues(
        self, jql: str, *, max_results: int = 25, jira_pat: str
    ) -> JiraSearchResult:
        result = await self.call_tool(
            "jira_search_issues",
            {"jql": jql, "max_results": max_results},
            jira_pat=jira_pat,
        )
        return self._parse_jira_search(result, jql=jql)

    async def jira_search_by_text(
        self,
        text: str,
        *,
        project: str | None = None,
        max_results: int = 25,
        jira_pat: str,
    ) -> JiraSearchResult:
        args: dict[str, Any] = {"text": text, "max_results": max_results}
        if project:
            args["project"] = project
        result = await self.call_tool("jira_search_by_text", args, jira_pat=jira_pat)
        return self._parse_jira_search(result, jql=f'text ~ "{text}"')

    async def jira_get_my_issues(self, *, max_results: int = 25, jira_pat: str) -> JiraSearchResult:
        result = await self.call_tool(
            "jira_get_my_issues",
            {"max_results": max_results},
            jira_pat=jira_pat,
        )
        return self._parse_jira_search(
            result, jql="assignee = currentUser() OR reporter = currentUser()"
        )

    async def jira_get_issue(self, issue_key: str, *, jira_pat: str) -> JiraIssue:
        result = await self.call_tool("jira_get_issue", {"issue_key": issue_key}, jira_pat=jira_pat)
        # mcp-atlassian shape: result is either an issue dict or wraps one in "content"
        issue = result.get("issue") or result.get("content") or result
        if isinstance(issue, list) and issue:
            issue = issue[0]
        return self._parse_jira_issue(issue if isinstance(issue, dict) else {})

    async def confluence_search(
        self,
        query: str,
        *,
        max_results: int = 25,
        confluence_pat: str,
    ) -> ConfluenceSearchResult:
        result = await self.call_tool(
            "confluence_search",
            {"query": query, "max_results": max_results},
            confluence_pat=confluence_pat,
        )
        return self._parse_confluence_search(result, query=query)

    async def confluence_get_page(self, page_id: str, *, confluence_pat: str) -> ConfluencePage:
        result = await self.call_tool(
            "confluence_get_page",
            {"page_id": page_id},
            confluence_pat=confluence_pat,
        )
        # mcp-atlassian shape: result is either a page dict or wraps one in "content"
        page = result.get("page") or result.get("content") or result
        if isinstance(page, list) and page:
            page = page[0]
        return self._parse_confluence_page(page if isinstance(page, dict) else {})

    @staticmethod
    def _parse_jira_search(result: dict[str, Any], *, jql: str) -> JiraSearchResult:
        # Tolerate a few shapes — Atlassian-Python-API + FastMCP can wrap
        # results in {content: [...]} or {issues: [...]} depending on version.
        raw_issues = (
            result.get("issues")
            or result.get("content")
            or result.get("data", {}).get("issues")
            or []
        )
        if not isinstance(raw_issues, list):
            raw_issues = []
        issues = tuple(
            AtlassianMCPClient._parse_jira_issue(i) for i in raw_issues if isinstance(i, dict)
        )
        total = int(result.get("total", len(issues)))
        return JiraSearchResult(issues=issues, total=total, jql=jql)

    @staticmethod
    def _parse_jira_issue(d: dict[str, Any]) -> JiraIssue:
        # Atlassian REST returns nested fields; FastMCP may flatten them. Try both.
        maybe_fields = d.get("fields")
        fields: dict[str, Any] = maybe_fields if isinstance(maybe_fields, dict) else d
        return JiraIssue(
            key=str(d.get("key", "")),
            summary=_extract_jira_summary(fields),
            status=_extract_jira_status(fields),
            assignee=_extract_jira_assignee(fields),
            issuetype=_extract_jira_issuetype(fields),
            url=_extract_jira_url(d),
            description=_extract_jira_description(fields),
            labels=_extract_jira_labels(fields),
        )

    @staticmethod
    def _parse_confluence_search(result: dict[str, Any], *, query: str) -> ConfluenceSearchResult:
        # Same tolerance story as Jira search — try the shapes mcp-atlassian
        # and FastMCP are known to produce.
        raw_pages = (
            result.get("results")
            or result.get("pages")
            or result.get("content")
            or result.get("data", {}).get("results")
            or []
        )
        if not isinstance(raw_pages, list):
            raw_pages = []
        pages = tuple(
            AtlassianMCPClient._parse_confluence_page(p) for p in raw_pages if isinstance(p, dict)
        )
        total = int(result.get("total", len(pages)))
        return ConfluenceSearchResult(pages=pages, total=total, query=query)

    @staticmethod
    def _parse_confluence_page(d: dict[str, Any]) -> ConfluencePage:
        # Confluence REST nests the rendered body under body.storage.value
        # or body.view.value depending on the `expand` params used; FastMCP
        # may instead flatten it to a top-level "content" string.
        body = d.get("body")
        content = ""
        if isinstance(body, dict):
            rendered = body.get("storage") or body.get("view") or {}
            if isinstance(rendered, dict):
                content = str(rendered.get("value", ""))
        elif isinstance(body, str):
            content = body
        if not content:
            content = str(d.get("content", ""))

        space_obj = d.get("space")
        space = space_obj.get("key", "") if isinstance(space_obj, dict) else str(space_obj or "")

        raw_links = d.get("_links")
        links = raw_links if isinstance(raw_links, dict) else {}
        url = d.get("url") or links.get("webui") or links.get("self")

        return ConfluencePage(
            id=str(d.get("id", "")),
            title=str(d.get("title", "")),
            space=space,
            url=str(url) if url else None,
            content=content[:_MAX_CONFLUENCE_CONTENT],
        )


__all__ = [
    "AtlassianMCPClient",
    "AtlassianMCPError",
    "ConfluencePage",
    "ConfluenceSearchResult",
    "JiraIssue",
    "JiraSearchResult",
]
