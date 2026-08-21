"""Security: /v1/setup/complete must be a one-shot first-run operation.

The setup wizard endpoint is PUBLIC (middleware/auth.py _PUBLIC_PREFIXES
covers '/v1/setup/'). complete_setup() unconditionally overwrites
stores.users["admin"] / ["user"]. Without a guard, any unauthenticated
attacker can POST /v1/setup/complete on an already-provisioned instance and
take over the admin account (account takeover).

These tests pin the fix: once setup is complete, a second complete_setup()
must be rejected (HTTP 409) and must NOT mutate existing admin credentials.
"""

from __future__ import annotations

import pathlib
import sys

import pytest

_BACKEND = pathlib.Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def test_second_complete_setup_is_rejected_and_creds_unchanged() -> None:
    """A second /v1/setup/complete on a provisioned instance is rejected and
    leaves the existing admin password hash untouched."""
    import stores
    from fastapi import HTTPException
    from routes.setup import _is_setup_complete, complete_setup

    # conftest seeds an admin + user, so setup is already "complete".
    assert _is_setup_complete() is True
    original_admin_hash = stores.users["admin"].password_hash

    with pytest.raises(HTTPException) as exc_info:
        complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "attacker",
                "admin_password": "attacker-owns-you",
                "user_username": "attacker2",
                "user_password": "also-pwned",
            }
        )

    assert exc_info.value.status_code == 409
    # The admin credential must NOT have been overwritten.
    assert stores.users["admin"].password_hash == original_admin_hash
    assert stores.users["admin"].username != "attacker"


def test_first_run_setup_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    """First-run setup (no users yet) must still succeed and create accounts."""
    import stores
    from models.schemas import HiveUser
    from routes.setup import complete_setup
    from services.model_store import ModelStore

    # Simulate a fresh, un-provisioned instance: empty users store, no kv.
    fresh_users = ModelStore("users", HiveUser)
    monkeypatch.setattr(stores, "users", fresh_users)
    # Ensure the kv-based check also reports "not complete".
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)

    out = complete_setup(
        {
            "hardware_preset": "auto",
            "admin_username": "newadmin",
            "admin_password": "s3cret-admin",
            "user_username": "newuser",
            "user_password": "s3cret-user",
        }
    )

    assert out["setup_complete"] is True
    assert stores.users["admin"].username == "newadmin"
    assert stores.users["user"].username == "newuser"


def test_requested_identity_failure_aborts_before_creating_accounts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """crypto_identity requested + identity runtime missing must fail the whole
    request BEFORE any account exists. Completing setup without the mnemonic
    would lock the one-shot endpoint behind its 409 guard with no later
    identity-provisioning step (SPEC-072726-3439 Phase 0)."""
    import sys

    import stores
    from fastapi import HTTPException
    from models.schemas import HiveUser
    from routes.setup import complete_setup
    from services.model_store import ModelStore

    fresh_users = ModelStore("users", HiveUser)
    monkeypatch.setattr(stores, "users", fresh_users)
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)
    # A None entry in sys.modules makes `from maistro.identity import ...`
    # raise ImportError, simulating the missing [identity] extra.
    monkeypatch.setitem(sys.modules, "maistro.identity", None)

    with pytest.raises(HTTPException) as exc_info:
        complete_setup(
            {
                "hardware_preset": "auto",
                "admin_username": "newadmin",
                "admin_password": "s3cret-admin",
                "user_username": "newuser",
                "user_password": "s3cret-user",
                "optional_modules": ["crypto_identity"],
            }
        )

    assert exc_info.value.status_code == 503
    assert "crypto_identity" in exc_info.value.detail
    # Nothing was mutated — the operator can repair the dependency and retry.
    assert "admin" not in fresh_users
    assert "user" not in fresh_users


def test_first_run_provisions_vault_and_persists_seed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """SPEC-072726-3439 Phase 3: setup initializes the age vault and stores
    the seed mnemonic encrypted BEFORE zero() — the once-shown mnemonic is
    the recovery path, not the only copy."""
    import shutil

    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        pytest.skip("age not installed")
    # importorskip is not enough: maistro.identity imports without bip_utils
    # and raises ImportError lazily at generate() — probe the real call.
    try:
        from maistro.identity import ConductorSeed

        _probe = ConductorSeed.generate()
        _probe.zero()
    except ImportError:
        pytest.skip("identity extra (bip_utils/pynacl) not installed")

    import stores
    from models.schemas import HiveUser
    from routes.setup import complete_setup
    from services.model_store import ModelStore

    fresh_users = ModelStore("users", HiveUser)
    monkeypatch.setattr(stores, "users", fresh_users)
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)
    vault_file = tmp_path / "vault" / "secrets.age"
    key_file = tmp_path / "vault" / "admin.key"
    monkeypatch.setattr("routes.setup._vault_paths", lambda: (str(vault_file), str(key_file)))

    out = complete_setup(
        {
            "hardware_preset": "auto",
            "admin_username": "newadmin",
            "admin_password": "s3cret-admin",
            "user_username": "newuser",
            "user_password": "s3cret-user",
            "optional_modules": ["crypto_identity"],
        }
    )

    assert out["config"]["vault_initialized"] is True
    assert out["config"]["identity_persisted"] is True
    assert vault_file.exists() and key_file.exists()
    # The persisted mnemonic matches the one shown once in the response.
    from maistro.vault import Vault

    stored = Vault(vault_path=vault_file, identity_path=key_file).use(
        "CONDUCTOR_SEED_MNEMONIC", lambda s: s
    )
    assert stored == " ".join(out["mnemonic"])
