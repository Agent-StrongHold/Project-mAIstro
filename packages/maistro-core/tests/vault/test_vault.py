"""SPEC-011: Secrets Vault — age-encrypted file unlocked by admin keypair.

These tests define the contract that the vault implementation must satisfy.
All tests should FAIL until the vault module is implemented.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_vault_dir(tmp_path: Path) -> Path:
    vault_dir = tmp_path / "conductor"
    vault_dir.mkdir()
    return vault_dir


@pytest.fixture()
def age_keypair(tmp_vault_dir: Path) -> dict[str, str]:
    if not _has_age():
        pytest.skip("age not installed")

    result = subprocess.run(
        ["age-keygen"],
        capture_output=True,
        text=True,
        check=True,
    )
    secret_key = result.stdout.strip()
    public_key = secret_key.split("# public key: ")[1].split("\n")[0]

    key_file = tmp_vault_dir / "admin.key"
    key_file.write_text(secret_key)
    key_file.chmod(0o600)

    return {"secret_key": secret_key, "public_key": public_key, "key_file": str(key_file)}


def _has_age() -> bool:
    return shutil.which("age") is not None and shutil.which("age-keygen") is not None


age_required = pytest.mark.skipif(not _has_age(), reason="age not installed")


class TestVaultPublicKeyAPI:
    """AC: secrets.use(name, callback) is the ONLY public API."""

    def test_no_secret_access_methods_besides_use(self) -> None:
        from maistro.vault import Vault

        for forbidden in ("get", "get_secret", "read", "read_secret", "fetch"):
            assert not hasattr(Vault, forbidden), f"Vault must not have '{forbidden}' method"

    def test_no_get_method_on_vault(self) -> None:
        from maistro.vault import Vault

        assert not hasattr(Vault, "get")
        assert not hasattr(Vault, "get_secret")

    def test_use_calls_callback_with_secret_value(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        plaintext = "api_key_abc123\n"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input=plaintext,
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        result: str | None = None

        def capture(val: str) -> None:
            nonlocal result
            result = val

        vault.use("api_key_abc123", capture)
        assert result == "api_key_abc123"

    def test_use_returns_callback_result(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input="my_secret_value\n",
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        ret = vault.use("my_secret_value", lambda v: v.upper())
        assert ret == "MY_SECRET_VALUE"


class TestVaultEncryption:
    """AC: Vault file is encrypted to admin's public key."""

    @age_required
    def test_vault_file_is_age_encrypted(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        plaintext = "sk-test-key-12345\n"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input=plaintext,
            text=True,
            check=True,
        )

        raw = vault_file.read_bytes()
        assert raw.startswith(b"age-encryption.org/v1\n")

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        vault.use("sk-test-key-12345", lambda v: None)

    def test_vault_unavailable_raises_on_missing_key(self, tmp_vault_dir: Path) -> None:
        from maistro.vault import Vault, VaultUnavailableError

        vault_file = tmp_vault_dir / "secrets.age"
        vault_file.write_text("garbage")

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=str(tmp_vault_dir / "nonexistent.key"),
        )
        with pytest.raises(VaultUnavailableError, match="VAULT_UNAVAILABLE"):
            vault.use("any_key", lambda v: None)

    def test_vault_unavailable_raises_on_missing_file(self, tmp_vault_dir: Path) -> None:
        from maistro.vault import Vault, VaultUnavailableError

        vault = Vault(
            vault_path=str(tmp_vault_dir / "nonexistent.age"),
            identity_path=str(tmp_vault_dir / "nonexistent.key"),
        )
        with pytest.raises(VaultUnavailableError, match="VAULT_UNAVAILABLE"):
            vault.use("any_key", lambda v: None)


class TestVaultFailClosed:
    """AC: Conductor refuses to start with an empty or partial vault — fail-closed."""

    def test_missing_required_secret_raises(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import SecretMissingError, Vault

        vault_file = tmp_vault_dir / "secrets.age"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input="existing_secret\n",
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        with pytest.raises(SecretMissingError, match="SECRET_MISSING"):
            vault.use("nonexistent_secret_name", lambda v: None)


class TestVaultCredentialPrefixScanning:
    """AC: Bouncer pattern set is the first 8 bytes of SHA-256 of each credential."""

    def test_credential_prefix_derivation(self) -> None:
        import hashlib

        from maistro.vault import credential_prefix

        value = "sk-super-secret-api-key"
        expected = hashlib.sha256(value.encode()).digest()[:8]
        assert credential_prefix(value) == expected

    def test_prefix_is_deterministic(self) -> None:
        from maistro.vault import credential_prefix

        assert credential_prefix("same_value") == credential_prefix("same_value")

    def test_different_values_different_prefixes(self) -> None:
        from maistro.vault import credential_prefix

        assert credential_prefix("value_a") != credential_prefix("value_b")


class TestVaultAuditTrail:
    """AC: All vault mutations are admin-signed and recorded."""

    def test_add_secret_records_audit_entry(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input="initial_value\n",
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        vault.add("new_key", "new_value")
        entries = vault.audit_log()
        assert any(e["action"] == "add" and e["key"] == "new_key" for e in entries)

    def test_remove_secret_records_audit_entry(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input="to_remove\n",
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )
        vault.remove("to_remove")
        entries = vault.audit_log()
        assert any(e["action"] == "remove" for e in entries)


class TestVaultMutationPrefixRefresh:
    """AC: Bouncer pattern set regenerated within 100ms of any vault mutation."""

    def test_prefix_set_updates_after_add(
        self, tmp_vault_dir: Path, age_keypair: dict[str, str]
    ) -> None:
        import time

        from maistro.vault import Vault

        vault_file = tmp_vault_dir / "secrets.age"
        subprocess.run(
            ["age", "-r", age_keypair["public_key"], "-o", str(vault_file)],
            input="existing\n",
            text=True,
            check=True,
        )

        vault = Vault(
            vault_path=str(vault_file),
            identity_path=age_keypair["key_file"],
        )

        before = vault.credential_prefixes()
        t0 = time.monotonic()
        vault.add("new_one", "new_secret_value")
        elapsed_ms = (time.monotonic() - t0) * 1000

        after = vault.credential_prefixes()
        assert len(after) > len(before)
        assert elapsed_ms < 100
