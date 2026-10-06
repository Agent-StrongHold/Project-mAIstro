---
inventory-delta:
  tests/: 0
---

# Issue 42: preserve claim conformance through the 11376c7 develop merge

The assigned worktree arrived mid-merge (HEAD 6731bffd, MERGE_HEAD
11376c7bef4ea7d17195b90bea8ca9a64a769bb1). Both incoming diffs were backed up
outside the worktree before edits. Driver check-1/check-2 failed parsing conflict
markers in `tests/migrations/test_capability_invocation_effect_index_migration.py`.

Resolved that conflict by preserving the surviving revision 035/store claim-schema
conformance checks and explicit absence of the superseded 043/045 revisions.
The incoming revision 058 follows 057; the chain guard now requires 058 as the
single head and includes it in the required ancestry. Accepting the incoming
side verbatim would resurrect assertions for nonexistent revisions. No migration
or production semantics changed in this resolution; all other staged incoming
merge work is preserved. Existing tests were updated, not added or removed;
incoming develop tests already have their own inventory notes.

Accepted ADRs 1f7c and a66b retain Attempt as Runtime identity and domain-owned
lifecycle persistence. f383 fencing is extended by b36a renewal/reclamation;
no new execution authority is introduced by this repair.

Fresh focused validation:

- `uv sync --locked --extra dev`: passed.
- `uv run pytest tests/migrations/test_capability_invocation_effect_index_migration.py
  tests/migrations/test_single_migration_head.py
  tests/migrations/test_task_admission_generation_upgrade.py -x -q`:
  5 passed, 14 skipped (live PostgreSQL unavailable).
- `uv run ruff check .` and `uv run ruff format --check .`: passed.
- Both Hive and Canvas frontend `npm audit --audit-level=high`: zero vulnerabilities.
- Exact assigned vulture command: passed, 1,332 findings / 1,335 reviewed
  identities, zero unclassified. No additional ledger edit justified.

Further acceptance validation and limitations are recorded in
`repair-42-handoff.md`. The Docker socket is unavailable; skipped live-database
cases must not be reported as acceptance passes. Local merge commit only.
