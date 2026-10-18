---
inventory-delta:
  packages/maistro-core/tests: +3
---
# fix-m1-1067-builders-canonical-parity-7dcf

3 new regression tests added while closing the 3 Codex-review findings on
this PR's own defect-1/defect-3 fixes (`packages/maistro-core/tests/builders/test_canonical_execution.py`):

- a transient-skip-marker case: a stage hit by the stale guard, later
  genuinely redispatched, whose real redispatch then fails — proves the
  compatibility receipt reports the real failure, not a stale `SKIPPED`.
- an arithmetic regression test for `_derived_max_steps` against the
  100-node repeated-free-frontier counterexample.
- a zero-delay `ScriptedDispatcher` race reproduction proving a revision
  queued mid-frontier by one task no longer causes its wave-mate to be
  silently skipped (the `flush()` frontier-boundary fix).

No production behavior changed for callers outside this PR's own new code.
