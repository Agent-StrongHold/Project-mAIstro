"""Daily status report — Jira 24h + Airtable 24h + research summary + suggested actions.

Each section returns a small, well-typed payload with a `source` field so the
UI can render either real data or a "needs setup" CTA. When a PAT is missing,
the section returns ``status='no_pat'`` and a deep link the user can click to
land on the right Credentials row.

The endpoint is intentionally tolerant — any one section failing should not
break the page. Errors are logged and surfaced as ``status='error'``.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import stores
from fastapi import APIRouter, HTTPException, Request
from services import user_credentials as cred_svc

from maistro.http import shared_client

router = APIRouter(tags=["daily-report"])
logger = logging.getLogger(__name__)


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


def _has_credential(user_id: str, provider_id: str) -> bool:
    store = cred_svc.get_credential_store()
    if store is None:
        return False
    try:
        return store.has_secret(user_id, provider_id)
    except Exception:
        return False


def _use_secret(user_id: str, provider_id: str) -> str | None:
    store = cred_svc.get_credential_store()
    if store is None:
        return None
    try:
        if not store.has_secret(user_id, provider_id):
            return None
        return store.use_secret(user_id, provider_id, lambda s: s)
    except Exception:
        return None


async def _poll_jira(user_id: str) -> dict[str, Any]:
    """Poll Jira project — same path as chat tools."""
    pat = _use_secret(user_id, "atlassian_server_jira")
    if not pat:
        pat = _use_secret(user_id, "jira") or _use_secret(user_id, "atlassian_rovo_mcp")
    if not pat:
        return {
            "status": "no_pat",
            "detail": "Add your Jira PAT to see updates",
            "credential_id": "atlassian_server_jira",
            "issues": [],
        }

    jira_server_url = os.environ.get("JIRA_SERVER_URL", "")
    if not jira_server_url:
        return {
            "status": "no_config",
            "detail": "JIRA_SERVER_URL env var is not set",
            "issues": [],
        }

    jql = "project = MY_PROJECT AND updated >= -7d ORDER BY updated DESC"
    try:
        async with shared_client(timeout=30.0) as client:
            r = await client.get(
                f"{jira_server_url}/rest/api/2/search",
                params={
                    "jql": jql,
                    "maxResults": 15,
                    "fields": "summary,status,assignee,issuetype,updated",
                },
                headers={"Authorization": f"Bearer {pat}", "Accept": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            issues = []
            for i in data.get("issues", []):
                f = i.get("fields", {})
                issues.append(
                    {
                        "key": i.get("key"),
                        "summary": f.get("summary"),
                        "status": (f.get("status") or {}).get("name"),
                        "assignee": ((f.get("assignee") or {}).get("displayName")),
                        "updated": f.get("updated"),
                    }
                )
            return {"status": "ok", "count": data.get("total", 0), "issues": issues, "jql": jql}
    except Exception as e:
        return {"status": "error", "detail": str(e), "issues": []}


async def _poll_airtable(user_id: str) -> dict[str, Any]:
    """Poll Airtable for record changes in the last 24h.

    Requires the user's PAT and a configured base id + table name (env or, later,
    a per-user setting). For v0, returns 'needs_config' if base id isn't set.
    """
    pat = _use_secret(user_id, "airtable")
    if not pat:
        return {
            "status": "no_pat",
            "detail": "Add your Airtable PAT to see updates",
            "credential_id": "airtable",
            "help_url": "https://airtable.com/create/tokens/new",
            "records": [],
        }

    # Read from per-user config (Credentials UI) with env-var fallback.
    user_config = stores.user_provider_config.get(f"{user_id}:airtable")
    user_config = dict(user_config) if isinstance(user_config, dict) else {}
    base_id = (user_config.get("base_id") or os.getenv("AIRTABLE_BASE_ID", "")).strip()
    table_name = (user_config.get("table") or os.getenv("AIRTABLE_TABLE", "")).strip()
    if not base_id or not table_name:
        return {
            "status": "needs_config",
            "detail": "Set base_id and table in Credentials → Airtable config",
            "records": [],
        }

    cutoff = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
    try:
        async with shared_client(timeout=8.0) as client:
            r = await client.get(
                f"https://api.airtable.com/v0/{base_id}/{table_name}",
                headers={"Authorization": f"Bearer {pat}"},
                params={
                    "pageSize": 20,
                    "filterByFormula": f"IS_AFTER(LAST_MODIFIED_TIME(), '{cutoff}')",
                    "sort[0][field]": "Last modified time",
                    "sort[0][direction]": "desc",
                },
            )
        if r.status_code == 401:
            return {
                "status": "auth_failed",
                "detail": "Airtable returned 401 — token may have expired",
                "credential_id": "airtable",
                "help_url": "https://airtable.com/create/tokens/new",
                "records": [],
            }
        if r.status_code != 200:
            return {
                "status": "error",
                "detail": f"Airtable returned HTTP {r.status_code}",
                "records": [],
            }
        data = r.json()
        records = [
            {"id": rec.get("id", ""), "fields": rec.get("fields", {})}
            for rec in data.get("records", [])[:20]
        ]
        return {"status": "ok", "records": records, "count": len(records)}
    except httpx.HTTPError as exc:
        logger.warning("daily_report airtable fetch failed: %s", exc)
        return {"status": "error", "detail": "Airtable unreachable", "records": []}


def _research_summary(user_id: str) -> dict[str, Any]:
    """Pull recent research outcomes from the maistro outcome store.

    For v0, the outcome store may be empty (no DAG runs yet). Return a
    structured 'no_data' response so the UI can show a CTA to run a pulse.
    """
    try:
        # The outcome store is wired in maistro container DI; for v0 we read
        # via the global container singleton if present.
        from maistro.container import get_container  # type: ignore

        container = get_container()
        outcome_store = getattr(container, "outcome_store", None)
        if outcome_store is None:
            return {
                "status": "no_data",
                "detail": "Run a fleet pulse to generate research",
                "items": [],
            }
        # get_experience_context returns a string; for v0 we surface the raw
        # recent outcomes if the store exposes them.
        outcomes = getattr(outcome_store, "_outcomes", [])
        recent = []
        cutoff = datetime.now(UTC) - timedelta(hours=24)
        for o in list(outcomes)[-20:]:
            ts = getattr(o, "recorded_at", None)
            if ts is None:
                continue
            try:
                if isinstance(ts, str):
                    ts = datetime.fromisoformat(ts)
            except Exception as _exc:
                __import__("logging").getLogger("hive.routes.daily_report").warning(
                    "error_swallowed file=%s line=%d: %s",
                    "packages/hive-conductor/backend/routes/daily_report.py",
                    228,
                    _exc,
                )
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=UTC)
            if ts < cutoff:
                continue
            recent.append(
                {
                    "task_type": getattr(o, "task_type", ""),
                    "tool_name": getattr(o, "tool_name", ""),
                    "success": bool(getattr(o, "success", False)),
                    "recorded_at": ts.isoformat(),
                    "summary": str(getattr(o, "summary", ""))[:240],
                }
            )
        if not recent:
            return {"status": "no_data", "detail": "No fleet activity in the last 24h", "items": []}
        return {"status": "ok", "items": recent, "count": len(recent)}
    except Exception as exc:
        logger.debug("research_summary lookup failed: %s", exc)
        return {"status": "no_data", "detail": "Research index unavailable", "items": []}


def _suggested_actions(
    user_id: str,
    jira: dict[str, Any],
    airtable: dict[str, Any],
    research: dict[str, Any],
) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    if jira.get("status") == "no_pat":
        actions.append(
            {
                "title": "Connect Jira to see real updates",
                "reason": "Daily report can't poll Jira until you add your PAT.",
                "link_label": "Open Credentials",
                "link_href": "/credentials",
            }
        )
    elif jira.get("status") == "auth_failed":
        actions.append(
            {
                "title": "Refresh your Jira PAT",
                "reason": "Jira returned 401 — token likely expired after 2FA.",
                "link_label": "Regenerate token",
                "link_href": jira.get("help_url", "/credentials"),
            }
        )
    elif jira.get("status") == "ok" and jira.get("count", 0) == 0:
        actions.append(
            {
                "title": "No Jira updates found",
                "reason": "Try picking a different project or widening the time window.",
                "link_label": "Ask in Chat",
                "link_href": "/chat",
            }
        )

    if airtable.get("status") == "no_pat":
        actions.append(
            {
                "title": "Connect Airtable",
                "reason": "Add your Airtable PAT so the fleet can read base updates.",
                "link_label": "Generate token",
                "link_href": airtable.get("help_url", "https://airtable.com/create/tokens/new"),
            }
        )
    elif airtable.get("status") == "needs_config":
        actions.append(
            {
                "title": "Tell Airtable which base to poll",
                "reason": "Set base_id + table in Credentials → Airtable.",
                "link_label": "Open Credentials",
                "link_href": "/credentials",
            }
        )

    if research.get("status") == "no_data":
        actions.append(
            {
                "title": "Run a fleet pulse",
                "reason": "No research outcomes recorded in the last 24h.",
                "link_label": "Trigger pulse",
                "link_href": "/agents",
            }
        )

    # Surface a few real items as actionable if status is ok.
    for issue in jira.get("issues", [])[:3]:
        actions.append(
            {
                "title": f"Review {issue.get('key', '')}: {issue.get('summary', '')}",
                "reason": f"Updated in last 24h — current status {issue.get('status', '?')}",
                "link_label": "Open in Jira",
                "link_href": issue.get("url", "/agents"),
            }
        )

    return actions


async def _jira_section_via_dag(user_id: str) -> dict[str, Any]:
    """Phase 4 path: route the Jira section through the daily-status DAG.

    Resolves the user's per-request PAT from the credential store + the
    on-prem Jira Server base URL, then invokes the DAG. Falls back to a
    structured no_pat shape (matching the legacy inline path) when no
    PAT is configured.
    """
    pat = (
        _use_secret(user_id, "atlassian_server_jira")
        or _use_secret(user_id, "jira")
        or _use_secret(user_id, "atlassian_rovo_mcp")
    )
    if not pat:
        return {
            "status": "no_pat",
            "detail": "Add your Jira PAT to see updates",
            "credential_id": "atlassian_server_jira",
            "issues": [],
            "source": "dag:daily-status",
        }

    # Decide on flavor + base from which credential the store provided.
    flavor = "server"
    base_url = os.environ.get("JIRA_SERVER_URL", "")
    if not base_url and not (
        _has_credential(user_id, "jira") or _has_credential(user_id, "atlassian_rovo_mcp")
    ):
        return {
            "status": "no_config",
            "detail": "JIRA_SERVER_URL env var is not set",
            "issues": [],
            "source": "dag:daily-status",
        }
    if _has_credential(user_id, "jira") or _has_credential(user_id, "atlassian_rovo_mcp"):
        cloud_site = os.environ.get("ATLASSIAN_SITE_URL", "").strip().rstrip("/")
        if cloud_site:
            base_url = cloud_site
            flavor = "cloud"

    from services.daily_status_runner import run_daily_status_dag

    return await run_daily_status_dag(
        user_id=user_id,
        project_id=None,  # Phase 2 ProjectMiddleware will fill this in
        pat=pat,
        base_url=base_url,
        flavor=flavor,
    )


@router.get("")
async def get_daily_report(request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    generated_at = datetime.now(UTC).isoformat()
    # Route Jira through the DAG (Phase 4); Airtable + research stay on
    # the inline path until Phases 5 + 6 extend the seed.
    jira = await _jira_section_via_dag(uid)
    airtable = await _poll_airtable(uid)
    research = _research_summary(uid)
    actions = _suggested_actions(uid, jira, airtable, research)
    return {
        "generated_at": generated_at,
        "window_hours": 24,
        "jira": jira,
        "airtable": airtable,
        "research": research,
        "suggested_actions": actions,
        "generated_by": "dag:daily-status (jira) + inline (airtable + research)",
    }


@router.get("/jira/projects")
async def search_jira_projects(request: Request, q: str = "") -> dict[str, Any]:
    """Search Jira projects the user has access to. Returns candidates for JQL config.

    If `q` is provided, filters by name/key. Otherwise returns all visible projects.
    The fleet uses this to suggest which projects to track.
    """
    uid = _user_id(request)
    pat = _use_secret(uid, "atlassian_server_jira")
    base_url = os.environ.get("JIRA_SERVER_URL", "")
    flavor = "server"
    if not pat:
        pat = _use_secret(uid, "jira") or _use_secret(uid, "atlassian_rovo_mcp")
        cloud_site = os.getenv("ATLASSIAN_SITE_URL", "").strip().rstrip("/")
        if pat and cloud_site:
            base_url = cloud_site
            flavor = "cloud"
        else:
            return {"status": "no_pat", "projects": []}
    if not base_url:
        return {
            "status": "no_config",
            "detail": "JIRA_SERVER_URL env var is not set",
            "projects": [],
        }

    api_path = "/rest/api/2/project" if flavor == "server" else "/rest/api/3/project/search"
    headers = {"Authorization": f"Bearer {pat}"} if flavor == "server" else {}
    auth = None
    if flavor == "cloud":
        email = os.getenv("ATLASSIAN_EMAIL", "").strip()
        auth = (email or pat, pat)

    try:
        async with shared_client(timeout=8.0) as client:
            r = await client.get(
                f"{base_url}{api_path}",
                headers=headers,
                auth=auth,
            )
        if r.status_code != 200:
            return {"status": "error", "detail": f"Jira returned {r.status_code}", "projects": []}

        data = r.json()
        # Server returns a list; Cloud returns {"values": [...]}
        raw_projects = data if isinstance(data, list) else data.get("values", [])

        projects = []
        q_lower = q.lower()
        for p in raw_projects:
            key = p.get("key", "")
            name = p.get("name", "")
            if q_lower and q_lower not in key.lower() and q_lower not in name.lower():
                continue
            projects.append(
                {
                    "key": key,
                    "name": name,
                    "jql_suggestion": f"project = {key} AND updated >= -7d ORDER BY updated DESC",
                }
            )

        # Sort by relevance: exact key match first, then alphabetical
        projects.sort(key=lambda p: (0 if p["key"].lower() == q_lower else 1, p["key"]))
        return {"status": "ok", "projects": projects[:25]}
    except httpx.HTTPError as exc:
        logger.warning("jira project search failed: %s", exc)
        return {"status": "error", "detail": "Jira unreachable", "projects": []}
