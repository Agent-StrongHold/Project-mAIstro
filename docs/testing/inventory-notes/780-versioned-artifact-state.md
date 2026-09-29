---
inventory-delta:
  packages/maistro-design/tests: +22
---
# Versioned creative artifact state inventory

Issue #780 adds `packages/maistro-design/tests/test_artifact_versions.py`
(+22 collected node IDs, all marked `contract: behavioral` and traced to
SPEC-092826-a780/AC-1..AC-9; +20 in the initial round plus two store-promise
tests added in the repair round below). The tests drive the real
`PgArtifactVersionStore` against SQLite file databases, including
close-and-reopen cycles, because the criteria are about what survives:
prior AI/human versions with distinct provenance, locks, guidance, and
per-branch control state across a refresh/reconnect or process restart.
No existing node IDs were removed or renamed.

## Independent verification record (job e1159b024b074099b9264c209f586f98, head d3f3aa468419)

Executed by the verifier (not trusted from the implement phase):

- `uv run pytest packages/maistro-design/tests/test_artifact_versions.py -x -q` → 20 passed.
- `uv run pytest packages/maistro-design/tests -q` → 371 passed (matches recorded inventory).
- `uv run ruff check .` → clean. `scripts/check-suite-inventory.py`,
  `scripts/check-execution-lifecycles.py` (19 classified → 19 discovered),
  `scripts/check-durable-table-inventory.py` (74 tables), `scripts/check-doc-links.py`,
  `scripts/check-vulture-baseline.py` → all pass at this head.
- Real-Postgres smoke (pgvector:pg17, `alembic upgrade head` through 047, then
  `PgArtifactVersionStore` end-to-end): three-version provenance chain, version-lock
  refusal + explicit release, decision-digest constraint, durable guidance via
  `agent_inputs`, branch-control projection of canonical `RunStatus`, and
  first-writer-wins via the real UNIQUE constraint — all passed.

Scope notes (documented, not hidden): browser-refresh projection and a
product-surface E2E are not reachable at this base (#775/#777 not landed);
SPEC-092826-a780 records a Reconciliation paragraph — forward-compatible
`brief_ref`/decision-digest inputs, not a deferral record — and AC-9's
mixed-control scenario is proven at store/service level
(`TestOneMixedControlProject`). Backend durability and the mixed-control
scenario are proven at store/service level.

### Finding (confirmed, needs repair)

`CreativeArtifactService.record_generation` (packages/maistro-design/src/maistro_design/versions.py)
never calls `_assert_not_locked`, unlike every other write path. Demonstrated
against real Postgres: a decision lock placed on a not-yet-started lineage does
not stop the first `record_generation` from landing v1 citing that decision with
a contradicting digest — no `ArtifactLockConflict`, while an identical manual
edit or refinement is refused. Version/region/branch locks are structurally
unreachable for a fresh lineage (they require an existing version/tip), so the
window is decision locks only, but it contradicts the spec Goals bullet "Locks
(version/region/decision/branch) are checked before every write" and the module
docstring "Every write checks the branch's active locks first".

## Repair record (job 4d7e250f72524359a0de4ce9f8c4727f, head 615bb73da7d0)

- The confirmed `record_generation` gap above is **fixed** (commit 615bb73da:
  the write path now checks branch/decision locks and refuses with
  `ArtifactLockConflict`). Re-proven live against real Postgres
  (pgvector:pg17, `alembic upgrade head` through 047): a decision lock on a
  not-yet-started lineage refuses the first `record_generation` citing that
  decision with a contradicting digest. A fresh 14-check live-PG smoke of
  AC-1..AC-9 (three-version provenance chain, version-lock refusal + release,
  decision-digest both directions, guidance durability + `agent_inputs`,
  fork, reopen projection, branch-lock conflict, shared export, mixed-control)
  passed 14/14 on this head.
- exact-debt-ledger: the production-only Vulture scan (`packages/*/src`) saw
  12 new identities in `versions.py` (`ControlMode.COLLABORATIVE` + 11
  `CreativeArtifactService` methods). All 12 are live contract surface —
  exercised by this file's 22 tests and waiting on #774/#777 consumers — so
  per the repo's `_vulture_*_usage` TYPE_CHECKING precedent (e1f16ddae,
  632c24c78: banking alone cannot pass the trusted-base ratchet and would
  misrecord contract surface as dead debt), a documented non-executing
  reference block keeps them visible to the scan. Bare-name matching marks
  `maistro-core` `memory/learnings/approval.py::reject` used as collateral,
  so that one reviewed ledger identity was pruned from
  `quality/vulture-baseline.json` (1402 → 1401). The gate exits 0:
  1402 reviewed identities -> 1401 findings, 0 unclassified.
