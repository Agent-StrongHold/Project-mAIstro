"""Setup wizard API — persists to SQLite, creates admin + user accounts."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["setup"])

logger = logging.getLogger("hive.setup")

_SETUP_KEY = "__hive_setup__"
_SEED_VAULT_KEY = "CONDUCTOR_SEED_MNEMONIC"

# Least-privilege permissions assigned to the daily account created at setup.
# Protected operations still require explicit password-backed /auth/elevate;
# assignment only makes that elevation possible. DAG authoring/optimization is
# a normal daily-user workflow, while broader configuration/infrastructure
# permissions remain admin-only until a dedicated grant-management surface is
# introduced.
_DEFAULT_DAILY_USER_PERMISSIONS = ["dags.write"]


def _vault_paths() -> tuple[str, str]:
    from config import get_settings

    s = get_settings()
    data_dir = Path(s.conductor_data_dir).expanduser()
    vault_path = s.conductor_vault_path or str(data_dir / "secrets.age")
    identity_path = s.conductor_identity_path or str(data_dir / "admin.key")
    return vault_path, identity_path


def _init_vault_best_effort() -> bool:
    """Provision the age vault at first run so vault-first secret resolution
    is live from day one. Best-effort: a host without the age toolchain gets
    a loud log line and `vault_initialized: false` in the setup config, not a
    failed setup."""
    try:
        from maistro.vault import init_vault

        vault_path, identity_path = _vault_paths()
        init_vault(vault_path, identity_path)
        return True
    except Exception as exc:
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the failure reason only, never secret values
        logger.warning("vault not initialized at setup (secrets stay env-based): %s", exc)
        return False


def _persist_identity_root(mnemonic_words: list[str]) -> bool:
    """Store the seed mnemonic encrypted in the vault BEFORE it is zeroed.

    Without this the runtime has no private root after the response is sent
    (ADR-021 signing), unless the operator re-enters the once-shown mnemonic.
    """
    try:
        from maistro.vault import Vault, init_vault

        vault_path, identity_path = _vault_paths()
        init_vault(vault_path, identity_path)
        Vault(vault_path=vault_path, identity_path=identity_path).add(
            _SEED_VAULT_KEY, " ".join(mnemonic_words)
        )
        return True
    except Exception as exc:
        logger.warning(
            "identity root NOT persisted to vault — the once-shown mnemonic is the only copy: %s",
            exc,
        )
        return False


def _get_kv() -> Any:
    import stores

    return stores.sessions if stores.sessions._persisted else None


def _is_setup_complete() -> bool:
    kv = _get_kv()
    if kv is not None:
        return _SETUP_KEY in kv
    import stores

    return len(stores.users) > 0


@router.get("/status")
def setup_status() -> dict[str, Any]:
    from settings_defaults import is_pm_poc_mode

    complete = _is_setup_complete()
    result: dict[str, Any] = {
        "setup_complete": complete,
        "pm_poc_mode": is_pm_poc_mode(),
    }
    if complete:
        kv = _get_kv()
        if kv is not None and _SETUP_KEY in kv:
            result["config"] = kv[_SETUP_KEY]
    return result


class SetupCompleteBody:
    pass


def _maybe_generate_identity(
    modules: list[str],
) -> tuple[str | None, list[str] | None, bool]:
    """Generate the ConductorSeed identity root when requested.

    Returns (did, mnemonic_words, persisted). The operator asked for a crypto
    identity root, and this runs BEFORE any account is created: completing
    setup without the mnemonic would lock the one-shot endpoint behind its
    409 guard with no later provisioning step, so a missing `identity` extra
    fails the whole request instead. The operator repairs the dependency and
    retries, or deselects the module.

    The seed is persisted encrypted (vault) BEFORE zero() — the once-shown
    mnemonic is the recovery path, not the only copy. `persisted` reports
    whether that succeeded.
    """
    if "crypto_identity" not in modules:
        return None, None, False
    try:
        from maistro.identity import ConductorSeed

        # The identity extra can also raise lazily at generate() time (the
        # module imports without bip_utils and defers the error) — keep
        # generation inside the same guard so both failure shapes abort setup.
        seed = ConductorSeed.generate()
    except ImportError as exc:
        logger.error("crypto_identity requested but maistro.identity is unavailable: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=(
                "crypto_identity was requested but the identity runtime is not "
                "installed (maistro-core[identity]). Install it and retry setup, "
                "or deselect the crypto identity module. No accounts were created. "
                f"Underlying error: {exc}"
            ),
        ) from exc
    user_did = seed.did_key()
    mnemonic = seed.mnemonic_words()
    persisted = _persist_identity_root(mnemonic)
    seed.zero()
    return user_did, mnemonic, persisted


@router.post("/complete")
def complete_setup(body: dict[str, Any]) -> dict[str, Any]:
    import stores

    from maistro.security.passwords import hash_password

    # /v1/setup/ is a PUBLIC (unauthenticated) prefix. Setup must be a one-shot
    # first-run operation — once complete, re-running it would let any
    # unauthenticated caller overwrite the admin/user credentials (account
    # takeover). Guard with the same check setup_status() reads.
    if _is_setup_complete():
        raise HTTPException(
            status_code=409,
            detail="Setup already complete. This endpoint is disabled after first-run provisioning.",
        )

    hardware_preset = body.get("hardware_preset")
    admin_username = body.get("admin_username", "admin")
    admin_password = body.get("admin_password")
    user_username = body.get("user_username", "user")
    user_password = body.get("user_password")

    if not hardware_preset:
        raise HTTPException(status_code=422, detail="hardware_preset required")
    if not admin_password:
        raise HTTPException(status_code=422, detail="admin_password required")
    if not user_password:
        raise HTTPException(status_code=422, detail="user_password required")

    now_ts = datetime.now(UTC)

    modules = body.get("optional_modules", [])
    vault_initialized = _init_vault_best_effort()
    user_did, config_mnemonic, identity_persisted = _maybe_generate_identity(modules)

    admin_hash = hash_password(admin_password)
    user_hash = hash_password(user_password)

    stores.users["admin"] = stores.users._model_class(
        id="admin",
        username=admin_username,
        password_hash=admin_hash,
        role="admin",
        is_active=True,
        created_at=now_ts,
        did=None,
    )
    stores.users["user"] = stores.users._model_class(
        id="user",
        username=user_username,
        password_hash=user_hash,
        role="user",
        is_active=True,
        permissions=list(_DEFAULT_DAILY_USER_PERMISSIONS),
        created_at=now_ts,
        did=user_did,
    )

    # v0 fix: persist the Setup-chosen default_model into stores.settings so
    # the Settings page reflects what the user actually picked (was showing
    # the hardcoded legacy cerebras- alias regardless of Setup choice).
    from config import get_settings

    chosen_default_model = body.get("default_model") or get_settings().chat_default_model
    config = {
        "hardware_preset": hardware_preset,
        "optional_modules": modules,
        "conductor_name": body.get("conductor_name", "Hive Conductor"),
        "default_model": chosen_default_model,
        "admin_username": admin_username,
        "user_username": user_username,
        "user_did": user_did,
        "vault_initialized": vault_initialized,
        "identity_persisted": identity_persisted,
        "completed_at": now_ts.isoformat(),
    }

    try:
        stores.settings.default_model = chosen_default_model
    except Exception as exc:
        # best-effort — don't fail Setup over a settings shape mismatch.
        import logging as _logging

        _logging.getLogger("hive.setup").warning(
            "default_model_set_failed: %s",
            exc,
        )

    kv = _get_kv()
    if kv is not None:
        kv[_SETUP_KEY] = config

    result = {"setup_complete": True, "config": config}
    if config_mnemonic is not None:
        result["mnemonic"] = config_mnemonic
        result["mnemonic_warning"] = (
            "Write these words down. This is the only time they will be shown. They are your root of trust for everything."
        )
    return result


@router.get("/presets")
def list_presets() -> dict[str, Any]:
    from maistro.config.presets import HARDWARE_PRESETS

    return {
        "kind": "hardware_presets",
        "presets": {
            name: {
                "name": p.name,
                "label": p.label,
                "description": p.description,
                "max_vcpu": p.max_vcpu,
                "max_memory_gb": p.max_memory_gb,
                "db_backend": p.db_backend,
                "networking": p.networking,
                "gpu_available": p.gpu_available,
                "reactor_enabled": p.reactor_enabled,
                "max_agents": p.max_agents,
            }
            for name, p in HARDWARE_PRESETS.items()
        },
    }


@router.get("/presets/{preset_name}")
def get_preset(preset_name: str) -> dict[str, Any]:
    from maistro.config.presets import HARDWARE_PRESETS

    p = HARDWARE_PRESETS.get(preset_name)
    if p is None:
        raise HTTPException(status_code=404, detail=f"Preset '{preset_name}' not found")
    return {"kind": "hardware_preset", **p.model_dump()}


@router.post("/presets/resolve")
def resolve_preset_auto(body: dict[str, Any] | None = None) -> dict[str, Any]:
    from maistro.config.presets import resolve_preset

    body = body or {}
    name = body.get("name", "auto")
    total_memory_gb = body.get("total_memory_gb")
    p = resolve_preset(name=name, total_memory_gb=total_memory_gb)
    return {
        "kind": "resolved_preset",
        "preset": p.name,
        "config": p.to_config(),
    }
