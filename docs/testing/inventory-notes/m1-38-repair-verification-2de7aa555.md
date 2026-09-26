# M1-A2 repair-phase verification record (head 2de7aa555)

Re-validation of the branch after the develop merges (95945b000 #1178, c829556c2 #1576)
landed on top of the previous repair (a4f0472ca). No code or test changes were needed:
every claim below was re-executed at this head against reachable production behavior,
not inherited from the 348e47cff record. Job dir had no check-*.log files; the prior
session transcript (events.jsonl) is not a check log, so all gates were re-run here.

## Gate results at 2de7aa555

- `uv run ruff check .` — pass; `uv run ruff format --check .` — pass (2535 files).
- `uv run mypy` (canonical six-package command) — Success, 713 source files.
- `scripts/check-shipped-surface-truth.py` — pass ("Shipped-surface truth matrix is
  complete"); the #1148 `remove_project_membership` classification survives the merges.
- `scripts/check-suite-inventory.py` — pass, 13/13 suites match.
- `scripts/check-ratchet-provenance.py` — pass (35 quality JSON consumers have
  provenance, 0 lifecycle violations, no candidate-approved expansion).
- `scripts/check-integration-scope.py` — re-proven both ways at this head: exits 0 for
  `pull_request` with all nine specialized checks successful, and exits 1 (fail-closed)
  when required results are missing.

## check-vulture-baseline.py — trunk ledger drift, now proven at the merge-base itself

The gate exits 1 at this head. Three independent measurements attribute the failure to
trunk/develop state, not to this branch:

1. The gate also exits 1 at develop head 03c8ba83 (`/tmp/base-wt` run) and at the
   merge-base 95945b000 the drift is present *against its own tree*: classifying
   tree@95945b000 with ledger@95945b000 yields 976 added / 952 removed identities
   (fastapi-route-handler 206/10, pydantic-declarative-field 121/210,
   dataclass-declarative-field 33/63, hive-service-api-surface 63/0, …). A ledger that
   does not match its own commit cannot blame any candidate.
2. Raw Vulture multiset (`path::message`, line-independent), develop head 03c8ba83 vs
   this head: the branch REMOVES 9 identities (stale `get_workspace_attention`,
   `chat_run_spine`, seven `pytestmark`/`_empty_job_queue` rows) and ADDS 2 —
   `hive-conductor/backend/routes/hitl.py::paused_at` and
   `maistro-turing/src/maistro_turing/self_model/types.py::source_kind` — both arriving
   with develop-side merged content (60862b6c5), outside every #38 surface.
3. The branch's own non-merge diff (95945b000..HEAD) is 10 files, +179/−13, confined to
   the #38 surfaces (projects API/tests, workspaces store, container wiring, context
   assembly, shipped-surface matrix, docs).

Repairing the gate here would require editing `quality/vulture-baseline.json` /
`quality/ratchet-authorizations.json` — a ledger/grant edit, prohibited for ordinary
implementation branches. Both prior code-level findings stay repaired: `79c3146d3`
removed the unreachable `_purge` from pg_store.py (the current file has no `_purge`),
and `bd3f9213a` classified the #1148 route in the shipped-surface matrix.

## MinIO finding — repaired at the CI-definition level; runner-only verifiable

`.github/workflows/ci.yml` no longer pulls any MinIO image: only comments mention
`minio/minio`, and the service is built from source via
`go install github.com/minio/minio@v0.0.0-20250422221226-0d7408fc9969` (checksum-verified
through sum.golang.org, 3-attempt retry, ci.yml:320-345); quality.yml carries the same
story. Whether GitHub runners can fetch the pin is verifiable only in CI; this sandbox
has no GitHub runner and anonymous egress cannot prove or disprove it.

## Runtime acceptance against a real PostgreSQL (re-executed)

Dedicated pgvector:pg18 container (lane-isolated, port 5599), `alembic upgrade head`
applied clean, `MAISTRO_REQUIRE_PG_LEGS=1 MAISTRO_TEST_PG_DSN=postgresql://…@127.0.0.1:5599/postgres`:

- `packages/maistro-core/tests/projects`: 93 passed, 1 skipped (the by-design skip:
  the PostgreSQL leg of `test_a_project_owning_runs_cannot_be_deleted` enforces via
  foreign key rather than a predicate — `pg_constraint` re-verified live, below).
- `packages/maistro-core/tests/workspaces` + `test_container_wiring.py`: 70 passed,
  2 skipped; root-provisioning rollback covered by
  `test_create_rolls_back_when_the_root_project_cannot_be_made` (store conformance:552).
- `packages/maistro-server/tests/api/test_projects_api.py`: 23 passed, including both
  #1148 revocation-authorization tests.
- Memory conformance (`test_scope_predicate.py`, `test_context_assembly.py`): 28 passed.
- Named acceptance cases pass on BOTH backends: root provisioning
  (`test_workspace_creation_provisions_exactly_one_persisted_root_project`),
  downward-only flow (`test_project_resources_flow_downward_not_upward_or_to_siblings`),
  deny-wins (`test_denies_accumulate_and_win_over_descendant_grants`),
  #1147 concurrency (`test_concurrent_opposite_moves_cannot_both_commit_a_cycle[postgres]`
  on the live pg18), #1148 lifecycle (`test_concurrent_membership_writes_leave_exactly_one_row`,
  `test_repeated_grants_update_the_one_canonical_membership`,
  `test_revoked_membership_is_gone_and_can_be_re_granted`, pre-#1148 SQLite in-place
  upgrade), restart survival (both fresh-store tests), and fail-closed
  tree/deletion refusals.
- Live schema evidence on the migrated database: `canonical_projects_parent_project_id_fkey`,
  `canonical_runs_project_id_fkey`, `canonical_project_memberships_project_id_fkey`,
  `canonical_project_resources_project_id_fkey` all `FOREIGN KEY … ON DELETE RESTRICT`,
  and `project_id` is NOT NULL on runs, memberships and resources — every
  project-scoped durable object belongs to exactly one Project and deletes fail closed.
