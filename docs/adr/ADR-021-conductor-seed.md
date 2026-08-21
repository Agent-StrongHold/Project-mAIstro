---
id: ADR-021
title: 'Conductor Seed — BIP39/BIP32 HD root of trust'
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-05-07
substrate: []
implements: []
related:
  - maistro-engine#ADR-020
  - maistro-engine#ADR-022
  - maistro-engine#ADR-023
  - maistro-engine#ADR-024
  - maistro-engine#ADR-028
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Accepted
    date: 2026-05-07
---

# ADR-021: Conductor Seed — BIP39/BIP32 HD root of trust

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** nothing — this is the HD root of trust, generated standalone.

> **Bootstrap order (resolves the apparent ADR-021 ↔ ADR-022 cycle).** The software seed
> initializes **first** and with no hardware: BIP39 generate → BIP32 derive → encrypted local
> storage (Mode 4, the default). ADR-022 hardware signing is **optional and post-init** — it
> *replaces or augments* the seed source (Modes 1–3), selectable in the setup wizard or later.
> So ADR-022 is `related`, not `substrate`: the seed never requires hardware to exist.

---

## Context

The conductor needs a single root of trust spanning multiple uses: signing AgentSpec envelopes, signing audit-log entries, signing HITL elevation approvals, future on-chain identity (DID), and wallet keys for crypto plugins. Generating separate keys per use creates multiple backup ceremonies and no unified provenance story.

**Source:** `Project_mAIstro/specs/security/S-149-conductor-seed.md` (115 lines)

## Decision

Adopt **BIP39 (24-word mnemonic) + BIP32 (hierarchical-deterministic derivation)** as the root. One seed phrase backs up everything. Domain separation via standard derivation paths.

### Derivation tree

```
Conductor Seed (24 words, BIP39)
├── m/0'              → AgentSpec / audit-log / elevation signing (SLIP-0010 Ed25519)
├── m/44'/0'/0'       → Bitcoin cold wallet
├── m/44'/0'/1'       → Bitcoin hot wallet
├── m/44'/60'/0'      → Ethereum / EVM cold
├── m/44'/60'/1'      → Ethereum / EVM hot
├── m/44'/501'/0'     → Solana cold
├── m/44'/9000'/0'    → Identity / DID anchor
└── m/44'/9000'/1'    → Vault identity anchor (optional, see Amendment below)
```

## Amendment (2026-06-19): baseline-vs-opt-in vault identity

**Decision, recorded so it isn't lost:** the project's security philosophy is to hold the
**baseline at "boring and safe"** and treat anything seed/DID/wallet-shaped as an **opt-in
upgrade**, never a requirement. This directly resolves how the SPEC-011 vault's `age`
identity (`admin.key`, a standalone X25519 keypair from `age-keygen`) relates to this seed:

- **Baseline (default, unconditional):** the vault keeps using a standalone `age-keygen`
  identity with zero dependency on `ConductorSeed`. Anyone who never sets up a seed — "no
  crypto, no DID, just `age`" — gets the full vault with no missing functionality and no
  forced exposure to wallet/DID machinery. `age`'s own design philosophy (no wallets, no
  registries, possession-of-keyfile trust model) is the right fit for this tier and is left
  untouched.
- **Opt-in upgrade (only if a seed already exists):** a deployment that *has* provisioned a
  `ConductorSeed` may derive the vault's identity from path `m/44'/9000'/1'` instead of
  maintaining a separate `admin.key` file. This folds vault-unlock material into the single
  seed backup/recovery ceremony the user already performed for DID/wallet use. It is never
  auto-enabled by the presence of a seed — switching tiers is an explicit user action (e.g.
  a setup-wizard / `maistro vault rotate-identity --source=conductor-seed` step), because
  collapsing the vault's trust root into the same seed as wallet keys is a real blast-radius
  increase (lose the seed → lose wallets *and* the secrets vault, not just one).
- Both tiers must always produce an `age`-compatible X25519 keypair at the storage layer —
  the upgrade changes *where the key comes from*, never the vault's on-disk format or its
  `use()`-only access API.

This generalizes beyond the vault: **any** future "exciting" feature gated behind
`ConductorSeed`/DID (e.g. agent-to-agent signing, on-chain identity) follows the same shape —
present by default with a standalone, non-seed-derived credential; offered as an explicit,
non-default upgrade once a seed exists. See SPEC-003 for the vault-specific implementation
of this tier.

### Key properties

- **Deterministic** — same seed produces same keys across reinstalls
- **Compartmented** — signing path (`m/0'`) is independent of wallet paths; non-crypto deployments never derive wallet material
- **Optional SLIP39** — 3-of-5 Shamir backup for high-value deployments
- **Storage** — encrypted file unlocked by OS keychain or hardware wallet (ADR-022); seed never written to disk in cleartext after wizard
- **Memory hygiene** — derived private keys zeroed after each signing operation

### Recovery card

One-page printable card containing: 24 words in 6x4 grid, QR of `m/0'` public key, instance name + date, warning text.

## Interface (spec)

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class DerivedKey:
    path: str          # e.g. "m/0'"
    public_key: bytes  # raw public key bytes
    curve: str         # "ed25519" | "secp256k1"

class ConductorSeed:
    @staticmethod
    def generate(word_count: int = 24) -> "ConductorSeed": ...
    @staticmethod
    def from_mnemonic(words: list[str]) -> "ConductorSeed": ...
    def derive(self, path: str) -> DerivedKey: ...
    def sign(self, path: str, message: bytes) -> bytes: ...
    def public_key(self, path: str) -> bytes: ...
    def mnemonic_words(self) -> list[str]: ...
    def zero(self) -> None: ...
```

## Acceptance criteria

- [ ] 24-word phrase generated from canonical BIP39 English wordlist
- [ ] Phrase displayed once with explicit "I have written these down" gate
- [ ] All derivation paths produce reproducible public keys across reboots/reinstalls
- [ ] Seed never written to disk in cleartext after wizard
- [ ] Lost-seed recovery: fresh install + 24 words → identical public keys at every path
- [ ] SLIP39 3-of-5: reconstruction works; <3 shards reveal nothing
- [ ] `m/0'` signing produces stable Ed25519 signatures
- [ ] Memory-zeroization: no reachable string equals the seed or derived private keys after signing

## Test plan

| Test | Type | Covers |
|---|---|---|
| `test_generate_24_words` | unit | BIP39 generation |
| `test_derive_m0_ed25519` | unit | m/0' Ed25519 derivation |
| `test_derive_bitcoin_paths` | unit | BIP44 secp256k1 paths |
| `test_deterministic_across_reboots` | integration | Same seed → same keys |
| `test_recovery_from_mnemonic` | integration | Fresh install recovery |
| `test_slip39_reconstruction` | integration | 3-of-5 Shamir |
| `test_memory_zeroization` | security | No seed in reachable memory after sign |

## Dependencies

- BIP39/BIP32 library (`bip-utils` in Python or `bip39`+`bitcoin` crates in Rust)
- SLIP-0010 for Ed25519 BIP32 derivation
- OS keychain integration for encrypted storage

## Out of scope

- Hardware wallet device communication (ADR-022)
- Wallet transaction construction (ADR-023)
- DID document generation (ADR-024)

## Source references

- `~/maistro-engine/specs/security/S-149-conductor-seed.md` — full spec

## Links

- Source spec: S-149
- Related ADRs: ADR-020 (Setup Wizard), ADR-022 (Hardware Signing), ADR-023 (Crypto Ops), ADR-024 (DID/VC), ADR-028 (Privilege Separation)
