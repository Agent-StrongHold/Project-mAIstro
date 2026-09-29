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

## Independent verify round (develop-merged head `b0e44b8c1ab2`)

Re-executed locally at the develop-merged head; no tests added, removed, or changed.

Passing, executed:

- `uv run pytest packages/maistro-design/tests` — 408 passed, 1 skipped (the PG leg, no
  server configured); the 58-test inventory delta passes inside it.
- PostgreSQL leg re-proven on a live server: `alembic upgrade head` applies the chain
  through `047`, then `test_creative_brief_pg.py::test_brief_round_trips_through_postgres`,
  `tests/migrations/test_migration_chain.py` (13/13), and
  `tests/migrations/test_capability_invocation_effect_index_migration.py` (2/2) all pass.
- `tools/lint_lifecycle.py` and `maistro_registry.cli lint . --strict` exit 0 (414 clean).
- `ruff check .`, `ruff format --check .`, CI-scope `uv run mypy` (727 files),
  `verify-monorepo-layout.sh`, `check-merge-markers.py`, `check-cross-package-imports.py`
  (2638 files), `check-suite-inventory.py`, `check-durable-table-inventory.py`,
  `check-reachability.py` plus `check-reachability-provenance.py` /
  `check-reachability-dispositions-provenance.py`, and `check-ratchet-provenance.py`
  all exit 0.

Correction — vulture scope: the "exits 0" claim above holds only for the debt this PR
owns. At this head both scan scopes exit 1 on debt the PR does not own: with
`packages/*/src --min-confidence 60`, 60 NEW identities, all under
`packages/maistro-evolve/.../third_party/`; with the canonical bare invocation
(`vulture packages tests ...`, what CI runs), 51 NEW / 69 stale-ledger paths. Their
intersection with this PR's 16-file diff is zero (one path, `maistro_server/main.py`,
arrives with develop's own merged commits). The trusted ledger at `origin/develop` is
stale against develop's own tree, so the residual redness is inherited base drift, not
#774 debt: the maistro-design scan contribution at this head is zero findings, zero
unclassified, and the brief-contract identities stay held by the documented
`_vulture_*_usage` block.

Provenance audit: the PR body ("Refs #774", draft claim-stake) and every commit body on
the branch contain no GitHub closure keywords (`fixes/closes/resolves #N`).
