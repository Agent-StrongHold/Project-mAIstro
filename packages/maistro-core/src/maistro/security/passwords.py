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
        # VerificationError is the parent of VerifyMismatchError and is what
        # argon2 raises when the stored string carries the prefix but cannot be
        # decoded ("Decoding failed"). Catching only the mismatch let a corrupt
        # column escape as a 500 from the login route instead of a denial —
        # still fail-closed, but an error where a decision belonged.
        from argon2.exceptions import InvalidHashError, VerificationError

        try:
            _hasher().verify(stored, plain)
            return True
        except (VerificationError, InvalidHashError):
            return False
    if stored.startswith(_BCRYPT_PREFIX):
        try:
            import bcrypt

            return bcrypt.checkpw(plain.encode(), stored.encode())
        except (ValueError, TypeError):
            return False
    return False


#: A real Argon2id hash of a value nothing can supply, built once on first use.
#:
#: Lazily, not at import: hashing costs ~90 ms and 64 MiB, and paying that in
#: every process that merely imports this module — including every test
#: collection — would be a self-inflicted version of the problem this exists to
#: solve.
_DECOY_HASH: str | None = None


def _decoy_hash() -> str:
    global _DECOY_HASH
    if _DECOY_HASH is None:
        from secrets import token_urlsafe

        # A fresh random secret per process. Nobody, including this process,
        # can produce the input that verifies against it — so `equal_cost_verify`
        # against it always fails, and always costs what a real check costs.
        _DECOY_HASH = hash_password(token_urlsafe(32))
    return _DECOY_HASH


def equal_cost_verify(plain: str, stored: str | None) -> bool:
    """Verify `plain`, spending the same work whether or not the account exists.

    `login` used to read::

        if user.username == body.username and user.verify_password(...)

    and `and` short-circuits, so an unknown username never reached Argon2 at
    all. Measured on the machine this was written on: **87.6 ms for a known
    username with the wrong password, ~0 ms for an unknown one** — not a
    statistical side channel, a different order of magnitude readable from a
    single request (#366).

    Passing `stored=None` for "no such account" makes the caller spend one
    verification against a decoy instead. The answer is always `False`; the
    point is entirely what it cost to get there.

    This does not make the two paths *identical* — a dictionary lookup that
    misses still differs from one that hits by microseconds, and an attacker on
    the same host with a clean signal could still find that. It removes the
    difference that mattered, which was four orders of magnitude wide and
    measurable across a network.
    """
    if stored is None:
        verify_password(plain, _decoy_hash())
        return False
    return verify_password(plain, stored)


def needs_rehash(stored: str) -> bool:
    """True when the stored hash should be upgraded to current Argon2id parameters."""
    if not stored.startswith(_ARGON2_PREFIX):
        return True
    try:
        return bool(_hasher().check_needs_rehash(stored))
    except Exception:
        return True
