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

**Residual — CORRECTED in round 3 (was: "unsatisfiable floor").** The round-2
residual below described `design_coverage` as unsatisfiable trunk drift (floor 38.4867,
develop measuring 33.9609). That measurement was an environment artifact, not trunk
state: it was taken **without a PostgreSQL server**, and the AC-outcome plugin counts a
*skip* as not-passing — exactly the trap `quality.yml`'s quality-gate job documents
(#328: "without a server, every criterion whose evidence needs one is unprovable
here"). Re-measured at CI parity (live `pgvector/pg18`, `MAISTRO_TEST_PG_DSN` +
`DATABASE_URL`, `--all-extras`, age + maistro-evolve installed), the merged #774 tree
measures **39.1237** — above the 38.4867 fold — deterministically across repeated
runs. The gate's only remaining complaint was the *unbanked improvement*, resolved by
banking `quality/ac-state-notes/auto-774.json` (`design_coverage: 39.1237`, measured
with tests). The full `--run-tests --ratchet --mandate origin/develop` invocation now
exits 0. No trunk-side correction is needed; the round-2 claim is retained below as
the provenance of the correction.

> Round-2 claim (superseded): the fold at develop `9fe61e216` takes `auto-374`/
> `auto-1096`'s banked 38.4867, but develop's own tree was measured at 33.9609
> (at tip `b9bcdd255`) and the merged #774 tree at 34.5978; both numbers are the
> no-database undercount, as established above.

## CI-repair round 3 (SAST + ratchet at merge `a58815784`, develop sync to `088cc1ef0`)

- **Develop sync**: `origin/develop` advanced to `088cc1ef0` mid-round (second
  collision in a row). #398's `048_canvas_job_retry_backoff` claimed the head the
  round-2 renumber had taken, so the briefs migration is renumbered again to
  `049_design_creative_briefs` (`down_revision = "048"`); `SPEC-092826` follows.
  No test node IDs moved; `tests/migrations` re-run 100/100 against live
  PostgreSQL with `alembic upgrade head` applying `…047 → 048 → 049`.
- **SAST repair (real, not cosmetic)**: round 2's semgrep fix rewrote
  `text(f"…")` as `text(_SELECT_FROM + "…")` — still a non-literal argument, still
  matching `python.sqlalchemy.security.audit.avoid-sqlalchemy-text` (verified by
  running the registry configs locally: 3 blocking findings at brief_store.py).
  The three read statements are now each one full plain string literal
  (`_GET_SQL`/`_LATEST_SQL`/`_VERSIONS_SQL`); behavior is unchanged (whitespace
  only — Postgres semantics identical) and the whole suite re-proves it:
  `p/security-audit + p/owasp-top-ten + p/secrets` over `packages/ tests/` =
  **0 findings**; bandit Medium+ = **0**; gitleaks over `origin/develop..HEAD` =
  **no leaks** (gitleaks 8.30.1, same pin as CI).
- **Acceptance-state ratchet**: the round-2 blocker is resolved as described in
  the correction above — measured **39.1237** at CI parity, banked to
  `quality/ac-state-notes/auto-774.json`; `--run-tests --ratchet --mandate
  origin/develop` exits 0 (10 debt counters on their ceilings, the progress
  counter exactly on its floor, mandate 14/14, chain clean).
- **Diff coverage** re-proven at this round's tree *and* at CI parity (the
  coverage-gate job has no Postgres): every measured changed file ≥ 90% lines /
  80% branch arcs (`__init__.py` 100%, `brief_store.py` 98.4% lines without PG,
  `brief.py` 98.3%, `protocols.py` 100%).
- Vulture per-identity ledger (the named CI-repair gate) exits 0
  (1374 reviewed identities → 1372 findings); no baseline amendment required —
  the two eliminated findings were not banked identities.
- **Measurement hygiene (proven the hard way):** re-running the gate against the
  same database *after* the design suite and `tests/migrations` (whose
  upgrade/downgrade cycles rewrite the schema) measured **34.6668** — shared
  mutable DB state undercounts and breaks the exact-equality bank. CI is immune
  (fresh service container, one `alembic upgrade head`, one measurement). Local
  reproduction must recreate + re-migrate the database per measurement; done,
  the committed head then measures **39.1237** and the gate exits 0.

## Round 4 (develop sync: resolve the CreativeBrief contract collision)

