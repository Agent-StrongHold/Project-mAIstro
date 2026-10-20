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
        # The log line names no secret at all: even the vault key *name*
        # reads as secret material to a scanner, and the exit message below
        # (printed by the interpreter on the way out) already carries it.
        logger.error("SECRET_MISSING: a required secret is not configured; see the exit message")
        raise SystemExit(f"SECRET_MISSING: {name}")
    return value


def litellm_api_key(settings: Settings, *, required: bool = False) -> str | None:
    return resolve_secret(
        "LITELLM_API_KEY",
        config_value=settings.litellm_api_key,
        env_var="LITELLM_API_KEY",
        required=required,
    )


def effective_llm_gateway_key(settings: Settings) -> str | None:
    """The one effective model-gateway credential (#1824).

    Every runtime consumer that needs "the key the deployment's model egress
    authenticates with" reads it through this contract instead of assembling
    its own alias chain, so the embedded runtime's legacy client, the
    canonical governed egress endpoint and any future consumer cannot drift
    onto different credentials.

    Effective-key precedence matrix (first non-empty wins; an empty string at
    any layer is *unset* and falls through, so a blanked variable never
    shadows a configured one):

    1. vault[``MAISTRO_LLM_API_KEY``] -- the deployment's own model key,
       stated in the conductor vault (SPEC-003 vault-first);
    2. ``Settings.maistro_llm_api_key`` -- the same name from the process
       environment / ``.env`` via pydantic-settings;
    3. vault[``LITELLM_API_KEY``];
    4. ``Settings.litellm_api_key`` -- env ``LITELLM_API_KEY`` / ``.env``
       (what the shipped compose file derives from ``LITELLM_MASTER_KEY``);
    5. bare-env proxy aliases ``LITELLM_PROXY_KEY`` then
       ``LITELLM_MASTER_KEY`` -- the supported LiteLLM proxy spellings some
       deployments state directly (they exist so a stack that only knows the
       proxy's own key still reaches the bundled gateway);
    6. ``None`` -- absent model configuration. Callers treat this as
       fail-closed: no credential is registered or dispatched, never a
       placeholder key.

    Conflicting values are resolved by this order -- the maistro-scoped key
    outranks the gateway aliases because it is the key this deployment
    intentionally named for its own model authority, while the aliases are
    compatibility fallbacks. Returns ``None`` (never ``""``) when nothing is
    configured, so callers can distinguish "unset" from a real empty value.
    """
    key = maistro_llm_api_key(settings)
    if key:
        return key
    key = litellm_api_key(settings)
    if key:
        return key
    for alias in ("LITELLM_PROXY_KEY", "LITELLM_MASTER_KEY"):
        key = os.environ.get(alias)
        if key:
            return key
    return None


def maistro_llm_api_key(settings: Settings, *, required: bool = False) -> str | None:
    return resolve_secret(
        "MAISTRO_LLM_API_KEY",
        config_value=settings.maistro_llm_api_key,
        env_var="MAISTRO_LLM_API_KEY",
        required=required,
    )
