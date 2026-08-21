"""Identity lifecycle — DID creation, capability tokens, recovery, offboarding.

Implements ADR-084 / SPEC-070226-6489 on top of the existing did:key work in
``maistro.identity`` (ADR-021/ADR-024). Local agent identities use ``did:key``
derived from an Ed25519 keypair; agent authority is a signed, expiring
:class:`CapabilityToken` (a VC-shaped credential per ADR-024).

All vault interaction goes through the :class:`SecretStore` protocol so the
real age-encrypted vault (``maistro.vault``) can be adapted in by the caller;
tests use :class:`InMemorySecretStore`.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Literal, Protocol

# See maistro/identity/__init__.py: these ship in the `identity` extra.
try:
    from bip_utils import Base58Decoder, Base58Encoder, Bip39SeedGenerator
    from nacl.exceptions import BadSignatureError
    from nacl.signing import SigningKey, VerifyKey
except ModuleNotFoundError as exc:  # covered by tests/identity/test_extra_guard.py
    raise ImportError(
        f"maistro.identity.lifecycle requires the 'identity' extra (missing: {exc.name}). "
        "Install it with:  pip install 'maistro-core[identity]'"
    ) from exc

# Multicodec prefix for an Ed25519 public key (varint(0xed) = 0xed 0x01),
# matching maistro.identity.ConductorSeed.did_key().
_ED25519_MULTICODEC_PREFIX = b"\xed\x01"

Capability = Literal["delegate", "read", "write"]
_VALID_CAPABILITIES: frozenset[str] = frozenset({"delegate", "read", "write"})

#: Grace TTL (seconds) for tokens re-issued during recovery.
RECOVERY_GRACE_TTL_SECONDS = 86400


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class IdentityLifecycleError(Exception):
    """Base error for the identity lifecycle."""


class IdentityNotFoundError(IdentityLifecycleError):
    """No identity is stored for the given agent id."""


class IdentityAlreadyExistsError(IdentityLifecycleError):
    """An identity already exists for the given agent id."""


class IdentityArchivedError(IdentityLifecycleError):
    """The identity has been offboarded (soft-archived)."""


class InvalidRecoverySeedError(IdentityLifecycleError):
    """The supplied recovery seed does not match the stored seed."""


class CapabilityTokenError(IdentityLifecycleError):
    """Base error for capability-token verification failures."""


class InvalidTokenSignatureError(CapabilityTokenError):
    """The token signature does not verify against the issuer DID."""


class TokenExpiredError(CapabilityTokenError):
    """The token's ``exp`` timestamp is in the past."""


class TokenRevokedError(CapabilityTokenError):
    """The token has been revoked."""


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentIdentity:
    """A did:key agent identity (ADR-084 section 1).

    The private key is never stored here — only the encrypted recovery seed
    (an opaque blob produced by a :class:`SecretStore`).
    """

    agent_id: str
    did: str
    public_key: bytes
    created_at: datetime
    recovery_seed_encrypted: bytes
    offboarded_at: datetime | None = None

    @property
    def is_offboarded(self) -> bool:
        return self.offboarded_at is not None


@dataclass
class CapabilityToken:
    """JWT-like credential signed by the issuer's Ed25519 key (ADR-024/084).

    Signature covers the canonical form ``{iss}.{sub}.{cap}.{exp}``.
    """

    iss: str  # issuer DID (the delegating agent)
    sub: str  # subject (delegated agent or service)
    cap: Capability
    exp: int  # unix expiry timestamp
    signature: bytes = b""

    def canonical_form(self) -> bytes:
        return f"{self.iss}.{self.sub}.{self.cap}.{self.exp}".encode()


# ---------------------------------------------------------------------------
# Protocols + in-memory implementations
# ---------------------------------------------------------------------------


class SecretStore(Protocol):
    """Vault-like secret sealing. Adapt ``maistro.vault`` behind this."""

    def encrypt(self, plaintext: bytes) -> bytes: ...

    def decrypt(self, ciphertext: bytes) -> bytes: ...


class IdentityStore(Protocol):
    async def get(self, agent_id: str) -> AgentIdentity | None: ...

    async def save(self, identity: AgentIdentity) -> None: ...


class TokenStore(Protocol):
    async def save(self, token: CapabilityToken) -> None: ...

    async def get_by_issuer(self, issuer_did: str) -> list[CapabilityToken]: ...

    async def revoke(self, token: CapabilityToken) -> None: ...

    async def is_revoked(self, token: CapabilityToken) -> bool: ...


class InMemorySecretStore:
    """Fake vault: opaque handle -> plaintext map (tests / dev only)."""

    def __init__(self) -> None:
        self._blobs: dict[bytes, bytes] = {}

    def encrypt(self, plaintext: bytes) -> bytes:
        handle = os.urandom(16)
        self._blobs[handle] = bytes(plaintext)
        return handle

    def decrypt(self, ciphertext: bytes) -> bytes:
        try:
            return self._blobs[bytes(ciphertext)]
        except KeyError:
            raise IdentityLifecycleError("Unknown secret handle") from None


