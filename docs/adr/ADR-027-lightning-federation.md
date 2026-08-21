---
id: ADR-027
title: "Lightning-Native Federation — Payment-graph reputation and spam resistance"
repo: maistro-engine
kind: adr
status: Deferred
created: 2026-05-07
substrate:
  - maistro-engine#ADR-021
  - maistro-engine#ADR-023
  - maistro-engine#ADR-024
  - maistro-engine#ADR-029
implements: []
related:
  - maistro-engine#ADR-025
  - maistro-engine#ADR-028
supersedes: []
blocks: []
blocked-by: []
contracts:
  - cross-service
tests: []
layer: Crypto
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-05-07
  - status: Deferred
    date: 2026-05-07
---

# ADR-027: Lightning-Native Federation — Payment-graph reputation and spam resistance

**Status:** Proposed
**Date:** 2026-05-07
**Depends on:** ADR-021 (Conductor Seed), ADR-023 (Agent Crypto Ops), ADR-024 (DID/VC Identity), ADR-029 (Networking Substrate)

---

## Context

DID/VC federation (ADR-024) provides identity and signed claims but has a free-rider problem: any conductor can issue a VC saying "trust me," and recipients must evaluate it. Lightning adds **spam resistance via cost** — the act of talking at all costs sats. It also provides implicit reputation via the payment graph itself, with no central registry.

**This spec is opt-in.** Only applies to conductors that have installed Lightning (ADR-023). Federation works without it over DID/VC + substrate (ADR-024, ADR-029). Lightning federation layers payment-bearing semantics onto the same identity primitives.

**Source:** `Project_mAIstro/specs/security/S-156-lightning-federation.md` (189 lines)

## Decision

Layer Lightning Network as a payment-bearing federation transport on top of DID/VC identity. Four parts: (1) friend handshake, (2) message format, (3) use-case primitives, (4) reputation signal.

### 1. Friend handshake protocol

1. **Discovery** — each conductor advertises LN node ID + DID via DID document service entries or out-of-band exchange
2. **Initial keysend** — Conductor A sends 1-sat keysend to B with custom TLV records: DID, BIP-322-signed scope request, ephemeral session key
3. **Handshake reply** — B replies with 1-sat keysend: DID, BIP-322 acknowledgment, B's session key
4. **Mutual VC issuance** — each admin issues a federation-trust VC with scope + quote terms + validity period
5. **Done** — subsequent messages flow over established session with payments attached

Handshake is idempotent: re-running rotates session keys + refreshes VC validity.

### 2. Message format

- **Small messages (<=1300 bytes):** carried in LN keysend TLV records. Sphinx-routed; recipient cannot trivially learn sender identity.
- **Large messages:** LN carries control plane (handshake + payment + session pointer); data plane flows over substrate (ADR-029) with E2E encryption from handshake session keys.

LN is the *checkout counter*; substrate is the *delivery truck*.

### 3. Use-case primitives

| Primitive | Description |
|---|---|
| **Pay-per-query** | 100 sats per federated memory query. Spam dies. Real questions get real answers. |
| **Subscription wisdom** | 1000 sats/month for morning digest stream. Cancel = stop paying. |
| **Skill Forge bounties** | Cross-conductor bounties for skills. First valid + Phantom-passing skill wins. |
| **Federated Red Team** | Pay peer conductors to attack yours. Paid only for novel finds. |
| **Conductor DM** | Sphinx-routed E2E encrypted messages between agents. No humans in the loop. |
| **Tip jar** | Message board posts tipable by other conductors. No platform extracting. |
| **Sensor streaming** | Cross-conductor cooperation signaled by payments rather than free-rider claims. |

### 4. Reputation via payment graph

The payment graph IS the reputation. Dashboard surfaces:
- Direct: "7 friend conductors"
- One-hop: "Conductor C has been paid by 4 of your friends"
- Total flow: "12,400 sats sent, 8,600 sats received in 30 days"
- Confidence: "90 days federated, 312 queries, 2.1s avg response, 0% refund"

No central registry. No signed reputation claims. Payments are the trust signal.

## Interface (spec)

```python
@dataclass
class FriendHandshake:
    peer_did: str
    peer_ln_node_id: str
    scope: list[str]
    quote_terms: dict[str, int]   # e.g., {"memory_query": 100}
    session_key: bytes
    trust_vc: VerifiableCredential | None

class FederationTransport:
    def initiate_handshake(self, peer_did: str, scope: list[str]) -> FriendHandshake: ...
    def send_message(self, peer_did: str, message: bytes, sats: int) -> str: ...
    def receive_message(self) -> tuple[str, bytes]: ...  # (peer_did, message)
    def get_reputation(self, peer_did: str) -> ReputationScore: ...
    def close_session(self, peer_did: str) -> None: ...
```

## Acceptance criteria

- [ ] Federation works without Lightning installed (DID/VC + substrate only)
- [ ] Two LN-enabled conductors complete friend handshake in <60s on signet
- [ ] Pay-per-query: A pays 100 sats, B returns memory entries as signed VCs, A verifies
- [ ] Subscription streaming works for one billing cycle with auto-rebalance
- [ ] Conductor DM via Sphinx routing; message opaque to substrate intermediaries
- [ ] Tip jar results in payment record + audit-log VC linking payment to post
- [ ] Reputation graph: dashboard shows direct friends, one-hop, total flow, confidence
- [ ] Spam test: conductor without handshake cannot send federation messages
- [ ] Mixed federation: LN conductor federates with non-LN peer over DID/VC + substrate
- [ ] Hot-channel balance cap (ADR-023) respected; federation doesn't bypass spending policy

## Out of scope

- LN node implementation (ADR-023 covers LDK/sidecar)
- Tor routing configuration (documented option, not required)
- Universal Resolver for cross-network DID resolution

## Source references

- `~/maistro-engine/specs/security/S-156-lightning-federation.md` — full 189-line spec

## Links

- Source spec: S-156
- Related ADRs: ADR-021 (Conductor Seed), ADR-023 (Agent Crypto Ops), ADR-024 (DID/VC), ADR-025 (Electrum Server), ADR-028 (Privilege Separation), ADR-029 (Networking Substrate)
