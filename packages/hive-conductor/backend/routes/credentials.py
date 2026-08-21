"""Per-user integration credentials — encrypted at rest, never returned in API responses."""

from __future__ import annotations

from typing import Any

import stores
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import user_credentials as cred_svc

from maistro.credentials import get_provider
from maistro.credentials.store import CredentialStoreUnavailable
from routes.audit import log_audit

router = APIRouter(tags=["credentials"])


def _config_key(user_id: str, provider_id: str) -> str:
    return f"{user_id}:{provider_id}"


def _config_field_dicts(provider: Any) -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "label": f.label,
            "placeholder": f.placeholder,
            "required": f.required,
        }
        for f in getattr(provider, "config_fields", ()) or ()
    ]


def _read_config(user_id: str, provider_id: str) -> dict[str, str]:
    raw = stores.user_provider_config.get(_config_key(user_id, provider_id))
    return dict(raw) if isinstance(raw, dict) else {}


def _user_id(request: Request) -> str:
    user = getattr(request.state, "user", None) or {}
    uid = user.get("id")
    if not uid:
        raise HTTPException(status_code=401, detail="Authentication required")
    return str(uid)


class SetCredentialBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    secret: str = Field(min_length=1, max_length=4096)


@router.get("/providers")
def list_providers() -> dict[str, Any]:
    return {"providers": cred_svc.list_provider_catalog()}


@router.get("")
def list_my_credentials(request: Request) -> dict[str, Any]:
    uid = _user_id(request)
    try:
        store = cred_svc.require_store()
    except CredentialStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    configured = store.list_providers_for_user(uid)
    catalog = cred_svc.list_provider_catalog()
    items = []
    for entry in catalog:
        meta = configured.get(entry["id"], {})
        provider = get_provider(entry["id"])
        items.append(
            {
                **entry,
                "configured": entry["id"] in configured,
                "updated_at": meta.get("updated_at"),
                "config_fields": _config_field_dicts(provider),
                "config_values": _read_config(uid, entry["id"]),
            }
        )
    return {"credentials": items}


class SetConfigBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Free-form dict of {field_name: value}; values are non-secret strings
    # (we enforce a small length cap so an attacker can't dump arbitrary
    # blobs into the store via this endpoint).
    config: dict[str, str] = Field(default_factory=dict)


@router.get("/{provider_id}/config")
def get_credential_config(provider_id: str, request: Request) -> dict[str, Any]:
    if get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)
    return {"provider": provider_id, "config": _read_config(uid, provider_id)}


@router.put("/{provider_id}/config")
def save_credential_config(
    provider_id: str,
    body: SetConfigBody,
    request: Request,
) -> dict[str, Any]:
    provider = get_provider(provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)

    # Reject unknown field names so the store can't be used as a free-form
    # KV by a malicious caller.
    allowed_names = {f.name for f in (getattr(provider, "config_fields", ()) or ())}
    bad = set(body.config) - allowed_names
    if bad:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown config field(s): {sorted(bad)}",
        )
    # Per-value length cap (256 chars is plenty for an Airtable base_id /
    # table name; rejects abuse).
    for k, v in body.config.items():
        if len(v) > 256:
            raise HTTPException(
                status_code=400,
                detail=f"Field {k!r} exceeds 256-char limit",
            )

    stores.user_provider_config[_config_key(uid, provider_id)] = dict(body.config)
    log_audit(
        action="credential_config_save",
        actor=uid,
        target=provider_id,
        detail={"keys": sorted(body.config.keys())},
    )
    return {"ok": True, "provider": provider_id, "config": dict(body.config)}


@router.put("/{provider_id}")
def save_credential(
    provider_id: str,
    body: SetCredentialBody,
    request: Request,
) -> dict[str, Any]:
    # SECURITY-REVIEW: user-controlled secret written to Fernet-encrypted store scoped by session user id.
    if get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)
    try:
        store = cred_svc.require_store()
        store.set_secret(uid, provider_id, body.secret)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    log_audit("credential_save", uid, target=provider_id)
    return {"ok": True, "provider": provider_id, "configured": True}


@router.delete("/{provider_id}", status_code=204)
def delete_credential(provider_id: str, request: Request) -> None:
    if get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)
    try:
        store = cred_svc.require_store()
        if not store.delete_secret(uid, provider_id):
            raise HTTPException(status_code=404, detail="Credential not configured")
    except CredentialStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    log_audit("credential_delete", uid, target=provider_id)
