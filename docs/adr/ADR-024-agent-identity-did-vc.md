---
id: ADR-024
title: 'Agent Identity & Verifiable Credentials (DID + VC)'
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-029
implements: []
related:
  - maistro-engine#ADR-023
  - maistro-engine#ADR-027
  - maistro-engine#ADR-028
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Identity
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-07
---

# ADR-024: Agent Identity & Verifiable Credentials (DID + VC)

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed), ADR-029 (Networking Substrate)

---

## Context

The conductor needs a public, verifiable identity for cross-instance federation trust, audit log verification, crypto counterparty identity, and plugin authenticity verification. Without it, trust claims are bare assertions.

**Source:** `Project_mAIstro/specs/security/S-152-agent-identity-did-vc.md` (190 lines)

## Decision

W3C **Decentralized Identifier (DID)** + W3C **Verifiable Credentials (VC)**. The conductor's identity is a DID; assertions about its actions, peers, and plugins are VCs signed by that DID.

### DID methods

Every conductor has at minimum:

- **`did:key`** — derived deterministically from ADR-021 path `m/44'/9000'/0'`. Always available, no infrastructure required. Works on localhost-only.

When the conductor has an HTTPS endpoint (ADR-029):

- **`did:web:<hostname>`** — resolves via `/.well-known/did.json`. Supports rotation and service endpoints.

Opt-in via Medley plugins: `did:ethr`, `did:ion`, `did:plc`, `did:dht`. All methods point to the same underlying keys from ADR-021.

### DID document structure

Served at `/.well-known/did.json` when substrate provides HTTPS:

```json
{
  "@context": ["https://www.w3.org/ns/did/v1"],
  "id": "did:web:brigid.example.ts.net",
  "alsoKnownAs": ["did:key:z6Mk..."],
  "verificationMethod": [
    { "id": "#agent-spec", "type": "Ed25519VerificationKey2020", "publicKeyMultibase": "z6Mk..." },
    { "id": "#audit-log", "type": "Ed25519VerificationKey2020", "publicKeyMultibase": "z6Mk..." }
  ],
  "service": [
    { "id": "#message-board", "type": "MessageBoard", "serviceEndpoint": "https://..." },
    { "id": "#lightning", "type": "LightningAddress", "serviceEndpoint": "brigid@example.ts.net" }
  ]
}
```

### Verifiable Credentials (four use cases)

1. **Audit log VCs** — every privileged operation produces a signed VC stored in audit log. Dashboard "verify" button resolves DID and validates signature offline.
2. **Federation trust VCs** — scoped trust credentials between conductors (e.g., `trustsForContributions: ["medical-knowledge"]`).
3. **Plugin publisher VCs** — Medley plugins ship with publisher-issued VCs. Unsigned plugins require admin override.
4. **Third-party certifications** — external authorities issue VCs to the conductor (e.g., API license verification).

### Standards

- W3C DID Core 1.0, W3C VC Data Model 2.0
- JWT-VC and JSON-LD-VC formats both supported
- BIP-322 for arbitrary message signing
- DIDComm v2 for conductor-to-conductor messaging

## Interface (spec)

```python
@dataclass
class DIDDocument:
    id: str
    also_known_as: list[str]
    verification_methods: list[dict]
    services: list[dict]

@dataclass
class VerifiableCredential:
    context: list[str]
    type: list[str]
    issuer: str              # DID
    valid_from: str          # ISO 8601
    credential_subject: dict
    proof: dict

class IdentityService:
    def get_did(self) -> DIDDocument: ...
    def sign_vc(self, subject: dict, type_: list[str]) -> VerifiableCredential: ...
    def verify_vc(self, vc: VerifiableCredential) -> bool: ...
    def rotate_keys(self) -> None: ...
    def publish_did(self) -> None: ...
```

## Acceptance criteria

- [ ] Every conductor has `did:key` from `m/44'/9000'/0'` with no additional config
- [ ] When substrate provides HTTPS hostname, `did:web` published automatically at `/.well-known/did.json`
- [ ] Every privileged operation in audit log recorded as signed VC
- [ ] Dashboard can verify any audit-log VC against the conductor's DID document
- [ ] Federation: two conductors exchange DIDs, admin issues scoped trust VC, federated contributions carry verifiable provenance
- [ ] Plugin publisher VCs verified at install; unsigned requires admin override
- [ ] Key rotation: new DID document published; old VCs verifiable against historical document

## Out of scope

- On-chain DID methods implementation (`did:ethr`, `did:ion`) — Medley plugin territory
- DIDComm v2 transport implementation (ADR-027 references it)
- Universal Resolver integration

## Source references

- `~/maistro-engine/specs/security/S-152-agent-identity-did-vc.md` — full 190-line spec

## Links

- Source spec: S-152
- Related ADRs: ADR-021 (Conductor Seed), ADR-023 (Crypto Ops), ADR-027 (Lightning Federation), ADR-028 (Privilege Separation), ADR-029 (Networking Substrate)
