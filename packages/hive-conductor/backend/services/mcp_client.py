"""Headless MCP / Atlassian connectivity for containerized Hive (no Cursor)."""

from __future__ import annotations

import logging
import os
import re
from typing import Any

import httpx

from maistro.http import shared_client

logger = logging.getLogger("hive.mcp_client")

_SITE_RE = re.compile(r"^https://[a-zA-Z0-9.-]+\.atlassian\.net/?$")


def _normalize_site(url: str) -> str:
    u = (url or "").strip().rstrip("/")
    if not u:
        return ""
    if not u.startswith("http"):
        u = f"https://{u}"
    return u.rstrip("/")


def atlassian_site_url() -> str:
    return _normalize_site(os.getenv("ATLASSIAN_SITE_URL", os.getenv("JIRA_SITE_URL", "")))


def resolve_atlassian_token(user_id: str | None) -> str | None:
    """Vault first, then env, then encrypted credential store (jira or atlassian_rovo_mcp)."""
    from services.secrets import resolve_secret

    for key in ("ATLASSIAN_API_TOKEN", "JIRA_API_TOKEN"):
        val = resolve_secret(key, env_var=key)
        if val:
            return val
    if not user_id:
        return None
    try:
        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if store is None:
            return None
        for provider in ("jira", "atlassian_rovo_mcp"):
            try:
                if store.has_secret(user_id, provider):
                    return store.use_secret(user_id, provider, lambda s: s)
            except Exception as _exc:
                __import__("logging").getLogger("hive.services.mcp_client").warning(
                    "error_swallowed file=%s line=%d: %s",
                    "packages/hive-conductor/backend/services/mcp_client.py",
                    48,
                    _exc,
                )
                continue
    except Exception as exc:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the exception, never credential material
        logger.debug("credential_lookup_failed: %s", exc)
    return None


async def test_jira_rest(*, user_id: str | None = None) -> dict[str, Any]:
    """Probe Jira REST with Basic auth (email + API token or token-only lab)."""
    token = resolve_atlassian_token(user_id)
    site = atlassian_site_url()
    if not token:
        return {
            "ok": False,
            "mode": "jira_rest",
            "detail": "No Jira/Rovo token — set Credentials or ATLASSIAN_API_TOKEN",
        }
    if not site:
        return {
            "ok": False,
            "mode": "jira_rest",
            "detail": "ATLASSIAN_SITE_URL not set (e.g. https://your-org.atlassian.net)",
        }
    if not _SITE_RE.match(site):
        return {"ok": False, "mode": "jira_rest", "detail": "Invalid ATLASSIAN_SITE_URL host"}

    email = os.getenv("ATLASSIAN_EMAIL", os.getenv("JIRA_EMAIL", "")).strip()
    auth_user = email if email else token
    url = f"{site}/rest/api/3/myself"
    try:
        async with shared_client(timeout=10.0) as client:
            r = await client.get(url, auth=(auth_user, token))
        if r.status_code == 200:
            data = r.json()
            return {
                "ok": True,
                "mode": "jira_rest",
                "detail": f"Connected as {data.get('displayName', 'user')}",
                "site": site,
            }
        return {
            "ok": False,
            "mode": "jira_rest",
            "detail": f"Jira API returned {r.status_code}",
            "site": site,
        }
    except httpx.HTTPError:
        return {"ok": False, "mode": "jira_rest", "detail": "Jira request failed", "site": site}


async def test_mcp_server(
    server_id: str,
    *,
    user_id: str | None = None,
    url: str = "",
) -> dict[str, Any]:
    """Connectivity probe by server kind."""
    from services.mcp_defaults import ATLASSIAN_ROVO_SERVER_ID, is_atlassian_rovo_url

    if server_id == ATLASSIAN_ROVO_SERVER_ID or is_atlassian_rovo_url(url):
        jira = await test_jira_rest(user_id=user_id)
        if jira.get("ok"):
            return {
                **jira,
                "server_id": server_id,
                "note": "Rovo MCP uses token auth in-container; Jira REST verified",
            }
        token = resolve_atlassian_token(user_id)
        if token:
            return {
                "ok": True,
                "server_id": server_id,
                "mode": "env_token",
                "detail": "Token present; Jira site not configured or REST probe skipped",
            }
        return {**jira, "server_id": server_id}

    if url.startswith("http://127.0.0.1") or url.startswith("http://localhost"):
        try:
            async with shared_client(timeout=2.0) as client:
                r = await client.get(url)
            if r.status_code < 500:
                return {
                    "ok": True,
                    "server_id": server_id,
                    "mode": "http_local",
                    "detail": "Local MCP reachable",
                }
        except httpx.HTTPError:
            pass
        return {
            "ok": False,
            "server_id": server_id,
            "mode": "http_local",
            "detail": "Local MCP not running on loopback",
        }

    return {"ok": False, "server_id": server_id, "detail": "Unknown server type"}
