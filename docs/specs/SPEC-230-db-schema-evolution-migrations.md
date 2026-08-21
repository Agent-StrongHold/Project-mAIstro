---
id: SPEC-230
title: "Database schema evolution: Alembic migration infrastructure (expand/contract pattern not yet exercised)"
repo: maistro-engine
kind: spec
status: Proposed
created: 2026-06-20
substrate: []
implements:
  - maistro-engine#ADR-087
related:
  - maistro-engine#ADR-012
tests: []
contracts: []
supersedes: []
blocks: []
blocked-by: []
layer: Foundation
owners:
  - '@BlakeMatthews-dev'
---

# SPEC-230: Database schema evolution migration infrastructure

## Context

ADR-087 establishes the expand/backfill/switch-reads/contract discipline as the
standing rule for every schema change after the first migration (ADR-012). The
migration tooling itself (generic Alembic) exists and is in active use; what does
not yet exist is a demonstrated, concrete instance of the four-phase pattern, a CI
gate that enforces it, or a test validating rollback-safety. This SPEC documents the
infrastructure as it stands and is honest about the gap — it does not claim the
discipline has been exercised in practice.

## Goals

- Document the actual Alembic migration setups and version files in the repo.
- State plainly what evidence of the expand/contract discipline exists (none, beyond
  the ADR text itself) so future migrations have a clear bar to meet.

## Non-goals

- Choosing or changing migration tooling.
- Implementing a CI migration-conformance gate (tracked as an open question/follow-up).
- Backfill batching/throttling strategy for large tables.

## Decision

Two separate Alembic setups exist:

- Root: `/home/user/maistro-engine/alembic/`, versions
  `001_initial_memory_schema.py`, `002_canvas_asset_039.py`.
- `packages/maistro-canvas/frontend/alembic/`, versions `001_initial_schema.py`,
  `003_canvas_job_lease_203.py`.

These are generic Alembic migrations (per ADR-012 / SPEC-213) — none of the four
version files demonstrate the expand/contract pattern (no nullable-column-add paired
with a later drop, no backfill script, no "expand"/"contract"/"backward-compatible"
comment). A repo-wide search for expand/contract language outside the ADR itself
returns nothing in `.py`/`.sql`/`.md` migration content.

No `.github/workflows/*.yml` file runs or tests migrations (no `migrat*` reference
across `ci.yml`, `quality.yml`, `security.yml`, `mutation.yml`, `registry.yml`,
`cage-guard.yml`, `formal-conformance{,-nightly}.yml`). No test file validates
migration rollback-safety or expand/contract conformance.

This SPEC therefore documents the *infrastructure* (Alembic exists, two migration
trees are live) as Implemented in the narrow sense, while marking the *discipline*
ADR-087 actually mandates (the four-phase pattern, CI gate, rollback test) as not yet
demonstrated. Status is `Proposed` rather than `Implemented` to reflect that gap
honestly.

## Acceptance criteria

- [x] Alembic migration infrastructure exists and is used for schema changes (root + canvas frontend trees)
- [x] Each existing migration applies cleanly (implied by repo's working test suite using these schemas)
- [ ] At least one migration pair demonstrates the expand phase (additive, nullable, backward-compatible) followed by a later contract phase
- [ ] A backfill step is demonstrated as a distinct, batched, online operation
- [ ] CI runs a migration-conformance gate that would catch a non-expandable change
- [ ] A test demonstrates rollback-safety (old code + new schema, or code rollback without schema rollback)
- [ ] A documented exception path exists for genuinely breaking changes (explicit maintenance window)

## Testing

No tests currently exist that exercise the expand/contract discipline specifically.
Existing coverage is indirect: the application test suites
(`packages/maistro-core/tests/`, `packages/maistro-canvas/tests/`) run against
databases provisioned via these Alembic trees, which implicitly confirms the
migrations apply without error, but does not test multi-phase evolution.

## Open questions

- Should a CI job be added that runs `alembic upgrade head` then `alembic downgrade -1`
  on a scratch database, to start enforcing rollback-safety mechanically?
- Should the next non-trivial schema change be used as the worked example this SPEC
  currently lacks, with its PR linked back here?
- Is a lint rule (e.g. flagging `DROP COLUMN`/`ALTER COLUMN ... NOT NULL` in the same
  migration as related `ADD COLUMN`) feasible to add as the "migration-conformance
  gate" ADR-087 calls for?

## References

- `/home/user/maistro-engine/alembic/versions/001_initial_memory_schema.py`
- `/home/user/maistro-engine/alembic/versions/002_canvas_asset_039.py`
- `packages/maistro-canvas/frontend/alembic/versions/001_initial_schema.py`
- `packages/maistro-canvas/frontend/alembic/versions/003_canvas_job_lease_203.py`
- `docs/adr/ADR-012-alembic-migration.md`
- `docs/specs/SPEC-213-alembic-memory-migration.md`
