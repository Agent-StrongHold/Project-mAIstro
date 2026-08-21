"""Tests for headless MCP / Atlassian connectivity helpers."""

from __future__ import annotations

import pytest
from services.mcp_client import atlassian_site_url, test_jira_rest
from services.mcp_defaults import platform_mcp_catalog


def test_platform_mcp_catalog_seeds_atlassian_rovo_only() -> None:
    """filesystem-local was removed from default seeding (task #29 —
    sidecar isn't deployed, surfacing 'disconnected' confused users)."""
    servers, tools = platform_mcp_catalog()
    ids = {s.id for s in servers}
    assert "mcp-atlassian-rovo" in ids
    assert "mcp-filesystem-local" not in ids
    assert len(tools) >= 1


@pytest.mark.asyncio
async def test_jira_rest_missing_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ATLASSIAN_API_TOKEN", raising=False)
    monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "token" in out["detail"].lower()


@pytest.mark.asyncio
async def test_jira_rest_missing_site(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ATLASSIAN_API_TOKEN", "test-token")
    monkeypatch.delenv("ATLASSIAN_SITE_URL", raising=False)
    monkeypatch.delenv("JIRA_SITE_URL", raising=False)
    out = await test_jira_rest(user_id=None)
    assert out["ok"] is False
    assert "ATLASSIAN_SITE_URL" in out["detail"]


def test_atlassian_site_url_normalizes() -> None:
    import os

    old = os.environ.get("ATLASSIAN_SITE_URL")
    try:
        os.environ["ATLASSIAN_SITE_URL"] = "myteam.atlassian.net"
        assert atlassian_site_url() == "https://myteam.atlassian.net"
    finally:
        if old is None:
            os.environ.pop("ATLASSIAN_SITE_URL", None)
        else:
            os.environ["ATLASSIAN_SITE_URL"] = old
