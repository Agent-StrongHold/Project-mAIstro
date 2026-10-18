# Repair notes — issue #1762 round: develop sync + revalidation (2026-10-18)

Branch `auto-1762`, starting head `a4a8ea6f8f34`, base/develop `eec7a587039e`.

## Summary

Issue #1762's fix was already on the branch (verified round at `31d891a56`,
`.cursor/context/verify-1762-31d891a56.md`): `classify_failure` gives typed
`TimeoutError` precedence before raw `401`/`403` substring matching, so opaque
deadline/attempt IDs containing HTTP-like digits can no longer become permanent
AUTH failures. CI gates were green; the only block was the merge queue (GH006).

This round: merged `origin/develop` (11 commits, queue head cleared), verified
the merge lost nothing, and re-ran the acceptance battery on the merged head.
No production or test code changed; authored delta is documentation only.

## Commands and outcomes (merged head)

- `git merge-tree $(git merge-base HEAD origin/develop) HEAD origin/develop`
  -> 0 conflicts, then `git merge --no-ff origin/develop` -> clean.
- `git diff --numstat origin/develop -- quality/` -> empty (no ledger rows
  lost); vs pre-merge head only additions (auto-788 +17, shipped-surface-truth
  +40, workflow-inventory +7), 0 deletions.
- `uv run ruff check .` -> All checks passed.
- `uv run ruff format --check .` -> 3323 files already formatted.
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` -> 1322 reviewed identities
  -> 1322 findings (gate green; no ledger amendment required).
- `uv run python scripts/check-suite-inventory.py` -> ok: 17 suite(s) match the
  recorded inventory.
- `uv run pytest packages/maistro-canvas/tests -q` -> 465 passed, 75 skipped
  (73 PG-DSN, 2 pptx; pre-existing/environmental).
- `uv run pytest packages/maistro-canvas/tests -q -k "TestFailureClassification
  or execution_deadline"` -> 29 passed.
- `uv run pytest packages/maistro-canvas/tests/test_canonical_executor_integration.py
  -q -k execution_deadline` -> 6 passed, x3 repeats (11.0s each), and again
  under `PYTHONASYNCIODEBUG=1 -W error::RuntimeWarning` -> 6 passed.
- `uv run pytest packages/maistro-canvas/tests/test_job_runner_lifecycle.py -q`
  -> 24 passed.
- `uv run pytest packages/maistro-canvas/tests/test_canonical_execution.py -q`
  -> 43 passed (genuine-cancellation canonical behavior separate from deadline).

## Known limitation of focused selection (pre-existing, upstream of this lane)

Single-module collection of `test_executor.py` fails before any test executes
with an order-dependent `maistro.runtime` <-> `maistro.runs` circular import
(introduced upstream by the M1-C spine epic that added
`from maistro import extensions` to `runtime/__init__.py`). Edge set is
byte-identical at pre-merge `a4a8ea6f` and at `origin/develop` — not caused by
this merge or round. CI's full-directory invocation is unaffected. Details in
`.cursor/context/verify-1762-repair-round.md`; the fix belongs to the spine/M9
owners (reachability-ratchet-relevant import reordering).
