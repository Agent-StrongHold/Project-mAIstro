"""Hive-facing credential service singleton."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from maistro.credentials import (
    PM_CREDENTIAL_PROVIDERS,
    CredentialStoreUnavailable,
    UserCredentialStore,
)

logger = logging.getLogger("hive.credentials")

_store: UserCredentialStore | None = None


def init_credential_store(data_dir: str | Path) -> bool:
    """Initialize encrypted credential store. Returns True on success."""
    global _store
    try:
        _store = UserCredentialStore.open(data_dir)
        # stdlib logger — keyword args raise TypeError. Use % formatting.
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the data directory path, never credential material
        logger.info("user_credential_store_ready data_dir=%s", str(data_dir))
        return True
    except Exception as exc:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the exception, never credential material
        logger.warning("user_credential_store_unavailable: %s", exc)
        _store = None
        return False


def get_credential_store() -> UserCredentialStore | None:
    return _store


def require_store() -> UserCredentialStore:
    if _store is None:
        raise CredentialStoreUnavailable("Credential store is not initialized")
    return _store


def list_provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": p.id,
            "label": p.label,
            "description": p.description,
            "help_url": p.help_url,
            "placeholder": p.placeholder,
        }
        for p in PM_CREDENTIAL_PROVIDERS
    ]
