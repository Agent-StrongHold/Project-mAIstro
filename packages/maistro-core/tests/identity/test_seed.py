"""Tests for maistro.identity — BIP39/BIP32 HD root of trust."""

from __future__ import annotations

import pytest

bip_utils = pytest.importorskip("bip_utils")
Base58Decoder = bip_utils.Base58Decoder

from maistro.identity import PATHS, ConductorSeed  # noqa: E402


def test_generate_24_words() -> None:
    seed = ConductorSeed.generate()
    words = seed.mnemonic_words()
    assert len(words) == 24
    assert all(isinstance(w, str) and len(w) > 0 for w in words)


def test_from_mnemonic_list() -> None:
    seed = ConductorSeed.generate()
    words = seed.mnemonic_words()
    restored = ConductorSeed.from_mnemonic(words)
    assert restored.mnemonic_words() == words


def test_from_mnemonic_string() -> None:
    seed = ConductorSeed.generate()
    mnemonic = " ".join(seed.mnemonic_words())
    restored = ConductorSeed.from_mnemonic(mnemonic)
    assert restored.mnemonic_words() == seed.mnemonic_words()


def test_deterministic_derivation() -> None:
    seed = ConductorSeed.generate()
    words = seed.mnemonic_words()
    seed2 = ConductorSeed.from_mnemonic(words)

    for name in PATHS:
        k1 = seed.derive_named(name)
        k2 = seed2.derive_named(name)
        assert k1.public_key == k2.public_key, f"{name} not deterministic"
        assert k1.path == k2.path


def test_sign_and_verify() -> None:
    seed = ConductorSeed.generate()
    msg = b"hello conductor"
    sig = seed.sign("m/0'", msg)
    assert isinstance(sig, bytes)
    assert len(sig) == 64
    assert seed.verify("m/0'", msg, sig) is True


def test_verify_wrong_message() -> None:
    seed = ConductorSeed.generate()
    sig = seed.sign("m/0'", b"correct")
    assert seed.verify("m/0'", b"wrong", sig) is False


def test_verify_wrong_path() -> None:
    seed = ConductorSeed.generate()
    sig = seed.sign("m/0'", b"message")
    assert seed.verify("m/44'/9000'/0'", b"message", sig) is False


def test_different_seeds_produce_different_keys() -> None:
    s1 = ConductorSeed.generate()
    s2 = ConductorSeed.generate()
    assert s1.public_key("m/0'") != s2.public_key("m/0'")


def test_did_key_format() -> None:
    seed = ConductorSeed.generate()
    did = seed.did_key()
    assert did.startswith("did:key:z")
    assert len(did) > 20


def test_did_key_deterministic() -> None:
    seed = ConductorSeed.generate()
    did1 = seed.did_key()
    did2 = seed.did_key()
    assert did1 == did2

    restored = ConductorSeed.from_mnemonic(seed.mnemonic_words())
    assert restored.did_key() == did1


def test_did_key_custom_path() -> None:
    seed = ConductorSeed.generate()
    did_identity = seed.did_key("m/44'/9000'/0'")
    did_signing = seed.did_key("m/0'")
    assert did_identity != did_signing


def test_did_key_spec_compliant_decoding() -> None:
    """did:key must be base58btc (z-prefix) of multicodec 0xed01 + 32-byte pubkey.

    Per the did:key spec / multiformats: Ed25519 public keys use the
    multicodec varint 0xed01 followed by the raw 32-byte key, multibase-
    encoded with base58btc whose prefix character is 'z'.
    """
    seed = ConductorSeed.generate()
    pub = seed.public_key("m/44'/9000'/0'")
    assert len(pub) == 32

    did = seed.did_key("m/44'/9000'/0'")
    assert did.startswith("did:key:z")

    # Strip the did:key: scheme; the 'z' is the base58btc multibase prefix.
    multibase = did[len("did:key:") :]
    assert multibase[0] == "z"
    decoded = Base58Decoder.Decode(multibase[1:])

    # multicodec prefix for Ed25519 public key is varint(0xed) = 0xed 0x01
    assert decoded[:2] == b"\xed\x01"
    # remaining bytes are exactly the raw public key
    assert decoded[2:] == pub
    assert len(decoded) == 34