class InMemoryIdentityStore:
    def __init__(self) -> None:
        self._identities: dict[str, AgentIdentity] = {}

    async def get(self, agent_id: str) -> AgentIdentity | None:
        return self._identities.get(agent_id)

    async def save(self, identity: AgentIdentity) -> None:
        self._identities[identity.agent_id] = identity


def _token_key(token: CapabilityToken) -> bytes:
    return token.canonical_form() + b"." + token.signature


@dataclass
class _TokenRecord:
    token: CapabilityToken
    revoked: bool = field(default=False)


class InMemoryTokenStore:
    def __init__(self) -> None:
        self._records: dict[bytes, _TokenRecord] = {}

    async def save(self, token: CapabilityToken) -> None:
        self._records[_token_key(token)] = _TokenRecord(token=token)

    async def get_by_issuer(self, issuer_did: str) -> list[CapabilityToken]:
        return [
            r.token for r in self._records.values() if r.token.iss == issuer_did and not r.revoked
        ]

    async def revoke(self, token: CapabilityToken) -> None:
        record = self._records.get(_token_key(token))
        if record is not None:
            record.revoked = True

    async def is_revoked(self, token: CapabilityToken) -> bool:
        record = self._records.get(_token_key(token))
        # Unknown tokens are treated as revoked: only tokens this store issued
        # (and has not revoked) are live.
        return record is None or record.revoked


# ---------------------------------------------------------------------------
# did:key helpers
# ---------------------------------------------------------------------------


def did_key_from_public_key(public_key: bytes) -> str:
    """Encode a raw 32-byte Ed25519 public key as a did:key."""
    if len(public_key) != 32:
        raise ValueError("Ed25519 public key must be 32 bytes")
    encoded: str = Base58Encoder.Encode(_ED25519_MULTICODEC_PREFIX + public_key)
    return f"did:key:z{encoded}"


def public_key_from_did_key(did: str) -> bytes:
    """Decode a did:key back to the raw 32-byte Ed25519 public key."""
    prefix = "did:key:z"
    if not did.startswith(prefix):
        raise ValueError(f"Not a base58btc did:key: {did!r}")
    decoded: bytes = Base58Decoder.Decode(did[len(prefix) :])
    if decoded[:2] != _ED25519_MULTICODEC_PREFIX or len(decoded) != 34:
        raise ValueError(f"Not an Ed25519 did:key: {did!r}")
    return decoded[2:]


def normalize_recovery_seed(seed: bytes | str | list[str]) -> bytes:
    """Normalize a recovery seed to 32 raw bytes.

    Accepts raw 32-byte seeds, or a BIP39 mnemonic (string or word list) whose
    BIP39 seed's first 32 bytes are used as the Ed25519 seed.
    """
    if isinstance(seed, (list, str)):
        mnemonic = " ".join(seed) if isinstance(seed, list) else seed
        try:
            derived: bytes = Bip39SeedGenerator(mnemonic).Generate()
        except Exception as exc:
            raise InvalidRecoverySeedError(f"Invalid mnemonic: {exc}") from exc
        return derived[:32]
    if len(seed) != 32:
        raise InvalidRecoverySeedError("Raw recovery seed must be 32 bytes")
    return bytes(seed)


def _keypair_from_seed(seed: bytes) -> SigningKey:
    return SigningKey(seed)


def _now() -> datetime:
    return datetime.now(UTC)


# ---------------------------------------------------------------------------
# Lifecycle operations
# ---------------------------------------------------------------------------


async def create_agent_identity(
    agent_id: str,
    *,
    identity_store: IdentityStore,
    secret_store: SecretStore,
    seed: bytes | str | list[str] | None = None,
) -> AgentIdentity:
    """Bootstrap an agent with a did:key identity (deterministic from seed).

    A random 32-byte seed is generated when none is supplied. The seed is
    sealed via the :class:`SecretStore` for the recovery ladder (ADR-084 s3).
    """
    existing = await identity_store.get(agent_id)
    if existing is not None:
        raise IdentityAlreadyExistsError(f"Identity already exists for {agent_id!r}")

    raw_seed = os.urandom(32) if seed is None else normalize_recovery_seed(seed)
    signing_key = _keypair_from_seed(raw_seed)
    public_key = bytes(signing_key.verify_key)

    identity = AgentIdentity(
        agent_id=agent_id,
        did=did_key_from_public_key(public_key),
        public_key=public_key,
        created_at=_now(),
        recovery_seed_encrypted=secret_store.encrypt(raw_seed),
    )
    await identity_store.save(identity)
    return identity


def sign_token(signing_key: SigningKey, token: CapabilityToken) -> bytes:
    """Ed25519 signature over the token's canonical form."""
    return bytes(signing_key.sign(token.canonical_form()).signature)


