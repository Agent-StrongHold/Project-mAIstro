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


class TestBcryptIsOptionalAndItsAbsenceIsADenial:
    """bcrypt is `maistro-core[bcrypt]`, so its absence is a supported state.

    It was previously installed only because `hive-conductor` happened to pin
    it; `maistro-core` imports it and declared nothing, so any other consumer
    with a pre-Argon2id column was verifying against a module nothing had
    promised to install (#514). Making the ownership explicit also makes the
    absent case real, and `verify_password` caught only `(ValueError,
    TypeError)` — so a `ModuleNotFoundError` escaped the function and reached
    the login route as a 500 rather than a denial.

    A 500 on a *correct* password is not merely untidy: it is an oracle. The
    caller learns the stored hash is legacy, which a denial does not tell them.
    """

    _LEGACY = "$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq"

    def _without_bcrypt(self, monkeypatch):
        """Hide bcrypt from the import system, whatever is installed here."""
        import builtins

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "bcrypt":
                raise ModuleNotFoundError("No module named 'bcrypt'")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", blocked)
        monkeypatch.delitem(__import__("sys").modules, "bcrypt", raising=False)

    def test_a_correct_legacy_password_is_denied_rather_than_raising(self, monkeypatch) -> None:
        """The password is right, so this is the case that used to raise."""
        from maistro.security.passwords import verify_password

        self._without_bcrypt(monkeypatch)

        assert verify_password("testpass", self._LEGACY) is False

    def test_the_denial_says_which_extra_is_missing(self, monkeypatch, caplog) -> None:
        """Fail-closed and silent is indistinguishable, to the person locked
        out, from a wrong password. The log is the only place the difference
        can be recovered."""
        import logging

        from maistro.security.passwords import verify_password

        self._without_bcrypt(monkeypatch)
        with caplog.at_level(logging.ERROR, logger="maistro.security.passwords"):
            verify_password("testpass", self._LEGACY)

        assert "maistro-core[bcrypt]" in caplog.text

    def test_argon2_verification_is_unaffected(self, monkeypatch) -> None:
        """The control. bcrypt's absence must not touch the current algorithm,
        which is the one every non-legacy account uses."""
        from maistro.security.passwords import hash_password, verify_password

        stored = hash_password("correct horse battery")
        self._without_bcrypt(monkeypatch)

        assert verify_password("correct horse battery", stored) is True
        assert verify_password("wrong", stored) is False


class TestEveryDenialCostsTheSame:
    """#366's oracle, and the corner of it #514 reopened (#667).

    `equal_cost_verify` spends a decoy Argon2 verification when no account
    exists, so an unknown username cannot be told from a known one by response
    time. #514's `ImportError` guard returned *before* spending anything, so a
    third cost appeared: a legacy bcrypt row in a deployment without the extra
    denied in ~0 ms while both other paths cost ~88 ms. That points at exactly
    the accounts whose hashes have never been migrated.

    Asserted as "a verification was performed", not as elapsed time. Wall-clock
    on a shared CI runner is not a stable assertion, and the property that
    matters is the work done rather than any particular duration.
    """

    _LEGACY = "$2b$12$hmpbR.C6bkLEJ4d9PYzoqOthlZNKk.WOSjXnLxHpC0Y3S6sgdYfPq"

    def _count_decoy_spends(self, monkeypatch) -> list[int]:
        """Record each decoy verification, without paying for it."""
        import maistro.security.passwords as passwords

        spends: list[int] = []
        real = passwords._spend_decoy_verification

        def counted(plain: str) -> None:
            spends.append(1)
            real(plain)

        monkeypatch.setattr(passwords, "_spend_decoy_verification", counted)
        return spends

    def test_an_unknown_account_spends_a_verification(self, monkeypatch) -> None:
        """The control: the behaviour #366 established, still in place."""
        from maistro.security.passwords import equal_cost_verify

        spends = self._count_decoy_spends(monkeypatch)

        assert equal_cost_verify("anything", None) is False
        assert spends == [1]

    def test_a_legacy_hash_with_no_bcrypt_spends_one_too(self, monkeypatch) -> None:
        """The regression. Without this the denial is free, and free is a
        different answer from the two that cost."""
        import builtins

        import maistro.security.passwords as passwords

        real_import = builtins.__import__

        def blocked(name, *args, **kwargs):
            if name == "bcrypt":
                raise ModuleNotFoundError("No module named 'bcrypt'")
            return real_import(name, *args, **kwargs)

        spends = self._count_decoy_spends(monkeypatch)
        monkeypatch.setattr(builtins, "__import__", blocked)
        monkeypatch.delitem(__import__("sys").modules, "bcrypt", raising=False)

        assert passwords.equal_cost_verify("testpass", self._LEGACY) is False
        assert spends == [1]

    def test_a_verifiable_account_spends_no_decoy(self, monkeypatch) -> None:
        """The decoy is the substitute for real work, never an addition to it.
        Spending both would double the cost of every ordinary login."""
        from maistro.security.passwords import equal_cost_verify, hash_password

        stored = hash_password("correct horse battery")
        spends = self._count_decoy_spends(monkeypatch)

        assert equal_cost_verify("correct horse battery", stored) is True
        assert equal_cost_verify("wrong", stored) is False
        assert spends == []
