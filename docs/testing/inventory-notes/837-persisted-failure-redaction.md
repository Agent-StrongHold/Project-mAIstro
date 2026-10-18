---
inventory-delta:
  packages/maistro-core/tests: +3
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

- a credential-shaped node failure persists
  `PhysicalExecutionError: ... api_key=<redacted> ...` and never the raw
  key literal;
- an oversized failure detail persists bounded to the 512-char Run.error
  ceiling, still naming the failure code;
- the sanitizer is idempotent across the two sanitizing passes
  (`_walk_frontier` then `_mark_failed`), so double-sanitizing cannot
  corrupt legitimate evidence.
