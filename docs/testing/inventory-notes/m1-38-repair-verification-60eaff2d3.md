# M1-A2 repair-phase verification record (head 60eaff2d3)

Follow-up to `m1-38-repair-verification-2de7aa555.md`. That round ended with one open
block: `scripts/check-vulture-baseline.py` exited 1 because develop's ledger
(03c8ba83) and the branch tree had diverged (976 added / 952 removed identities at the
merge-base itself). The resolution was the merge of develop into auto-38 (commit
60eaff2d3, merging 03c8ba83), which brought the reviewed develop ledger and the tree
into agreement. No code or test changes were needed in this round; every claim below
was re-executed at this head against reachable production behavior. The job dir
(`/home/dev/maistro/jobs/bc03063b1718404d9c3f9f9c1fed6831`) contains no `check-*.log`
files, so all gates were re-run here rather than read from logs.

`inventory-delta: pytest:maistro-core/tests/projects=+0/-0; pytest:maistro-core/tests/workspaces=+0/-0; pytest:maistro-core/tests/memory=+0/-0; pytest:maistro-server/tests/api/test_projects_api.py=+0/-0; docs:1 note added`

## Prior findings, resolved at this head

1. **`workspaces/pg_store.py:316` unreachable `_purge`** — the `_purge` method no
   longer exists anywhere under `packages/maistro-core/src/maistro/workspaces/`
   (verified by grep; only unrelated `retention`/`runs` `_purge*` symbols remain).
   Nothing to fix; nothing to bank.
2. **`api/projects.py:307` route without vulture disposition** — the
   `remove_project_membership` DELETE route is banked by the merged develop ledger
   under the `fastapi-route-handler` identity class and classified in
   `quality/shipped-surface-truth.json`; `check-vulture-baseline.py` and
   `check-shipped-surface-truth.py` both exit 0.
3. **check-integration-scope MinIO=failure / in_progress** — the remote run's
   `minio/minio:latest` pull denial predates the in-tree fix: `.github/workflows/
   ci.yml` now builds the pinned MinIO RELEASE from source via `go install`
   (checksum-verified pseudo-version, 3-attempt retry) and pulls no image. Runner
   fetchability of the Go module proxy remains verifiable only in CI. The script's
   deterministic modes were re-proven locally: exit 0 for `pull_request` with all
   nine required checks successful, and exit 1 (fail-closed) when required evidence
   is missing or the scope JSON is malformed.

## Gate results at 60eaff2d3

- `uv run python scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` — exit 0; 1415 reviewed identities, 1415 findings, 0
  unclassified, 0 never_allowlist. The 2de7aa555 ledger-drift block is closed by the
  merge; no ledger amendment was required.
- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass (2542 files).
- `uv run mypy` (canonical six-package command) — Success, 713 source files.
- `scripts/check-shipped-surface-truth.py`, `scripts/check-suite-inventory.py`
  (13/13), `scripts/check-ratchet-provenance.py` — all exit 0.
- Targeted pytest against a freshly started, fully migrated pgvector:pg18
  (container `auto-38-repair-pg`, `uv run alembic upgrade head` to 036_audit_log_org_scope):
  - `packages/maistro-core/tests/projects` with `MAISTRO_REQUIRE_PG_LEGS=1` —
    93 passed, 1 skipped (test_scope_store_conformance.py:330, by design: the PG
    backend enforces the rule with a foreign key, not a predicate).
  - `packages/maistro-core/tests/workspaces` + `packages/maistro-core/tests/memory`
    — 507 passed, 2 skipped.
  - `packages/maistro-server/tests/api/test_projects_api.py` — 23 passed.

## Acceptance evidence re-executed on live pg18 + sqlite

- One immutable Root Project per Workspace:
  `test_workspace_creation_provisions_exactly_one_persisted_root_project` PASSED.
- #1147 concurrent reparenting cannot create cycles:
  `test_concurrent_opposite_moves_cannot_both_commit_a_cycle[sqlite]` and
  `[postgres]` PASSED on the live pg18.
- #1148 membership lifecycle: `test_concurrent_membership_writes_leave_exactly_one_row[sqlite]`
  and `[postgres]` PASSED; `test_repeated_grants_update_the_one_canonical_membership`
  and `test_revoked_membership_is_gone_and_can_be_re_granted` ran inside the 93.
- Fail-closed deletions verified independently in the live database:
  `canonical_projects.parent_project_id`, `canonical_project_memberships.project_id`,
  `canonical_project_resources.project_id`, and `canonical_runs.project_id` all carry
  `ON DELETE RESTRICT` foreign keys (pg_constraint inspection), so a run-owning or
  non-empty project delete is refused by the database itself; historical Run scope is
  therefore immutable.
- Scope semantics (downward-only flow, denies win, cross-Workspace refusals,
  empty-only delete): `test_project_resources_flow_downward_not_upward_or_to_siblings`,
  `test_denies_accumulate_and_win_over_descendant_grants`,
  `test_the_tree_rejects_cross_workspace_moves_cycles_and_root_mutation`, and
  `test_delete_requires_an_explicitly_empty_project` all ran inside the 93.

## Residual risks

- MinIO leg: the `go install` fetch from the Go module proxy can only be proven on a
  GitHub runner; in-tree there is no image pull left to fail.
- One intentionally skipped PG leg (`...conformance.py:330`) — FK-enforced rule has no
  predicate to exercise on that backend.
