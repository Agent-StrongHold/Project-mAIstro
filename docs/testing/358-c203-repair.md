# Issue 358 repair checkpoint

## Frozen scope

Only issue #358, starting HEAD `222b5e0415dcbc40845a48b98833797a69923ec0`,
assigned develop base `56332162cf636e9a1e8a7e346101803ed6ec7b1f`.
Process the existing merge, the named integration-scope and vulture gates, and
focused audit-pagination acceptance validation. No remote mutations.

Initial state: unfinished merge with MERGE_HEAD exactly the assigned base.
Preserved unstaged and staged diffs in `../incoming-358.patch` and
`../incoming-358-index.patch`. Two unresolved files:
`tests/migrations/test_capability_invocation_effect_index_migration.py` and
`tests/migrations/test_task_admission_generation_upgrade.py`.
Assumption: finish the existing exact-base merge rather than fetch moving develop.
Other staged files are inherited merge content, not a new implementation scope.
Potential repair files are those two conflicts, reviewed retained audit identities
in `quality/vulture-baseline.json` (explicit lane exception), audit pagination
production/tests if executed evidence demands it, and this validation note.

Prior result reports unapproved retained vulture identities, missing integration
producer results, memory fallback full-corpus visits, external E2E mismatch, and
unverified frontend/PostgreSQL behavior. These are claims to revalidate.

## Initial executed evidence

Driver check-1/check-2 fail on the two conflict markers; check-3 targets an
external API returning the obsolete array contract (200 where canonical admin
protection requires 403). check-4 passes 77 focused tests; check-6 names an
unregistered inventory parent rather than `packages/hive-conductor/tests/e2e`.
All eight supplied logs inspected. Docker probe cannot connect to
`unix:///var/run/docker.sock` in this job.

Fresh exact Vulture command fails: its default trusted base is stale
`c560d4ccad82`, not the assigned develop base. Four retained get_page identities
are reported new and six inherited identities removed. Candidate ledger versus
assigned base differs only by the four get_page rows; no merged ledger rows lost.
Fresh integration-scope invocation fails closed with nine missing producer
results; no synthetic success evidence will be supplied.

Merge inspection proves a duplicate revision 057: develop's Run-store planner
migration and this lane's unlanded audit indexes. Necessary merge-resolution
scope therefore also includes renaming/reparenting the audit revision to 058
and updating its existing chain/rollback test. Preserve develop revision 057.
Keep the admission rollback assertion against the captured original stamp,
rather than weakening it to a hardcoded previous head. No execution authority or
authorization changes; ADR-073 keeps canonical decision audits admin-only.

## Merge repair checkpoint

Renamed `057_audit_cursor_indexes.py` to `058_audit_cursor_indexes.py` and
reparented it onto develop's unchanged 057. `uv run alembic heads` changed from
a duplicate-057 warning/two heads to exactly `058 (head)`.
Added `tests/migrations/test_audit_cursor_indexes.py` (two parametrized cases)
to independently pin upgrade and downgrade DDL; inventory delta recorded in
`inventory-notes/358-c203-migration.md`. Existing chain test pins both 057/058
filenames and parent edges. Live rollback test now preserves the Run-store index.

Executed `uv run pytest` over the audit DDL, effect-index, status-domain,
chain, and admission-upgrade migration files: **12 passed, 28 PostgreSQL skips**.
`uv run ruff check .`: PASS. `uv run ruff format --check .`: PASS (3,006 files).
`git diff --check`: PASS.
Explicit RATCHET_BASE_REV still resolves the old merge base until the existing
merge is committed; gate will be rerun after recording the merge.
