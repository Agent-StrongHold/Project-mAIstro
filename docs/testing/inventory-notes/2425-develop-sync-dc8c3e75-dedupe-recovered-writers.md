---
issue: 2425
round: develop-sync-dc8c3e75-dedupe-recovered-writers
date: 2026-11-21
---

# #2425 develop sync @ dc8c3e75: dedupe recovered-writer definitions

No suite inventory delta: no test files were added, removed, or edited, and
per-suite collected counts are unchanged from the recorded baseline at the
new head, so this note carries no `inventory-delta:` block — the canonical
encoding of a zero delta (`check-suite-inventory.py --update` writes the
block only when a delta exists, and an indented `suites: []` list is not a
readable `<suite>: <±count>` entry, which the gate rightly refuses).

## What happened

PR #2425 retargeted to `develop` after #2424 (P4a) squash-merged as `dc8c3e75`.
The branch already carried P4a's content (absorbed pre-restack), so merging
`origin/develop` auto-resolved by git's ort strategy while both sides placed
the same recovered-disposition definitions at different offsets in their
shared files. The result compiled and imported cleanly (Python silently lets
the second definition shadow the first), but `uv run mypy` — the
`lint-and-type-check` CI step — failed on the redefinitions. That is the red
`lint-and-type-check` run captured at head `9cd03298` (2026-11-21T21:58Z).

## Resolution

Removed the develop-side duplicate copies; the byte-identical branch-side
copies (the restacked, repositioned ones) remain, single-copy per class:

- `packages/maistro-core/src/maistro/runs/pg_store.py` — duplicate
  `_locked_recovered_disposition_tree` + `apply_recovered_attempt_disposition`
- `packages/maistro-core/src/maistro/runs/sqlite_store.py` — duplicate
  `apply_recovered_attempt_disposition`
- `packages/maistro-core/src/maistro/runs/store.py` — duplicate protocol stub
  and duplicate `InMemoryRunStore` implementation of
  `apply_recovered_attempt_disposition`
- `packages/maistro-core/src/_vulture_whitelist.py` — duplicate 4-entry
  `apply_recovered_attempt_disposition` block; kept the branch's block

Each deletion was guarded: the script asserted the twin copies were
byte-identical before removing one, and re-checked that every method now
appears exactly once per class (`RunStore` protocol + `InMemoryRunStore`
retains its legitimate one-each pair).

## Evidence at the resolved head

- `uv run mypy packages/maistro-core/src ... packages/maistro-ext-harness/src`
  (CI's exact 10-package argument list): **Success: no issues found in 1128
  source files** — this was the failing gate step.
- `bash scripts/verify-monorepo-layout.sh` ok; `check-merge-markers.py` ok;
  `check-cross-package-imports.py` ok (3604 files, 11 packages).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`: 1221 reviewed identities
  -> 1221 findings (exact ledger match against base dc8c3e75).
- `uv run ruff check .` clean; `uv run ruff format --check .` clean (3617 files).
- Targeted P4b/P4a suite (canvas canonical execution + durable-runs store +
  8 runs recovery suites): 459 passed, 154 skipped — identical counts to the
  pre-merge verification at 9cd03298.
- `test_reconciler_recovered_provenance.py` verbosely: all 5 tests pass —
  persisted-cause authority (unknown null cause refuses despite caller
  RECOVERED; conflicting caller cause refuses) and typed-RECOVERED delegation
  to `apply_recovered_attempt_disposition`.
- Suite inventory gates: hive-conductor/backend/tests,
  maistro-canvas/tests, maistro-core/tests — all "match the recorded
  inventory".
- `packages/hive-conductor/backend/tests/test_audit_pagination.py`: 32 passed.
