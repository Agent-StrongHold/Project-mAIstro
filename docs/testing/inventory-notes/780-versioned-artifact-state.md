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
