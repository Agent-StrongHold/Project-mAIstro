"""Atlassian MCP client — talks to mcp-atlassian over HTTP.

Per-request authentication: each call accepts (jira_pat, confluence_pat)
explicitly so callers can inject the *current user's* PATs decrypted
from the credential store. PATs are never bundled into env or stored in
this module's state.

23-day bridge until Atlassian Cloud migration (~2026-06-13);
after migration the same caller switches to Rovo Cloud by changing the
MCP URL — credential pattern is unchanged.
"""

from __future__ import annotations

from maistro.tools.atlassian.client import (
    AtlassianMCPClient,
    AtlassianMCPError,
    ConfluencePage,
    ConfluenceSearchResult,
    JiraIssue,
    JiraSearchResult,
)

__all__ = [
    "AtlassianMCPClient",
    "AtlassianMCPError",
    "ConfluencePage",
    "ConfluenceSearchResult",
    "JiraIssue",
    "JiraSearchResult",
]
