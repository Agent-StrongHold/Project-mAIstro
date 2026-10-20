# M1-A2 independent verification at auto-38 head a7608fc0c (2026-09-25)

Verifier round for issue #38 at merge head `a7608fc0c` (develop base `84402748f`,
the M2-A7 learnings-scope merge). Successor to `m1-38-verify-a0bd5d6ae.md`; the
new develop merge is the only tree delta plus the round's own commit. Job dir
`/home/dev/maistro/jobs/d5a377a7a606499c92ad1cb1920beb2a` shipped driver-run
check logs (check-0..5), all green: sync, `ruff check .`, `ruff format --check .`,
64 pytest, core+server suite inventories (10932 / 371). Everything below was
re-executed by the verifier at this head, not inherited.

`inventory-delta: pytest:maistro-core/tests/projects=+0/-0; pytest:maistro-core/tests/workspaces=+0/-0; pytest:maistro-server/tests/api/test_projects_api.py=+0/-0; docs:1 note added`

## Executed evidence

- Driver pytest set re-run in verifier hands: 64 passed.
- `uv run pytest packages/maistro-core/tests/projects packages/maistro-core/tests/workspaces -q`
  -> 162 passed, 59 skipped (PG legs skip without DSN; memory+sqlite legs green).
- PG legs on `auto-38-repair-pg` (pgvector @ 127.0.0.1:5590; `alembic_version` =
  036_audit_log_org_scope == `alembic heads` after the develop merge):
  projects -> 93 passed, 1 skipped; workspaces -> 125 passed, 2 skipped.
- #1147/#1148 named tests PASSED on both sqlite and postgres backends:
  test_concurrent_opposite_moves_cannot_both_commit_a_cycle,
  test_concurrent_membership_writes_leave_exactly_one_row,
  test_revoked_membership_is_gone_and_can_be_re_granted,
  test_a_pre_1148_sqlite_database_upgrades_its_membership_table_in_place (sqlite leg).
- Atomic-root round-trip (this branch's `purge_workspace` rollback): workspace
  conformance create-failure/_assert_gone and failed-delete/_assert_whole tests
  green on memory+sqlite+postgres; `remove_project_membership` API tests (owner
  204 + non-owner 403 preserving the row) inside the re-run 64.
- `uv run mypy` (documented 6-package command) -> Success, 715 source files.
- `uv run python scripts/check-shipped-surface-truth.py` -> complete.
- `check-vulture-baseline.py` with the canonical CI invocation
  (`packages/*/src --min-confidence 60 --exclude '*/third_party/*'`, as pinned in
  `.github/workflows/vulture-ratchet.yml` and `quality.yml`) -> exit 0, 1414
  reviewed identities -> 1414 findings, 0 unclassified, 0 never_allowlist.
  Note: the broader ad-hoc scan (`packages tests`) reports 39 additional
  unreviewed identities under `packages/hive-conductor/backend/` and `tests/`;
  verified pre-existing on develop base `84402748f` (e.g. `list_confirms` present
  at base, absent from the base ledger) and outside the CI-scanned scope. Not
  introduced by this branch.
- `check-integration-scope.py` deterministic modes re-proven: pull_request with
  missing evidence exits 1 and lists all nine required checks (fail-closed).

## Prior findings, resolved at this head

1. `workspaces/pg_store.py:316` `_purge` — symbol absent (grep); moot.
2. `api/projects.py:307` revocation route disposition — `shipped-surface-truth.json`
   entry present; vulture gate green under the canonical CI invocation.
3. check-integration-scope MinIO pull — in-tree fix (source build in ci.yml)
   unchanged; remote CI legs remain externally UNVERIFIED.

## Previous block resolution

The 60eaff2d3-era push rejection (non-fast-forward) is moot: `origin/auto-38`
resolves to `a7608fc0c` — identical to the local head. Local and remote agree;
no push was performed by the verifier (read-only role).

## Closure-keyword review

PR #1323 snapshot body: "Refs #38" only. Commit messages in
`84402748f..a7608fc0c`: no fixes/closes/resolves. No premature closure.

## Scope note

Local lane verification only; writer handoff. Specialized CI evidence (MinIO,
postgres pg17/pg18 matrix, docker-build, hive E2E, wheel-imports, durable-events,
strike-ladder) not claimed; treat as UNVERIFIED until the PR rollup shows green.
