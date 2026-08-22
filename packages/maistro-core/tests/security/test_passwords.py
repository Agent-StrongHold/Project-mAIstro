"""Password hashing — Argon2id and bcrypt legacy."""

from __future__ import annotations

from maistro.security.passwords import hash_password, needs_rehash, verify_password


def test_argon2_hash_and_verify() -> None:
    stored = hash_password("correct horse battery")
    assert stored.startswith("$argon2")
    assert verify_password("correct horse battery", stored)
    assert not verify_password("wrong", stored)


def test_bcrypt_legacy_still_verifies() -> None:
    legacy = "$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq"
    assert verify_password("testpass", legacy)
    assert needs_rehash(legacy)


def test_needs_rehash_for_argon2_is_false() -> None:
    stored = hash_password("fresh")
    assert not needs_rehash(stored)


def test_unrecognized_hash_format_does_not_verify() -> None:
    assert not verify_password("anything", "plaintext-not-a-hash")


def test_malformed_bcrypt_hash_returns_false() -> None:
    assert not verify_password("testpass", "$2b$not-a-valid-hash")


def test_needs_rehash_for_unrecognized_format_is_true() -> None:
    assert needs_rehash("plaintext-not-a-hash")


def test_needs_rehash_for_malformed_argon2_hash_is_true() -> None:
    assert needs_rehash("$argon2id$garbage")


def test_undecodable_argon2_hash_returns_false_rather_than_raising() -> None:
    """argon2 raises VerificationError ("Decoding failed"), not
    VerifyMismatchError, for a string that carries the prefix but is not a hash.
    Letting it escape turned a corrupt stored hash into a 500 from the login
    route instead of a denial."""
    assert not verify_password("testpass", "$argon2id$garbage")
    assert not verify_password("testpass", "$argon2id$v=19$m=65536,t=3,p=4$short")
