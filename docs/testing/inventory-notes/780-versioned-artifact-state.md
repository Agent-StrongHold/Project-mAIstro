---
inventory-delta:
  packages/maistro-design/tests: +20
---
# Versioned creative artifact state inventory

Issue #780 adds `packages/maistro-design/tests/test_artifact_versions.py`
(+20 collected node IDs, all marked `contract: behavioral` and traced to
SPEC-092826-a780/AC-1..AC-9). The tests drive the real
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
SPEC-092826 records the deferral. Backend durability and the mixed-control
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
  exercised by this file's 20 tests and waiting on #774/#777 consumers — so
  per the repo's `_vulture_*_usage` TYPE_CHECKING precedent (e1f16ddae,
  632c24c78: banking alone cannot pass the trusted-base ratchet and would
  misrecord contract surface as dead debt), a documented non-executing
  reference block keeps them visible to the scan. Bare-name matching marks
  `maistro-core` `memory/learnings/approval.py::reject` used as collateral,
  so that one reviewed ledger identity was pruned from
  `quality/vulture-baseline.json` (1402 → 1401). The gate exits 0:
  1402 reviewed identities -> 1401 findings, 0 unclassified.
- Observation recorded, NOT changed this round (pre-existing at the merge
  base, out of repair scope): `PgArtifactVersionStore.append_version`
  translates *every* `IntegrityError` to `ArtifactVersionExistsError`
  (version_store.py `except IntegrityError`); a live FK violation
  (`design_artifact_versions_project_id_fkey`, no parent `design_projects`
  row) surfaces as "version already exists". A unique-vs-FK split (pgcode
  23505 vs 23503) would surface integrity conflicts more precisely.
- Re-validated on this head: `uv run ruff check .`, `uv run ruff format
  --check .`, `uv run pytest packages/maistro-design/tests -q` (371 passed),
  `check-durable-table-inventory.py` (74 tables),
  `check-execution-lifecycles.py`, `check-ratchet-provenance.py`,
  `check-shipped-surface-truth.py` — all pass.
