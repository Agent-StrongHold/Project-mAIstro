---
inventory-delta:
  packages/maistro-core/tests: +0
---

No new tests. Existing suites re-proven: the migration chain against an
empty pgvector:pg18 after the 044 re-parent, and the quota/persistence/wiring
suites on the merge-resolved tree.

# auto-72 develop sync: usage-event-identity collision + merge repair

Round on top of the `origin/develop` sync (`8bfd35903`). No store behavior
changed; the work is the sync the previous block preserved mid-conflict and
the migration-chain branch that sync created.

- **Develop sync resolved.** The worktree held a preserved in-progress merge
  of `d2c74137d` with conflicts in
  `packages/maistro-core/src/maistro/container.py` (dataclass field docs;
  `flush_usage_log` vs `_flush_usage_log_on_shutdown`; local store init) and
  `packages/maistro-core/src/maistro/quota/sqlite_usage_log.py` (both sides
  implement the same #1204 identity contract — branch used a process-local
  `_persisted_event_ids` watermark, develop replays retained events with
  `ON CONFLICT (event_id) DO NOTHING`). Resolutions:
  - `container.py` keeps both fields (`usage_log_persistence` doc merged,
    `stores_memory_backed` retained for the #72 health diagnostics), both
    flush methods (public `flush_usage_log()` raises, called by
    `main.py`'s lifespan; `_flush_usage_log_on_shutdown()` delegates to it
    inside a try/except, called by `aclose()`), and both local initializers.
  - `sqlite_usage_log.py` and `quota/usage_log.py` take develop's canonical
    versions wholesale: same semantics (stable `UsageEvent.event_id`,
    unique-index idempotent snapshot, restore preserving identity), and
    develop's shape avoids the watermark whose update can be lost after a
    successful commit. The textual auto-merge of `usage_log.py` had left a
    duplicate `event_id` field in `UsageEvent` and a duplicate `event_id=`
    kwarg in `InMemoryUsageLog.record` (a TypeError on every call); both are
    gone with develop's file. A stray duplicate `usage_log=` /
    `usage_log_persistence=` kwarg pair in the `Container(...)` constructor
    call (SyntaxError) was also dropped.
  Then `origin/develop` (moved to `8bfd35903`) merged clean on top.
- **Elevation migration renumbered 043 -> 044.** develop's #1204 migration
  `039_quota_usage_event_identity` (revision `"039_quota_usage_event_identity"`,
  parent `"042"`) landed on the same parent this branch's elevation migration
  had attached to, so `alembic heads` reported two heads and `alembic upgrade
  head` would refuse. The elevation migration now attaches after the develop
  chain tip `039_quota_usage_event_identity` as revision `044` — one head,
  linear chain (`alembic heads` → `044 (head)`). The
  `quality/durable-table-retention.json` note text was updated to say 044;
  the ledger entry itself is unchanged.
- **Merge-commit provenance.** Salvage copies of the conflicted working-tree
  files are preserved in the job directory (`salvage/`).

Validation this round: recorded in the round report; the chain suite
(`tests/migrations/test_migration_chain.py`) is re-proven live against an
empty `pgvector:pg18` after the re-parent, and the quota/persistence/
wiring/health batteries were re-run green on the resolved tree.
