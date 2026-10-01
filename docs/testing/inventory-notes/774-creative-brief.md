---
inventory-delta:
  packages/maistro-design/tests: +59
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

The package-surface case in `test_creative_brief.py`
(`test_package_surface_lazy_loads_the_brief_contract`) was extended — not
added — to also cover the `__getattr__` fall-through to `AttributeError` and
the `PgDesignProjectStore` lazy branch. Still +59 node IDs (suite-inventory
holds at 410), so the `inventory-delta` above is unchanged. This completed the
diff-coverage repair: the prior surface test covered the two new `if`-True
arcs but left the fall-through branch arc uncovered (75% < 80%); the extension
takes `__init__.py` changed-branch coverage to 100%. No new test functions
were added. The remaining deterministic gate failures on this head were
addressed as follows:

- `brief_store.py` composes all SQL from module-level literal constants (`_INSERT_SQL`,
  `_GET_SQL`, `_LATEST_SQL`, `_VERSIONS_SQL`) with bound parameters only — no
  f-string/concatenated SQL reaches `text()`, clearing the three
  `python.sqlalchemy.security.audit.avoid-sqlalchemy-text` SAST findings.
  `uvx semgrep --config p/security-audit` on the store is 0 findings; `bandit`
  Medium+ is 0.
- `test_creative_brief.py` `test_package_surface_lazy_loads_the_brief_contract`
  was extended to cover the `__getattr__` fall-through (`AttributeError`) and
  the `PgDesignProjectStore` branch, completing the diff-coverage repair of
  `maistro_design/__init__.py`: changed branch arcs go 75% → 100%
  (`check-diff-coverage.py` reports OK on every touched maistro-design file).

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

## CI-repair round 2 — develop sync (merge `a9d243ef1` onto develop `9fe61e216`)

The previous launch died in preflight: the driver's orphan-rebuild patch was corrupt
("corrupt patch at line 526123"), leaving an index that matched no ref (staged = a
partial develop tree; worktree = this branch's HEAD, byte-identical except the repair
plan). Salvage: both diffs + the plan are preserved verbatim under the job directory
(`salvage/incoming-774-{staged-index-vs-HEAD,unstaged}.patch`); the worktree was then
normalized to HEAD (nothing unique was lost — the disk differed from HEAD only by the
untracked plan file) and develop was merged properly instead.

The only merge conflict was the predicted migration collision: develop's
`047_capability_binding_revocations` (#1133) and this branch's
`047_design_creative_briefs` both claimed `down_revision = 046`. Per the chain's
one-linear-head convention the briefs migration is renumbered to
**`048_design_creative_briefs`** (`down_revision = "047"`); the effect-index chain test
now walks to `048` and asserts `get_heads() == ["048"]`. `SPEC-092826`'s "migration
047" mention follows the renumber. No test node IDs moved; the inventory holds.

A second develop sync (round 3, develop tip `51c0e1188`) collided the same way
once more: #398's `048_canvas_job_retry_backoff` claimed the head this branch's
renumber had taken. Per the same one-linear-head convention the briefs migration
is renumbered again to **`049_design_creative_briefs`** (`down_revision = "048"`);
the effect-index chain test now walks to `049` and asserts `get_heads() == ["049"]`,
and `SPEC-092826`'s "migration 048" mention follows. No test node IDs moved.

Re-executed on the merged head:

- `uv run ruff check .` / `ruff format --check .` clean (2693 files); `uv run pytest
  packages/maistro-design/tests` 409 passed + PG leg 1 passed (live server), 1 skipped
  without a server; `tests/migrations/` **100/100 pass against live PostgreSQL** —
  `alembic upgrade head` applies `…046 → 047 (revocations) → 048 (canvas backoff) →
  049 (briefs)`, and
  `test_migration_chain.py` asserts both new tables in the live catalog.
- The whole deterministic Quality-gate step list re-run green: radon ratchet,
  version consistency, release consistency, doc links, enumerations, vendored IFEval
  and BFCL provenance, xenon (67 ≤ 77), **vulture per-identity ledger (the named
  CI-repair gate — exits 0)**, reachability, credential authority, wiring reads,
  agent-store writes, contract markers, convergence matrix, reachability dispositions,
  security/image inventories, backlog consistency, execution lifecycles, model egress,
  `mypy --strict packages/maistro-core/src`, pyright (21 = baseline 21), `formal/`
  (663 passed), fitness (22 passed), suite inventory (14 suites), lifecycle lint,
  registry lint `--strict`, merge markers, cross-package imports, durable-table
  inventory, monorepo layout.
- The acceptance-state **mandate** halves are green (14 criteria this change declares:
  all proven; chain: no orphan spec/ADR/criterion-less doc introduced).
- The diff-coverage failure stays fixed: `maistro_design/__init__.py` measures 100%
  (29 stmts / 0 miss) under `coverage run --branch`.

**Residual (inherited, not #774 debt):** the acceptance-state ratchet's
`design_coverage` floor is unsatisfiable at this base for *any* candidate. The fold at
develop `9fe61e216` takes `auto-374`/`auto-1096`'s banked **38.4867**, but develop's own
tree now measures **33.9609** (measured at develop tip `b9bcdd255`: 157 decisions, 92
at zero — the M3-C6/M7-A doc merges added Accepted ADRs without proportional proof).
The merged #774 tree measures **34.5978 — strictly above develop**, and the single
per-decision delta is this lane's own contribution (ADR-036: 0.0 → 100.0 from
SPEC-092826's 14 reachable criteria). Closing the remaining ~3.9 points would mean
proving ~6 other epics' Accepted ADRs (out of lane scope), and the sanctioned
corrections (`--bank` writes only this branch's note; grants are read at the base, and
no `ac-state` grant exists there) cannot lower a `max`-folded floor from a candidate
commit by design. This needs a trunk-side correction (prove decisions up or a
develop-landed grant) — recorded here as the handoff, not gamed in this lane.
