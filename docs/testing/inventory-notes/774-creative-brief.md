---
inventory-delta:
  packages/maistro-design/tests: +58
---
# 774-creative-brief — issue #774: the versioned CreativeBrief contract

Fifty-eight maistro-design node IDs, all additive, holding the three layers
the CreativeBrief contract (#774) actually lives in. No other suite moved.

- `test_creative_brief.py` (+45): the domain contract. Every brief references
  the canonical Goal identity plus its exact revision (validated against
  `INTEROP_ONTOLOGY_V1`, so a Goal without its Project or a Workspace-less
  Project is refused); Persona and Design System are versioned references,
  never copies; versions are frozen, so an update is `new_version()` — which
  mints identity/provenance and cannot move scope — and a projection derived
  before a redirect still cites the version it consumed. Two artifact
  branches assert `shared_context()` equality while differing only in
  explicit request/overrides; overrides without a reason, or against
  protected shared context, are domain errors. The authorization criterion is
  held negatively in two ways: no model field may share vocabulary with
  grants/capabilities/bindings/approvals, and `extra='forbid'` rejects an
  authorization payload riding along on a brief. Refusal shapes carry the
  module-level `contract("boundary")` marker; the tests that assert what the
  system *does* (version minting, projection derivation, redirect
  provenance) additionally carry `contract("behavioral")` per ADR-032.
- `test_creative_brief_store.py` (+12): the SQL the store composes and the
  guards around it, against a real SQLite schema — every operation takes the
  caller's `workspace_id` keyword-only, another Workspace reads as absent, a
  Project registered elsewhere (or nowhere) is a cross-Workspace refusal, and
  a duplicate `(lineage_id, version)` is a `BriefVersionConflictError`
  (first writer wins), not a silent overwrite. The read/commit/ordering
  behaviors carry `contract("behavioral")`.
- `test_creative_brief_pg.py` (+1): the created-row round-trip the SQLite
  shim cannot express (`CAST(:payload AS jsonb)`); create → get →
  `new_version` → `latest`/`list_versions`, the unique-version race, and the
  cross-Workspace refusal against real PostgreSQL under the migration chain.
  Skips without `MAISTRO_TEST_DATABASE_URL`, like the rest of the PG legs.

## CI-repair round (this head)

No tests added, removed, or changed in this round — the `inventory-delta`
above is unchanged. The repair addressed the deterministic gate failures on
this head only:

- `SPEC-092826` front-matter gained the required `layer: Ability` and
  `owners:` fields (matching the sibling Design Studio specs). `uv run python
  tools/lint_lifecycle.py` and `uv run python -m maistro_registry.cli lint .
  --strict` both exit 0 (414 files clean).
- The 15 vulture identities in `brief.py` are live contract surface (pydantic
  model validators, declarative fields read reflectively, and the
  `shared_context()` two-branch seam the tests assert on), so per the repo's
  `_vulture_*_usage` TYPE_CHECKING precedent (e1f16ddae) they are referenced
  by a documented non-executing block instead of being banked as reviewed
  debt. Two `core-public-api-surface` ledger entries were pruned because their
  findings no longer exist: `workspaces/model.py::_require_non_blank` (already
  referenced elsewhere in-scope before this round) and
  `scheduling/model.py::_validate` (vulture matches by bare name, so the
  block's `_validate` references mark it used; the rationale is recorded in
  the block's docstring). `check-vulture-baseline.py` exits 0: 1402 reviewed
  identities → 1400 findings, 0 unclassified.
- `brief.py`'s `maistro.interop` import makes `maistro.interop` and
  `maistro.interop.contract` runtime-reachable, so both were pruned from the
  reachability baseline and the obsolete `interop-contract` LIBRARY
  disposition was removed. `check-reachability-provenance.py`,
  `check-reachability-dispositions-provenance.py`, and the full
  `check-ratchet-provenance.py` inventory all exit 0.
- The PostgreSQL leg was re-proven on a live server: `alembic upgrade head`
  applies the chain through 047 ("Durable CreativeBrief versions"),
  `tests/migrations/test_migration_chain.py` 13/13 pass, and
  `test_creative_brief_pg.py::test_brief_round_trips_through_postgres` passes
  against the migrated database.