async def issue_capability_token(
    agent_id: str,
    target_agent_id: str,
    capability: str,
    ttl_seconds: int = 3600,
    *,
    identity_store: IdentityStore,
    token_store: TokenStore,
    secret_store: SecretStore,
) -> CapabilityToken:
    """Issue a signed, expiring capability token from agent -> target."""
    if capability not in _VALID_CAPABILITIES:
        raise CapabilityTokenError(
            f"Unknown capability {capability!r}; expected one of {sorted(_VALID_CAPABILITIES)}"
        )
    cap: Capability = capability  # type: ignore[assignment]
    if ttl_seconds <= 0:
        raise CapabilityTokenError("ttl_seconds must be positive")

    identity = await identity_store.get(agent_id)
    if identity is None:
        raise IdentityNotFoundError(f"No identity for {agent_id!r}")
    if identity.is_offboarded:
        raise IdentityArchivedError(f"Agent {agent_id!r} is offboarded")

    signing_key = _keypair_from_seed(secret_store.decrypt(identity.recovery_seed_encrypted))
    token = CapabilityToken(
        iss=identity.did,
        sub=target_agent_id,
        cap=cap,
        exp=int(time.time()) + ttl_seconds,
    )
    token.signature = sign_token(signing_key, token)
    await token_store.save(token)
    return token


async def verify_capability_token(
    token: CapabilityToken,
    *,
    token_store: TokenStore | None = None,
    now: int | None = None,
) -> bool:
    """Verify signature, expiry, and (if a store is given) revocation.

    Raises a :class:`CapabilityTokenError` subclass on failure; returns True
    on success. Expiry is checked on every verification (ADR-084: an expired
    token grants nothing).
    """
    try:
        verify_key = VerifyKey(public_key_from_did_key(token.iss))
        verify_key.verify(token.canonical_form(), token.signature)
    except (BadSignatureError, ValueError) as exc:
        raise InvalidTokenSignatureError(str(exc)) from exc

    if (int(time.time()) if now is None else now) >= token.exp:
        raise TokenExpiredError(f"Token expired at {token.exp}")

    if token_store is not None and await token_store.is_revoked(token):
        raise TokenRevokedError("Token has been revoked")
    return True


async def recover_agent_identity(
    agent_id: str,
    recovery_seed: bytes | str | list[str],
    *,
    identity_store: IdentityStore,
    token_store: TokenStore,
    secret_store: SecretStore,
    grace_ttl_seconds: int = RECOVERY_GRACE_TTL_SECONDS,
) -> AgentIdentity:
    """Recover a lost agent key from its recovery seed (ADR-084 ladder).

    The correct seed deterministically regenerates the same keypair, so the
    DID is unchanged. Live tokens are revoked and re-issued with a grace TTL;
    a wrong seed raises :class:`InvalidRecoverySeedError`.
    """
    identity = await identity_store.get(agent_id)
    if identity is None:
        raise IdentityNotFoundError(f"No identity for {agent_id!r}")
    if identity.is_offboarded:
        raise IdentityArchivedError(f"Agent {agent_id!r} is offboarded")

    stored_seed = secret_store.decrypt(identity.recovery_seed_encrypted)
    if normalize_recovery_seed(recovery_seed) != stored_seed:
        raise InvalidRecoverySeedError("Recovery seed does not match")

    # Deterministic regeneration: same seed -> same keypair -> same DID.
    signing_key = _keypair_from_seed(stored_seed)
    if did_key_from_public_key(bytes(signing_key.verify_key)) != identity.did:
        raise IdentityLifecycleError("Recovered DID mismatch")  # pragma: no cover

    # Re-issue live tokens with a grace TTL; the old ones are revoked.
    old_tokens = await token_store.get_by_issuer(identity.did)
    for old in old_tokens:
        await token_store.revoke(old)
        await issue_capability_token(
            agent_id,
            old.sub,
            old.cap,
            ttl_seconds=grace_ttl_seconds,
            identity_store=identity_store,
            token_store=token_store,
            secret_store=secret_store,
        )
    return identity


async def offboard_agent(
    agent_id: str,
    *,
    identity_store: IdentityStore,
    token_store: TokenStore,
    emit: Callable[[str, str], None] | None = None,
) -> AgentIdentity:
    """Offboard an agent: revoke all its tokens and soft-archive the identity.

    The identity is archived (``offboarded_at`` set), never hard-deleted
    (ADR-084 s4). Emits ``identity.offboarded`` via the injected callable.
    """
    identity = await identity_store.get(agent_id)
    if identity is None:
        raise IdentityNotFoundError(f"No identity for {agent_id!r}")

    for token in await token_store.get_by_issuer(identity.did):
        await token_store.revoke(token)

    if not identity.is_offboarded:
        identity = replace(identity, offboarded_at=_now())
        await identity_store.save(identity)

    if emit is not None:
        emit("identity.offboarded", agent_id)
    return identity
