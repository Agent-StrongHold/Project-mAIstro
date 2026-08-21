"""Daily report v2 — simple, uses same path as chat tools."""

from __future__ import annotations

import contextlib
import os
from typing import Any

from fastapi import APIRouter, Request

from maistro.http import shared_client

router = APIRouter(tags=["daily-report"])


def _use_secret(store: object, user_id: str, provider_id: str) -> str | None:
    """Single allowlisted callsite for use_secret — lambda is centralised here."""
    try:
        return store.use_secret(user_id, provider_id, lambda s: s)  # type: ignore[union-attr]
    except Exception:
        return None


def _get_pat(user_id: str) -> str | None:
    try:
        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if not store:
            return None
        for pid in ("atlassian_server_jira", "jira", "atlassian_rovo_mcp"):
            try:
                if store.has_secret(user_id, pid):
                    return _use_secret(store, user_id, pid)
            except Exception:
                continue
    except Exception:
        pass
    return None


async def _fetch_jira(user_id: str) -> dict[str, Any]:
    """Run the mounted Daily Report Jira section through the canonical durable Graph path."""
    pat = _get_pat(user_id)
    if not pat:
        return {"status": "no_pat", "count": 0, "issues": []}

    jira_server_url = os.environ.get("JIRA_SERVER_URL", "")
    if not jira_server_url:
        return {
            "status": "no_config",
            "detail": "JIRA_SERVER_URL env var is not set",
            "count": 0,
            "issues": [],
        }

    try:
        from services.daily_status_runner import run_daily_status_dag

        return await run_daily_status_dag(
            user_id=user_id,
            project_id=None,
            pat=pat,
            base_url=jira_server_url,
            flavor="server",
        )
    except Exception as exc:
        return {
            "status": "error",
            "detail": str(exc),
            "count": 0,
            "issues": [],
        }


def _get_airtable_pat(user_id: str) -> str | None:
    airtable_pat = None
    try:
        from services import user_credentials as cred_svc

        store = cred_svc.get_credential_store()
        if not store:
            return None
        for pid in ("airtable", "airtable_pat"):
            try:
                if store.has_secret(user_id, pid):
                    airtable_pat = _use_secret(store, user_id, pid)
                    break
            except Exception:
                continue
        # If still not found, the PAT might be stored but under a different mechanism
        if not airtable_pat:
            with contextlib.suppress(Exception):
                airtable_pat = _use_secret(store, user_id, "airtable")
    except Exception:
        return None
    return airtable_pat


def _airtable_records(payload: dict[str, Any]) -> dict[str, Any]:
    records = payload.get("records", [])
    items = []
    for rec in records[:10]:
        fields = rec.get("fields", {})
        name = (
            fields.get("Name")
            or fields.get("Title")
            or fields.get("Use Case Name")
            or next(iter(fields.values()), "")
        )
        items.append({"id": rec.get("id"), "name": str(name)[:100]})
    return {"status": "ok", "count": len(records), "records": items}


async def _fetch_airtable(user_id: str) -> dict[str, Any]:
    airtable_pat = _get_airtable_pat(user_id)
    if not airtable_pat:
        return {"status": "not_configured", "count": 0, "issues": []}

    base_id = "appXXXXXXXXXXXXXX"  # MAISTRO base
    headers = {"Authorization": f"Bearer {airtable_pat}"}
    try:
        async with shared_client(timeout=15.0) as client:
            r = await client.get(
                f"https://api.airtable.com/v0/meta/bases/{base_id}/tables",
                headers=headers,
            )
            table_id = ""
            if r.status_code == 200:
                tables = r.json().get("tables", [])
                if tables:
                    table_id = tables[0].get("id", "")

            if not table_id:
                return {"status": "not_configured", "count": 0, "issues": []}

            r = await client.get(
                f"https://api.airtable.com/v0/{base_id}/{table_id}",
                params={"maxRecords": 10},
                headers=headers,
            )
            if r.status_code == 200:
                return _airtable_records(r.json())
            return {
                "status": "error",
                "detail": f"Airtable {r.status_code}",
                "count": 0,
                "issues": [],
            }
    except Exception as e:
        return {"status": "error", "detail": str(e)[:100], "count": 0, "issues": []}


@router.get("")
async def daily_report(request: Request) -> dict[str, Any]:
    from datetime import UTC, datetime

    user = getattr(request.state, "user", None) or {}
    user_id = str(user.get("id", ""))

    jira = await _fetch_jira(user_id)
    airtable = await _fetch_airtable(user_id)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "jira": jira,
        "airtable": airtable,
        "research": {"status": "not_configured", "count": 0},
        "suggested_actions": [
            {
                "title": "Ask in Chat",
                "reason": "Use chat to query Jira, blockers, or Confluence",
                "link_label": "Open Chat",
                "link_href": "/chat",
            },
        ],
    }
