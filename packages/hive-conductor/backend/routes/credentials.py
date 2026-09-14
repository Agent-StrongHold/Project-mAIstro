"""Per-user integration credentials — encrypted at rest, never returned in API responses."""

from __future__ import annotations

import ssl
from typing import Any
from urllib.parse import urlsplit

import httpx
import stores
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from services import user_credentials as cred_svc

from maistro.capabilities.binding import Binding
from maistro.capabilities.providers.llm_gateway import GatewayEndpoint
from maistro.credentials import CredentialNotFound, get_provider
from maistro.credentials.store import CredentialStoreUnavailable
from maistro.http import sync_client
from maistro.security.outbound import OutboundBlockedError, configure_outbound_policy
from maistro.security.ssrf import SSRFBlockedError
from routes.audit import log_audit

router = APIRouter(tags=["credentials"])

_OPENAI_COMPATIBLE_ID = "openai_compatible"


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
    return {str(key): str(value) for key, value in raw.items()} if isinstance(raw, dict) else {}


def _public_config(config: dict[str, str]) -> dict[str, str]:
    """Remove lifecycle bookkeeping from the browser-facing config shape."""
    return {key: value for key, value in config.items() if key != "enabled"}


def _config_enabled(config: dict[str, str]) -> bool:
    return config.get("enabled", "true").lower() not in {"0", "false", "no", "off"}


def _validate_openai_config(config: dict[str, str]) -> dict[str, str]:
    """Validate the non-secret endpoint before it can be saved or probed.

    A configured private endpoint is allowed by the explicit-endpoint policy
    (#67) only after this route has accepted the exact origin. Redirects and
    any later destination still go through the shared outbound guard.
    """
    display_name = config.get("display_name", "").strip()
    base_url = config.get("base_url", "").strip().rstrip("/")
    if not display_name:
        raise HTTPException(status_code=422, detail="display_name is required")
    if len(display_name) > 128:
        raise HTTPException(status_code=422, detail="display_name exceeds 128 characters")
    if not base_url:
        raise HTTPException(status_code=422, detail="base_url is required")
    if len(base_url) > 2048:
        raise HTTPException(status_code=422, detail="base_url exceeds 2048 characters")
    try:
        parsed = urlsplit(base_url)
        port = parsed.port
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="base_url has an invalid port") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        # Empty query/fragment delimiters are still not endpoint data. Reject
        # them, plus whitespace and backslashes, before httpx normalizes them.
        or "?" in base_url
        or "#" in base_url
        or "\\" in base_url
        or any(char.isspace() or ord(char) < 32 for char in base_url)
        or (port is None and ":" in parsed.netloc.rsplit("]", 1)[-1])
    ):
        raise HTTPException(
            status_code=422,
            detail="base_url must be an http(s) URL without credentials, query, or fragment",
        )
    result = dict(config)
    result.update({"display_name": display_name, "base_url": base_url})
    for field in ("organization", "project"):
        result[field] = result.get(field, "").strip()
        if len(result[field]) > 256:
            raise HTTPException(status_code=422, detail=f"{field} exceeds 256 characters")
    # Registration is the explicit operator decision that permits an internal
    # gateway origin. The shared transport remains authoritative for redirects.
    configure_outbound_policy(base_url)
    return result


def _models_url(endpoint: GatewayEndpoint) -> str:
    return f"{endpoint._base}/models"


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
                "enabled": _config_enabled(_read_config(uid, entry["id"])),
                "updated_at": meta.get("updated_at"),
                "config_fields": _config_field_dicts(provider),
                "config_values": _public_config(_read_config(uid, entry["id"])),
            }
        )
    return {"credentials": items}


class SetConfigBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Free-form dict of {field_name: value}; values are non-secret strings
    # (we enforce a small length cap so an attacker can't dump arbitrary
    # blobs into the store via this endpoint).
    config: dict[str, str] = Field(default_factory=dict)
    # Enabled is lifecycle state, not provider configuration. Keeping it out of
    # `config` prevents it from becoming a user-visible text field.
    enabled: bool | None = None


class TestCredentialBody(BaseModel):
    model_config = ConfigDict(extra="ignore")

    config: dict[str, str] = Field(default_factory=dict)
    # Optional for a first-time test; when absent the encrypted stored key is
    # used through UserCredentialStore.use_secret and never returned.
    secret: str | None = Field(default=None, max_length=4096)


@router.get("/{provider_id}/config")
def get_credential_config(provider_id: str, request: Request) -> dict[str, Any]:
    if get_provider(provider_id) is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)
    config = _read_config(uid, provider_id)
    return {
        "provider": provider_id,
        "config": _public_config(config),
        "enabled": _config_enabled(config),
    }


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
    # table name; rejects abuse). The generic endpoint URL gets its own larger
    # limit because a private gateway may include a long path prefix.
    for k, v in body.config.items():
        limit = 2048 if provider_id == _OPENAI_COMPATIBLE_ID and k == "base_url" else 256
        if len(v) > limit:
            raise HTTPException(
                status_code=400,
                detail=f"Field {k!r} exceeds {limit}-char limit",
            )

    if provider_id == _OPENAI_COMPATIBLE_ID:
        current = _read_config(uid, provider_id)
        config = _validate_openai_config({**current, **body.config})
    else:
        config = dict(body.config)
    if body.enabled is not None:
        config["enabled"] = "true" if body.enabled else "false"

    stores.user_provider_config[_config_key(uid, provider_id)] = config
    log_audit(
        action="credential_config_save",
        actor=uid,
        target=provider_id,
        detail={"keys": sorted(body.config.keys())},
    )
    return {
        "ok": True,
        "provider": provider_id,
        "config": _public_config(config),
        "enabled": _config_enabled(config),
    }


