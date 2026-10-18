"""Conductor identity — HTTP principal and optional crypto root of trust (ADR-021).

``Principal`` (P0.1 / ADR-068) is always importable. BIP39/BIP32 seed helpers and
agent lifecycle symbols load lazily and require the ``identity`` extra.
"""

from __future__ import annotations

from typing import Any

from maistro.identity.principal import Principal

# Populated lazily by ``__getattr__``; declared for mypy strict.
ConductorSeed: Any
DerivedKey: Any
PATHS: Any

__all__ = [
    "PATHS",
    "AgentIdentity",
    "CapabilityToken",
    "CapabilityTokenError",
    "ConductorSeed",
    "DerivedKey",
    "IdentityAlreadyExistsError",
    "IdentityArchivedError",
    "IdentityLifecycleError",
    "IdentityNotFoundError",
    "IdentityStore",
    "InMemoryIdentityStore",
    "InMemorySecretStore",
    "InMemoryTokenStore",
    "InvalidRecoverySeedError",
    "InvalidTokenSignatureError",
    "Principal",
    "SecretStore",
    "TokenExpiredError",
    "TokenRevokedError",
    "TokenStore",
    "create_agent_identity",
    "did_key_from_public_key",
    "issue_capability_token",
    "offboard_agent",
    "public_key_from_did_key",
    "recover_agent_identity",
    "verify_capability_token",
]

_CRYPTO_NAMES = frozenset({"ConductorSeed", "DerivedKey", "PATHS"})
_LIFECYCLE_NAMES = frozenset(
    name for name in __all__ if name not in _CRYPTO_NAMES and name != "Principal"
)

_crypto_loaded = False
_lifecycle_loaded = False


def _ensure_crypto() -> None:
    global _crypto_loaded, ConductorSeed, DerivedKey, PATHS
    if _crypto_loaded:
        return
    from maistro.identity import _crypto as crypto_module

    ConductorSeed = crypto_module.ConductorSeed
    DerivedKey = crypto_module.DerivedKey
    PATHS = crypto_module.PATHS
    _crypto_loaded = True


def _ensure_lifecycle() -> None:
    global _lifecycle_loaded
    if _lifecycle_loaded:
        return
    from maistro.identity import lifecycle as lifecycle_module

    exports = {
        "AgentIdentity": lifecycle_module.AgentIdentity,
        "CapabilityToken": lifecycle_module.CapabilityToken,
        "CapabilityTokenError": lifecycle_module.CapabilityTokenError,
        "IdentityAlreadyExistsError": lifecycle_module.IdentityAlreadyExistsError,
        "IdentityArchivedError": lifecycle_module.IdentityArchivedError,
        "IdentityLifecycleError": lifecycle_module.IdentityLifecycleError,
        "IdentityNotFoundError": lifecycle_module.IdentityNotFoundError,
        "IdentityStore": lifecycle_module.IdentityStore,
        "InMemoryIdentityStore": lifecycle_module.InMemoryIdentityStore,
        "InMemorySecretStore": lifecycle_module.InMemorySecretStore,
        "InMemoryTokenStore": lifecycle_module.InMemoryTokenStore,
        "InvalidRecoverySeedError": lifecycle_module.InvalidRecoverySeedError,
        "InvalidTokenSignatureError": lifecycle_module.InvalidTokenSignatureError,
        "SecretStore": lifecycle_module.SecretStore,
        "TokenExpiredError": lifecycle_module.TokenExpiredError,
        "TokenRevokedError": lifecycle_module.TokenRevokedError,
        "TokenStore": lifecycle_module.TokenStore,
        "create_agent_identity": lifecycle_module.create_agent_identity,
        "did_key_from_public_key": lifecycle_module.did_key_from_public_key,
        "issue_capability_token": lifecycle_module.issue_capability_token,
        "offboard_agent": lifecycle_module.offboard_agent,
        "public_key_from_did_key": lifecycle_module.public_key_from_did_key,
        "recover_agent_identity": lifecycle_module.recover_agent_identity,
        "verify_capability_token": lifecycle_module.verify_capability_token,
    }
    globals().update(exports)
    _lifecycle_loaded = True


def __getattr__(name: str) -> object:
    if name in _CRYPTO_NAMES:
        _ensure_crypto()
    elif name in _LIFECYCLE_NAMES:
        _ensure_lifecycle()
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return globals()[name]
