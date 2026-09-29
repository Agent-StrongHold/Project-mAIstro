# Core Runtime ADRs

Progressive-disclosure index for ADRs governing shared runtime contracts, schemas, parsing, execution primitives, and other cross-agent runtime behavior.

Each audited entry records current status, next steps, a concise current-state summary, and a relative link to the canonical ADR. Full rationale and history remain in `docs/adr/`.

## ADR-005: Pydantic schemas + SCHEMA_REGISTRY

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Strengthen ADR-005 acceptance evidence before promotion: explicitly assert that all 15 promised schema classes are importable and that `SCHEMA_REGISTRY` contains the complete 15-key contract, then run the focused suite and transition the ADR to `Implemented` if all acceptance criteria pass.  
**Current state:** The complete 15-class typed output schema surface and runtime schema resolver are implemented. Known/unknown/dynamic resolution, score bounds, round-trips, and forward-reference rebuilding are covered or present, but the current import and registry tests are weaker than the ADR's exact acceptance language because they verify module import and only a representative subset of registry keys.  
**ADR:** [ADR-005: Pydantic schemas + SCHEMA_REGISTRY](../../../adr/ADR-005-schemas.md)

## ADR-012: First Alembic migration (memory tables + pgvector)

**Status:** Accepted  
**Last updated:** 2026-09-28  
**Next steps:** Add or run fresh-Postgres migration verification that proves `alembic upgrade head`, the required downgrade semantics, pgvector extension setup, and model/migration drift detection (`alembic check` or equivalent). Once all four accepted criteria are directly evidenced, transition ADR-012 to `Implemented`. Reconcile SPEC-213's stale `Proposed` status during the spec audit.  
**Current state:** The initial migration exists, creates the memory-era schema and pgvector prerequisite, and the repository has a substantial live Alembic chain. SPEC-213 confirms most of the intended implementation but explicitly records that downgrade behavior was not independently re-verified and that no drift-check CI step currently proves the ADR's `alembic check` criterion, so the ADR is not yet promoted.  
**ADR:** [ADR-012: First Alembic migration (memory tables + pgvector)](../../../adr/ADR-012-alembic-migration.md)
