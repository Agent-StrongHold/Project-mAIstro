"""Conductor identity — BIP39/BIP32 HD root of trust (ADR-021).

One 24-word mnemonic backs everything: agent signing, audit log,
DID identity, and future crypto wallet keys. Domain separation
via standard derivation paths.
"""

from __future__ import annotations

from dataclasses import dataclass

# Declared by the `identity` extra, not the base dependencies — bip-utils pulls
# coincurve, which has no wheel for the Python the API image ships. Raise loudly
# and name the fix rather than degrading silently to a partial identity module.
try:
    from bip_utils import (
        Base58Encoder,
        Bip32Slip10Ed25519,
        Bip32Slip10Secp256k1,
        Bip39MnemonicGenerator,
        Bip39SeedGenerator,
    )
    from nacl.signing import SigningKey, VerifyKey
except ModuleNotFoundError as exc:  # covered by tests/identity/test_extra_guard.py
    raise ImportError(
        f"maistro.identity requires the 'identity' extra (missing: {exc.name}). "
        "Install it with:  pip install 'maistro-core[identity]'"
    ) from exc

# Multicodec prefix for an Ed25519 public key: varint(0xed) = 0xed 0x01.
# Used by the did:key / multiformats spec; the leading multibase character
# 'z' on the encoded value denotes base58btc.
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"

# BIP-44 coin types that use the secp256k1 curve: Bitcoin (0') and Ethereum
# (60'). Their keys MUST derive on secp256k1 — an Ed25519-derived key cannot
# produce a valid BTC/ETH address or verify a secp256k1 signature. Every other
# path (Solana 501', identity, signing) stays on Ed25519.
_SECP256K1_COIN_TYPES = {"0'", "60'"}


def _curve_for_path(path: str) -> str:
    """Pick the curve for a derivation path. BIP-44 layout is
    ``m / purpose' / coin_type' / ...``; only the BTC/ETH coin types use
    secp256k1. ``m/0'`` (signing) has no coin_type segment, so it correctly
    stays Ed25519.

    bip_utils accepts both ``'`` and ``h``/``H`` for hardened nodes, so we
    normalize to ``'`` first — otherwise ``m/44h/0h/0h`` would be misclassified
    as Ed25519 while the deriver treats it as hardened Bitcoin (a parser
    differential that would re-introduce the wrong-curve bug and bypass the
    ``sign()`` guard)."""
    normalized = path.replace("H", "'").replace("h", "'")
    parts = normalized.split("/")
    if (
        len(parts) >= 3
        and parts[0] == "m"
        and parts[1] == "44'"
        and parts[2] in _SECP256K1_COIN_TYPES
    ):
        return "secp256k1"
    return "ed25519"


_PATHS = {
    "signing": "m/0'",
    "bitcoin_cold": "m/44'/0'/0'",
    "bitcoin_hot": "m/44'/0'/1'",
    "evm_cold": "m/44'/60'/0'",
    "evm_hot": "m/44'/60'/1'",
    "solana_cold": "m/44'/501'/0'",
    "identity": "m/44'/9000'/0'",
}


@dataclass(frozen=True)
class DerivedKey:
    path: str
    public_key: bytes
    curve: str = "ed25519"


