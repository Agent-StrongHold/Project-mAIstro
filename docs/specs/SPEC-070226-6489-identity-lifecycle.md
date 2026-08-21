---
id: SPEC-070226-6489
title: "Identity lifecycle: DID method, agent authority tokens, recovery, offboarding"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-07-02
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-024
  - maistro-engine#ADR-084
  - maistro-engine#SPEC-003
implements:
  - maistro-engine#ADR-084
related:
  - maistro-engine#ADR-026
  - maistro-engine#ADR-059
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests:
  - packages/maistro-core/tests/identity/test_lifecycle.py
layer: Identity
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070226-6489: Identity lifecycle — DID method, agent authority tokens, recovery, offboarding

## Context

ADR-084 specifies identity lifecycle: onboarding (agent identity creation), authority token issuance
(CapabilityToken per ADR-024), recovery (if key is lost), and offboarding (revoke all tokens).

DID method is did:key (per ADR-021 baseline); agent authority tokens are JWT-like credentials
signed by the agent's DID. This SPEC wires the full lifecycle.

## Goals

- Agent identity creation via did:key on bootstrap.
- CapabilityToken issuance for agent→agent delegation (ADR-024).
- Key recovery if agent loses its private key (recovery ladder: seed phrase → new key → re-issue tokens).
- Offboarding: revoke all tokens, archive identity.

## Non-goals

- Multi-key rotation (Phase 2).
- Cross-tenant identity federation (Stronghold).

## Decision

Implemented in `packages/maistro-core/src/maistro/identity/lifecycle.py`, extending the
existing did:key work in `maistro/identity/__init__.py` (ConductorSeed, ADR-021). Ed25519 via
PyNaCl (`nacl.signing`, already a core dependency); did:key encoding (multicodec `0xed01` +
base58btc `z` multibase) is byte-compatible with `ConductorSeed.did_key()`.

All dependencies are injected explicitly (no module-level `identity_store`/`vault` globals),
per the core protocol-driven-DI convention:

- `SecretStore` protocol (`encrypt`/`decrypt`) — the vault boundary. The real age-encrypted
  vault (`maistro/vault.py`) is adapted behind this by the caller; `InMemorySecretStore` is the
  test/dev fake.
- `IdentityStore` protocol (`get`, `save`) + `InMemoryIdentityStore`.
- `TokenStore` protocol (`save`, `get_by_issuer(issuer_did)`, `revoke`, `is_revoked`) +
  `InMemoryTokenStore`. Tokens are keyed by issuer **DID** (not agent_id); lifecycle
  functions resolve agent_id → DID via the IdentityStore.

### Agent identity creation

```python
async def create_agent_identity(
    agent_id: str,
    *,
    identity_store: IdentityStore,
    secret_store: SecretStore,
    seed: bytes | str | list[str] | None = None,  # raw 32 bytes or BIP39 mnemonic
) -> AgentIdentity: ...
```

Generates a random 32-byte seed when none is given; a supplied seed (raw bytes or BIP39
mnemonic, normalized via `normalize_recovery_seed`) makes the keypair — and therefore the
DID — fully deterministic. The seed is sealed via the SecretStore and stored as
`recovery_seed_encrypted` on the frozen `AgentIdentity` dataclass
(`agent_id, did, public_key, created_at, recovery_seed_encrypted, offboarded_at`).
Duplicate agent ids raise `IdentityAlreadyExistsError`.

### CapabilityToken issuance

```python
@dataclass
class CapabilityToken:
    """JWT-like token signed by agent DID; grants authority to delegate to sub-agents."""
    iss: str  # issuer DID (the agent)
    sub: str  # subject (delegated agent or service)
    cap: Literal["delegate", "read", "write"]
    exp: int  # expiry timestamp
    signature: bytes  # Ed25519 signature over canonical form {iss}.{sub}.{cap}.{exp}

async def issue_capability_token(
    agent_id: str, target_agent_id: str, capability: str, ttl_seconds: int = 3600,
    *, identity_store: IdentityStore, token_store: TokenStore, secret_store: SecretStore,
) -> CapabilityToken: ...
```