`origin/develop` landed e5c461087 (PR #1695, WIP parent-epic #773) ahead of
this child lane: a second, dataclass-based CreativeBrief prototype
(`maistro_design/creative_brief.py`, in-memory store only, V105-marked
retained API) colliding with this lane's contract in
`maistro_design/__init__.py` and `tests/test_creative_brief.py`. The merge
(`e48e16266`) resolves in favor of the #774 implementation, per the
acceptance criterion that ONE schema/model and persistence contract owns
CreativeBrief domain state:

- kept `brief.py` + `brief_store.py` + migration `049_design_creative_briefs`
  + the three-suite test pyramid; removed `creative_brief.py` (develop-side
  consumers were only its own `__init__` re-exports and its own test file —
  no other develop code imports it; provenance preserved at e5c461087);
- removed the two develop inventory notes that recorded the removed suite's
  deltas (`773-creative-brief-projection.md` +42, `auto-773-48e0.md` +1), so
  the ledger sum matches collection again; this note's +59 holds (46
  contract + 12 store + 1 PG node IDs, unchanged);
- reverted the `pyproject.toml` `V105` ruff-external hunk: it existed solely
  for `creative_brief.py`'s `noqa: V105` markers; `brief.py` holds its
  identities via the documented `_vulture_usage` TYPE_CHECKING block;
- took everything else from develop as-is, including the #1769 revert of the
  principal-identity/route-permissions ratchets and the ADR-131 changes.

Re-validated on the resolved tree (not inherited from round 3):

- `uv run ruff check .` and `ruff format --check .` clean (2713 files);
- `packages/maistro-design/tests`: 409 passed, 1 skipped (PG leg); the 58
  node IDs of `test_creative_brief.py` + `test_creative_brief_store.py` were
  also run as the explicit acceptance set (58 passed);
- the named CI-repair gate `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exits 0: 1374 reviewed
  identities -> 1372 findings, 0 unclassified. Removing `creative_brief.py`
  resurrected nothing: `brief.py`'s same-named `_require_non_blank` helper
  still masks the `workspaces/model.py` field-validator identity, and no
  creative_brief identity was ever banked in either parent's ledger. No
  ledger amendment required;
- `check-suite-inventory.py` ok (14 suites match — the removal of the +43
  delta notes exactly matches the removed tests);
- `check-reachability.py` exit 0 (1170 modules); `check-merge-markers.py`,
  `check-cross-package-imports.py` (2725 files),
  `check-durable-table-inventory.py` (79 tables), and
  `verify-monorepo-layout.sh` all exit 0;
- live PostgreSQL (fresh `pgvector/pg18` container): `alembic upgrade head`
  applies the merged chain through `049_design_creative_briefs` (develop's
  047 revocations + 048 canvas backoff, then the briefs migration — one
  linear head), `tests/migrations` 100/100, and
  `test_creative_brief_pg.py::test_brief_round_trips_through_postgres`
  passes. DSN note for reproducers: `MAISTRO_TEST_DATABASE_URL` must be a
  plain `postgresql://` URL for the `tests/migrations` and store legs (they
  hand it to asyncpg/alembic directly); only the design PG leg accepts a
  `postgresql+asyncpg://` scheme;
- merge-touched suites from the develop side re-run green:
  `maistro-core` chat-admission/container-chat-run/identity suites plus
  `hive-conductor` chat-run admission = 170 passed;
- a direct behavioral probe against the resolved production module
  (independent of the test suite) re-proved: two artifact branches receive
  byte-identical `shared_context()` with only `artifact_request` differing;
  a creative-context redirect mints v2 (`supersedes_brief_id`, same
  lineage/Goal revision) with v1 untouched; a Goal-revision change (3 -> 4)
  is a new version without rewriting v1/v2; projections carry
  Goal+brief+Persona+DS versions verbatim; explained `copy_variant`
  overrides apply while `cta`/`goal_revision`/`audience`/`required_facts`
  overrides are refused as protected (notably `cta` itself is protected —
  channel branches cannot rewrite the shared CTA); a cross-Workspace
  persona reference is rejected at construction; the schema carries no
  authorization vocabulary.


## Round 5 (CI-repair: restore the V105 ruff-external registration the round-4 merge over-reverted)

The verifier's deterministic check flagged `RUF102 Invalid rule code in
`# noqa`: V105` at `maistro_design/consistency.py:105`. Root cause: the
round-4 merge resolution reverted the `V105` entry from pyproject
`[tool.ruff.lint] external` believing the removed develop prototype
`creative_brief.py` was its only user — but develop-side PR #1663
(`bebc51fd8`, cross-artifact consistency) had independently landed a second
legitimate user: the Pydantic-dispatched `ClaimRule._require_evidence_backing`
validator carries `# noqa: V105` (vulture "unused method") per the
[779 note](779-cross-artifact-consistency.md), which states those markers
assume "codes registered in ruff `external`". Dropping the marker instead
would have surfaced `_require_evidence_backing` as a new unbanked vulture
identity, failing the exact-debt-ledger gate; re-registering the code is the
state the 779 note documents as intended.