class ConductorSeed:
    def __init__(self, mnemonic: str) -> None:
        # Hold the mnemonic in a mutable buffer so zero() can overwrite the
        # secret bytes in place rather than merely dropping a reference.
        self._mnemonic: bytearray | None = bytearray(mnemonic.encode("utf-8"))
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        self._root: Bip32Slip10Ed25519 | None = Bip32Slip10Ed25519.FromSeed(seed_bytes)
        # Separate secp256k1 root for the BTC/ETH wallet paths; both roots come
        # from the same BIP-39 seed, differing only by curve.
        self._secp_root: Bip32Slip10Secp256k1 | None = Bip32Slip10Secp256k1.FromSeed(seed_bytes)

    @staticmethod
    def generate() -> ConductorSeed:
        mnemonic = str(Bip39MnemonicGenerator().FromWordsNumber(24))
        return ConductorSeed(mnemonic)

    @staticmethod
    def from_mnemonic(words: list[str] | str) -> ConductorSeed:
        mnemonic = " ".join(words) if isinstance(words, list) else words
        Bip39SeedGenerator(mnemonic).Generate()
        return ConductorSeed(mnemonic)

    def derive(self, path: str) -> DerivedKey:
        if _curve_for_path(path) == "secp256k1":
            node = self._require_secp_root().DerivePath(path)
            # SEC1 compressed pubkey: 0x02/0x03 parity prefix + 32-byte X. Keep
            # the full 33 bytes — the prefix is required to recover the point /
            # derive a BTC/ETH address.
            pub = node.PublicKey().RawCompressed().ToBytes()
            return DerivedKey(path=path, public_key=pub, curve="secp256k1")
        node = self._require_root().DerivePath(path)
        # Ed25519 RawCompressed is a 33-byte value with a leading 0x00; strip it
        # to return the raw 32-byte Ed25519 public key.
        pub = node.PublicKey().RawCompressed().ToBytes()
        return DerivedKey(path=path, public_key=pub[1:], curve="ed25519")

    def derive_named(self, name: str) -> DerivedKey:
        path = _PATHS.get(name)
        if path is None:
            raise ValueError(f"Unknown path name: {name}")
        return self.derive(path)

    def sign(self, path: str, message: bytes) -> bytes:
        self._require_ed25519_path(path, "sign")
        priv = self._require_root().DerivePath(path).PrivateKey().Raw().ToBytes()
        return SigningKey(priv).sign(message).signature

    def verify(self, path: str, message: bytes, signature: bytes) -> bool:
        self._require_ed25519_path(path, "verify")
        pub = self.public_key(path)
        try:
            VerifyKey(pub).verify(message, signature)
            return True
        except Exception:
            return False

    def public_key(self, path: str) -> bytes:
        return self.derive(path).public_key

    def did_key(self, path: str = "m/44'/9000'/0'") -> str:
        pub = self.public_key(path)
        prefixed = _ED25519_MULTICODEC_PREFIX + pub
        # Multibase base58btc: the 'z' prefix denotes the base58btc alphabet.
        encoded = Base58Encoder.Encode(prefixed)
        return f"did:key:z{encoded}"

    def mnemonic_words(self) -> list[str]:
        if self._mnemonic is None:
            return []
        return self._mnemonic.decode("utf-8").split()

    def zero(self) -> None:
        if self._mnemonic is not None:
            # Overwrite the secret bytes in place before dropping the buffer.
            for i in range(len(self._mnemonic)):
                self._mnemonic[i] = 0
            self._mnemonic = None
        self._root = None
        self._secp_root = None

    def _require_root(self) -> Bip32Slip10Ed25519:
        if self._root is None:
            raise RuntimeError("Seed has been zeroed")
        return self._root

    def _require_secp_root(self) -> Bip32Slip10Secp256k1:
        if self._secp_root is None:
            raise RuntimeError("Seed has been zeroed")
        return self._secp_root

    @staticmethod
    def _require_ed25519_path(path: str, op: str) -> None:
        # The Ed25519 identity API does not do secp256k1 (ECDSA) signing;
        # refuse wallet paths instead of silently signing on the wrong curve.
        if _curve_for_path(path) != "ed25519":
            raise ValueError(
                f"{op}() supports only Ed25519 identity/signing paths, "
                f"not the secp256k1 wallet path {path!r}"
            )


PATHS = _PATHS

from maistro.identity.lifecycle import (  # noqa: E402
    AgentIdentity,
    CapabilityToken,
    CapabilityTokenError,
    IdentityAlreadyExistsError,
    IdentityArchivedError,
    IdentityLifecycleError,
    IdentityNotFoundError,
    IdentityStore,
    InMemoryIdentityStore,
    InMemorySecretStore,
    InMemoryTokenStore,
    InvalidRecoverySeedError,
    InvalidTokenSignatureError,
    SecretStore,
    TokenExpiredError,
    TokenRevokedError,
    TokenStore,
    create_agent_identity,
    did_key_from_public_key,
    issue_capability_token,
    offboard_agent,
    public_key_from_did_key,
    recover_agent_identity,
    verify_capability_token,
)

__all__ = [
    "PATHS",
    "AgentIdentity",
    "CapabilityToken",
    "CapabilityTokenError",
    "ConductorSeed",
    "DerivedKey",
    "IdentityAlreadyExistsError",
    "IdentityArchivedError",
    "IdentityLifecycleError",
    "IdentityNotFoundError",
    "IdentityStore",
    "InMemoryIdentityStore",
    "InMemorySecretStore",
    "InMemoryTokenStore",
    "InvalidRecoverySeedError",
    "InvalidTokenSignatureError",
    "SecretStore",
    "TokenExpiredError",
    "TokenRevokedError",
    "TokenStore",
    "create_agent_identity",
    "did_key_from_public_key",
    "issue_capability_token",
    "offboard_agent",
    "public_key_from_did_key",
    "recover_agent_identity",
    "verify_capability_token",
]
