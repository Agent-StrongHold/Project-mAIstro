"""Tests for the code registry's resolve/compatible/signature core (SPEC-257 / ADR-069)."""

from __future__ import annotations

import hashlib

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from maistro.code_registry.registry import CodeRegistry
from maistro.code_registry.types import CodeEntry, CodeKind, CodeRefUnresolved, InvalidSignature
from maistro.code_registry.verify import Ed25519Verifier


def _make_signed_entry(
    *, name: str = "my_compensator", version: str = "1.0.0", signer: Ed25519PrivateKey
) -> CodeEntry:
    code_sha256 = hashlib.sha256(b"body").hexdigest()
    payload = f"{name}@{version}:{code_sha256}".encode()
    signature = signer.sign(payload)
    return CodeEntry(
        name=name,
        version=version,
        kind=CodeKind.COMPENSATOR,
        code_sha256=code_sha256,
        signature=signature,
    )


class TestEd25519Verifier:
    def test_verifies_valid_signature(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw()
        verifier = Ed25519Verifier(public_key)
        message = b"hello"
        signature = private_key.sign(message)
        assert verifier.verify(message, signature) is True

    def test_rejects_tampered_message(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        public_key = private_key.public_key().public_bytes_raw()
        verifier = Ed25519Verifier(public_key)
        signature = private_key.sign(b"hello")
        assert verifier.verify(b"goodbye", signature) is False

    def test_rejects_wrong_key(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        other_key = Ed25519PrivateKey.generate()
        verifier = Ed25519Verifier(other_key.public_key().public_bytes_raw())
        signature = private_key.sign(b"hello")
        assert verifier.verify(b"hello", signature) is False


class TestRegisterAndResolve:
    def test_register_then_resolve_exact_match(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        verifier = Ed25519Verifier(private_key.public_key().public_bytes_raw())
        entry = _make_signed_entry(signer=private_key)

        registry = CodeRegistry()
        registry.register(entry, verifier=verifier)

        resolved = registry.resolve("my_compensator@1.0.0")
        assert resolved == entry

    def test_resolve_unversioned_ref_raises(self) -> None:
        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.resolve("my_compensator")

    def test_resolve_unknown_ref_raises(self) -> None:
        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.resolve("nonexistent@1.0.0")

    def test_register_rejects_invalid_signature(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        wrong_key = Ed25519PrivateKey.generate()
        verifier = Ed25519Verifier(wrong_key.public_key().public_bytes_raw())
        entry = _make_signed_entry(signer=private_key)

        registry = CodeRegistry()
        with pytest.raises(InvalidSignature):
            registry.register(entry, verifier=verifier)

        with pytest.raises(CodeRefUnresolved):
            registry.resolve("my_compensator@1.0.0")

    def test_register_rejects_unversioned_entry(self) -> None:
        private_key = Ed25519PrivateKey.generate()
        verifier = Ed25519Verifier(private_key.public_key().public_bytes_raw())
        entry = _make_signed_entry(version="", signer=private_key)

        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.register(entry, verifier=verifier)


class TestCompatible:
    def test_same_major_minor_bump_compatible(self) -> None:
        registry = CodeRegistry()
        assert registry.compatible("name@2.1.0", "name@2.9.0") is True

    def test_major_bump_incompatible(self) -> None:
        registry = CodeRegistry()
        assert registry.compatible("name@2.1.0", "name@3.0.0") is False

    def test_identical_version_compatible(self) -> None:
        registry = CodeRegistry()
        assert registry.compatible("name@1.0.0", "name@1.0.0") is True

    def test_malformed_base_ref_raises(self) -> None:
        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.compatible("name", "name@2.0.0")

    def test_malformed_overlay_ref_raises(self) -> None:
        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.compatible("name@2.0.0", "name")

    def test_non_semver_version_raises(self) -> None:
        registry = CodeRegistry()
        with pytest.raises(CodeRefUnresolved):
            registry.compatible("name@not-a-version", "name@2.0.0")
