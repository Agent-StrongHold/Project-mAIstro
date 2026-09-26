"""Deployment health for the optional Conductor identity capability.

The engine owns identity primitives; this product-side probe only reports
whether this deployment can use them. It never creates a seed or becomes an
identity store, so setup remains the sole provisioning authority.
"""

from __future__ import annotations

from typing import Any

_SETUP_KEY = "__hive_setup__"
_SEED_VAULT_KEY = "CONDUCTOR_SEED_MNEMONIC"


def _validate_identity_seed(mnemonic: str, did: str) -> tuple[bool, str]:
    """Validate the seed and compare its derived DID without returning it."""
    from maistro.identity import ConductorSeed

    seed: ConductorSeed | None = None
    try:
        seed = ConductorSeed.from_mnemonic(mnemonic)
        if seed.did_key() != did:
            return False, "identity_seed_did_mismatch"
        return True, "provisioned"
    except Exception:
        # BIP39 checksum/word errors and malformed vault values have the same
        # public outcome; neither the value nor library-specific details belong
        # in a health response.
        return False, "identity_seed_invalid"
    finally:
        if seed is not None:
            seed.zero()


def _identity_seed_status(did: str) -> tuple[bool, str]:
    """Decrypt and validate the encrypted identity root without exposing it."""
    try:
        from routes.setup import _vault_paths

        from maistro.vault import SecretMissingError, Vault, VaultUnavailableError

        vault_path, identity_path = _vault_paths()
        vault = Vault(vault_path=vault_path, identity_path=identity_path)
        return vault.use(_SEED_VAULT_KEY, lambda mnemonic: _validate_identity_seed(mnemonic, did))
    except SecretMissingError:
        return False, "identity_seed_missing"
    except VaultUnavailableError:
        # Vault errors intentionally collapse to a stable public reason; age
        # stderr and filesystem paths are not health API data.
        return False, "identity_vault_unavailable"
    except Exception:
        return False, "identity_vault_unavailable"


def identity_health() -> dict[str, Any]:
    """Return a public, non-secret identity deployment status.

    ``unavailable`` means the selected runtime cannot import the engine extra;
    ``misconfigured`` means setup selected identity but did not leave a valid
    DID and matching encrypted seed record; ``operational`` means the vault
    decrypts a valid BIP39 seed whose derived DID matches the persisted DID;
    ``disabled`` is the supported no-crypto Conductor profile.
    A pre-setup instance is reported as misconfigured with a distinct reason,
    but is not treated as a failed optional capability until setup selects it.
    """
    try:
        from maistro.identity import (  # type: ignore[import-untyped]
            public_key_from_did_key,
        )
    except ImportError:
        return {"status": "unavailable", "reason": "identity_runtime_missing"}

    try:
        import stores

        config = stores.sessions.get(_SETUP_KEY)
    except Exception:
        return {"status": "misconfigured", "reason": "setup_state_unreadable"}

    if not isinstance(config, dict):
        return {"status": "misconfigured", "reason": "setup_incomplete"}

    modules = config.get("optional_modules")
    if not isinstance(modules, list) or "crypto_identity" not in modules:
        return {"status": "disabled", "reason": "crypto_identity_not_enabled"}

    did = config.get("user_did")
    if not isinstance(did, str) or not did or config.get("identity_persisted") is not True:
        return {"status": "misconfigured", "reason": "identity_not_provisioned"}

    try:
        public_key_from_did_key(did)
    except (TypeError, ValueError):
        return {"status": "misconfigured", "reason": "invalid_provisioned_did"}

    seed_available, reason = _identity_seed_status(did)
    if not seed_available:
        return {"status": "misconfigured", "reason": reason}
    return {"status": "operational", "reason": reason}


def identity_is_required(status: dict[str, Any]) -> bool:
    """Whether an identity failure is a deployment degradation, not a choice."""
    return status.get("status") in {"unavailable", "misconfigured"} and status.get(
        "reason"
    ) not in {"setup_incomplete"}
