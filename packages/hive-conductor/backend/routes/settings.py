"""Settings routes — the acknowledging surface for SPEC-082926-0b72.

Every write here returns the record `services.settings_store` read back out of
the store, never the body the caller sent. The three failure modes are distinct
on the wire because they need different reactions: `400` means fix the value,
`409` means re-read and retry, `503` means the store is the problem.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import BaseModel, ConfigDict, ValidationError
from services import settings_store

from routes.audit import log_audit

logger = logging.getLogger(__name__)

router = APIRouter(tags=["settings"])


def _save(values: SettingsModel, expected_revision: int | None) -> SettingsModel:
    """Persist `values`, translating the store's refusals into status codes."""
    try:
        return settings_store.save(values, expected_revision=expected_revision).values
    except settings_store.SettingsSecretError as exc:
        # `exc.field` and `exc.credential_type`, never the value: this detail
        # reaches an HTTP response and the log.
        raise HTTPException(
            status_code=400,
            detail=(
                f"settings field {exc.field!r} carries {exc.credential_type} material; "
                "store the secret in the vault and reference it here"
            ),
        ) from exc
    except settings_store.SettingsConflictError as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "settings were modified by someone else",
                "expected_revision": exc.expected,
                "current_revision": exc.current.revision,
                "current": exc.current.values.model_dump(mode="json"),
            },
        ) from exc
    except settings_store.SettingsPersistenceError as exc:
        logger.error("settings write not confirmed: %s", exc)
        raise HTTPException(status_code=503, detail=f"settings were not persisted: {exc}") from exc


@router.get("", response_model=SettingsModel)
def get_settings() -> SettingsModel:
    # No repair on a read path. `apply_default_settings_if_needed` now writes,
    # and it runs once at startup instead of on every GET.
    return settings_store.current()


@router.get("/record")
def get_settings_record() -> dict[str, Any]:
    """The durable record with the revision a conditional write needs."""
    record = settings_store.record()
    return {
        "durable": settings_store.durable(),
        "schema_version": record.schema_version,
        "revision": record.revision,
        "updated_at": record.updated_at.isoformat(),
        "values": record.values.model_dump(mode="json"),
    }


@router.put("", response_model=SettingsModel)
def put_settings(body: SettingsModel, expected_revision: int | None = None) -> SettingsModel:
    saved = _save(body, expected_revision)
    log_audit("settings_update", "system", detail=saved.model_dump())
    return saved


class PatchSettingsBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    api_base_url: str | None = None
    default_model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream_responses: bool | None = None
    # `theme` and `log_level` are the two enumerated fields on `SettingsModel`,
    # and they were `str | None` here — so a value the model forbids passed the
    # request boundary and was written straight through by `model_copy`, which
    # skips validation. Now the boundary refuses it (422) *and* the merge below
    # revalidates, because a durable record that will not load is worse than a
    # rejected request.
    theme: Literal["dark", "light", "system"] | None = None
    notifications_enabled: bool | None = None
    auto_save_sessions: bool | None = None
    telemetry_enabled: bool | None = None
    log_level: Literal["debug", "info", "warn", "error"] | None = None
    capabilities: dict[str, CapabilitySetting] | None = None


@router.patch("", response_model=SettingsModel)
def patch_settings(body: PatchSettingsBody, expected_revision: int | None = None) -> SettingsModel:
    updates = body.model_dump(exclude_none=True)
    # model_copy(update=...) skips validation, so keep nested models as instances
    # (not the dicts model_dump produced) — otherwise capabilities is stored as
    # plain dicts and downstream readers (the bridge) break.
    if body.capabilities is not None:
        updates["capabilities"] = body.capabilities
    # Re-validate the merged result before it can reach the store: model_copy
    # skipping validation is convenient for the nested models above and unsafe
    # for a value about to be written, since an invalid one would be stored and
    # then refuse to load.
    try:
        merged = SettingsModel.model_validate(
            settings_store.current().model_copy(update=updates).model_dump(mode="python")
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors(include_url=False)) from exc
    saved = _save(merged, expected_revision)
    log_audit("settings_patch", "system", detail=body.model_dump(exclude_none=True))
    return saved


@router.get("/volatile")
def get_volatile_settings() -> dict[str, Any]:
    """Preview overrides. Separate surface, `durable: false`, never in the record."""
    return {"durable": False, "values": settings_store.preview()}


@router.put("/volatile")
def put_volatile_settings(body: dict[str, Any]) -> dict[str, Any]:
    return {"durable": False, "values": settings_store.set_preview(body)}


@router.delete("/volatile")
def delete_volatile_settings() -> dict[str, Any]:
    """Drop every preview override.

    This inherits `config.delete` from the `/v1/settings` prefix in
    `middleware/auth.py`, which is a heavier scope than clearing a value that
    was never durable needs. Deliberately not carved out: an exception in that
    prefix table is a change to the authorization surface, and it would be a
    poor trade for an overlay. Over-restrictive fails safe.
    """
    return {"durable": False, "values": settings_store.clear_preview()}


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
        return [settings_store.current().default_model]
    try:
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = f"{base.rstrip('/')}/models"
        resp = httpx.get(url, headers=headers, timeout=5.0)
        resp.raise_for_status()
        data = resp.json()
        model_ids = [m.get("id", m.get("model", "")) for m in data.get("data", [])]
        return sorted({m for m in model_ids if m}) or [settings_store.current().default_model]
    except Exception:
        logger.debug("model list fetch failed, returning default")
        return [settings_store.current().default_model]


@router.get("/features")
def settings_features() -> dict:
    values = settings_store.current()
    return {
        "stream_responses": values.stream_responses,
        "notifications_enabled": values.notifications_enabled,
        "auto_save_sessions": values.auto_save_sessions,
        "telemetry_enabled": values.telemetry_enabled,
    }
