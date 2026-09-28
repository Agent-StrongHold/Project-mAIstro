---
id: ADR-002
title: Per-port spec-first workflow
repo: maistro-engine
kind: adr
status: Superseded
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
  - status: Superseded
    date: 2026-09-28
---

# ADR-002: Per-port spec-first workflow

> **Superseded on 2026-09-28 by the active pre-1.0 development standards in [`docs/development-standards/pre-v1-development.md`](../development-standards/pre-v1-development.md).** The fixed 12-step porting ceremony below is historical. Current work remains specification- and verification-driven, but autonomous delivery is the normal path, manual ceremony is not a routine prerequisite, `develop` is the active integration branch, and obsolete compatibility/process constraints are not preserved merely because they existed.

**Status:** Superseded  
**Date:** 2026-04-26  
**Tranche:** T0  
**Depends on:** ADR-095

---

## Context

maistro-engine was receiving improvements ported from two adjacent repos: `stronghold` (production multi-agent platform) and `Project_mAIstro` (Python conductor + TypeScript app layer). At the time, each port was required to follow a repeatable, auditable 12-step engineering workflow.

## Historical decision

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

## Current disposition

The useful principles survive: define intended behavior, test meaningful behavior, verify quality, and keep architecture decisions traceable. The fixed ceremony does not. Current development follows the active pre-1.0 standards and current repository governance, including progressive disclosure and automated verification.

## Historical spec format

The original decision used ADR-style records at `docs/adr/ADR-XXX-name.md` and sequential numbering. Sequential allocation is no longer the active numbering policy; current repository guidance governs new record IDs.

## Acceptance criteria

- [x] ADR template exists at `docs/adr/ADR-000-template.md`
- [x] Historical workflow is retained for provenance
- [x] Current guidance points to the active pre-1.0 development standards instead of requiring this ceremony

## Out of scope

The replacement development standards own current workflow policy; this ADR remains only as the historical record of the former per-port process.
