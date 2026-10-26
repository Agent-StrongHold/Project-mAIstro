---
inventory-delta:
  packages/maistro-core/tests: +24
---

# P2b: exact-ID store reclaim persists CANCELLED+RECOVERED (#2358 / #232)

Adds `RunStore.reclaim_expired_attempt(attempt_id, *, now=None) -> Attempt | None`
on the protocol and in-memory / SQLite / PostgreSQL stores. Each implementation
re-reads under authoritative mutation protection, commits CANCELLED +
`cancellation_cause=RECOVERED` + `finished_at` via `reclaim_attempt`, and
returns only newly written rows (`None` when nothing new was written; missing
ids raise `AttemptNotFound`). SQLite batch reclaim re-validates inside the
write lock so renewed / already-terminal nominees are skipped.

## Collected node IDs

`packages/maistro-core/tests/runs/test_reclaim_expired_attempt_exact_id.py`
(+24 collected: 6 spine × {memory,sqlite,postgres} + 6 memory_spine):

- exact-ID expired → persisted CANCELLED + RECOVERED; get/reopen returns cause
- live lease → `None` (no rewrite)
- already-reclaimed → `None` (idempotent; cause retained)
- requested/unknown CANCELLED winner → `None` (cause not rewritten)
- batch reclaim returns only newly written rows and persists RECOVERED
- missing id → `AttemptNotFound`

Spine helper `_assert_a_lapsed_lease_is_reclaimed` now also asserts the
persisted RECOVERED cause on batch reclaim (no new collected nodes).
