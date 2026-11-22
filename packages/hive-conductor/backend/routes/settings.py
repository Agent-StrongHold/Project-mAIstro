"""Settings routes — the acknowledging surface for SPEC-082926-0b72.

Every write here returns the record `services.settings_store` read back out of
the store, never the body the caller sent. The three failure modes are distinct
on the wire because they need different reactions: `400` means fix the value,
`409` means re-read and retry, `503` means the store is the problem.

The auxiliary routes are real queries or real operations against the same
durable owners, not canned responses (#389):

- `POST /reload` re-reads the durable record (services.settings_store.reload);
  `503` means the store read failed — it never claims a reload it did not do.
- `GET /audit` is the settings-change trail, read from the durable audit log
  (stores.audit_log, the same store `GET /v1/audit` serves). Empty means no
  settings write has been recorded — an empty-valid answer, not a stub.
- `GET /quotas` is the provider usage panel, served by the same LiteLLM-backed
  aggregation as `GET /v1/quotas/providers`; one owner, one source of truth.
- `GET|PUT|DELETE /volatile` are the PREVIEW surface: values that are never
  persisted to the record. The OpenAPI descriptions say so ("Preview"), per
  the #389 rule that preview/unsupported operations identify themselves.
"""

from __future__ import annotations

import json
import logging
import ssl
from typing import Any, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from models.schemas import CapabilitySetting, SettingsModel
from pydantic import BaseModel, ConfigDict, ValidationError
from services import settings_store
from services.provider_usage import provider_panel

from routes.audit import audit_entries_view, log_audit

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


@router.get("/volatile", summary="Preview overrides (non-durable)")
def get_volatile_settings() -> dict[str, Any]:
    """Preview overrides. Separate surface, `durable: false`, never in the record.

    Preview surface (#389): the values here are deliberately volatile — an
    overlay for trying a change before committing it. They are never written
    to the durable record, and this operation says so in the schema.
    """
    return {"durable": False, "values": settings_store.preview()}


@router.put("/volatile", summary="Preview overrides (non-durable)")
def put_volatile_settings(body: dict[str, Any]) -> dict[str, Any]:
    return {"durable": False, "values": settings_store.set_preview(body)}


@router.delete("/volatile", summary="Preview overrides (non-durable)")
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
def reload_settings() -> dict[str, Any]:
    """Re-read the settings record from its durable store, for real (#389).

    This route used to return `{"status": "reloaded"}` without touching
    anything — a success for an operation that did nothing. Now it drops the
    in-process cache and reads the store: the response is the record the store
    holds *after* the reload (same shape as `GET /record`), so a caller can
    compare its revision against what it saw before and observe the change an
    out-of-band write made. `503` means the store could not be read; nothing
    was reloaded and no success is claimed.
    """
    try:
        record = settings_store.reload()
    except Exception as exc:  # store read failure — unavailable, not empty
        logger.error("settings reload failed: %s", exc)
        raise HTTPException(
            status_code=503, detail=f"settings could not be reloaded: {exc}"
        ) from exc
    log_audit("settings_reload", "system", detail={"revision": record.revision})
    return {
        "durable": settings_store.durable(),
        "schema_version": record.schema_version,
        "revision": record.revision,
        "updated_at": record.updated_at.isoformat(),
        "values": record.values.model_dump(mode="json"),
    }


#: The audit actions this surface owns. `GET /audit` is the settings-scoped
#: view over the ONE durable audit log that `GET /v1/audit` serves whole --
#: not a second log.
_SETTINGS_AUDIT_ACTIONS = frozenset({"settings_update", "settings_patch", "settings_reload"})


@router.get("/audit")
async def settings_audit(request: Request, limit: int = 100) -> list[dict[str, Any]]:
    """The settings-change trail, read from the durable audit log (#389).

    Read through the shared `audit_entries_view` — the same core-store-first
    paginated read `GET /v1/audit` serves, never a second log. Returned newest-first,
    capped at `limit` (bounded 1..1000). Empty means no settings write has
    been recorded yet — an empty-valid answer, distinct from a failure (which
    raises) or an authorization refusal (handled by the `/v1/settings` auth
    scope in middleware/auth.py).
    """
    limit = max(1, min(limit, 1000))
    entries = []
    for action in sorted(_SETTINGS_AUDIT_ACTIONS):
        count = 0
        async for entry in audit_entries_view(request, action=action):
            entries.append(entry)
            count += 1
            if count >= limit:
                break
    entries.sort(key=lambda e: (e.get("created_at", ""), e["id"]), reverse=True)
    return entries[:limit]


@router.get("/quotas")
def settings_quotas() -> dict[str, Any]:
    """The provider usage panel, from the one canonical owner (#389).

    This used to return `{"providers": []}` — a hard-coded empty collection.
    The provider panel's canonical owner is the LiteLLM proxy aggregation
    behind `GET /v1/quotas/providers`; this route delegates to it (same
    envelope — `state` distinguishes ok / no_data / unavailable / error)
    rather than maintaining a second source that would drift. The panel
    lives in `services.provider_usage`, so this delegation imports a service
    module, not another router file.
    """
    return provider_panel()


