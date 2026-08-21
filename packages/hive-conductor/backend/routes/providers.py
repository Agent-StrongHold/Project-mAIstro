"""LLM provider activation — vault-backed keys + LiteLLM dynamic registration.

Provider API keys are deployment-wide vault material (SPEC-072726-3439
Phase 4), not per-user integration credentials: they live in the age vault,
never in `.env` or the per-user Fernet credential store. Activation registers
the provider's models with the running LiteLLM instance via its admin API (no
container recreate) and finishes with a one-token test completion — the
install journey's "first model call".

Both mutating routes are gated under `config.write` in the auth middleware:
they use the LiteLLM master key, mutate the global model registry, and can
trigger billed calls.
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["providers"])
logger = logging.getLogger("hive.providers")

_KV_PREFIX = "__llm_provider__::"

# Mirrors litellm_config.yaml's provider set. env_key doubles as the vault
# secret name; test_model must be cheap and fast.
LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "gemini": {
        "label": "Google Gemini",
        "env_key": "GEMINI_API_KEY",
        "test_model": "gemini/gemini-2.5-flash",
        "models": ["gemini/gemini-2.5-flash", "gemini/gemini-2.5-pro"],
    },
    "anthropic": {
        "label": "Anthropic",
        "env_key": "ANTHROPIC_API_KEY",
        "test_model": "anthropic/claude-3-5-haiku-20241022",
        "models": [
            "anthropic/claude-sonnet-4-20250514",
            "anthropic/claude-3-5-haiku-20241022",
        ],
    },
    "openai": {
        "label": "OpenAI",
        "env_key": "OPENAI_API_KEY",
        "test_model": "openai/gpt-4o-mini",
        "models": ["openai/gpt-4o", "openai/gpt-4o-mini"],
    },
    "groq": {
        "label": "Groq",
        "env_key": "GROQ_API_KEY",
        "test_model": "groq/llama-3.3-70b-versatile",
        "models": ["groq/llama-3.3-70b-versatile"],
    },
    "mistral": {
        "label": "Mistral",
        "env_key": "MISTRAL_API_KEY",
        "test_model": "mistral/mistral-large-latest",
        "models": ["mistral/mistral-large-latest"],
    },
    "xai": {
        "label": "xAI",
        "env_key": "XAI_API_KEY",
        "test_model": "xai/grok-3-mini",
        "models": ["xai/grok-3-mini"],
    },
    "openrouter": {
        "label": "OpenRouter",
        "env_key": "OPENROUTER_API_KEY",
        "test_model": "openrouter/openai/gpt-4o-mini",
        "models": [
            "openrouter/google/gemini-2.5-flash",
            "openrouter/anthropic/claude-sonnet-4",
            "openrouter/openai/gpt-4o-mini",
        ],
    },
}


def _provider_or_404(name: str) -> dict[str, Any]:
    p = LLM_PROVIDERS.get(name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Unknown LLM provider '{name}'")
    return p


def _vault() -> Any:
    """Open the vault, provisioning it on first use. 503 when age is missing."""
    from maistro.vault import Vault, VaultUnavailableError, init_vault
    from routes.setup import _vault_paths

    vault_path, identity_path = _vault_paths()
    try:
        init_vault(vault_path, identity_path)
    except VaultUnavailableError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Secrets vault unavailable — install the age toolchain. ({exc})",
        ) from exc
    return Vault(vault_path=vault_path, identity_path=identity_path)


def _litellm_admin_base() -> str:
    base = os.environ.get("LITELLM_PROXY_URL")
    if not base:
        from config import get_settings

        api_base = os.environ.get("LITELLM_API_BASE") or (get_settings().litellm_api_base or "")
        base = api_base.removesuffix("/v1")
    if not base:
        raise HTTPException(status_code=503, detail="LiteLLM gateway is not configured")
    return base.rstrip("/")


def _litellm_master_key() -> str:
    key = os.environ.get("LITELLM_PROXY_KEY") or os.environ.get("LITELLM_API_KEY")
    if not key:
        from config import get_settings

        secret = get_settings().litellm_api_key
        key = secret.get_secret_value() if secret is not None else ""
    if not key:
        raise HTTPException(status_code=503, detail="LiteLLM master key is not configured")
    return key


def _kv() -> Any | None:
    import stores

    return stores.sessions if getattr(stores.sessions, "_persisted", None) else None


def _record_activation(name: str) -> None:
    kv = _kv()
    if kv is not None:
        kv[f"{_KV_PREFIX}{name}"] = {"activated_at": datetime.now(UTC).isoformat()}


def _is_activated(name: str) -> bool:
    kv = _kv()
    return kv is not None and f"{_KV_PREFIX}{name}" in kv


def any_provider_activated() -> bool:
    """Used by the setup checklist's llm_provider item."""
    return any(_is_activated(name) for name in LLM_PROVIDERS)