def test_zero_clears_mnemonic_material() -> None:
    """zero() must actually destroy the secret, not just the derivation root."""
    seed = ConductorSeed.generate()
    seed.zero()

    # The 24-word master secret must no longer be retrievable.
    assert seed.mnemonic_words() == []


def test_zero_prevents_operations() -> None:
    seed = ConductorSeed.generate()
    seed.zero()
    with pytest.raises(RuntimeError, match="zeroed"):
        seed.sign("m/0'", b"test")
    with pytest.raises(RuntimeError, match="zeroed"):
        seed.derive("m/0'")
    with pytest.raises(RuntimeError, match="zeroed"):
        seed.public_key("m/0'")


def test_derive_named_unknown() -> None:
    seed = ConductorSeed.generate()
    with pytest.raises(ValueError, match="Unknown path name"):
        seed.derive_named("nonexistent")


# BIP-44 coin types Bitcoin (0') and Ethereum (60') use the secp256k1 curve;
# everything else in PATHS (Solana 501', identity, signing) uses Ed25519.
_SECP256K1_NAMES = {"bitcoin_cold", "bitcoin_hot", "evm_cold", "evm_hot"}


def test_all_named_paths_derive() -> None:
    seed = ConductorSeed.generate()
    for name in PATHS:
        key = seed.derive_named(name)
        if name in _SECP256K1_NAMES:
            assert key.curve == "secp256k1", f"{name} must derive on secp256k1"
            # SEC1 compressed public key: 0x02/0x03 parity prefix + 32-byte X.
            assert len(key.public_key) == 33
            assert key.public_key[0] in (0x02, 0x03)
        else:
            assert key.curve == "ed25519", f"{name} must derive on ed25519"
            assert len(key.public_key) == 32


def test_bitcoin_and_evm_use_secp256k1() -> None:
    """Wallet keys must derive on secp256k1, not Ed25519 (the bug this fixes)."""
    seed = ConductorSeed.generate()
    assert seed.derive_named("bitcoin_cold").curve == "secp256k1"
    assert seed.derive_named("evm_hot").curve == "secp256k1"
    # Solana is correctly Ed25519 and must stay that way.
    assert seed.derive_named("solana_cold").curve == "ed25519"


def test_sign_rejects_secp256k1_wallet_paths() -> None:
    """The Ed25519 identity-signing API must refuse secp256k1 wallet paths
    rather than silently producing a wrong-curve signature."""
    seed = ConductorSeed.generate()
    with pytest.raises(ValueError, match="secp256k1"):
        seed.sign("m/44'/0'/0'", b"msg")
    with pytest.raises(ValueError, match="secp256k1"):
        seed.verify("m/44'/60'/0'", b"msg", b"\x00" * 64)


# bip_utils accepts lowercase 'h' as an alternate hardened marker (it rejects
# uppercase 'H'); the curve classifier must agree with the deriver regardless of
# which accepted notation is used, or m/44h/0h/0h would re-introduce the
# wrong-curve bug and bypass the sign guard. (_curve_for_path also normalizes
# 'H' defensively, though bip_utils refuses it before derivation.)
@pytest.mark.parametrize(
    "btc_path",
    ["m/44h/0h/0h", "m/44'/0h/0'", "m/44h/60h/1h"],
)
def test_hardened_h_notation_classified_as_secp256k1(btc_path: str) -> None:
    seed = ConductorSeed.generate()
    key = seed.derive(btc_path)
    assert key.curve == "secp256k1", f"{btc_path} must derive on secp256k1"
    assert len(key.public_key) == 33
    # The sign guard must reject the h form too, not just the apostrophe form.
    with pytest.raises(ValueError, match="secp256k1"):
        seed.sign(btc_path, b"msg")


def test_h_and_apostrophe_notation_derive_identical_keys() -> None:
    seed = ConductorSeed.generate()
    assert seed.derive("m/44h/0h/0h").public_key == seed.derive("m/44'/0'/0'").public_key
