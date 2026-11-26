---
inventory-delta:
  packages/maistro-core/tests: +1
---

# PG token reads are pool-shape independent (#102)

`PgDocumentState.get_tokens` indexed the jsonb `tokens` column and iterated it
directly. `maistro.persistence.get_pool` registers a JSON codec, so production
reads see the decoded array — but a raw `asyncpg.create_pool` (the conformance
suite's own pool, tools) leaves asyncpg's default `str` codec in place, and the
unpack iterated characters. The live leg
`test_authority_cutover.py::test_pg_ledger_and_document_state_survive_a_restart`
failed against a real server for exactly this reason; it had only ever been
recorded skipped (every prior validation round ran the 77-passed/19-skipped
offline shape), so the defect shipped silently in earlier rounds.

The fix routes the read through `decode_payload`
(`maistro.runs.evidence_json`) via a new `_token_pairs` helper — the store's
own stated rule ("a store may not depend on how somebody else built the
pool"). Writes were already shape-safe (`$n::text::jsonb`).

New test: `test_authority_cutover.py::test_pg_token_reads_are_pool_shape_independent`
pins the contract offline (text shape, decoded shape, non-array rejection) so
the regression does not depend on a live server to resurface.

Validation this round: live PostgreSQL 18 + pgvector (`pgvector/pgvector:pg18`),
fresh `alembic upgrade head` walks 052→053→054_learning_applicability→
055_task_admission→043_invocation_quota_door→056_backlog_work_source→
057_backlog_authority_cutover, backlog suites 94 passed + 2 skipped live,
103 passed in `tests/migrations` live.
