"""Cryptographically secure random utilities.

Thin wrappers around Python's `secrets` module. Ported from
TypeScript secure-random reference to replace any usage of `random`
in security-sensitive contexts.
"""

from __future__ import annotations

import secrets


def secure_id(n_bytes: int = 16) -> str:
    """Generate a hex-encoded random ID.

    Args:
        n_bytes: Number of random bytes (default 16 = 128 bits = 32 hex chars)
    """
    return secrets.token_hex(n_bytes)


def secure_urlsafe(n_bytes: int = 32) -> str:
    """Generate a URL-safe base64-encoded random token."""
    return secrets.token_urlsafe(n_bytes)


def secure_int(min_val: int, max_val: int) -> int:
    """Generate a cryptographically secure random integer in [min_val, max_val)."""
    return secrets.randbelow(max_val - min_val) + min_val


def secure_base36(length: int = 8) -> str:
    """Generate a base36 random string (lowercase alphanumeric)."""
    alphabet = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "".join(secrets.choice(alphabet) for _ in range(length))
