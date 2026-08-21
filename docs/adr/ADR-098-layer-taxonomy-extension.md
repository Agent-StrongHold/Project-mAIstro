---
id: ADR-098
title: "Layer taxonomy extension — Evolve, Crypto, Connectivity, Ability, Identity"
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-10
accepted: 2026-06-10
substrate:
  - maistro-engine#ADR-031
implements: []
related:
  - maistro-engine#ADR-030
  - maistro-engine#ADR-088
supersedes: []
blocks: []
blocked-by: []
contracts: []
tests:
  - tests/tools/registry/test_schema.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# ADR-098: Layer Taxonomy Extension — Evolve, Crypto, Connectivity, Ability, Identity

## Context

ADR-031 §1 defined a closed 9-layer classification: Foundation, Orchestration,
Agents, Tools, Memory, Observability, Reliability, Governance, UserClient.

When registry CI flipped to strict, three specs were found using layers outside
that list — SPEC-202 (`Optimization`), SPEC-203 and SPEC-204 (`Ability`) — and
were provisionally relabeled to pass the gate. That drift was a signal, not an
error: a corpus survey shows whole subsystem families squeezed into layers that
don't describe them.

- **Self-improvement** (maistro-evolve, RSI, fitness fidelity) is not the agent
  runtime; it sits above it and optimizes it. Parked under `Agents`.
- **Cryptocurrency / value transfer** (Conductor Seed, hardware signing,
  spending policy, Electrum, Lightning federation) is scattered across
  `Foundation`, `Governance`, and `Tools`.
- **Transport and channels** (networking/mesh substrate, email channel,
  outbound delivery gateway, A2A networking) is scattered across `Foundation`,
  `Orchestration`, and `Tools`.
- **Product abilities** (the canvas ability, maistro-design) are first-class
  product vocabulary ("the canvas ability is standalone" is a root design
  decision) but have no layer; the family is split across `Foundation`,
  `Agents`, and `UserClient`.

ADR-031's stated purpose for `layer:` is drift detection — multiple records
claiming the same layer without substrate linkage. That only works if layers
describe the architecture as it actually is.

## Decision

Extend the ADR-031 §1 `layer` enumeration (and `maistro_registry.schema.Layer`)
with five members. The taxonomy remains closed; further additions require an
ADR amending this one.

| Layer | Scope |
|---|---|
| `Evolve` | Self-improvement loops: genome evolution, fitness/benchmark signal, reflective optimization, RSI. |
| `Crypto` | Cryptocurrency and value transfer: seed/HD root of trust, hardware signing, spending policy, Electrum, Lightning federation. General cryptography (PKI, DID, redaction, vault) stays in `Governance`/`Foundation`. |
| `Connectivity` | Transport, channels, and mesh: networking/identity substrate transport, channel integrations (email), outbound delivery, agent-to-agent networking. The A2A delegation *protocol* itself stays `Orchestration`. |
| `Ability` | Packaged product abilities composed from the substrate: canvas, maistro-design, builders, and future ability packages. |
| `Identity` | Who things are: agent identity, user identity, instance identity — DID/VC, trust roots, authentication, identity lifecycle. Authorization/elevation (what identities may do) stays `Governance`. |

Existing records are relabeled accordingly:

| New layer | Records |
|---|---|
| Evolve | ADR-088, SPEC-202, SPEC-207 |
| Crypto | ADR-021, ADR-022, ADR-023, ADR-025, ADR-027, SPEC-017, SPEC-018 |
| Connectivity | ADR-029, ADR-047, SPEC-002, SPEC-008, SPEC-016 |
| Ability | ADR-040, ADR-041, ADR-042, ADR-043, ADR-044, ADR-045, ADR-061, ADR-067, ADR-090, SPEC-160, SPEC-200, SPEC-201, SPEC-203 |
| Identity | ADR-024, ADR-026, ADR-059, ADR-084, SPEC-183 |

SPEC-204 (partial-feature hardening) remains `Reliability` — its provisional
relabel was correct on the merits.

## Consequences

### Positive
- The taxonomy matches the repo's own vocabulary; drift detection per layer
  becomes meaningful for the evolve, crypto, connectivity, and ability families.
- Future evolve/RSI, wallet/Lightning, channel, and ability specs have an
  obvious home instead of inventing layers (which strict CI now rejects).

### Negative / Trade-offs
- 13-layer taxonomy is harder to hold in your head than 9; the bar for the
  *next* addition should stay high (this ADR is the amendment precedent).
- Cross-repo consumers of the schema pick up the new members on their next
  registry-tool update; older tool versions will reject the relabeled files.

### Neutral
- `Optimization` (used briefly by SPEC-202/206) is folded into `Evolve` rather
  than kept as a synonym — one name per concern.