- Correction to an earlier draft of this bullet: it claimed the
  `IntegrityError` translation below was "pre-existing at the merge base,
  out of repair scope". That was wrong — `version_store.py` does not exist
  at a3f6b3c (or at 9fb68e47); the file and the defect were both introduced
  by this PR's own commit 4f4f8ccc0, so the defect was in repair scope. It
  is fixed in the round recorded below.
- Re-validated on this head: `uv run ruff check .`, `uv run ruff format
  --check .`, `uv run pytest packages/maistro-design/tests -q` (371 passed),
  `check-durable-table-inventory.py` (74 tables),
  `check-execution-lifecycles.py`, `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py` — all pass.

## Repair record (job e138177b676a426ab86e3d08bb8dfc66, head bbb9b58999…)

- `PgArtifactVersionStore.append_version` no longer translates *every*
  `IntegrityError` to `ArtifactVersionExistsError`. The handler now reads the
  driver's constraint code (`pgcode` on asyncpg, `sqlite_errorname` on
  sqlite3, both normalized to SQLSTATE): a real unique violation (23505) still
  raises `ArtifactVersionExistsError` (first-writer-wins race backstop), and
  any other integrity failure — e.g. the `design_artifact_versions_project_id_fkey`
  violation for a missing parent `design_projects` row (23503) — raises
  `ArtifactVersionError` naming the constraint class, never a false "already
  exists".
- Two tests added to `TestTheStoreKeepsItsPromises` (the +2 above): the UNIQUE
  hit a pre-check misses (org is not in the key) still reads as the
  supersession conflict, and an orphan-project FK insert (SQLite FK enabled,
  parent table + seeded row) raises `ArtifactVersionError` with SQLSTATE 23503
  in the message, is not `ArtifactVersionExistsError`, and the same version
  lands once the parent row exists.
- Re-proven live against real Postgres (pgvector:pg17, `alembic upgrade head`
  through 047), probe 3/3: orphan project → `ArtifactVersionError ... (SQLSTATE
  23503)`; duplicate slot via pre-check → `ArtifactVersionExistsError`; UNIQUE
  race backstop through the except branch → `ArtifactVersionExistsError`.
- Prior-round note fixes: the "out of repair scope" claim is corrected (see
  above), and the scope note no longer claims SPEC-092826 records a deferral —
  the spec records a Reconciliation paragraph; the product-surface E2E remains
  out of reach at this base, and AC-9 stands proven at store/service level.
- Validated on this head: `uv run ruff check .`, `uv run ruff format --check
  .`, `uv run pytest packages/maistro-design/tests -q` (373 passed),
  `check-suite-inventory.py`, `check-vulture-baseline.py` (production-only
  scan, gate green), `check-durable-table-inventory.py`,
  `check-execution-lifecycles.py`.

## Verification record (job f8c74827e9b74e429ce73c1e2de52b7c, head 1ccf5b689bfe)

Independent re-verification of the e138 repair claims — nothing trusted from
the prior round, all re-executed:

- `uv run pytest packages/maistro-design/tests -q` → 373 passed; the nine
  AC test classes (`TestOneArtifactThreeVersionsWithProvenance`,
  `TestLockingAnAcceptedArtifact`, `TestLockingASharedDecision`,
  `TestGuidanceIsDurableProjectInput`, `TestForkWithoutErasing`,
  `TestControlAndLocksSurviveRestart`, `TestConflictsAreSurfacedNeverSilent`,
  `TestManualAndAgentShareOneRepresentation`, `TestOneMixedControlProject`)
  re-run explicitly → 15 passed.
- `uv run ruff check .` and `uv run ruff format --check .` → clean.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` → exit 0, 1402 reviewed →
  1401 findings, 0 unbanked (no ledger amendment required). Plus
  `check-durable-table-inventory.py` (74 tables),
  `check-execution-lifecycles.py` (19), `check-doc-links.py`,
  `check-suite-inventory.py` (14 suites) → all pass.
- Fresh live-PG probe (new pgvector:pg17 container, `alembic upgrade head`
  through 047) against `PgArtifactVersionStore.append_version` at this head,
  3/3: orphan `design_projects` id → `ArtifactVersionError … (SQLSTATE
  23503)`, not `ArtifactVersionExistsError`; UNIQUE hit the pre-check misses
  (different org, same `(project, lineage, version)` slot) →
  `ArtifactVersionExistsError` through the except branch; duplicate slot via
  pre-check → `ArtifactVersionExistsError`.
- Git evidence re-checked: `git cat-file -e` → `version_store.py` absent at
  a3f6b3c and 9fb68e47, introduced by 4f4f8ccc0 (so the repair-scope
  correction above is right); SPEC-092826-a780 line 64 is a Reconciliation
  paragraph (forward-compatible `brief_ref`/decision-digest), not a deferral
  record — matching the corrected scope note.
- Still out of reach at this base, unchanged: product-surface E2E and
  browser-refresh projection (#774/#775/#777 not landed); AC-9 remains
  proven at store/service level only.
