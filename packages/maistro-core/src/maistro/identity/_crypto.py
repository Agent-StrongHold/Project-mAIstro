"""BIP39/BIP32 HD root of trust (ADR-021).

Loaded lazily from ``maistro.identity`` so ``Principal`` can import without the
``identity`` extra.
"""

from __future__ import annotations

from dataclasses import dataclass

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
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"

# ADR-021 fixed curve identifiers for BIP32/SLIP-0010 path routing (not runtime
# agility). Bitcoin/EVM BIP44 coin types use secp256k1; identity/signing use Ed25519.
CURVE_ED25519 = "ed25519"  # DevSkim: ignore DS440100 until 2027-12-31 -- ADR-021 Ed25519 paths
CURVE_SECP256K1 = "secp256k1"  # DevSkim: ignore DS440100 until 2027-12-31 -- BIP44 secp256k1

_SECP256K1_COIN_TYPES = {"0'", "60'"}


def _curve_for_path(path: str) -> str:
    normalized = path.replace("H", "'").replace("h", "'")
    parts = normalized.split("/")
    if (
        len(parts) >= 3
        and parts[0] == "m"
        and parts[1] == "44'"
        and parts[2] in _SECP256K1_COIN_TYPES
    ):
        return CURVE_SECP256K1
    return CURVE_ED25519


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
    curve: str = CURVE_ED25519


class ConductorSeed:
    def __init__(self, mnemonic: str) -> None:
        self._mnemonic: bytearray | None = bytearray(mnemonic.encode("utf-8"))
        seed_bytes = Bip39SeedGenerator(mnemonic).Generate()
        self._root: Bip32Slip10Ed25519 | None = Bip32Slip10Ed25519.FromSeed(seed_bytes)
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
        if _curve_for_path(path) == CURVE_SECP256K1:
            node = self._require_secp_root().DerivePath(path)
            pub = node.PublicKey().RawCompressed().ToBytes()
            return DerivedKey(path=path, public_key=pub, curve=CURVE_SECP256K1)
        node = self._require_root().DerivePath(path)
        pub = node.PublicKey().RawCompressed().ToBytes()
        return DerivedKey(path=path, public_key=pub[1:], curve=CURVE_ED25519)

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
        encoded = Base58Encoder.Encode(prefixed)
        return f"did:key:z{encoded}"

    def mnemonic_words(self) -> list[str]:
        if self._mnemonic is None:
            return []
        return self._mnemonic.decode("utf-8").split()

    def zero(self) -> None:
        if self._mnemonic is not None:
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
        if _curve_for_path(path) != CURVE_ED25519:
            raise ValueError(
                f"{op}() supports only Ed25519 identity/signing paths, "
                f"not the {CURVE_SECP256K1} wallet path {path!r}"
            )


PATHS = _PATHS
