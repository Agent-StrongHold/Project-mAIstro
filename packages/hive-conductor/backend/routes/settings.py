from __future__ import annotations

import logging

import httpx
import stores
from fastapi import APIRouter
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import BaseModel, ConfigDict

from routes.audit import log_audit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


@router.get("", response_model=SettingsModel)
def get_settings() -> SettingsModel:
    from settings_defaults import apply_default_settings_if_needed

    return apply_default_settings_if_needed()


@router.put("", response_model=SettingsModel)
def put_settings(body: SettingsModel) -> SettingsModel:
    stores.settings = body
    log_audit("settings_update", "system", detail=body.model_dump())
    return stores.settings


class PatchSettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_base_url: str | None = None
    default_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream_responses: bool | None = None
    theme: str | None = None
    notifications_enabled: bool | None = None
    auto_save_sessions: bool | None = None
    telemetry_enabled: bool | None = None
    log_level: str | None = None
    capabilities: dict[str, CapabilitySetting] | None = None


@router.patch("", response_model=SettingsModel)
def patch_settings(body: PatchSettingsBody) -> SettingsModel:
    updates = body.model_dump(exclude_none=True)
    # model_copy(update=...) skips validation, so keep nested models as instances
    # (not the dicts model_dump produced) — otherwise capabilities is stored as
    # plain dicts and downstream readers (the bridge) break.
    if body.capabilities is not None:
        updates["capabilities"] = body.capabilities
    stores.settings = stores.settings.model_copy(update=updates)
    log_audit("settings_patch", "system", detail=body.model_dump(exclude_none=True))
    return stores.settings


@router.post("/reload")
def reload_settings() -> dict:
    return {"status": "reloaded"}


@router.get("/audit")
def settings_audit() -> list:
    return []


@router.get("/quotas")
def settings_quotas() -> dict:
    return {"providers": []}


@router.get("/models")
def settings_models() -> dict:
    models = _fetch_available_models()
    return {"models": models}


def _fetch_available_models() -> list[str]:
    import os

    base = os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL") or ""
    key = os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""
    if not base:
        return [stores.settings.default_model]
    try:
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = f"{base.rstrip('/')}/models"
        resp = httpx.get(url, headers=headers, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        model_ids = [m.get("id", m.get("model", "")) for m in data.get("data", [])]
        return sorted({m for m in model_ids if m}) or [stores.settings.default_model]
    except Exception:
        logger.debug("model list fetch failed, returning default")
        return [stores.settings.default_model]


@router.get("/features")
def settings_features() -> dict:
    return {
        "stream_responses": stores.settings.stream_responses,
        "notifications_enabled": stores.settings.notifications_enabled,
        "auto_save_sessions": stores.settings.auto_save_sessions,
        "telemetry_enabled": stores.settings.telemetry_enabled,
    }
