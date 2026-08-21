---
id: ADR-087
title: "Database Schema Evolution — expand/contract, zero-downtime"
repo: maistro-engine
kind: adr
status: Accepted
accepted: 2026-06-10
created: 2026-05-30
substrate:
  - maistro-engine#ADR-012
implements: []
related:
  - maistro-engine#ADR-018
  - maistro-engine#ADR-081
supersedes: []
blocks: []
blocked-by: []
contracts:
  - behavioral
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
  - status: Accepted
    date: 2026-06-10
    date: 2026-05-30
---

# ADR-087: Database Schema Evolution — expand/contract, zero-downtime

**Status:** Proposed
**Date:** 2026-05-30
**Extends the first migration** (ADR-012) into a standing rule for how schema changes ship without
taking the system down: expand, backfill, switch, contract.

---

## Context

ADR-012 established the first migration but not a discipline for evolving the schema afterward.
Deploys are rolling: for a window, old and new application code run against the same database at the
same time. A naive `ALTER` that renames or drops a column breaks whichever version of the code does
not expect it, forcing downtime. This ADR makes the **expand/contract** pattern the default so schema
changes are zero-downtime and rollback-safe.

## Decision

Schema changes follow the **EXPAND / CONTRACT** pattern, in four ordered phases across a deploy
window during which **old and new code COEXIST**:

1. **Expand** — add the new shape (new columns / tables) in a **nullable, backward-compatible** way.
   Old code ignores it; new code can begin writing it. No destructive change yet.
2. **Backfill** — populate the new shape for existing rows, in batches, online.
3. **Switch reads** — once the new shape is fully populated, move reads over to it. Both shapes still
   exist; the old one is now redundant but harmless.
4. **Contract** — in a *later* deploy, after no running code reads the old shape, drop it.

**Every migration is rollback-safe and tested in CI.** Because each phase is backward-compatible, a
deploy can roll back to the previous code version without a schema rollback. CI exercises migrations
(apply + the relevant phase invariants) so a non-expandable change cannot land unnoticed.

**Breaking, non-expandable changes are the exception.** Where a change genuinely cannot be expressed
as expand/contract, it calls for an **explicit maintenance window** — a deliberate, announced
exception, not the default path.

This **extends ADR-012**: that ADR set up the first migration; this one sets the rule every migration
after it follows.

## Acceptance criteria

- [ ] Schema changes are expressed as expand -> backfill -> switch-reads -> contract, with expand and
      contract in separate deploys.
- [ ] The expand phase is additive and backward-compatible (nullable columns / new tables); old code
      keeps working against the expanded schema.
- [ ] Old and new application code coexist correctly against the schema throughout the deploy window.
- [ ] Each migration is rollback-safe (a code rollback needs no schema rollback) and is tested in CI.
- [ ] A genuinely breaking, non-expandable change is flagged as the exception and scheduled into an
      explicit maintenance window rather than shipped as a rolling deploy.

## Consequences

- ADR-012's single migration becomes a repeatable, zero-downtime discipline.
- Schema changes cost two deploys (expand, then contract) instead of one — deliberate friction that
  buys safety and rollback.
- CI gains a migration-conformance gate, catching non-expandable changes before they reach a deploy.

## Out of scope

- The migration tooling / framework choice and its file layout.
- Backfill batching strategy and throttling for very large tables (an operational detail).
- Data migrations that change semantics rather than shape (covered case-by-case).
