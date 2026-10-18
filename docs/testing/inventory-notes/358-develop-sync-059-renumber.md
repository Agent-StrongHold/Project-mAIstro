---
inventory-delta:
  tests/: 0
---

# Issue #358 develop sync — audit migration renumbered past develop's 058 tip

Merge of `origin/develop` (`a8258ee24dd9`, M9-F3 pack-activation WIP) into
`auto-358` at `95b254f514b6`, plus the collision resolution it forced. Net
suite count is unchanged: `tests/` keeps every node from both sides; no test
was added or removed by this round.

## The collision

Develop's Gauntlet-validation-provenance revision (M4-B2, #118) landed as
`058_learning_validation_provenance` while this branch's audit-index revision
(#358) sat unlanded as `058_audit_cursor_indexes` — two revisions claiming
`058` on the same parent `057`, so Alembic saw two heads. Per the convention
recorded in `tests/migrations/test_capability_invocation_effect_index_migration.py`
(every develop collision re-parents the branch-side unlanded revision onto the
deployed tip), the audit indexes move past develop's tip as
`059_audit_cursor_indexes` (`down_revision = "058"`). Develop's deployed
revisions are untouched; the single linear head is `059`.

## Conflict resolutions

- `tests/migrations/test_capability_invocation_effect_index_migration.py` —
  both sides rewrote the chain-walk comment and assertions. Merged narrative:
  develop's full collision history ending at
  `058_learning_validation_provenance`, continued by this lane's unlanded
  audit indexes as `059`. The walk runs `base`→`059`; parent chain
  `…056 → 057 → 058 → 059` with both filename pins; one head `059`.
- `tests/migrations/test_task_admission_generation_upgrade.py` — took the
  head-tracking assertion (`_stamped_version() == _chain_head()`, develop's
  side) over this branch's fixed `version_before` literal; the literal has
  rotted on every prior collision and the head-resolved form subsumes the
  transactionality invariant. Dropped the now-unused `version_before` local.
- `tests/migrations/test_audit_cursor_indexes.py` — pins the audit DDL
  contract to the renumbered file (`059_audit_cursor_indexes.py`,
  `revision == "059"`, `down_revision == "058"`).

## Evidence

- `alembic get_heads` → `['059']`.
- `tests/migrations/` — 150 passed against PostgreSQL 18 (docker
  `pgvector/pgvector:pg18`), covering the resolved files and the full-chain
  upgrade/downgrade through `059`.
- `uv run alembic upgrade head` on a fresh database → `…057 -> 058 (Learning
  validation provenance) -> 059 (Ordered exact-scope audit cursor indexes)`.
- `packages/maistro-core/tests/persistence` — 825 passed, 84 skipped on PG;
  `test_audit_pages.py` 16/16 including the PostgreSQL million-row envelope.
- Full `scripts/check-suite-inventory.py` (CI invocation, no args): 16 suites
  match the recorded inventory.