@router.get("")
def list_providers() -> dict[str, Any]:
    try:
        vault = _vault()
        vault_ok = True
    except HTTPException:
        vault = None
        vault_ok = False
    out = []
    for name, p in LLM_PROVIDERS.items():
        has_key = False
        if vault is not None:
            try:
                has_key = vault.has(p["env_key"])
            except Exception:
                has_key = False
        out.append(
            {
                "name": name,
                "label": p["label"],
                "models": p["models"],
                "test_model": p["test_model"],
                "has_key": has_key,
                "activated": _is_activated(name),
            }
        )
    return {"kind": "llm_providers", "vault_available": vault_ok, "providers": out}


@router.put("/{name}/key")
def put_provider_key(name: str, body: dict[str, Any]) -> dict[str, Any]:
    p = _provider_or_404(name)
    api_key = body.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise HTTPException(status_code=422, detail="api_key required")
    vault = _vault()
    vault.add(p["env_key"], api_key.strip())
    logger.info("provider key stored in vault: %s", name)
    return {"name": name, "has_key": True}


@router.post("/{name}/activate")
def activate_provider(name: str) -> dict[str, Any]:
    """Register the provider's models with LiteLLM and run a one-token test
    completion. Success is the install journey's first model call."""
    p = _provider_or_404(name)
    vault = _vault()

    from maistro.vault import SecretMissingError

    # Key first: "store a key" is the actionable fix for the operator, and it
    # should surface even when the gateway is misconfigured.
    if not vault.has(p["env_key"]):
        raise HTTPException(
            status_code=409,
            detail=f"No key stored for '{name}' — PUT /v1/providers/{name}/key first.",
        )

    admin_base = _litellm_admin_base()
    master_key = _litellm_master_key()
    headers = {"Authorization": f"Bearer {master_key}"}

    def _register_and_test(api_key: str) -> dict[str, Any]:
        with httpx.Client(timeout=30.0) as client:
            for model in p["models"]:
                r = client.post(
                    f"{admin_base}/model/new",
                    headers=headers,
                    json={
                        "model_name": model,
                        "litellm_params": {"model": model, "api_key": api_key},
                    },
                )
                if r.status_code >= 400:
                    raise HTTPException(
                        status_code=502,
                        detail=f"LiteLLM registration failed for {model}: HTTP {r.status_code}",
                    )
            r = client.post(
                f"{admin_base}/v1/chat/completions",
                headers=headers,
                json={
                    "model": p["test_model"],
                    "max_tokens": 1,
                    "messages": [{"role": "user", "content": "ping"}],
                },
            )
        if r.status_code >= 400:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"Test completion failed on {p['test_model']}: HTTP {r.status_code}. "
                    "Check that the API key is valid and has quota."
                ),
            )
        data = r.json()
        return {"model": p["test_model"], "usage": data.get("usage", {})}

    try:
        result = vault.use(p["env_key"], _register_and_test)
    except SecretMissingError:
        raise HTTPException(
            status_code=409,
            detail=f"No key stored for '{name}' — PUT /v1/providers/{name}/key first.",
        ) from None
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LiteLLM gateway unreachable: {exc}") from exc

    _record_activation(name)
    logger.info("provider activated (test completion OK): %s", name)
    return {"name": name, "activated": True, "first_model_call": result}