def _probe_openai_endpoint(
    endpoint: GatewayEndpoint,
    config: dict[str, str],
    secret: str,
    provider_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """Call the canonical OpenAI-compatible model-discovery seam."""
    probe_endpoint = endpoint.model_copy(update={"api_key": secret})
    try:
        with sync_client(timeout=15.0, follow_redirects=True) as client:
            response = client.get(
                _models_url(probe_endpoint), headers=probe_endpoint.authorization_header()
            )
    except (OutboundBlockedError, SSRFBlockedError) as exc:
        raise HTTPException(
            status_code=422, detail=f"policy rejection: {exc.detail or 'outbound URL blocked'}"
        ) from exc
    except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ProxyError) as exc:
        raise HTTPException(status_code=502, detail=f"connectivity: {type(exc).__name__}") from exc
    except httpx.ConnectError as exc:
        category = "TLS" if _looks_like_tls_error(exc) else "connectivity"
        raise HTTPException(status_code=502, detail=f"{category}: gateway unavailable") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"connectivity: {type(exc).__name__}") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(
            status_code=401,
            detail=f"authentication: gateway rejected the API key (HTTP {response.status_code})",
        )
    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail=f"incompatible API behavior: /models returned HTTP {response.status_code}",
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(
            status_code=502, detail="incompatible API behavior: /models was not JSON"
        ) from exc
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raise HTTPException(
            status_code=502,
            detail="incompatible API behavior: /models did not return a data list",
        )
    models = sorted(
        {str(item["id"]) for item in raw_models if isinstance(item, dict) and item.get("id")}
    )
    binding = Binding(
        workspace_id=workspace_id,
        project_id="default",
        capability="model.chat",
        provider_name="openai-compatible",
        config=_public_config(config),
        credential_refs=(provider_id,),
    )
    return {
        "ok": True,
        "provider": provider_id,
        "display_name": config["display_name"],
        "models": models,
        "model_count": len(models),
        "config": _public_config(config),
        "binding": binding.model_dump(mode="json"),
    }


@router.post("/{provider_id}/test")
def test_credential(provider_id: str, body: TestCredentialBody, request: Request) -> dict[str, Any]:
    """Probe an OpenAI-compatible `/models` endpoint without persisting input."""
    provider = get_provider(provider_id)
    if provider_id != _OPENAI_COMPATIBLE_ID or provider is None:
        raise HTTPException(status_code=404, detail="Unknown credential provider")
    uid = _user_id(request)
    allowed_names = {field.name for field in provider.config_fields}
    bad = set(body.config) - allowed_names
    if bad:
        raise HTTPException(status_code=400, detail=f"Unknown config field(s): {sorted(bad)}")
    config = _validate_openai_config({**_read_config(uid, provider_id), **body.config})
    endpoint = GatewayEndpoint(
        base_url=config["base_url"],
        organization=config.get("organization", ""),
        project=config.get("project", ""),
        timeout_s=15.0,
    )
    if body.secret is not None:
        if not body.secret.strip():
            raise HTTPException(status_code=422, detail="API key is required for a test")
        return _probe_openai_endpoint(endpoint, config, body.secret.strip(), provider_id, uid)
    try:
        store = cred_svc.require_store()
        return store.use_secret(
            uid,
            provider_id,
            lambda secret: _probe_openai_endpoint(endpoint, config, secret, provider_id, uid),
        )
    except CredentialNotFound as exc:
        raise HTTPException(status_code=422, detail="API key is required for a test") from exc
    except CredentialStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _looks_like_tls_error(exc: BaseException) -> bool:
    current: BaseException | None = exc
    for _ in range(3):
        message = str(current).lower()
        if isinstance(current, ssl.SSLError) or any(
            marker in message
            for marker in (
                "ssl",
                "tls",
                "certificate verify failed",
                "certificate_unknown",
                "wrong version number",
            )
        ):
            return True
        current = current.__cause__ or current.__context__
        if current is None:
            break
    return False


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
        deleted_secret = store.delete_secret(uid, provider_id)
    except CredentialStoreUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # Non-secret configuration can be saved before the first key. Deleting a
    # draft must remove that configuration too, rather than reporting 404 and
    # leaving an endpoint behind with no vault secret.
    deleted_config = stores.user_provider_config.pop(_config_key(uid, provider_id), None)
    if not deleted_secret and deleted_config is None:
        raise HTTPException(status_code=404, detail="Credential not configured")
    log_audit("credential_delete", uid, target=provider_id)
