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


@pytest.mark.parametrize("password", ["", "short", "1234567"])
def test_public_setup_api_rejects_weak_admin_password_before_claim(
    monkeypatch: pytest.MonkeyPatch, password: str
) -> None:
    """The HTTP boundary must enforce the canonical policy, not just the UI."""
    import stores
    from fastapi.testclient import TestClient
    from main import app
    from models.schemas import HiveUser
    from services.model_store import ModelStore

    fresh_users = ModelStore("users", HiveUser)
    monkeypatch.setattr(stores, "users", fresh_users)
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)

    response = TestClient(app).post(
        "/v1/setup/complete",
        json={
            "hardware_preset": "auto",
            "admin_username": "newadmin",
            "admin_password": password,
            "user_username": "newuser",
            "user_password": "s3cret-user",
        },
    )

    assert response.status_code == 422
    assert "Password must be at least 8 characters." in response.text
    assert "__hive_setup_claim__" not in stores.sessions
    assert len(fresh_users) == 0


def test_setup_body_validates_boundary_and_unicode_passwords() -> None:
    """The shared length policy counts supplied Unicode characters as-is."""
    from routes.setup import SetupCompleteBody

    for password in ("12345678", "密码密码密码密码", "éééé"):
        body = SetupCompleteBody.model_validate(
            {
                "hardware_preset": "auto",
                "admin_password": password,
                "user_password": "s3cret-user",
            }
        )
        assert body.admin_password == password


def test_public_setup_api_reports_typed_validation_errors_without_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed requests fail Pydantic validation before provisioning starts."""
    import stores
    from fastapi.testclient import TestClient
    from main import app
    from models.schemas import HiveUser
    from services.model_store import ModelStore

    fresh_users = ModelStore("users", HiveUser)
    monkeypatch.setattr(stores, "users", fresh_users)
    monkeypatch.setattr("routes.setup._get_kv", lambda: None)

    response = TestClient(app).post(
        "/v1/setup/complete",
        json={
            "hardware_preset": "auto",
            "user_password": "s3cret-user",
        },
    )

    assert response.status_code == 422
    assert any(error["loc"][-1] == "admin_password" for error in response.json()["detail"])
    assert len(fresh_users) == 0
    assert "__hive_setup_claim__" not in stores.sessions


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


def test_empty_hardware_preset_is_rejected() -> None:
    from pydantic import ValidationError
    from routes.setup import SetupCompleteBody

    with pytest.raises(ValidationError) as exc_info:
        SetupCompleteBody.model_validate(
            {
                "hardware_preset": "",
                "admin_password": "s3cret-admin",
                "user_password": "s3cret-user",
            }
        )

    assert any(
        error["loc"] == ("hardware_preset",)
        and error["msg"] == "Value error, hardware_preset required"
        for error in exc_info.value.errors()
    )


def test_direct_setup_validation_rejects_weak_password_with_422() -> None:
    from fastapi import HTTPException
    from routes.setup import SetupCompleteBody, complete_setup

    with pytest.raises(HTTPException) as exc_info:
        complete_setup(
            {
                "hardware_preset": "auto",
                "admin_password": "1234567",
                "user_password": "s3cret-user",
            }
        )

    assert exc_info.value.status_code == 422
    assert "Password must be at least 8 characters." in str(exc_info.value.detail)

    # A model instance is the FastAPI path: it skips the dict compatibility
    # branch and reaches the normal one-shot guard.
    with pytest.raises(HTTPException) as model_exc_info:
        complete_setup(
            SetupCompleteBody(
                hardware_preset="auto",
                admin_password="s3cret-admin",
                user_password="s3cret-user",
            )
        )
    assert model_exc_info.value.status_code == 409


def test_get_preset_returns_named_hardware_preset() -> None:
    from routes.setup import get_preset

    result = get_preset("laptop")

    assert result["kind"] == "hardware_preset"
    assert result["name"] == "laptop"


def test_resolve_preset_auto_returns_resolved_config() -> None:
    from routes.setup import resolve_preset_auto

    result = resolve_preset_auto({"name": "auto", "total_memory_gb": 4})

    assert result["kind"] == "resolved_preset"
    assert result["preset"] == "laptop"
    assert result["config"]["hardware_preset"] == "laptop"


def test_persist_identity_root_stores_seed_before_returning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sys
    import types

    from routes import setup as setup_routes

    calls: dict[str, object] = {}

    def init_vault(vault_path: str, identity_path: str) -> None:
        calls["init_vault"] = (vault_path, identity_path)

    class FakeVault:
        def __init__(self, *, vault_path: str, identity_path: str) -> None:
            calls["paths"] = (vault_path, identity_path)

        def add(self, key: str, value: str) -> None:
            calls["added"] = (key, value)

    vault_module = types.ModuleType("maistro.vault")
    vault_module.__dict__.update(Vault=FakeVault, init_vault=init_vault)
    monkeypatch.setitem(sys.modules, "maistro.vault", vault_module)

    result = setup_routes._persist_identity_root(["alpha", "beta"])

    assert result is True
    assert calls["added"] == ("CONDUCTOR_SEED_MNEMONIC", "alpha beta")
