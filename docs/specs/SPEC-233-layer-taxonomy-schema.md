---
id: SPEC-233
title: "Registry Layer enum: 14-member taxonomy (ADR-031 base + ADR-098 extension)"
repo: maistro-engine
kind: spec
status: Implemented
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-098
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests:
  - tests/tools/registry/test_schema.py
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-233: Registry Layer enum extension

## Context

ADR-098 extends the closed `layer:` enumeration in the front-matter schema from 9 to
14 members (adding `Evolve`, `Crypto`, `Connectivity`, `Ability`, `Identity`) and
relabels a defined set of existing ADR/SPEC records to use the new layers. This SPEC
documents the schema change and the relabeling as shipped.

## Goals

- Document the exact `Layer` enum as coded.
- Confirm test coverage for the new members and for rejection of unlisted layers
  (e.g. `Optimization`).
- Confirm the cited example records were actually relabeled.

## Non-goals

- Adding further layers beyond the 14 — any future addition requires its own ADR
  amending ADR-098, per that ADR's closed-taxonomy rule.

## Decision

`packages/maistro-registry/src/maistro_registry/schema.py` (lines 59-74):

```python
class Layer(StrEnum):
    FOUNDATION = "Foundation"
    ORCHESTRATION = "Orchestration"
    AGENTS = "Agents"
    TOOLS = "Tools"
    MEMORY = "Memory"
    OBSERVABILITY = "Observability"
    RELIABILITY = "Reliability"
    GOVERNANCE = "Governance"
    USER_CLIENT = "UserClient"
    # ADR-098 extension — see that ADR for scope definitions.
    EVOLVE = "Evolve"
    CRYPTO = "Crypto"
    CONNECTIVITY = "Connectivity"
    ABILITY = "Ability"
    IDENTITY = "Identity"
```

9 original (ADR-031 §1) + 5 new (ADR-098) = 14 members, confirmed present.

Relabeled example records confirmed via grep:
`docs/adr/ADR-088-maistro-evolve-experimental.md` -> `layer: Evolve`,
`docs/specs/SPEC-202-evolve-fitness-fidelity.md` -> `layer: Evolve`,
`docs/specs/SPEC-207-evolve-reflective-prompt-evolution.md` -> `layer: Evolve`.
(ADR-098's full relabeling table additionally covers `Crypto`, `Connectivity`,
`Ability`, and `Identity` records across ADR-021/022/023/025/027, ADR-029/047,
ADR-040/041/042/043/044/045/061/067/090, and ADR-024/026/059/084 plus their related
SPECs — sampled above, not exhaustively re-verified record by record in this audit.)

## Acceptance criteria

- [x] `Layer` enum contains all 9 original members
- [x] `Layer` enum contains all 5 ADR-098 members (`Evolve`, `Crypto`, `Connectivity`, `Ability`, `Identity`)
- [x] Schema validation accepts each of the 5 new layers
- [x] Schema validation rejects an unlisted layer (e.g. `"Optimization"`)
- [x] At least the cited Evolve-family example records (ADR-088, SPEC-202, SPEC-207) carry the new layer in front matter
- [ ] Full relabeling table (Crypto/Connectivity/Ability/Identity record lists) independently re-verified record-by-record (sampled, not exhaustive, in this audit)

## Testing

`tests/tools/registry/test_schema.py`:
- `test_adr_098_extension_layers_accepted` — parametrized over
  `("Evolve", "Crypto", "Connectivity", "Ability", "Identity")`, asserts each is
  accepted by the schema.
- `test_invalid_layer_rejected` — confirms `"Optimization"` (the pre-ADR-098
  provisional name folded into `Evolve`) is rejected.

## Open questions

- Should a follow-up audit fully re-verify every record in ADR-098's relabeling table
  (rather than the sampled subset here) as part of a registry `lint`/`validate` sweep?
- `SPEC-204` is explicitly called out in ADR-098 as correctly remaining `Reliability`
  (not relabeled) — confirm no regression has since moved it.

## References

- `packages/maistro-registry/src/maistro_registry/schema.py`
- `tests/tools/registry/test_schema.py`
- `docs/adr/ADR-098-layer-taxonomy-extension.md`
- `docs/adr/ADR-088-maistro-evolve-experimental.md`
- `docs/specs/SPEC-202-evolve-fitness-fidelity.md`
- `docs/specs/SPEC-207-evolve-reflective-prompt-evolution.md`
