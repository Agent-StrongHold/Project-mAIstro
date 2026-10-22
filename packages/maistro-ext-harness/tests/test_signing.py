"""The signing helpers' failure faces (#975).

The certification suite drives `sign_payload`/`verify_payload` through happy
paths and tamper attacks; this file pins the arms those never reach: the
missing-backend outcome, malformed key material at each validation rung, the
key-generation helpers, and the digest of record.
"""

from __future__ import annotations

import sys

import pytest

from maistro_ext_harness.signing import (
    SigningUnavailable,
    _private_key_from_seed,
    _require_cryptography,
    generate_signing_key_hex,
    public_key_hex_from_seed,
    sha256_hex,
    sign_payload,
    verify_payload,
)


class TestBackendAvailability:
    def test_a_missing_cryptography_backend_names_the_extra_to_install(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An import of a shadowed-out module fails closed with the fix in
        the message — never a bare ImportError from cryptography's depths."""
        monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.asymmetric.ed25519", None)
        with pytest.raises(SigningUnavailable, match=r"maistro-ext-harness\[signing\]"):
            _require_cryptography()

    def test_verification_without_a_backend_is_not_a_failed_verification(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`verify_payload` re-raises SigningUnavailable: "cannot check" and
        "does not verify" are different answers with different actions."""
        monkeypatch.setitem(sys.modules, "cryptography.hazmat.primitives.asymmetric.ed25519", None)
        with pytest.raises(SigningUnavailable):
            verify_payload(b"payload", "00" * 64, "11" * 32)


class TestKeyMaterial:
    def test_generation_and_public_key_derivation_round_trip(self) -> None:
        seed = generate_signing_key_hex()
        assert len(seed) == 64
        public_hex = public_key_hex_from_seed(seed)
        assert len(public_hex) == 64
        # The same seed always derives the same publisher key.
        assert public_key_hex_from_seed(seed) == public_hex

    def test_a_seed_that_is_not_hex_is_rejected(self) -> None:
        with pytest.raises(SigningUnavailable, match="64 hex characters"):
            _private_key_from_seed("zz" * 32, object)  # type: ignore[arg-type]

    def test_a_seed_of_the_wrong_length_is_rejected(self) -> None:
        with pytest.raises(SigningUnavailable, match="exactly 32 bytes"):
            _private_key_from_seed("ab" * 31, object)  # type: ignore[arg-type]

    def test_unusable_key_material_fails_closed(self) -> None:
        class ExplodingKey:
            def __init__(self, seed: bytes) -> None:
                raise ValueError("not usable")

        with pytest.raises(SigningUnavailable, match="not usable"):
            _private_key_from_seed("ab" * 32, ExplodingKey)  # type: ignore[arg-type]

    def test_sign_payload_returns_the_publisher_key_and_signature(self) -> None:
        seed = generate_signing_key_hex()
        public_hex, signature_hex = sign_payload(b"payload", seed)
        assert public_hex == public_key_hex_from_seed(seed)
        assert verify_payload(b"payload", signature_hex, public_hex) is True

    def test_verify_payload_returns_false_for_malformed_material(self) -> None:
        seed = generate_signing_key_hex()
        public_hex, signature_hex = sign_payload(b"payload", seed)
        # A signature of the wrong byte shape is an answer (False), not a crash.
        assert verify_payload(b"payload", "not-hex", public_hex) is False
        assert verify_payload(b"payload", "00" * 64, public_hex) is False
        assert verify_payload(b"other payload", signature_hex, public_hex) is False


class TestDigestOfRecord:
    def test_sha256_hex_is_hex_sha256_over_exact_bytes(self) -> None:
        import hashlib

        assert sha256_hex(b"") == hashlib.sha256(b"").hexdigest()
        assert sha256_hex(b"maistro") == hashlib.sha256(b"maistro").hexdigest()
