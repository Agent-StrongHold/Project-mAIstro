# Independent verifier round — #718 quota ledger at the develop-merged head (a851692e)

Verification-only round at head `a851692e6eb30a84359e637ae5a4471082eca4ba`
(the lane repair `c0555611b` merged with develop base `151bcfe2`); no
production code changed. Everything below was executed in this round, not
trusted from prior claims.

- Prior block resolved without action: the develop sync conflict was already
  committed as `434d31398`, and the final develop base `151bcfe2` is merged
  at the assigned head `a851692e`. Worktree clean at that exact head; no
  conflict markers in any changed file.
- Driver check logs (job e8bcf429): uv sync resolved, `ruff check .` clean,
  format clean, two pytest batches 237 + 90 passed, suite inventories ok
  (hive-conductor 2907, maistro-core 11432, maistro-server 408).
- Verifier-executed: acceptance battery `pytest test_canonical_invocation_recorder
  test_reconciliation test_reconciled_usage_quota test_model_chat_egress
  test_governed_quota test_conductor test_factory test_taskrunner_quota_ledger
  test_legacy_dag_governed_quota -q` -> 168 passed; `test_evolution_service.py`
  -> 34 passed; persistence `test_sqlite_quota test_pg_quota test_tracker` +
  `tests/migrations` -> 60 passed / 79 DB-skipped, then the full migration
  suite re-run against live Postgres (`auto-718-repair-pg`, port 18718) with
  `MAISTRO_TEST_DATABASE_URL` -> 96 passed, covering migration 041 (canonical
  invocation evidence) and the chain. `ruff check .` clean; mypy over the full
  AGENTS.md scope (724 files) clean.
- Prior finding closed: evolution raw egress is governed. `_build_llm_call`
  resolves the bridge's `governed_egress` + Container Workspace and returns a
  governed closure with cycle-scoped run identity and per-call attempt/effect
  keys (evolution.py:360-473); the raw poster survives only where the process
  has no canonical authority at all (stub port / engine absent), the same
  documented rule as `LocalTaskBackend`. Proven by
  `test_build_llm_call_crosses_the_engine_bridge_governed_egress` (bomb on
  raw egress) and `test_build_llm_call_stub_port_keeps_the_raw_fallback`.
- Acceptance re-derived from the issue, all hold at this head: single
  canonical recorder at Invocation terminalization
  (effect_context.py:129-131, wired with the Container's real quota tracker
  at container.py:2017-2020); missing usage is unreported evidence with
  `usage_complete=False`/`unreported_count` in in-memory, SQLite and PG
  trackers; ambient/header reconciliation explicitly retired (recorder.py
  docstring, reconciliation.py retirement note, disposition
  `quota-verification` CONNECT honestly recording the owed explicit-verifier
  half); verifier outages isolated to error evidence + metric + warning;
  `matched=False` hits `quota_reconciliation_mismatches_total` + warning +
  policy shrink regardless of caller; reconciled usage records exactly once.
- Closure-keyword review: PR #1386 body says "Refs #718" only; commit
  subjects/bodies in `151bcfe2..HEAD` contain no fixes/closes/resolves
  markers.
- Still UNVERIFIED locally: per-file diff-coverage (needs CI's full
  coverage.xml).