@router.get("/models")
def settings_models() -> dict:
    """Gateway model catalog plus discovery provenance (#287).

    `models` remains the field every existing consumer reads. `discovered`,
    `source`, and `error` are additive: a caller must be able to tell a real
    gateway catalog from a stored-default substitute, because a failed fetch
    presented as a valid catalog is exactly what let a broken or unauthorized
    gateway look usable in Setup.
    """
    models, discovery = _discover_gateway_models()
    return {"models": models, **discovery}


class _MalformedCatalogError(Exception):
    """The gateway answered, but the payload is not a model catalog."""


def _classify_http_status(status: int) -> str:
    """Map a gateway HTTP status onto the wizard's failure taxonomy (#287)."""
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status >= 500:
        return "server"
    return "http"


def _is_tls_failure(exc: BaseException | None) -> bool:
    """Walk the exception chain looking for a TLS/certificate failure."""
    seen = 0
    while exc is not None and seen < 6:
        if isinstance(exc, ssl.SSLError):
            return True
        exc = exc.__cause__ or exc.__context__
        seen += 1
    return False


def _parse_gateway_catalog(data: object) -> list[str]:
    """Validate and normalize a gateway catalog payload, or raise malformed."""
    if not isinstance(data, dict) or not isinstance(data.get("data"), list):
        raise _MalformedCatalogError()
    model_ids: list[str] = []
    for entry in data["data"]:
        if not isinstance(entry, dict):
            raise _MalformedCatalogError()
        raw = entry.get("id", entry.get("model", ""))
        if raw is not None:
            model_ids.append(str(raw))
    return sorted({m for m in model_ids if m})


def _discover_gateway_models() -> tuple[list[str], dict[str, Any]]:
    """Return (model_ids, discovery_metadata) for the configured gateway.

    The metadata's `error.kind` carries the failure taxonomy the Setup wizard
    surfaces (#287): `not_configured`, `auth`, `not_found`, `server`, `http`,
    `policy`, `connectivity`, `tls`, `malformed`, `empty`, `unexpected`.
    Messages are sanitized on purpose — failure class plus HTTP status, never
    a gateway URL, key, or response body. The function never raises: the
    contract is "answer with the best-known catalog plus the reason it is not
    a live gateway catalog".
    """
    import os

    base = os.environ.get("LITELLM_API_BASE") or os.environ.get("LITELLM_PROXY_URL") or ""
    key = os.environ.get("LITELLM_API_KEY") or os.environ.get("LITELLM_PROXY_KEY") or ""
    if not base:
        return [settings_store.current().default_model], {
            "discovered": False,
            "source": "stored_default",
            "error": {
                "kind": "not_configured",
                "message": "No LLM gateway is configured; the stored default is the only known-good model.",
            },
        }
    try:
        headers = {}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        url = f"{base.rstrip('/')}/models"
        resp = httpx.get(url, headers=headers, timeout=5.0)
        resp.raise_for_status()
        unique = _parse_gateway_catalog(resp.json())
        if not unique:
            return [], {
                "discovered": False,
                "source": "gateway",
                "error": {
                    "kind": "empty",
                    "message": "The gateway answered but returned an empty model catalog.",
                },
            }
        return unique, {"discovered": True, "source": "gateway", "error": None}
    except httpx.UnsupportedProtocol:
        kind = "policy"
        message = "The configured gateway URL uses a scheme that is not allowed; only http/https gateway URLs are permitted."
    except httpx.TransportError as exc:
        if _is_tls_failure(exc):
            kind = "tls"
            message = "TLS certificate verification failed while contacting the gateway."
        else:
            kind = "connectivity"
            message = "Could not reach the gateway (connection error or timeout)."
    except httpx.HTTPStatusError as exc:
        kind = _classify_http_status(exc.response.status_code)
        message = (
            f"The gateway rejected the model-discovery request (HTTP {exc.response.status_code})."
        )
    except (json.JSONDecodeError, UnicodeDecodeError, _MalformedCatalogError):
        kind = "malformed"
        message = "The gateway response could not be parsed as a model catalog."
    except Exception as exc:  # contract is never-raise: classify and degrade.
        kind = "unexpected"
        message = "An unexpected error occurred while discovering gateway models."
        logger.info("gateway model discovery raised %s", type(exc).__name__)
    logger.warning("gateway model discovery failed: kind=%s detail=%s", kind, message)
    return [settings_store.current().default_model], {
        "discovered": False,
        "source": "stored_default",
        "error": {"kind": kind, "message": message},
    }


def _fetch_available_models() -> list[str]:
    """Back-compat view: just the catalog, defaulting to the stored model.

    Kept separate from `settings_models` because "which models" and "was this
    actually discovered from the gateway" are different questions (#287).
    """
    models, _ = _discover_gateway_models()
    return models or [settings_store.current().default_model]


@router.get("/features")
def settings_features() -> dict:
    values = settings_store.current()
    return {
        "stream_responses": values.stream_responses,
        "notifications_enabled": values.notifications_enabled,
        "auto_save_sessions": values.auto_save_sessions,
        "telemetry_enabled": values.telemetry_enabled,
    }
