---
inventory-delta:
  packages/maistro-core/tests: +6
---
# auto-42 durable effect-scope claim (L42 repair, head 2a549ae0 + this round)

Repair round closing the previously recorded residual risk: the durable
capability Invocation stores' partial unique index
`uq_capability_invocation_active_effect` was keyed on
`(run_id, node_run_id, binding_id, effect_key)`, so the database-level hard
guarantee did not span NodeRun visits even though `list_effect` and the
in-memory store scoped the identity logically (`effect_scope or node_run_id`).

## Defect reproduced, then fixed (evidence-first)

- Reproduction at the incoming head (scratch script, not committed): two
  services on separate connections to one SQLite file dispatch the same stable
  logical effect (same `effect_scope`) under different NodeRun/Attempt
  identities concurrently → **dispatches=2**, two COMPLETED rows. The prior
  finding was real and unaddressed at the durable layer.
- Fix (all three schema truths agree): the claim index is now
  `(run_id, effect_scope, binding_id, effect_key)` and its predicate covers
  every non-FAILED status; every write normalizes an empty scope to
  `node_run_id`, making the column total and the index equal
  `Invocation.effect_identity`:
  - `packages/maistro-core/src/maistro/capabilities/invocation_store.py`:
    `_TABLE_DDL`/`_CLAIM_DDL` split, `UPDATE ... SET effect_scope = node_run_id
    WHERE effect_scope = ''` backfill, `DROP INDEX IF EXISTS` +
    scope-keyed `CREATE UNIQUE INDEX` (in-place migration pattern of
    `idx_canonical_runs_occurrence`), scope-keyed admission SELECT in
    `create`, normalized scope in `save`/`_row_values`.
  - `packages/maistro-core/src/maistro/capabilities/pg_invocation_store.py`:
    same `_CLAIM_DDL`, column ALTERs ordered before the backfill/index,
    `_find_effect` keyed by logical scope.
  - `alembic/versions/035_capability_invocations.py`: deployment schema truth
    set to the same final shape; databases already migrated by the earlier
    035 revision are reconciled at runtime by `PgInvocationStore.ensure_schema`.
- Predicate subtlety found by real-PostgreSQL verification: an
  `('created','running','unknown')`-only predicate (the original shape) lets a
  later cross-NodeRun visit slip past the index after the first visit
  terminalized to COMPLETED, re-dispatching the effect. The predicate now
  includes `completed`; a proven-FAILED record still admits a new
  chronological visit, and `InvocationExecutionService.invoke`'s
  `UnsafeEffectRetry` handler re-reads scoped history so a lost race returns
  the completed result instead of double-dispatching.
- Post-fix reproduction: **dispatches=1**, loser refused with
  `UnsafeEffectRetry`, one scoped history row.

## Executed evidence at this round's head

- Real PostgreSQL (`pgvector/pgvector:pg18` container, removed afterwards):
  `tests/migrations` **96 passed**; conformance script against the live server:
  scope-keyed index created with the four-status predicate, concurrent
  cross-NodeRun race → 1 dispatch, legacy-shape database (pre-scope 035 DDL)
  reconciled in place (backfill verified, index replaced, backfilled row
  honored by the claim).
- pytest: capabilities **345 passed** (includes 6 new regression tests:
  SQLite cross-NodeRun claim refusal + service-level dedupe + legacy-schema
  migration; PG cross-NodeRun refusal + completed-claim refusal + service-level
  dedupe); graph + runs + a2a **2474 passed**; maistro-server **394 passed**.
- `ruff check .` clean; `ruff format --check .` clean (2589 files); mypy over
  the six src trees clean (723 files).
- Gates: `check-execution-lifecycles` PASS (19 classified, 0 violations);
  `check-lifecycle-provenance` PASS; `check-shipped-surface-truth` PASS;
  `check-suite-inventory` PASS after this note records the +6.

## Prior findings re-verification

- Invocation/pg-store/migration uniqueness finding: **closed by this round**
  (reproduced → fixed → regression-locked, real-PG evidence above).
- Debt ledger: `check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` still exits 1 on exactly one identity —
  `create_a2a_task` — against the **trusted base** only. The candidate ledger
  banks it (`quality/vulture-baseline.json`, rules[0]/findings) and the
  reviewed grant is committed (`quality/ratchet-authorizations.json`, #42).
  `scripts/ratchet_provenance.load_authorizations` reads grants **from the
  base revision by design** ("a new grant does not take effect in the change
  that introduces it", #534), so this axis turns green only at integration
  when the grant is prior at the trusted base. This round's fix eliminated no
  scanned identities; no further ledger amendment was possible or needed.
- Upstream (re-checked read-only in the prior round, unchanged policy here):
  #1169 CLOSED, #1170 CLOSED, #1194 OPEN — the #1194 contract is shipped and
  now DB-enforced; administrative closure remains an orchestrator action.
