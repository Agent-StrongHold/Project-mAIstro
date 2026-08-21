"""SPEC-011: Secrets Vault — age-encrypted file unlocked by admin keypair.

The vault stores secrets in an age-encrypted file. Secrets are accessed
exclusively through ``use(name, callback)`` — the callback receives the
secret value and returns a result. The value is never exposed outside
the callback scope.

File format: one secret per line, either ``key = value`` or bare ``value``
(which is indexed as value -> value for single-secret vaults).
"""

from __future__ import annotations

import hashlib
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

_PUBLIC_KEY_PREFIX = "# public key: "


class VaultUnavailableError(Exception):
    """Raised when the vault cannot be opened (missing file, missing key, bad decrypt)."""


class SecretMissingError(Exception):
    """Raised when a requested secret name does not exist in the vault."""


def credential_prefix(value: str) -> bytes:
    """Return the first 8 bytes of SHA-256 of a credential value.

    Used by Bouncer to screen agent output for leaked secrets.
    """
    return hashlib.sha256(value.encode()).digest()[:8]


def _extract_public_key(identity_path: str | Path) -> str:
    for line in Path(identity_path).read_text().splitlines():
        if line.startswith(_PUBLIC_KEY_PREFIX):
            return line[len(_PUBLIC_KEY_PREFIX) :].strip()
    raise VaultUnavailableError("VAULT_UNAVAILABLE: no public key found in identity file")


def _parse_secrets(plaintext: str) -> dict[str, str]:
    secrets: dict[str, str] = {}
    for line in plaintext.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if " = " in line:
            k, v = line.split(" = ", 1)
            secrets[k.strip()] = v.strip()
        elif "=" in line:
            k, v = line.split("=", 1)
            secrets[k.strip()] = v.strip()
        else:
            secrets[line] = line
    return secrets


def _serialize_secrets(secrets: dict[str, str]) -> str:
    lines: list[str] = []
    for k, v in secrets.items():
        if k == v:
            lines.append(k)
        else:
            lines.append(f"{k} = {v}")
    return "\n".join(lines) + "\n" if lines else ""


def init_vault(vault_path: str | Path, identity_path: str | Path) -> bool:
    """Create the age identity key and an empty encrypted vault if absent.

    Idempotent first-run provisioning (SPEC-072726-3439 Phase 3): returns
    True when anything was created, False when both files already exist.
    Raises VaultUnavailableError when the age toolchain is missing — callers
    decide whether that is fatal (a vault the operator asked for) or a loud
    degradation (best-effort init on a host without age).
    """
    import shutil

    vault_p = Path(vault_path)
    ident_p = Path(identity_path)
    if vault_p.exists() and ident_p.exists():
        return False
    if shutil.which("age") is None or shutil.which("age-keygen") is None:
        raise VaultUnavailableError("VAULT_UNAVAILABLE: age/age-keygen not found on PATH")

    if not ident_p.exists():
        ident_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            # age-keygen creates the file 0600 and refuses to overwrite.
            subprocess.run(  # nosec — age trust root, args fully controlled (B603 + B607)
                ["age-keygen", "-o", str(ident_p)],
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise VaultUnavailableError(
                f"VAULT_UNAVAILABLE: age-keygen failed: {e.stderr.decode(errors='replace')}"
            ) from None

    if not vault_p.exists():
        public_key = _extract_public_key(ident_p)
        vault_p.parent.mkdir(parents=True, exist_ok=True)
        try:
            subprocess.run(  # nosec — age trust root, args fully controlled (B603 + B607)
                ["age", "-r", public_key, "-o", str(vault_p)],
                input=b"",
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise VaultUnavailableError(
                f"VAULT_UNAVAILABLE: vault encryption failed: {e.stderr.decode(errors='replace')}"
            ) from None
    return True


class Vault:
    """Age-encrypted secrets vault with ``use``-only access API."""

    def __init__(self, vault_path: str | Path, identity_path: str | Path) -> None:
        self._vault_path = Path(vault_path)
        self._identity_path = Path(identity_path)
        self._secrets: dict[str, str] | None = None
        self._audit: list[dict[str, Any]] = []

    def _ensure_loaded(self) -> dict[str, str]:
        if self._secrets is not None:
            return self._secrets

        if not self._vault_path.exists():
            raise VaultUnavailableError(
                f"VAULT_UNAVAILABLE: vault file not found: {self._vault_path}"
            )
        if not self._identity_path.exists():
            raise VaultUnavailableError(
                f"VAULT_UNAVAILABLE: identity key not found: {self._identity_path}"
            )

        try:
            # Invoking the `age` decryption CLI via $PATH is the explicit
            # trust contract: age is the cryptographic root for at-rest
            # secrets. Args are not user-controlled (-d, -i, identity_path),
            # stdin is the ciphertext we wrote ourselves.
            result = subprocess.run(  # nosec — age decryption trust root (B603 + B607)
                ["age", "-d", "-i", str(self._identity_path)],
                input=self._vault_path.read_bytes(),
                capture_output=True,
                check=True,
            )
        except FileNotFoundError:
            raise VaultUnavailableError("VAULT_UNAVAILABLE: age command not found") from None
        except subprocess.CalledProcessError as e:
            raise VaultUnavailableError(
                f"VAULT_UNAVAILABLE: decryption failed: {e.stderr.decode(errors='replace')}"
            ) from None

        self._secrets = _parse_secrets(result.stdout.decode())
        return self._secrets

    def use(self, name: str, callback: Callable[[str], T]) -> T:
        """Access a secret by name. The value is passed to ``callback`` and never returned directly."""
        secrets = self._ensure_loaded()
        if name not in secrets:
            raise SecretMissingError(f"SECRET_MISSING: {name}")
        return callback(secrets[name])

    def has(self, name: str) -> bool:
        """True if a secret exists — presence check without exposing the value."""
        return name in self._ensure_loaded()

    def add(self, key: str, value: str) -> None:
        secrets = self._ensure_loaded()
        secrets[key] = value
        self._audit.append({"action": "add", "key": key, "timestamp": time.time()})
        self._write()

    def remove(self, key: str) -> None:
        secrets = self._ensure_loaded()
        secrets.pop(key, None)
        self._audit.append({"action": "remove", "key": key, "timestamp": time.time()})
        self._write()

    def audit_log(self) -> list[dict[str, Any]]:
        self._ensure_loaded()
        return list(self._audit)

    def credential_prefixes(self) -> list[bytes]:
        secrets = self._ensure_loaded()
        return [credential_prefix(v) for v in secrets.values()]

    def _write(self) -> None:
        assert self._secrets is not None
        public_key = _extract_public_key(self._identity_path)
        plaintext = _serialize_secrets(self._secrets)
        try:
            # Same age-encryption trust contract as load() above.
            subprocess.run(  # nosec — age trust root, args fully controlled (B603 + B607)
                ["age", "-r", public_key, "-o", str(self._vault_path)],
                input=plaintext.encode(),
                capture_output=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(
                f"Failed to re-encrypt vault: {e.stderr.decode(errors='replace')}"
            ) from None
