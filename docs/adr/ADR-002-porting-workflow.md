---
id: ADR-002
title: Per-port spec-first workflow
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-04-26
substrate:
  - maistro-engine#ADR-095
implements: []
related:
  - maistro-engine#ADR-000
supersedes: []
blocks: []
blocked-by: []
contracts: [behavioral]
tests: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-04-26
  - status: Accepted
    date: 2026-04-26
---

# ADR-002: Per-port spec-first workflow

> **Reconciliation note (2026-09-28):** This ADR remains lifecycle-valid `Accepted` until a successor ADR is created and accepted. Several fixed workflow details below conflict with the active pre-1.0 development standards in [`docs/development-standards/pre-v1-development.md`](../development-standards/pre-v1-development.md), including mandatory manual ceremony, the retired `integration` target, and historical sequential numbering. Those conflicting details are not current operating guidance.

**Status:** Accepted  
**Date:** 2026-04-26  
**Tranche:** T0  
**Depends on:** ADR-095

---

## Context

maistro-engine was receiving improvements ported from two adjacent repos: `stronghold` and `Project_mAIstro`. At the time, each port was required to follow a repeatable, auditable 12-step engineering workflow.

## Decision as accepted

Every port followed this sequence without collapsing steps:

1. **ADR drafted** — sections: Context, Decision, Interface (spec), Acceptance criteria, Test plan, Dependencies, Out of scope, Source references.
2. **ADR-only PR opened** to `integration` for review.
3. **Failing happy-path test** written after ADR merged.
4. **Edge cases enumerated** in ADR test-plan section.
5. **Failing edge-case tests** written.
6. **Implementation** written to make all tests pass.
7. **`pytest tests/`** — full suite green.
8. **Coverage check** — new code must have test coverage.
9. **Assertion-strength audit** — tests must pin meaningful behavior, not just "doesn't crash."
10. **Code-smell audit** — duplication, dead code, half-finished abstractions.
11. **Lint, formatting, typing, and dependency audit** — all required checks pass.
12. **Implementation PR** opened to `integration`; links back to ADR; ADR Status updated to Implemented.

Trivial typo/rename fixes were exempt from the full workflow.

## Current reconciliation

The durable principles remain useful: define intended behavior, test meaningful behavior, verify quality, and keep architecture decisions traceable. The fixed ceremony conflicts with the active pre-1.0 agent-native development model and current repository topology.

A successor ADR must define the canonical agent-native development workflow. Once that ADR is accepted, this record can transition `Accepted -> Superseded` with a valid `superseded-by` relationship.

## Historical spec format

The original decision used ADR-style records at `docs/adr/ADR-XXX-name.md` and sequential numbering. Sequential allocation is no longer the active numbering policy; current repository guidance governs new record IDs.

## Acceptance criteria

- [x] ADR template exists at `docs/adr/ADR-000-template.md`
- [x] Historical workflow is retained for provenance
- [x] Conflicting historical details are explicitly identified as non-current guidance
- [ ] Successor ADR defines the canonical pre-1.0 agent-native development workflow

## Out of scope

Defining the successor workflow in this historical ADR. That belongs in the successor decision record.
