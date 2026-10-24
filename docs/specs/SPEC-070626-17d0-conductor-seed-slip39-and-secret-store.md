---
id: SPEC-070626-17d0
title: "ConductorSeed gaps: SLIP-39 recovery sharding and pluggable encrypted-at-rest storage"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-07-06
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#SPEC-011
implements:
  - maistro-engine#ADR-021
related:
  - maistro-engine#SPEC-070226-6489
  - maistro-engine#ADR-026
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-070626-17d0: ConductorSeed gaps — SLIP-39 recovery sharding and pluggable encrypted storage

## Context

`ConductorSeed` (`maistro/identity/__init__.py`, ADR-021) implements the HD root of trust:
BIP39 24-word mnemonic generation, BIP32/SLIP-0010 derivation across Ed25519 and secp256k1,
domain-separated paths, did:key export, and in-place zeroing. Two gaps remain against the
ADR:

1. **No recovery sharding.** The only recovery mechanism is the single 24-word mnemonic — a
   single point of loss (destroyed) or theft (stolen and used). ADR-021 names Shamir sharding
   as the intended recovery-card mechanism.
2. **No at-rest persistence.** `ConductorSeed` holds its mnemonic in memory only; every
   process restart requires re-entering it. What actually needs persisting is not the mnemonic
   itself (only needed at generation/recovery time) but the *encrypted seed material*, so a
   session can resume without re-prompting.

## Goals

- SLIP-39 Shamir secret sharing: split a `ConductorSeed`'s entropy into `member_threshold`-of-
  `member_count` shares (default 3-of-5); recombine from any threshold-sized subset of shares
  to reconstruct the identical seed.
- A pluggable `SecretStore` protocol for encrypted-seed-at-rest, decoupled from `ConductorSeed`
  itself — vault.py (age-encrypted) is the default implementation; OS keychain or other
  backends can implement the same protocol later without touching `ConductorSeed`.
- Migration path: an existing single-mnemonic seed can be re-sharded into SLIP-39 shares
  without changing the derived keys (same entropy in, same DID/keys out).

## Non-goals

- OS-keychain / Vaultwarden backend implementations — only the protocol + vault.py default
  ship here; other backends are follow-up work behind the same interface.
- Recovery-card physical/printable format (paper wallet layout, QR encoding) — that's a
  hive-conductor UI concern, out of scope for maistro-core.
- Changing `ConductorSeed`'s existing derivation paths, curve selection, or did:key encoding
  — all unchanged.

## Decision

### SLIP-39 sharding

```python
# maistro/identity/slip39.py

@dataclass(frozen=True)
class Slip39Shares:
    """member_threshold-of-member_count shares of a ConductorSeed's entropy."""
    shares: tuple[str, ...]          # each share is a SLIP-39 mnemonic (word list, joined)
    member_threshold: int
    member_count: int

def split_seed(
    seed: ConductorSeed, *, member_threshold: int = 3, member_count: int = 5
) -> Slip39Shares:
    """Split the seed's underlying entropy into SLIP-39 shares. Does not
    consume or mutate the seed."""
    ...

def combine_shares(shares: Sequence[str]) -> ConductorSeed:
    """Reconstruct a ConductorSeed from >= member_threshold shares.
    Raises InsufficientSharesError if too few distinct shares are given,
    or Slip39ChecksumError if a share is malformed/corrupted."""
    ...
```

- Implemented via the `shamir-mnemonic` / `slip39` reference algorithm (pure-Python; no new
  heavy dependency — a small, auditable implementation, since `bip_utils` does not include
  SLIP-39).
- `split_seed` is deterministic given the same seed entropy and group config only in the sense
  that it reconstructs to the same seed; the shares themselves use fresh randomness for the
  polynomial coefficients each call (repeated splits of the same seed produce different, all
  equally valid, share sets — this is intentional and matches the SLIP-39 spec).
- `combine_shares` with fewer than `member_threshold` shares raises `InsufficientSharesError`
  (fails closed — never returns a partial/guessed seed).

### Pluggable SecretStore for encrypted seed persistence

Reuses the `SecretStore` protocol shape already established in
`maistro/identity/lifecycle.py` (SPEC-070226-6489) rather than inventing a second one:

```python
# maistro/identity/lifecycle.py (existing)
class SecretStore(Protocol):
    def encrypt(self, plaintext: bytes) -> bytes: ...
    def decrypt(self, ciphertext: bytes) -> bytes: ...
```

New in this SPEC — a vault.py-backed default implementation and the seed-persistence helpers:

```python
# maistro/identity/seed_store.py

class VaultSecretStore(SecretStore):
    """SecretStore backed by maistro/vault.py (age-encrypted at rest)."""
    def __init__(self, vault: Vault, key_name: str = "conductor_seed") -> None: ...

async def persist_seed(seed: ConductorSeed, *, secret_store: SecretStore) -> None:
    """Seal seed.mnemonic_words() via secret_store and write it under a
    well-known vault key. Does not affect in-memory ConductorSeed state."""

async def load_seed(*, secret_store: SecretStore) -> ConductorSeed:
    """Read and unseal the persisted seed, reconstructing a ConductorSeed.
    Raises SeedNotFoundError if nothing has been persisted."""
```

`InMemorySecretStore` (already defined in `lifecycle.py`) is reused as-is for tests — no
duplicate fake needed.

## Acceptance criteria

- [ ] `split_seed(seed, member_threshold=3, member_count=5)` produces 5 shares; combining any
      3 distinct shares reconstructs a `ConductorSeed` whose `derive_named("signing")` produces
      the identical keypair as the original (property test over random seeds).
- [ ] Combining fewer than `member_threshold` shares raises `InsufficientSharesError`, never a
      seed (property: no partial reconstruction is ever possible).
- [ ] A corrupted/tampered share raises `Slip39ChecksumError` on combine, not a silently wrong
      seed.
- [ ] `persist_seed` followed by `load_seed` against the same `SecretStore` instance
      reconstructs an identical `ConductorSeed` (round-trip test, `InMemorySecretStore` and
      `VaultSecretStore` both covered).
- [ ] `VaultSecretStore` never writes plaintext mnemonic words anywhere (asserted by inspecting
      the underlying vault file/subprocess call in the test).
- [ ] Existing `ConductorSeed` behavior (derive/sign/verify/did_key/zero) is unchanged —
      pre-existing identity tests keep passing unmodified.

## Testing

- Unit: `split_seed`/`combine_shares` round-trip, threshold enforcement, checksum corruption.
- Unit: `persist_seed`/`load_seed` round-trip against `InMemorySecretStore` and
  `VaultSecretStore` (using a temp-directory vault instance).
- Property (Hypothesis): for any generated 32-byte seed entropy and any valid
  `(member_threshold, member_count)` pair with `1 <= threshold <= count <= 16`, splitting then
  combining any `threshold`-sized subset of shares reconstructs identical derived keys.

## Open questions

- Whether re-sharding (going from one group config to another, e.g. 3-of-5 to 2-of-3) should
  be a first-class operation or just "combine then split again" — leaning toward the latter
  (no special-cased re-share function; combining recovers the seed, from which a fresh
  `split_seed` call produces a new share set).

## References

- [ADR-021: Conductor Seed](../adr/ADR-021-conductor-seed.md)
- [SPEC-011: Vault](SPEC-011-vault.md)
- [SPEC-070226-6489: Identity lifecycle](SPEC-070226-6489-identity-lifecycle.md) — `SecretStore` protocol origin
- `packages/maistro-core/src/maistro/identity/__init__.py` (`ConductorSeed`)
- `packages/maistro-core/src/maistro/vault.py`
