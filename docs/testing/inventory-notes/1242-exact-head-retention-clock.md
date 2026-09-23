---
inventory-delta:
  packages/maistro-core/tests: +2
---

# #1242 exact-head verification — retention cutoff on the database clock

The exact-head `uv run pytest -x -q` for #1242 failed once, on
`packages/maistro-core/tests/persistence/test_pg_sessions_concurrency.py:89`:
`test_retention_sweep_cannot_delete_fresh_concurrent_appends` read `[]`
instead of seq 0..7. An isolated rerun passed, so the run-to-run difference
was not scheduling — it was clocks.

`PgSessionStore` stamps `sessions.timestamp` and `session_turns.timestamp`
with the database's `now()` server default, but every retention decision
computed its cutoff from the client's `time.time()` and shipped it as a
literal (`to_timestamp($1)`). A client clock running ahead of the server by
more than the TTL — the WSL-after-host-sleep class of skew this host is
known for — pushed the cutoff into the server's future, and a retention
sweep then deleted rows the server had stamped moments earlier. That is the
flake: live conversation deleted by drift, and the concurrency test caught
it because it genuinely races a purge against fresh appends.

The fix moves the cutoff arithmetic onto the clock that stamped the rows:
`timestamp <= now() - make_interval(secs => $1)` with the TTL as the
parameter, in `_purge_through` (both DELETEs) and the `get_history` TTL
filter. Client skew is no longer an input to any retention decision. The
explicit-zero "purge through now" contract keeps working — inside one
transaction `now()` is the transaction timestamp, the same instant that
stamped the rows, and the documented zero/negative TTL still means "purge
everything".

## The two tests (+2 node IDs in `packages/maistro-core/tests`)

- `test_retention_cutoff_is_derived_from_the_database_clock`
  (`tests/persistence/test_pg_sessions.py`) — pins that the purge DELETEs
  carry no `to_timestamp` client literal, derive the cutoff from
  `now() - make_interval`, and pass the TTL as the parameter.
- `test_get_history_ttl_filter_uses_the_database_clock` — pins the same
  property on the history read, where drift silently emptied or truncated
  conversation instead of deleting it.

## Evidence

Deterministic skew experiment against the real PG17 test container
(`pgvector/pgvector:pg17`, `aud6-skew-pg` on :55433, migrated to head):
with the client clock 4000 s ahead and TTL 3600, the old SQL
(`timestamp <= to_timestamp($cutoff)`) deleted a row the server stamped
*now* (0 of 1 survived); the new SQL kept it (1 of 1); `ttl=0` still purged
through now. The full real-PG concurrency suite
(`test_pg_sessions_concurrency.py`, 3 tests) passes at this head with
`MAISTRO_TEST_PG_DSN` set, including the line-89 test that flaked.

This is test-and-store hardening adjacent to #1242's own fix (see
`1242-requested-cancellation-stops-work.md`); it does not change task
cancellation behavior.

Re-verified at exact head 25fd3551c (2026-09-23): full persistence suite
624 passed against a live pgvector pg17 on :55917, and
`test_pg_sessions_concurrency.py` green 5× in isolation back-to-back —
no recurrence of the line-89 flake. See the verification record in
`1242-requested-cancellation-stops-work.md`.
