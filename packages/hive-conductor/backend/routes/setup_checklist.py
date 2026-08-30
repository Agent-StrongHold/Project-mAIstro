"""Setup checklist — first-run guidance items that auto-complete from real state.

Items can be in three states:
  - incomplete: not yet done; appears in checklist
  - completed:  auto-detected from real state (PAT set, interview done…); hidden
  - dismissed:  manually checked by user; shown with 7-day countdown then hidden

Manual dismissals live in kv_store under store_name='setup_checklist',
key = item_id, value = {"dismissed_at": ISO8601}. The 7-day expiry is computed
at read time — no background job needed.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from services import user_credentials as cred_svc

router = APIRouter(tags=["setup-checklist"])
logger = logging.getLogger(__name__)

_STORE_NAME = "setup_checklist"
_DISMISS_TTL_DAYS = 7


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


def _kv() -> Any | None:
    import stores

    return stores.sessions if getattr(stores.sessions, "_persisted", None) else None


def _dismiss_key(user_id: str, item_id: str) -> str:
    return f"{user_id}::{item_id}"


def _load_dismissals(user_id: str) -> dict[str, datetime]:
    """Return {item_id: dismissed_at} for this user, excluding expired entries."""
    import stores

    out: dict[str, datetime] = {}
    if not getattr(stores.sessions, "_persisted", None):
        return out
    persisted = stores.sessions._persisted
    now = datetime.now(UTC)
    expired: list[str] = []
    try:
        for key, raw in persisted.list_all_raw(_STORE_NAME):
            if not key.startswith(f"{user_id}::"):
                continue
            try:
                import json as _json

                payload = _json.loads(raw)
                ts = datetime.fromisoformat(payload["dismissed_at"])
            except Exception:
                expired.append(key)
                continue
            if ts + timedelta(days=_DISMISS_TTL_DAYS) <= now:
                expired.append(key)
                continue
            item_id = key.split("::", 1)[1]
            out[item_id] = ts
    except Exception as exc:
        logger.warning("setup_checklist load_dismissals failed: %s", exc)
        return out
    for key in expired:
        try:
            persisted.delete(_STORE_NAME, key)
        except Exception as _exc:
            __import__("logging").getLogger("hive.routes.setup_checklist").warning(
                "error_swallowed file=%s line=%d: %s",
                "packages/hive-conductor/backend/routes/setup_checklist.py",
                86,
                _exc,
            )
            pass
    return out


def _put_dismissal(user_id: str, item_id: str, dismissed_at: datetime) -> None:
    import json as _json

    import stores

    persisted = getattr(stores.sessions, "_persisted", None)
    if persisted is None:
        return
    persisted.put_raw(
        _STORE_NAME,
        _dismiss_key(user_id, item_id),
        _json.dumps({"dismissed_at": dismissed_at.isoformat()}),
    )


def _delete_dismissal(user_id: str, item_id: str) -> None:
    import stores

    persisted = getattr(stores.sessions, "_persisted", None)
    if persisted is None:
        return
    try:
        persisted.delete(_STORE_NAME, _dismiss_key(user_id, item_id))
    except Exception as exc:
        import logging as _logging

        _logging.getLogger("hive.setup_checklist").warning(
            "dismiss_delete_failed user=%s item=%s: %s",
            user_id,
            item_id,
            exc,
        )


def _has_credential(user_id: str, provider_id: str) -> bool:
    store = cred_svc.get_credential_store()
    if store is None:
        return False
    try:
        return store.has_secret(user_id, provider_id)
    except Exception:
        return False


def _interview_complete(user_id: str) -> bool:
    """Return True if the program intake interview has been completed."""
    try:
        from services import program_store as prog

        ctx = prog.get_context(user_id)
        return bool(getattr(ctx, "interview_complete", False))
    except Exception:
        return False


def _default_model_picked() -> bool:
    """True if the Setup wizard wrote a non-legacy default_model into settings."""
    try:
        from services import settings_store

        m = (settings_store.current().default_model or "").strip()
        return bool(m) and m != "cerebras-qwen-3-235b-a22b-2507"
    except Exception:
        return False


def _build_catalog() -> list[dict[str, Any]]:
    """Static catalog of checklist items. Each `complete` is a 0-arg callable
    that returns True if the underlying action has been taken; the front end
    only sees the boolean result.
    """
    jira_server_url = os.environ.get("JIRA_SERVER_URL", "")
    confluence_server_url = os.environ.get("CONFLUENCE_SERVER_URL", "")

    jira_pat_help = (
        jira_server_url + "/secure/ViewProfile.jspa"
        "?selectedTab=com.atlassian.pats.pats-plugin:jira-user-personal-access-tokens"
        if jira_server_url
        else None
    )
    confluence_pat_help = (
        confluence_server_url + "/plugins/personalaccesstokens/usertokens.action"
        if confluence_server_url
        else None
    )

    jira_item: dict[str, Any] = {
        "id": "cred_atlassian_server_jira",
        "title": "Add your Jira PAT",
        "description": (
            "Lets the Delivery + Reporting agents poll Jira on your behalf. "
            "Your Jira instance is on-prem (Server); switch to the Cloud Rovo path "
            "when you migrate."
        ),
        "link_label": "Open Credentials",
        "link_href": "/credentials",
        "category": "integrations",
        "context": "On-prem path; switch to the Rovo token below after Cloud migration.",
    }
    if jira_pat_help:
        jira_item["external_help"] = jira_pat_help

    confluence_item: dict[str, Any] = {
        "id": "cred_atlassian_server_confluence",
        "title": "Add your Confluence PAT",
        "description": "Lets agents read Confluence pages (RFCs, runbooks, status docs).",
        "link_label": "Open Credentials",
        "link_href": "/credentials",
        "category": "integrations",
    }
    if confluence_pat_help:
        confluence_item["external_help"] = confluence_pat_help

    return [
        {
            "id": "llm_provider",
            "title": "Add + activate an LLM provider key (admin)",
            "description": (
                "Store a provider API key in the encrypted vault and activate it — "
                "activation runs a one-token test completion, your first model call. "
                "Do this from the admin account."
            ),
            "link_label": "Open Credentials",
            "link_href": "/credentials",
            "category": "setup",
        },
        {
            "id": "first_chat",
            "title": "Send your first chat (daily-driver account)",
            "description": (
                "Switch to your daily-driver login — the admin account is blocked "
                "from chat by design — and ask the conductor to build a small "
                "agent DAG. That prompt is the guided end of the install tutorial."
            ),
            "link_label": "Open Chat",
            "link_href": "/chat",
            "category": "setup",
        },
        {
            "id": "default_model",
            "title": "Pick your default model",
            "description": (
                "Choose the LLM the PM fleet uses by default. You picked one in "
                "Setup, but you can change it any time in Settings."
            ),
            "link_label": "Open Settings",
            "link_href": "/settings",
            "category": "fleet",
        },
        {
            "id": "interview",
            "title": "Tell the fleet about your program",
            "description": (
                "The Intake agent runs a short interview to seed program context "
                "(name, goals, stakeholders). Without it, the other agents fly "
                "blind."
            ),
            "link_label": "Start interview",
            "link_href": "/agents",
            "category": "fleet",
        },
        jira_item,
        confluence_item,
        {
            "id": "cred_atlassian_rovo_mcp",
            "title": "Add your Atlassian Rovo MCP token (post-Cloud)",
            "description": (
                "Atlassian Cloud + Rovo MCP path. Optional today; recommended "
                "before your Cloud migration so the fleet keeps reading "
                "Jira/Confluence after the on-prem path retires."
            ),
            "link_label": "Open Credentials",
            "link_href": "/credentials",
            "external_help": (
                "https://id.atlassian.com/manage-profile/security/api-tokens"
                "?autofillToken&expiryDays=max&appId=mcp&selectedScopes=all"
            ),
            "category": "integrations",
        },
        {
            "id": "cred_airtable",
            "title": "Add your Airtable PAT",
            "description": (
                "Lets the Reporting agent poll Airtable bases for daily status "
                "updates. Scope token to data.records:read on the bases the fleet "
                "needs to see."
            ),
            "link_label": "Open Credentials",
            "link_href": "/credentials",
            "external_help": "https://airtable.com/create/tokens/new",
            "category": "integrations",
        },
        {
            "id": "cred_github",
            "title": "Add your GitHub PAT",
            "description": (
                "Used for repository and PR context when the fleet ties work-items back to code."
            ),
            "link_label": "Open Credentials",
            "link_href": "/credentials",
            "external_help": "https://github.com/settings/tokens?type=beta",
            "category": "integrations",
        },
    ]


def _check_complete(item_id: str, user_id: str) -> bool:
    if item_id == "default_model":
        return _default_model_picked()
    if item_id == "interview":
        return _interview_complete(user_id)
    if item_id == "llm_provider":
        return _llm_provider_activated()
    if item_id == "first_chat":
        return _has_chat_session(user_id)
    if item_id.startswith("cred_"):
        provider_id = item_id[len("cred_") :]
        return _has_credential(user_id, provider_id)
    return False


def _llm_provider_activated() -> bool:
    try:
        from routes.providers import any_provider_activated

        return any_provider_activated()
    except Exception:
        return False


def _has_chat_session(user_id: str) -> bool:
    """Has this person started a chat of their own?

    This test was dead until #312: nothing wrote `user_id`, so it compared
    every session against a value none of them had and the checklist item could
    never complete. Binding ownership makes it live, which is also what makes
    the seed exclusion necessary — the starter session is handed to the user,
    not written by them, and counting it would tick the item for someone who
    has never opened chat.
    """
    try:
        import stores
        from services.owned_records import Owner, owned_chat_sessions

        owned = owned_chat_sessions(Owner(id=user_id))
        return any(not s.id.startswith(stores.SEED_SESSION_PREFIX) for s in owned.values())
    except Exception:
        return False


@router.get("")
def get_checklist(request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    dismissals = _load_dismissals(uid)
    now = datetime.now(UTC)
    items: list[dict[str, Any]] = []
    for entry in _build_catalog():
        completed = _check_complete(entry["id"], uid)
        if completed:
            # Auto-detected completions drop out — also clear any stale dismissal.
            if entry["id"] in dismissals:
                _delete_dismissal(uid, entry["id"])
            continue
        dismissed_at = dismissals.get(entry["id"])
        if dismissed_at is not None:
            expires_at = dismissed_at + timedelta(days=_DISMISS_TTL_DAYS)
            seconds_remaining = max(0, int((expires_at - now).total_seconds()))
            entry = {
                **entry,
                "status": "dismissed",
                "dismissed_at": dismissed_at.isoformat(),
                "expires_at": expires_at.isoformat(),
                "seconds_until_expiry": seconds_remaining,
            }
        else:
            entry = {**entry, "status": "incomplete"}
        items.append(entry)
    return {
        "items": items,
        "dismiss_ttl_days": _DISMISS_TTL_DAYS,
        "generated_at": now.isoformat(),
    }


@router.post("/{item_id}/dismiss")
def dismiss(item_id: str, request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    catalog_ids = {e["id"] for e in _build_catalog()}
    if item_id not in catalog_ids:
        raise HTTPException(status_code=404, detail=f"Unknown checklist item {item_id!r}")
    now = datetime.now(UTC)
    _put_dismissal(uid, item_id, now)
    expires_at = now + timedelta(days=_DISMISS_TTL_DAYS)
    return {
        "id": item_id,
        "status": "dismissed",
        "dismissed_at": now.isoformat(),
        "expires_at": expires_at.isoformat(),
        "seconds_until_expiry": int((expires_at - now).total_seconds()),
    }


@router.post("/{item_id}/undismiss")
def undismiss(item_id: str, request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    _delete_dismissal(uid, item_id)
    return {"id": item_id, "status": "incomplete"}
