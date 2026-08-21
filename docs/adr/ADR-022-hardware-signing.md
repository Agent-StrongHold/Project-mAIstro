---
id: ADR-022
title: 'Hardware Signing Devices — Ledger / Trezor / YubiKey / Mobile'
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
implements: []
related:
  - maistro-engine#ADR-020
  - maistro-engine#ADR-023
  - maistro-engine#ADR-028
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-07
---

# ADR-022: Hardware Signing Devices — Ledger / Trezor / YubiKey / Mobile

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed)

---

## Context

The Conductor Seed (ADR-021) is encrypted at rest but decrypted into process memory during signing. For high-value deployments, or for operators who already keep keys on dedicated hardware, the seed should never enter the conductor process. Hardware-wallet integration is also what crypto-native users expect by default.

**Source:** `Project_mAIstro/specs/security/S-150-hardware-signing.md` (101 lines)

## Decision

Four integration modes, all selectable in the setup wizard (ADR-020). Modes 1–3 **replace**
the seed source from ADR-021 with hardware; **Mode 4 is the ADR-021 software seed itself** and
is always available. Hardware is therefore optional and post-init — ADR-021 bootstraps first
with no hardware, then migrates if the operator selects a hardware mode (no ADR-021 ↔ ADR-022
bootstrap cycle).

### Mode 1: Ledger / Trezor as seed source

- Hardware device generates/holds BIP39 seed; conductor never sees private material
- Signing requests route via WebUSB/HID (desktop) or Bluetooth (Ledger Nano X)
- Every signature shows structured prompt on device screen; user confirms with buttons
- Full BIP39 + BIP32 paths — both signing and wallets

### Mode 2: YubiKey HSM (PIV applet)

- Holds Ed25519 + secp256k1 keypair in tamper-resistant storage
- Not BIP32-HD-derivable — suitable for `m/0'`-equivalent (AgentSpec / audit / elevation) only
- Wallet paths stay in software (ADR-021)
- Enterprise use case: constant signing, rare wallet ops

### Mode 3: Mobile device with hardware-backed keystore

- Admin's phone holds signing key in iOS Secure Enclave or Android Keystore
- Conductor sends signed-payload requests to BIP-322-compatible wallet app
- Admin signs via biometric tap
- Unified UX for both Lightning payments (ADR-023) and HITL elevation requests (ADR-028)
- Operational default for non-paranoid users

### Mode 4: Software seed (ADR-021 default)

- Default with explicit messaging that hardware-backed modes are stronger

### Device support matrix

| Device | BIP39/BIP32 | Curves | Connectivity | Sign types |
|---|---|---|---|---|
| Ledger Nano S+ | Yes | secp256k1, Ed25519 | USB-C | All |
| Ledger Nano X | Yes | secp256k1, Ed25519 | USB-C, Bluetooth | All |
| Trezor Model T | Yes | secp256k1, Ed25519 | USB-C | All |
| Trezor Safe 3 | Yes | secp256k1, Ed25519 | USB-C | All |
| YubiKey 5 (PIV) | No | secp256k1, Ed25519 | USB / NFC | Signing only; no HD wallet |
| iOS Secure Enclave | Via wallet app | secp256k1, P-256 | Push + biometric | BIP-322 messages |
| Android Keystore | Via wallet app | Per-device | Push + biometric | BIP-322 messages |

## Interface (spec)

```python
from typing import Protocol

class SigningDevice(Protocol):
    def is_connected(self) -> bool: ...
    def sign(self, path: str, message: bytes) -> bytes: ...
    def public_key(self, path: str) -> bytes: ...
    def device_type(self) -> str: ...  # "ledger" | "trezor" | "yubikey" | "mobile" | "software"
    def supports_hd_derivation(self) -> bool: ...
```

## Acceptance criteria

- [ ] Setup wizard offers all four modes; modes 1-2 require device detection before selectable
- [ ] Ledger/Trezor: sign AgentSpecs, elevation approvals, and chain txs; conductor never holds private key
- [ ] YubiKey: signs AgentSpecs + elevation; rejects HD-derivation with clear error
- [ ] Mobile: push notification within 5s; admin biometric-signs within 30s
- [ ] Hardware unplugged: conductor enters degraded mode (no signing) rather than crashing
- [ ] Mode-switching: migrate from software to hardware without reinstall
- [ ] Audit log records signing modality for every signed operation

## Out of scope

- Mobile wallet app development (uses existing BIP-322-compatible wallets)
- Tor routing for LN federation (ADR-027 covers this)
- Bluetooth pairing UX details (device-specific)

## Source references

- `~/maistro-engine/specs/security/S-150-hardware-signing.md` — full spec

## Links

- Source spec: S-150
- Related ADRs: ADR-020 (Setup Wizard), ADR-021 (Conductor Seed), ADR-023 (Crypto Ops), ADR-028 (Privilege Separation)
