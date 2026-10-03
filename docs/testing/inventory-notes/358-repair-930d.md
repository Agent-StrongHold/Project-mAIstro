---
inventory-delta:
  packages/hive-conductor/backend/tests: 0
  packages/maistro-core/tests: 0
  packages/hive-conductor/tests/e2e: 0
  tests/: 0
---

# Issue 358 interrupted-merge repair (930d)

Frozen item: #358 only, initial HEAD `e28cead5071353646dcc5558d95211627cc64a0e`,
assigned develop base `83db0175dd9465727691d9429c36c4b4c597f2a7`.
Incoming unstaged/conflicted and staged work preserved in job-directory patches.
`git fetch origin` resolved origin/develop to the same in-progress MERGE_HEAD;
complete that merge rather than starting a second merge or discarding work.

## Conflict reconciliation

- `backend/routes/audit.py`: retain bounded canonical core list/export and
  pre-query admin authorization. ADR-073 overrides legacy personal-scope access
  to canonical decision audit. Keep canonical Principal (ADR-068); introduce no
  scheduler, Goal store, execution/event authority, or authorization alternative.
- `backend/services/agent_materialization.py`: retain incoming develop's scan of
  every forwarded message, including trailing assistant/tool/system messages,
  with bounded canonical context and pre-serialization budgets (ADR-073).
- Keep inventory front matter in both conflicted historical inventory notes.
- Preserve all other incoming develop changes. In particular, integration-scope
  now selects the largest check-run ID rather than trusting API response order.
  Its eight shipped-script regression tests are supplied by develop; this repair
  adds no test nodes, grants, or quality-ledger entries.

## Independently executed initial validation

Logs: `/home/dev/maistro/jobs/930d49bfca1a47cd946714b290eee220/repair-*.log`.

- `uv sync --locked --extra dev`: PASS.
- `uv run ruff check .`: PASS.
- `uv run ruff format --check .`: PASS, 2772 files.
- `uv run node --test tests/ci/integration-scope.test.cjs`: 8 PASS. Actual shipped
  workflow exercised with fake GitHub API results; this is not remote producer
  success evidence.
- `uv run pytest packages/hive-conductor/backend/tests/test_audit_convergence.py
  packages/hive-conductor/backend/tests/test_audit_pagination.py
  packages/hive-conductor/backend/tests/test_audit_routes.py
  packages/hive-conductor/backend/tests/test_chat_scan_forwarded_history.py -x -q -s`:
  84 PASS. Legacy million-row first page 0.0007s, scoped page 0.0004s, all measured
  query shapes <2800 VM instructions; index migration 9.379s.
- Named vulture command: FAIL before merge commit, 1363 findings vs 1359 trusted
  identities. Four `get_page` declarations are already banked exactly and retained:
  protocol plus PostgreSQL, SQLite, memory adapters. Production consumer is
  `services.audit_bridge.page_core_audit_entries`, outside `packages/*/src` scan.
  Candidate ledger banking does not authorize new debt; no duplicate rows or
  guessed findings added. Recheck against completed merge before final report.

Driver logs also show invalid inventory recipe `packages/hive-conductor/tests`
and a live-service test returning 200 instead of admin-only 403. The latter ran
against an external service, not proof of this checkout's behavior. In-process
booted-container tests above enforce 403 before any canonical store query.

Next: finish merge checkpoint; validate inventory/core adapters and available
PostgreSQL/browser infrastructure. Retention/purge is explicitly delegated to
#325; do not invent a purge policy to claim #358 complete. Memory adapter still
scans linearly; bounded query/DOM and full acceptance remain to be assessed.
