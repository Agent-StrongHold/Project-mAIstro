---
inventory-delta:
  packages/maistro-core/tests: +4
---
# Issue 837 Persisted-Failure Redaction

The auto-837 branch's remaining delta over develop is that durable Graph
failure evidence is sanitized before it is persisted: `_walk_frontier`
(attempt_executor) and `_mark_failed` (executor) now route failure text
through `failure.sanitize_failure_message`, so a failed Run's canonical
`error` field cannot carry provider credential text or unbounded detail.

Added behavioral cases to `graph/durable_runs/test_executor_gaps.py`
(class `TestPersistedFailureRedaction`), driven through the real `_walk`
path with a failing node:

- a credential-shaped node failure persists the failure code the node's
  own evidence carries (`RuntimeError: provider rejected
  api_key=[REDACTED_SECRET_ASSIGNMENT] for tenant 42`) and never the raw
  key literal; `PhysicalExecutionError` is the separate walk-level
  boundary in `_walk_frontier`, whose message is sanitized at the same
  call site;
- an oversized failure detail persists bounded to the 512-char Run.error
  ceiling, still naming the failure code;
- the sanitizer is idempotent across the two sanitizing passes
  (`_walk_frontier` then `_mark_failed`), so double-sanitizing cannot
  corrupt legitimate evidence;
- the `NodeRun.error` field is also sanitized, preventing credential
  leakage in canonical node-run state (`_logical_outcome` in
  `authoritative_fold.py`, added after the initial redaction covered
  only `Run.error`).

## Verification (2026-10-18 repair round)

- The `NodeRun.error` case is load-bearing: with
  `authoritative_fold.sanitize_failure_message` replaced by an identity
  pass, the same `_walk` reproduces the leak —
  `NodeRun.error` carries `api_key=sk-proj-ABCdef123456` verbatim —
  which is exactly what the pinned equality assertion refuses.
- Full `packages/maistro-core/tests/graph/durable_runs` suite: 744
  passed against pgvector:pg18 (`auto837_test`) after
  `alembic upgrade head`.
- Writers audit: every durable `Run.error`/`NodeRun.error` writer in
  `durable_runs/` is either a static reason string, derived from
  already-sanitized state, or sanitized at the write site. Physical
  Attempt rows deliberately keep the raw `str(exc)` disposition
  (`runs/execution.py` `_failure_disposition`) as immutable physical
  evidence; only the logical Run/NodeRun projections are redacted.
- Deferred (recorded, not repaired here): consolidating
  `recovery._redacted` and `failure._SAFE_DETAIL` into the canonical
  `maistro.security.redact.redact`. A differential probe shows the
  merge changes pinned evidence labels
  (`[REDACTED_SECRET_ASSIGNMENT]` → `[REDACTED_API_KEY]`) and relaxes
  `apikey=<value>` coverage (canonical `is_secret_key_name` does not
  claim the bare `apikey` spelling), so it is a behavior-changing
  refactor needing its own re-pinned tests, not a repair.