- `pyproject.toml`: `external` is again `["V102", "V105", "V106", "V107"]`,
  with a comment naming the consistency.py marker and the round-4
  over-revert. No suppression semantics changed: RUF102 external registration
  only teaches Ruff that V105 is a valid external-analyzer code; the vulture
  per-identity ledger still enforces every identity.
- `quality/vulture-baseline.json`: **unchanged** — the gate re-run exits 0
  (1371 reviewed identities -> 1370 findings, `unclassified: 0`,
  `never_allowlist: 0`), so no amendment was needed in this CI-repair round.

Re-validated on the repaired tree:

- `uv run ruff check .` clean; `ruff format --check .` clean (2721 files);
- `uv run pytest packages/maistro-design/tests -x -q`: 428 passed, 1 skipped
  (PG leg); the explicit acceptance set (`test_creative_brief.py` +
  `test_creative_brief_store.py`) is 58 passed;
- the named CI-repair gate `check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` exits 0;
- canonical `uv run mypy` over core/server/turing/canvas/bootstrap/registry:
  no issues in 745 source files;
- `check-suite-inventory.py` (14 suites), `verify-monorepo-layout.sh`, and
  `check-merge-markers.py` all exit 0.

## Repair round (auto-780 develop sync, merge of `33bcd3ce28`)

The auto-780 (#780) branch's develop sync merged the CreativeBrief work and
collided the migration head a third time: #780's
`049_design_artifact_versions` had already taken `049` (renumbered there from
`048` by the same convention). Per the one-linear-head convention the briefs
migration is renumbered once more to **`050_design_creative_briefs`**
(`down_revision = "049"`); the effect-index chain test now walks to `050` and
asserts `get_heads() == ["050"]`, `SPEC-092826` follows. No test node IDs
moved; the inventory delta (+59) is unchanged.

## Round 6 (develop sync at the #792 repair: the briefs migration re-parents onto the eval 049 as 050)

The #792 lane's develop sync merged `origin/develop` (tip `33bcd3ce288`) into
`auto-792` and preserved the conflict for resolution. Both branches had taken
revision `049` on the same parent `048` — this contract's
`design_creative_briefs` on develop, the canonical Run eval-score evidence on
the #792 branch — so `get_heads()` answered `["049", "049"]` and Alembic's
script directory refused the duplicate. Per the same one-linear-head
convention the rounds above document, the eval-score migration keeps `049`
(it re-parented onto 048 first, in the #792 lane's round 2) and the briefs
migration is renumbered to **`050_design_creative_briefs`**
(`down_revision = "049"`). The effect-index chain test now walks to `050`,
asserts `get_heads() == ["050"]`, and its resolution comment names the
collision. `SPEC-092826`'s "migration 049" mention follows the renumber. No
test node IDs moved; this note's inventory delta (+59) is unchanged.

## Round 7 (auto-780 develop sync of the #792 repair: the eval evidence re-parents onto this branch's `050` as `051`)

Merging the #792 eval-on-run work into auto-780 collided the head a fourth
time, from the other side: this branch's `049_design_artifact_versions` (#780)
and the eval-score migration had both taken `049` on the same parent `048`,
and this branch's `050_design_creative_briefs` already continued that `049`.
Per the same one-linear-head convention, the branch's own chain stands
(`049` artifact versions -> `050` briefs) and the incoming eval-score
migration re-parents onto that `050` as **`051_canonical_run_eval_scores`**
(`down_revision = "050"`; Round 6's opposite numbering was the auto-792
lane's resolution and is superseded on this branch). The effect-index chain
test now walks to `051` and asserts `get_heads() == ["051"]`;
`test_migration_chain`'s eval-table comment and `retention_scope`'s policy
comment follow the renumber. No test node IDs moved; the inventory deltas are
unchanged.

## Round 8 (auto-117 develop sync: the knowledge-stage ladder re-parents onto `051` as `052`)

Merging develop into auto-117 (M4-B1, #117) collided the head a fifth time:
this branch's knowledge-stage ladder — re-parented onto `050` as `051` in
Round 7's world — met develop's own `051_canonical_run_eval_scores` sitting
on the same parent. Per the one-linear-head convention the develop chain
stands and the ladder re-parents onto that `051` chain tip as
**`052_learning_stage_ladder`** (`down_revision = "051"`). The effect-index
chain test walked to `052` and asserted `get_heads() == ["052"]`, and the
ladder's own live-pgvector round trip upgrades/downgrades `051`↔`052`.
Round 7's head-`051` statement is superseded on this branch. No test node
IDs moved; the inventory deltas are unchanged.

Update (auto-119 develop sync, M4-B3 merge): #119's applicability migration
had also taken `052` on parent `051`, the same collision; it re-parents onto
the ladder as **`054_learning_applicability_epistemics`**. The chain test now
walks to `054` and asserts `get_heads() == ["054"]`; every assertion this
round added still holds with `052` an interior revision.