The signing key is re-derived from the sealed seed at issue time (private keys are never
persisted). Issued tokens are saved to the TokenStore so revocation works. Issuing from an
offboarded identity raises `IdentityArchivedError`; unknown capabilities and non-positive
TTLs raise `CapabilityTokenError`.

Verification (`verify_capability_token(token, *, token_store=None, now=None)`) checks, in
order: Ed25519 signature against the public key recovered from the `iss` did:key
(`InvalidTokenSignatureError`), expiry on every use (`TokenExpiredError`), and — when a
TokenStore is provided — revocation (`TokenRevokedError`; tokens unknown to the store are
treated as revoked). Returns `True` on success, raises a typed `CapabilityTokenError`
subclass on failure.

### Key recovery (recovery ladder)

```python
async def recover_agent_identity(
    agent_id: str,
    recovery_seed: bytes | str | list[str],  # raw 32 bytes or BIP39 phrases
    *, identity_store: IdentityStore, token_store: TokenStore, secret_store: SecretStore,
    grace_ttl_seconds: int = 86400,
) -> AgentIdentity: ...
```

- The supplied seed is normalized and compared to the vault-sealed seed; mismatch raises
  `InvalidRecoverySeedError` (no partial information leaked).
- The correct seed deterministically regenerates the same keypair, so the DID is unchanged.
- Live tokens are **revoked** and re-issued with a 1-day grace TTL (the spec's original
  pseudocode only re-issued; the implementation also revokes the old ones so "old ones are
  now invalid" actually holds).
- Recovering an offboarded identity raises `IdentityArchivedError`.

### Offboarding (revocation)

```python
async def offboard_agent(
    agent_id: str, *, identity_store: IdentityStore, token_store: TokenStore,
    emit: Callable[[str, str], None] | None = None,
) -> AgentIdentity: ...
```

Revokes every live token issued by the agent's DID, soft-archives the identity by setting
`offboarded_at` (archive, never hard-delete — ADR-084 §4), and emits
`("identity.offboarded", agent_id)` via the injected `emit` callable (event-bus wiring is the
caller's concern). Idempotent: a second offboard keeps the original `offboarded_at`.

## Acceptance criteria

- [x] New agent gets a did:key identity with Ed25519 public key.
- [x] CapabilityToken issued by agent A to agent B can be verified (signature check).
- [x] Recovery with correct seed phrase regenerates the same DID (deterministic).
- [x] Recovery with wrong seed phrase raises InvalidRecoverySeedError (property: no guessing).
- [x] Offboarding revokes all issued tokens; agents can't use old tokens.
- [x] Token expiry is checked on every use (expired tokens rejected).

## Deviations from the original draft

- **Explicit DI instead of globals:** all functions take `identity_store` / `token_store` /
  `secret_store` keyword arguments (core convention); no ambient `vault` object — vault access
  is behind the `SecretStore` protocol with `InMemorySecretStore` for tests.
- **Seed forms:** recovery accepts raw 32-byte seeds *or* BIP39 mnemonics (string/word list,
  normalized through `bip_utils.Bip39SeedGenerator`, first 32 bytes as the Ed25519 seed).
- **Recovery revokes old tokens** before re-issuing with the grace TTL (draft only re-issued).
- **`get_by_issuer` takes the issuer DID**, not the agent_id; lifecycle functions resolve it.
- **Typed failures:** verification raises `InvalidTokenSignatureError` / `TokenExpiredError` /
  `TokenRevokedError` rather than returning a bare boolean failure.

## Testing

- Unit: identity creation (DID derivation), token signing/verification.
- Unit: recovery (seed → key regeneration determinism).
- Integration: agent issues token to sub-agent, sub-agent uses token, token accepted/rejected
  correctly.
- Offboarding: mark agent as offboarded, confirm old tokens are invalid.
- Property: "recovery from seed always produces the same DID and tokens" (use Hypothesis to
  generate seeds).

## References

- [ADR-084: Identity Lifecycle](../adr/ADR-084-identity-lifecycle.md)
- [ADR-024: Agent Identity & Verifiable Credentials](../adr/ADR-024-agent-identity-did-vc.md)
