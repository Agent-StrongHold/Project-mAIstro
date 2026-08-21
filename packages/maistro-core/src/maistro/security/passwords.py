"""Password hashing — Argon2id (OWASP-preferred) with bcrypt legacy verification."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argon2 import PasswordHasher

_ARGON2_PREFIX = "$argon2"
_BCRYPT_PREFIX = "$2"


def _hasher() -> PasswordHasher:
    from argon2 import PasswordHasher

    # OWASP-aligned defaults for interactive login (64 MiB, 3 iterations).
    return PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        salt_len=16,
    )


def hash_password(plain: str) -> str:
    """Hash a password with Argon2id."""
    return str(_hasher().hash(plain))


def verify_password(plain: str, stored: str) -> bool:
    """Verify plain text against Argon2id or legacy bcrypt hash."""
    if stored.startswith(_ARGON2_PREFIX):
        from argon2.exceptions import InvalidHashError, VerifyMismatchError

        try:
            _hasher().verify(stored, plain)
            return True
        except (VerifyMismatchError, InvalidHashError):
            return False
    if stored.startswith(_BCRYPT_PREFIX):
        try:
            import bcrypt

            return bcrypt.checkpw(plain.encode(), stored.encode())
        except (ValueError, TypeError):
            return False
    return False


def needs_rehash(stored: str) -> bool:
    """True when the stored hash should be upgraded to current Argon2id parameters."""
    if not stored.startswith(_ARGON2_PREFIX):
        return True
    try:
        return bool(_hasher().check_needs_rehash(stored))
    except Exception:
        return True
