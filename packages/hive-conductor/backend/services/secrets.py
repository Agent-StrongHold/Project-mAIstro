"""Centralized secret resolution: vault first, config/env fallback (SPEC-003).

Generalizes the vault-first pattern already used for HOST_HEALTH_TOKEN (see
capabilities_wiring.py) to the other plaintext-env secrets named in SPEC-003.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING

from pydantic import SecretStr

if TYPE_CHECKING:
    from config import Settings

logger = logging.getLogger("hive.secrets")


def _vault() -> object | None:
    from services.foundation import get_foundation

    try:
        foundation = get_foundation()
    except RuntimeError:
        return None
    return foundation.vault if foundation.vault_available else None


def _from_vault(name: str) -> str | None:
    vault = _vault()
    if vault is None:
        return None
    try:
        return vault.use(name, lambda s: s)  # type: ignore[attr-defined]
    except Exception:
        return None


def resolve_secret(
    name: str,
    *,
    config_value: SecretStr | str | None = None,
    env_var: str | None = None,
    required: bool = False,
) -> str | None:
    """Resolve a secret: vault[name] -> config_value -> env_var.

    Required secrets that resolve to nothing anywhere log SECRET_MISSING and
    raise SystemExit — conductor fails closed rather than starting degraded.
    """
    value = _from_vault(name)
    if not value and config_value is not None:
        value = (
            config_value.get_secret_value()
            if isinstance(config_value, SecretStr)
            else str(config_value)
        )
    if not value and env_var:
        value = os.environ.get(env_var)
    value = value or None
    if required and not value:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the secret's *name* (a vault key), never its value
        logger.error("SECRET_MISSING: %s", name)
        raise SystemExit(f"SECRET_MISSING: {name}")
    return value


def litellm_api_key(settings: Settings, *, required: bool = False) -> str | None:
    return resolve_secret(
        "LITELLM_API_KEY",
        config_value=settings.litellm_api_key,
        env_var="LITELLM_API_KEY",
        required=required,
    )


def maistro_llm_api_key(settings: Settings, *, required: bool = False) -> str | None:
    return resolve_secret(
        "MAISTRO_LLM_API_KEY",
        config_value=settings.maistro_llm_api_key,
        required=required,
    )
