---
inventory-delta:
  packages/maistro-core/tests: +27
---

# m1-38-1148-memory-conformance-leg

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

CI repair round for #38 (head 9f84000bf). The Coverage gate failed per-file
diff coverage on exactly the lines the #1148 atomic-merge commit added:

- `scope_store.py` (in-memory `merge_membership`): 16.7% of 12 changed lines
  -- the whole body was unexecuted, because the conformance suite
  parametrized only `sqlite`/`postgres` and the CI coverage producers never
  run `maistro-server` tests, where the in-memory store's only exercising
  test lived.
- `pg_scope_store.py` / `sqlite_scope_store.py`: 75% of 4 changed branch arcs
  -- the Workspace-mismatch refusal arm of `merge_membership` was never taken
  on either durable backend.

What moved (26 node IDs: the memory leg parametrizes the 24 existing
backend-parametrized tests, and the new refusal test adds 3 -- one per
backend):

- The conformance `backend` fixture gained a `memory` leg
  (`_MemoryBackend`). The in-memory store is the container's default wiring,
  so #38's "memory/SQLite/PostgreSQL conformance" acceptance line now runs
  the whole scope-store contract against it instead of trusting protocol
  coincidence. The one test that cannot apply -- the `_MAX_PURGE_PASSES`
  bound, which exists only for the durable iterative drain -- skips the
  memory leg with the reason stated in the skip message.
- `test_a_delegated_merge_must_match_its_projects_workspace` (all backends):
  the delegated merge refuses a membership filed under another Workspace and
  writes nothing -- the same invariant `set_membership`'s refusal test pins,
  now proven for the one write path that bypasses owner-only checks. This is
  the branch arc the durable backends were missing.

Unchanged behavior: no production code was touched in this round. The
`quality/ratchet-authorizations.json` `ac-state` grant `design_coverage@33.9095`
was pruned in the same commit, executing the Quality gate's own printed
remedy (SPEC-083026-fcc9): three independent already-landed notes
(auto-48, auto-1138, auto-1158) hold the floor above it, so the grant is
superseded and every Quality-gate run refused until pruned.
