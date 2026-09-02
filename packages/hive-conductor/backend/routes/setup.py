"""Setup wizard API — persists to SQLite, creates admin + user accounts."""

from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["setup"])

logger = logging.getLogger("hive.setup")

_SETUP_KEY = "__hive_setup__"
#: The first-run *claim*, taken before any account exists (#313). Insert-only
#: in the same store as the config record, so which of two concurrent
#: first-run attempts is the one that provisions is decided by a conflict-safe
#: insert rather than by which request writes the admin hash last.
_SETUP_CLAIM_KEY = "__hive_setup_claim__"
#: Serialises the claim-check-then-claim sequence inside this process; the
#: durable conflict rule covers writers that are not this process.
_SETUP_LOCK = threading.Lock()
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
    """True once first-run setup has begun or finished and cannot re-run.

    In a persisted deployment the signals are the records setup itself writes:
    the claim (a first-run attempt is underway — a concurrent second attempt
    must not also mint accounts) and the config record (setup finished). Users
    alone do not count here, so the pre-existing retry-after-failure contract
    holds: an attempt that died between creating accounts and persisting its
    config left the instance retryable, exactly as before (#334's loud-failure
    pattern). An unpersisted run has no durable marker to read, so any account
    at all is the only "setup happened" signal this process can see — and
    notably it is *not* the signal the register route consults; that inversion
    is what #313 fixes.
    """
    import stores

    if _get_kv() is not None:
        return _SETUP_KEY in stores.sessions or _SETUP_CLAIM_KEY in stores.sessions
    if _SETUP_KEY in stores.sessions or _SETUP_CLAIM_KEY in stores.sessions:
        return True
    return len(stores.users) > 0


@router.get("/status")
def setup_status() -> dict[str, Any]:
    """The unauthenticated bootstrap probe.

    Says two things only: whether setup still needs doing, and the active
    registration *mode* (so the login surface can stop offering a signup form
    the policy would refuse). The setup config itself — which carries the
    admin and daily-account usernames and the operator's DID — stopped being
    returned here with #313: it was account enumeration served to strangers,
    and nothing in the product read it from this route. The wizard gets its
    one-time copy from `/complete`'s response instead.
    """
    from services import registration_policy

    return {
        "setup_complete": _is_setup_complete(),
        "registration": registration_policy.public_view(),
    }


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


def _provision_first_run(
    body: dict[str, Any],
    *,
    hardware_preset: str,
    admin_username: str,
    admin_password: str,
    user_username: str,
    user_password: str,
) -> tuple[dict[str, Any], list[str] | None]:
    """The claimed work of first-run setup: accounts, settings, policy close-out.

    Runs only while this request holds the one-time setup claim, so nothing
    here has to defend against a concurrent provisioner — the claim already
    settled which attempt that is. Returns `(config, mnemonic_words)`; the
    mnemonic is None unless the crypto-identity module was requested.

    Kept as a function rather than inlined into `complete_setup` for a
    structural reason a reader cannot see from this file alone: the durable
    settings write below must stay caught only by the narrow handlers around
    it (#334 — a broad handler around it is the exact shape that used to
    report `setup_complete: true` while losing the operator's choice, and
    `test_settings_durability.py` pins that structurally).
    """
    import stores

    from maistro.security.passwords import hash_password

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

    # v0 fix: persist the Setup-chosen default_model so the Settings page
    # reflects what the user actually picked (was showing the hardcoded legacy
    # cerebras- alias regardless of Setup choice).
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

    # Was `stores.settings.default_model = ...` — an in-place mutation of a
    # module-level object, so the Setup wizard's choice never outlived the
    # process (#334). It goes through the durable record now.
    #
    # Deliberately NOT inside the old best-effort `except Exception`. That
    # handler was written for a settings *shape* mismatch, and wrapping a
    # durable write in it reproduced the exact defect this change exists to
    # remove: setup returning `setup_complete: true` while the operator's
    # model choice was silently lost at the next restart (Codex, #334). A
    # failure here means the install has no durable configuration, which is
    # not a state to report success from.
    from services import settings_store

    try:
        settings_store.save(
            settings_store.current().model_copy(update={"default_model": chosen_default_model})
        )
    except settings_store.SettingsPersistenceError as exc:
        logging.getLogger("hive.setup").error("setup could not persist settings: %s", exc)
        raise HTTPException(
            status_code=503,
            detail=f"setup did not complete: settings were not persisted ({exc})",
        ) from exc
    except settings_store.SettingsSecretError as exc:
        raise HTTPException(
            status_code=400,
            detail=(
                f"setup did not complete: field {exc.field!r} carries "
                f"{exc.credential_type} material; store the secret in the vault"
            ),
        ) from exc

    # #313: close registration durably, with the same acknowledgement rule
    # the admin route uses, BEFORE setup reports success. The default is
    # already closed, so a write lost to a crash fails toward closed; what
    # this records is the transition itself — an instance that finished
    # bootstrap holds a policy record saying who closed it and when.
    from services import registration_policy

    try:
        registration_policy.close_after_setup()
    except registration_policy.RegistrationPolicyError as exc:
        logging.getLogger("hive.setup").error(
            "setup could not persist the registration policy: %s", exc
        )
        raise HTTPException(
            status_code=503,
            detail=(
                "setup did not complete: the registration policy was not "
                "persisted, so registration state would not be durable"
            ),
        ) from exc

    kv = _get_kv()
    if kv is not None:
        kv[_SETUP_KEY] = config
    else:
        # Unpersisted run: the claim was only ever an in-flight lock —
        # "setup happened" in this mode is signalled by the accounts it
        # created, so releasing it here keeps complete ⟺ users-exist, the
        # contract the memory-mode fallback always had. A persisted run
        # keeps the claim forever: it is the durable one-shot marker.
        with _SETUP_LOCK:
            stores.sessions.pop(_SETUP_CLAIM_KEY, None)

    return config, config_mnemonic


@router.post("/complete")
def complete_setup(body: dict[str, Any]) -> dict[str, Any]:
    import stores

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

    # Claim first-run BEFORE any account exists (#313). The insert is
    # conflict-safe at the durable layer, so two concurrent first-user
    # attempts produce exactly one owner: the loser is refused here, before
    # it can write an admin credential over the winner's.
    with _SETUP_LOCK:
        claimed = stores.sessions.put_if_absent(
            _SETUP_CLAIM_KEY, {"claimed_at": datetime.now(UTC).isoformat()}
        )
        if not claimed:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Setup already complete. This endpoint is disabled after "
                    "first-run provisioning."
                ),
            )

    try:
        config, config_mnemonic = _provision_first_run(
            body,
            hardware_preset=hardware_preset,
            admin_username=admin_username,
            admin_password=admin_password,
            user_username=user_username,
            user_password=user_password,
        )
    except BaseException:
        # Release the claim so a failed first run stays retryable: the failure
        # modes inside (identity runtime missing, settings or policy not
        # persisted) are operator-fixable, and a claimed-but-abandoned instance
        # would lock bootstrap behind manual database surgery. The handler
        # re-raises everything it catches — it is a rollback, not a swallow.
        # The delete is enqueued, so a crash in the instant between failure
        # and flush can resurrect the claim — fail-closed (setup stays locked,
        # registration stays closed) rather than fail-open, which is the only
        # direction this endpoint is allowed to fail in.
        with _SETUP_LOCK:
            stores.sessions.pop(_SETUP_CLAIM_KEY, None)
        raise

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
