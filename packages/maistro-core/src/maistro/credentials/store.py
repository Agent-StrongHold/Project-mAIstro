"""Per-user credential store — Fernet-encrypted JSON at rest.

# SECURITY-REVIEW: secrets encrypted with deployment master key file (0o600).
Values are never returned from list APIs; use ``use_secret`` for server-side tool access.

Master-key rotation (post-disclosure remediation, see
``docs/CREDENTIAL-ROTATION-RUNBOOK.md``) lives here too: ``rotate_master_key``
re-encrypts every stored secret under a fresh key, and
``repair_interrupted_rotation`` finishes a rotation that was killed mid-swap.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger("maistro.credentials")

T = TypeVar("T")

_MASTER_KEY_ENV = "HIVE_CREDENTIALS_MASTER_KEY"
_MASTER_KEY_DIR_ENV = "HIVE_CREDENTIALS_MASTER_KEY_DIR"
_MASTER_KEY_FILENAME = "credential_master.key"
_STORE_FILENAME = "user_credentials.enc"
# Staging names used by rotation. ``credential_master.key.new`` doubles as the
# recovery anchor: while it exists, it holds the key for whatever ciphertext is
# live at ``user_credentials.enc``.
_PENDING_MASTER_KEY_FILENAME = _MASTER_KEY_FILENAME + ".new"
_PENDING_STORE_FILENAME = _STORE_FILENAME + ".new"

#: Public aliases for operator tooling (``maistro security ...``).
MASTER_KEY_ENV_VAR = _MASTER_KEY_ENV
MASTER_KEY_DIR_ENV_VAR = _MASTER_KEY_DIR_ENV
MASTER_KEY_FILENAME = _MASTER_KEY_FILENAME
STORE_FILENAME = _STORE_FILENAME

_KEY_FILE_MODE = 0o600

# Persona/Workspace system, Phase F: a credential is scoped by
# (user_id, provider, workspace_id, connection_name), not just (user_id,
# provider) -- so one workspace can hold two connections to the same
# provider (e.g. two Jira accounts). The default scope maps onto the exact
# bare-provider bucket key used before this phase, so every pre-Phase-F
# on-disk record keeps resolving unchanged -- no migration needed.
DEFAULT_WORKSPACE_ID = "default"
DEFAULT_CONNECTION_NAME = "default"
_SCOPE_SEPARATOR = "::"


def _resolve_master_key_dir(data_dir: Path, explicit: Path | None) -> Path:
    """Directory the master-key file lives in.

    Precedence: explicit ``master_key_dir`` argument, then the
    ``HIVE_CREDENTIALS_MASTER_KEY_DIR`` env var, then ``data_dir`` (the
    original, unchanged default) so existing callers keep their exact
    current behavior.
    """
    if explicit is not None:
        return Path(explicit).expanduser()
    env_dir = os.getenv(_MASTER_KEY_DIR_ENV, "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return data_dir


def _bucket_key(provider: str, workspace_id: str, connection_name: str) -> str:
    if workspace_id == DEFAULT_WORKSPACE_ID and connection_name == DEFAULT_CONNECTION_NAME:
        return provider
    return f"{provider}{_SCOPE_SEPARATOR}{workspace_id}{_SCOPE_SEPARATOR}{connection_name}"


class CredentialStoreError(Exception):
    """Base error for credential storage."""


class CredentialStoreUnavailable(CredentialStoreError):
    """Store cannot be opened or decrypted."""


class CredentialNotFound(CredentialStoreError):
    """No secret stored for this user/provider."""


@dataclass(frozen=True)
class MasterKeyRotationResult:
    """What a completed ``rotate_master_key`` actually did."""

    users: int
    secrets: int
    key_path: Path
    store_path: Path
    env_var_active: bool


def generate_master_key() -> bytes:
    """Return a fresh Fernet master key suitable for ``rotate_master_key``."""
    return Fernet.generate_key()


def _fsync_dir(directory: Path) -> None:
    """Flush a directory entry so a rename is durable, not just visible."""
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:  # pragma: no cover — platforms without directory fds
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover — some filesystems reject dir fsync
        pass
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes, *, mode: int = _KEY_FILE_MODE) -> None:
    """Write ``data`` to ``path`` atomically.

    Temp file in the same directory (so ``os.replace`` stays within one
    filesystem), fsynced and chmodded before the rename. A reader either sees
    the whole previous file or the whole new one — never a truncated mix.
    """
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    _fsync_dir(path.parent)


def _key_reads_store(key_path: Path, store_path: Path) -> bool:
    """True if the key at ``key_path`` can decrypt the ciphertext at ``store_path``.

    A missing store file counts as readable (nothing to decrypt); a missing key
    file never does.
    """
    if not key_path.exists():
        return False
    if not store_path.exists():
        return True
    try:
        Fernet(key_path.read_bytes()).decrypt(store_path.read_bytes())
    except (InvalidToken, ValueError, TypeError, OSError):
        return False
    return True


def repair_interrupted_rotation(
    data_dir: str | Path, *, master_key_dir: str | Path | None = None
) -> bool:
    """Finish (or discard) a master-key rotation that was interrupted.

    Rotation swaps the ciphertext first and the key file second, with the new
    key already durable at ``credential_master.key.new``. This closes that
    window:

    * live key file still reads the live ciphertext → the rotation never
      reached the ciphertext swap; drop the staged files and keep the old key.
    * staged key reads the live ciphertext → the rotation was interrupted
      between the two renames; promote the staged key.
    * neither reads it → do not guess. Leave everything for the operator.

    ``master_key_dir`` defaults to ``data_dir``, preserving prior behavior for
    callers that keep the key alongside the store.

    Returns True only when a staged key was promoted.
    """
    path = Path(data_dir).expanduser()
    key_dir = Path(master_key_dir).expanduser() if master_key_dir is not None else path
    pending_key = key_dir / _PENDING_MASTER_KEY_FILENAME
    if not pending_key.exists():
        return False

    key_path = key_dir / _MASTER_KEY_FILENAME
    store_path = path / _STORE_FILENAME
    pending_store = path / _PENDING_STORE_FILENAME

    if _key_reads_store(key_path, store_path):
        pending_key.unlink(missing_ok=True)
        pending_store.unlink(missing_ok=True)
        return False

    if not _key_reads_store(pending_key, store_path):
        # stdlib logger — keyword args raise TypeError. Use % formatting.
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the data dir and three module-level FILENAME constants, never key material
        logger.error(
            "credential_rotation_unrecoverable dir=%s — neither %s nor %s decrypts %s",
            str(path),
            _MASTER_KEY_FILENAME,
            _PENDING_MASTER_KEY_FILENAME,
            _STORE_FILENAME,
        )
        return False

    os.replace(pending_key, key_path)
    _fsync_dir(key_dir)
    pending_store.unlink(missing_ok=True)
    # stdlib logger — keyword args raise TypeError. Use % formatting.
    # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the key FILE path, never the key material
    logger.warning("credential_rotation_repaired path=%s", str(key_path))
    return True


class UserCredentialStore:
    """Encrypts per-user integration secrets in a single file."""

    def __init__(
        self,
        data_dir: Path,
        *,
        master_key: bytes | None = None,
        master_key_dir: Path | None = None,
    ) -> None:
        self._data_dir = data_dir.expanduser()
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._master_key_dir = _resolve_master_key_dir(self._data_dir, master_key_dir)
        self._master_key_dir.mkdir(parents=True, exist_ok=True)
        self._master_key_path = self._master_key_dir / _MASTER_KEY_FILENAME
        self._store_path = self._data_dir / _STORE_FILENAME
        self._master_key = self._resolve_master_key(master_key)
        self._fernet = Fernet(self._master_key)
        self._cache: dict[str, dict[str, str]] | None = None

    def _resolve_master_key(self, explicit: bytes | None) -> bytes:
        if explicit is not None:
            return explicit
        env_key = os.getenv(_MASTER_KEY_ENV, "").strip()
        if env_key:
            return env_key.encode()
        if self._master_key_path.exists():
            return self._master_key_path.read_bytes()
        raise CredentialStoreUnavailable(
            f"Missing {_MASTER_KEY_FILENAME} under {self._data_dir} or {_MASTER_KEY_ENV}"
        )

    @classmethod
    def open(
        cls, data_dir: str | Path, *, master_key_dir: str | Path | None = None
    ) -> UserCredentialStore:
        """Open or create the encrypted store under ``data_dir``.

        ``master_key_dir`` (or the ``HIVE_CREDENTIALS_MASTER_KEY_DIR`` env var)
        optionally relocates just the master-key file to a directory separate
        from ``data_dir`` — e.g. a more restricted volume than the one holding
        the encrypted secrets themselves. Leaving it unset preserves the
        original behavior of keeping the key alongside the store.
        """
        path = Path(data_dir).expanduser()
        path.mkdir(parents=True, exist_ok=True)
        key_dir = _resolve_master_key_dir(
            path, Path(master_key_dir).expanduser() if master_key_dir is not None else None
        )
        key_dir.mkdir(parents=True, exist_ok=True)
        # Before deciding the key file is missing, settle any rotation that was
        # killed mid-swap — otherwise we would mint a third key over the top.
        repair_interrupted_rotation(path, master_key_dir=key_dir)
        key_path = key_dir / _MASTER_KEY_FILENAME
        if not key_path.exists():
            key = generate_master_key()
            _atomic_write_bytes(key_path, key)
            # stdlib logger — keyword args raise TypeError. Use % formatting.
            # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs the key FILE path, never the key material
            logger.info("credential_master_key_created path=%s", str(key_path))
        return cls(path, master_key=key_path.read_bytes(), master_key_dir=key_dir)

    def _load(self) -> dict[str, dict[str, str]]:
        if self._cache is not None:
            return self._cache
        if not self._store_path.exists():
            self._cache = {}
            return self._cache
        try:
            raw = self._fernet.decrypt(self._store_path.read_bytes())
            data = json.loads(raw.decode())
        except (InvalidToken, json.JSONDecodeError) as exc:
            raise CredentialStoreUnavailable("Failed to decrypt credential store") from exc
        if not isinstance(data, dict):
            raise CredentialStoreUnavailable("Invalid credential store format")
        self._cache = {str(uid): dict(vals) for uid, vals in data.items() if isinstance(vals, dict)}
        return self._cache

    def _persist(self) -> None:
        assert self._cache is not None
        payload = json.dumps(self._cache).encode()
        _atomic_write_bytes(self._store_path, self._fernet.encrypt(payload))

    def snapshot_counts(self) -> tuple[int, int]:
        """Return ``(users, secrets)`` currently stored. Never returns values."""
        data = self._load()
        return len(data), sum(len(bucket) for bucket in data.values())

    def rotate_master_key(self, new_key: bytes) -> MasterKeyRotationResult:
        """Re-encrypt every stored secret under ``new_key``.

        Crash-safety argument (the ordering below is load-bearing):

        1. Everything is decrypted under the *current* key first. If that fails
           the method raises and not one byte on disk has been touched.
        2. The re-encrypted ciphertext is staged at ``user_credentials.enc.new``
           and then re-read from disk and decrypted with the new key. A staged
           file that does not round-trip aborts the rotation with the live files
           still untouched.
        3. The new key is made durable at ``credential_master.key.new`` *before*
           any live file moves.
        4. The ciphertext is swapped (``os.replace``), then the key file.

        Between (4a) and (4b) the live key file and the live ciphertext
        disagree — but the key that reads the live ciphertext is durably on disk
        at ``credential_master.key.new``, so the state is recoverable, not lost.
        ``repair_interrupted_rotation`` (run automatically by
        :meth:`open`) completes or discards the swap idempotently. There is no
        interruption point at which the ciphertext is readable by neither key.
        """
        try:
            new_fernet = Fernet(new_key)
        except (ValueError, TypeError) as exc:
            raise ValueError("new_key is not a valid Fernet key") from exc
        if new_key == self._master_key:
            raise ValueError("new_key must differ from the current master key")

        data = self._load()
        payload = json.dumps(data).encode()

        pending_store = self._data_dir / _PENDING_STORE_FILENAME
        pending_key = self._master_key_dir / _PENDING_MASTER_KEY_FILENAME

        _atomic_write_bytes(pending_store, new_fernet.encrypt(payload))
        try:
            verified = json.loads(new_fernet.decrypt(pending_store.read_bytes()).decode())
        except (InvalidToken, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
            pending_store.unlink(missing_ok=True)
            raise CredentialStoreUnavailable(
                "Re-encrypted credential store failed verification — rotation aborted"
            ) from exc
        if verified != data:
            pending_store.unlink(missing_ok=True)
            raise CredentialStoreUnavailable(
                "Re-encrypted credential store failed verification — rotation aborted"
            )

        _atomic_write_bytes(pending_key, new_key)
        os.replace(pending_store, self._store_path)
        _fsync_dir(self._data_dir)
        os.replace(pending_key, self._master_key_path)
        _fsync_dir(self._master_key_dir)

        self._master_key = new_key
        self._fernet = new_fernet
        self._cache = data

        env_var_active = bool(os.getenv(_MASTER_KEY_ENV, "").strip())
        result = MasterKeyRotationResult(
            users=len(data),
            secrets=sum(len(bucket) for bucket in data.values()),
            key_path=self._master_key_path,
            store_path=self._store_path,
            env_var_active=env_var_active,
        )
        # stdlib logger — keyword args raise TypeError. Use % formatting.
        # nosemgrep: python.lang.security.audit.logging.logger-credential-leak.python-logger-credential-disclosure -- logs counts and the key FILE path, never the key material
        logger.warning(
            "credential_master_key_rotated path=%s users=%d secrets=%d env_override=%s",
            str(self._master_key_path),
            result.users,
            result.secrets,
            env_var_active,
        )
        return result

    def list_providers_for_user(
        self,
        user_id: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        connection_name: str = DEFAULT_CONNECTION_NAME,
    ) -> dict[str, dict[str, Any]]:
        """Return metadata only — never secret values — for one (workspace, connection) scope."""
        data = self._load()
        user_secrets = data.get(user_id, {})
        if workspace_id == DEFAULT_WORKSPACE_ID and connection_name == DEFAULT_CONNECTION_NAME:
            providers = [key for key in user_secrets if _SCOPE_SEPARATOR not in key]
        else:
            suffix = f"{_SCOPE_SEPARATOR}{workspace_id}{_SCOPE_SEPARATOR}{connection_name}"
            providers = [key[: -len(suffix)] for key in user_secrets if key.endswith(suffix)]
        return {
            provider: {
                "configured": True,
                "updated_at": datetime.now(UTC).isoformat(),
            }
            for provider in providers
        }

    def set_secret(
        self,
        user_id: str,
        provider: str,
        secret: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        connection_name: str = DEFAULT_CONNECTION_NAME,
    ) -> None:
        secret = secret.strip()
        if not secret:
            raise ValueError("Secret cannot be empty")
        data = self._load()
        bucket = data.setdefault(user_id, {})
        bucket[_bucket_key(provider, workspace_id, connection_name)] = secret
        self._persist()

    def delete_secret(
        self,
        user_id: str,
        provider: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        connection_name: str = DEFAULT_CONNECTION_NAME,
    ) -> bool:
        data = self._load()
        bucket = data.get(user_id, {})
        key = _bucket_key(provider, workspace_id, connection_name)
        if key not in bucket:
            return False
        del bucket[key]
        if not bucket:
            data.pop(user_id, None)
        self._persist()
        return True

    def has_secret(
        self,
        user_id: str,
        provider: str,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        connection_name: str = DEFAULT_CONNECTION_NAME,
    ) -> bool:
        data = self._load()
        return _bucket_key(provider, workspace_id, connection_name) in data.get(user_id, {})

    def use_secret(
        self,
        user_id: str,
        provider: str,
        callback: Callable[[str], T],
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        connection_name: str = DEFAULT_CONNECTION_NAME,
    ) -> T:
        """Pass decrypted secret to callback; never return it from this method."""
        data = self._load()
        bucket = data.get(user_id, {})
        key = _bucket_key(provider, workspace_id, connection_name)
        if key not in bucket:
            raise CredentialNotFound(f"No credential for provider {provider!r}")
        return callback(bucket[key])
