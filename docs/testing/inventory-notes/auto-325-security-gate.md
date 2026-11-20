---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-325 salvage round: bandit-clean nosec placement + honest absent-table probe

Two-part salvage of the security-gate failure recorded on d33f3b4bf
(SAST / Bandit: 4× B608 Medium findings). The `# nosec B608` annotations on the
three SQLite purge statements (`events/durable_log.py`, `events/envelope.py`,
`persistence/sqlite_audit.py`) sat on the line *above* the flagged statement,
where bandit does not see them; they moved onto the flagged lines. No statement
text changed. The fourth finding (`observability/metrics.py`) hid a real bug
behind the same misplacement: `postgres_table_sample` guarded the existence
check with `if not await fetchrow(...)`, but asyncpg answers
`SELECT to_regclass($1) IS NOT NULL AS ok` for an absent table with a truthy
one-row record whose `ok` field is `False` — so the guard never fired and the
probe queried an unprovisioned table (raising on a real backend) instead of
reporting the honest `None` its contract states. The guard now consults the
field (`exists is None or not exists["ok"]`).

New tests in
`packages/maistro-core/tests/observability/test_retention_health.py` (+2),
pinning the repaired contract at the fake `fetchrow` boundary:

- `test_a_postgres_sample_of_an_absent_table_is_none`: the `ok=False` record
  yields `None` and the probe never issues the count query. Against the
  pre-fix code this fabricates a full sample (`rows=7, total_bytes=4096`) for
  a table that does not exist — demonstrated by running the identical scenario
  against the committed module.
- `test_a_postgres_sample_of_an_unanswered_existence_check_is_none`: a boundary
  that cannot answer the existence check at all (`None`) yields no sample
  either.

Both assert structure (which queries were issued), not wall-clock timing.
