# #2418 verifier revalidation at develop sync `280e286ff4`

The branch's second develop sync (merge of `origin/develop` `228dec753f`,
PR #2422's ledger + suite growth) landed as `280e286ff4` after the note in
`2418-develop-sync-a3efc93c92-and-gate-revalidation.md` was written for the
earlier sync. This round re-derived the branch's local evidence at that exact
head; no count moved, so no `inventory-delta` is recorded (the +6 core cases
from #2422 arrive with develop's own delta note via the merge).

Independently executed at `280e286ff45f7c442586b11d4c19c624e6e5eba6`
(`origin/develop` verified `228dec753f42`, merge-base == base):

- Focused suites: 189 core (factory, delegation, quota, admission, execution
  identity, tool choice, egress) + 53 hive (effective gateway key, adapter,
  materialized authority) — all pass.
- `test_configured_hive_agents_use_admitted_execution_and_usage[boot]` and
  `[materialized]` pass; `test_materialized_model_authority.py` collects
  exactly 20 cases, all pass; the five `admitted_model.py` coverage closers
  (replay `_stream_chunks`/finish_reason, text-only fallback,
  `required_workspace_id` mismatch, early `aclose`) pass by name.
- Ratchets with CI-exact arguments: vulture 1229 → 1229 (`packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'`); wiring-reads 11 → 11
  (`RATCHET_BASE_REV=origin/develop`); suite inventory per-suite gates ok
  (hive 4297, core 18752); cross-package imports ok (3590 files / 11 packages);
  diff-coverage gate (`scripts/check-diff-coverage.py --base 228dec753f`) ok —
  full core producer run (17485 passed, 1260 skipped, 7 xfailed) plus the hive
  materialization/adapter subset; CI's hive producer is a strict superset.
- Lint/type: `ruff check .` and `ruff format --check .` clean; `uv run mypy`
  over CI's exact ten-package list: 1126 files, no issues.
- Cheap CI gates: compliance registry, monorepo layout, merge-marker scan,
  test-duplicate scan — all ok. `quality/` and `baseline.json` are
  byte-identical to `origin/develop` (`git diff --numstat` empty).
- Closure-keyword scan over branch-unique commit messages: no
  fixes/closes/resolves markers; PR body refs #1084 without closing it.

Still unverifiable locally (hosted, left unchecked in the PR body): full CI on
this PR, including the Docker/e2e/MinIO/Postgres legs; the container-scan High
(Node 24.22.1 via locked patchright 1.64.4) stays upstream-blocked per the
maintainer's 2026-11-20 comment.
