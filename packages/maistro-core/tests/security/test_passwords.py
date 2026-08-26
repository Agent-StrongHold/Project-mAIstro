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


class TestAnUnknownAccountCostsWhatAKnownOneCosts:
    """`login` used to read::

        if user.username == body.username and user.verify_password(...)

    and `and` short-circuits, so a username matching nothing never reached
    Argon2. Measured on the machine this was written on: **87.6 ms for a known
    username with the wrong password, ~0 ms for an unknown one** — four orders
    of magnitude, readable from a single request rather than from a sample
    (#366).
    """

    def test_a_missing_account_still_returns_false(self) -> None:
        from maistro.security.passwords import equal_cost_verify

        assert equal_cost_verify("anything", None) is False

    def test_a_wrong_password_returns_false(self) -> None:
        from maistro.security.passwords import equal_cost_verify, hash_password

        assert equal_cost_verify("wrong", hash_password("right")) is False

    def test_the_right_password_returns_true(self) -> None:
        from maistro.security.passwords import equal_cost_verify, hash_password

        assert equal_cost_verify("right", hash_password("right")) is True

    def test_a_missing_account_actually_runs_a_verification(self) -> None:
        """The property the whole fix rests on, asserted on the call rather
        than on a clock: timing assertions are flaky on shared CI, and what
        matters is that the work happens at all."""
        from unittest import mock

        from maistro.security import passwords

        with mock.patch.object(
            passwords, "verify_password", wraps=passwords.verify_password
        ) as spy:
            passwords.equal_cost_verify("anything", None)

        assert spy.call_count == 1

    def test_a_known_account_runs_exactly_one_verification_too(self) -> None:
        """Equal cost means equal, not merely non-zero. Two verifications on
        one path would be a side channel pointing the other way."""
        from unittest import mock

        from maistro.security import passwords

        stored = passwords.hash_password("right")
        with mock.patch.object(
            passwords, "verify_password", wraps=passwords.verify_password
        ) as spy:
            passwords.equal_cost_verify("wrong", stored)

        assert spy.call_count == 1

    def test_the_decoy_is_a_real_argon2_hash(self) -> None:
        """A cheap placeholder would reintroduce the gap it exists to close."""
        from maistro.security import passwords

        passwords.equal_cost_verify("x", None)

        assert passwords._DECOY_HASH is not None
        assert passwords._DECOY_HASH.startswith("$argon2")

    def test_the_decoy_is_built_once_not_per_call(self) -> None:
        """Hashing costs ~90 ms and 64 MiB. Doing it per request would make the
        mitigation a worse version of the attack."""
        from maistro.security import passwords

        passwords.equal_cost_verify("x", None)
        first = passwords._DECOY_HASH
        passwords.equal_cost_verify("y", None)

        assert passwords._DECOY_HASH is first

    def test_the_decoy_is_not_built_at_import(self) -> None:
        """Every process that merely imports this module — including every test
        collection — would otherwise pay 64 MiB and ~90 ms."""
        import importlib

        from maistro.security import passwords

        reloaded = importlib.reload(passwords)
        try:
            assert reloaded._DECOY_HASH is None
        finally:
            importlib.reload(passwords)

    def test_nothing_can_verify_against_the_decoy(self) -> None:
        """It is a hash of a fresh random secret, so `False` is the only answer
        it can give — which is what makes it safe to verify arbitrary input
        against."""
        from maistro.security import passwords

        passwords.equal_cost_verify("x", None)
        for guess in ["", "password", "x", passwords._DECOY_HASH or ""]:
            assert passwords.verify_password(guess, passwords._DECOY_HASH or "") is False
