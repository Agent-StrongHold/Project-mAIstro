---
id: ADR-062026-9b30
title: Date-based ADR/SPEC IDs for new records (sequential numbering frozen)
repo: maistro-engine
kind: adr
status: Accepted
created: 2026-06-20
accepted: 2026-06-20
implemented: 2026-06-20
substrate:
  - maistro-engine#ADR-031
related: []
supersedes: []
blocks: []
blocked-by: []
contracts:
  - boundary
tests: []
layer: Governance
owners:
  - '@BlakeMatthews-dev'
history:
  - status: Proposed
    date: 2026-06-20
  - status: Accepted
    date: 2026-06-20
---

# ADR-062026-9b30: Date-based ADR/SPEC IDs for new records

## Context

Sequential `ADR-NNN`/`SPEC-NNN` IDs are assigned by hand, by reading the highest existing
number and picking the next one. Two PRs opened around the same time can both pick the same
"next" number with no way to detect the collision until both land. This happened concretely:
PR #156 (`ADR-100-bundled-open-design-systems.md`) and PR #157
(`ADR-100-foreign-harness-adapters-and-portability.md`) both claimed `ADR-100`, and the
registry's `walk` duplicate-ID check only caught it once both were merged to `main` — by
then renumbering means rewriting cross-references in already-merged files.

## Decision

New ADRs and SPECs use a date-based ID instead of the next sequential integer:

```
ADR-MMDDYY-XXXX
SPEC-MMDDYY-XXXX
```

- `MMDDYY` is the `created` date.
- `XXXX` is 4 lowercase hex characters, derived from `sha1(<slug-of-title>)[:4]` (or any
  other reproducible/random 4-hex source) — its only job is disambiguating same-day records,
  not encoding meaning.

Existing `ADR-NNN`/`SPEC-NNN` IDs are **not** renumbered en masse; sequential numbering is
simply frozen — no *new* sequential IDs are assigned going forward. `packages/maistro-registry`
accepts both forms (`schema.py::_ID_PATTERN`).

### Out of scope

- Renaming the ~150 existing sequential ADRs/SPECs.
- A central ID-issuing service. The hex suffix is collision-resistant enough for this repo's
  PR volume without needing one.

## Consequences

- Two concurrent PRs can no longer collide on ID, since each derives its own ID from its own
  title/date — no shared counter to race.
- IDs are slightly less readable than `ADR-101`, but sort chronologically by creation date,
  which sequential numbers already approximated.
- The one immediate collision (`ADR-100` claimed twice) is resolved by renumbering the
  later/less-final of the two records: `ADR-100-foreign-harness-adapters-and-portability.md`
  → `ADR-061526-f383-foreign-harness-adapters-and-portability.md`. The other (`ADR-100-bundled-open-design-systems.md`,
  already `Accepted`/`Implemented`) keeps its sequential ID.

## Acceptance Criteria

- **AC-1**: `maistro_registry.schema._ID_PATTERN` accepts both `^(ADR|SPEC)-\d{3}$` (legacy)
  and `^(ADR|SPEC)-\d{6}-[0-9a-f]{4}$` (current).
- **AC-2**: `python -m maistro_registry.cli walk .` reports zero duplicate IDs across the
  full ADR/SPEC tree after this change.
- **AC-3**: All cross-references to the renumbered harness ADR (`SPEC-208`, etc.) point at
  `ADR-061526-f383`.
