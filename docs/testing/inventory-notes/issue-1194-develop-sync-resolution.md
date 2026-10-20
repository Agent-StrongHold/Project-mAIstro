---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# issue-1194 develop-sync conflict resolution (merge b2daddffa repair)

The develop sync merge `b2daddffa` (and the salvage merge `97e53b4ff` beneath
it) had been committed with conflict markers still embedded in three files,
which is what the previous round's `ruff check` failure
(jobs/6488ba4de8664175ac0c9acbc3c318ba/check-1.log) recorded. This round
resolved every conflict in place and reconciled the two behaviors the merge
had left contradictory. No tests were added or removed; two were rewritten or
re-pinned in place (net +0).

## Conflict resolutions

- `packages/maistro-core/src/maistro/graph/nodes/agent_delegate_remote.py`
  — imports: keep develop's `Mapping, Sequence` shape; drop `hashlib`/`json`
  (the merged body computes delegation keys through `replay_effect_key`, not
  a local digest). Provenance block: keep develop's receipt model (no
  `a2a_task_id` at child creation; it is attached once, after acceptance, by
  `_attach_receipt`) — the merged `_create_child_run` has no `task_id`
  parameter, so the branch-side write would have been a `NameError`. The
  branch-side `delegation_key`/`effect_key` provenance entries survive on
  both sides of the original conflict.
- `packages/maistro-core/src/maistro/graph/nodes/base.py` — failure metadata:
  combine both intents, `{**_failure_metadata(exc), **({"replay_effect_key":
  effect_key} if effect_key else {})}`, so a raising node's typed failure
  metadata and the replay-contract key both land on the failed NodeResult.
- `tests/migrations/test_audit_scope_migration.py` — comment/assertion
  reconciled with the merged chain (below).

## Behavior reconciliation forced by the merge

1. `agent.delegate_remote` parent validation vs replay adoption. Develop's
   `_preflight_child_scope` raised `RunIntegrityError` when `ctx.node_run_id`
   was absent or not visible in the store, unconditionally — before the
   delegation-key lookup. That broke the #1194 replay path: a lease-loss
   retry carries a fresh NodeRun identity, and
   `test_replaying_the_same_logical_delegation_reuses_the_child_and_task`
   failed with `parent_node_run_id 'node-run-retry-3' does not belong to
   parent_run_id`. Resolution: scope/workspace validation stays
   unconditional and ahead of dispatch; the parent-NodeRun correlation check
   moved to `_create_child_run`, guarding creation only — the store's own
   `create_run` already enforces the same invariant durably. Adoption of an
   existing reservation under the same delegation key no longer re-derives
   parentage from the retry's fresh physical identities. Develop's contract
   test (`test_a_missing_parent_node_run_is_refused_before_dispatch`) still
   passes: the check still fires before any transport dispatch.
2. Synth-dag retry vs NON_RETRYABLE (#1193 vs #1194). Develop's
   `test_a_retried_synth_dag_after_a_failed_child_starts_one_level_deeper`
   (b632e0cd3) expected `max_attempts: 2` to re-visit a failed
   `agent.synth_dag`; the enforced contract classifies the kind
   NON_RETRYABLE (a revisit re-synthesizes an LLM call and re-dispatches a
   whole sub-graph — the ambiguous effect #1194 refuses to re-execute
   blindly). This is the same reconciliation the sibling auto-42 lane landed
   as 3ed48faf7: the test is rewritten in place as
   `test_a_synth_dag_whose_child_failed_burns_depth_but_is_not_revisited_inline`,
   pinning both surviving invariants — the failed child's recursion level
   stays charged to the persisted blackboard (`synth_depth == 1`), and
   exactly one dispatch happens despite the declared budget.
3. Migration chain two-head fork. The merged tree had both `043`
   (#1194 Invocation effect index) and `039_quota_usage_event_identity`
   (#1204) as children of `042`. `043` was re-parented onto
   `039_quota_usage_event_identity` (develop's tip), restoring one linear
   head (`043`), and
   `tests/migrations/test_capability_invocation_effect_index_migration.py`
   re-pinned its parent assertion accordingly. The audit-scope test keeps
   `036_audit_log_org_scope.down_revision == "041"` (the branch's re-parent)
   with a comment recording the full extended chain.

## Evidence

- `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run mypy packages/*/src` — no issues in 723 files.
- `uv run pytest packages/maistro-core/tests` — 10613 passed, 713 skipped.
- `uv run pytest packages/maistro-server/tests` — 403 passed.
- `uv run pytest packages/maistro-turing/tests tests/migrations` — passed
  (with the 043 re-pin).
- `uv run python -c` ScriptDirectory probe: heads `['043']`.
- Gates: ratchet-provenance, lifecycle-provenance, suite-inventory,
  contract-markers, branch-independence, citation-status, adr-index,
  cross-package-imports, verify-monorepo-layout — all PASS.
- Vulture per-identity ledger: unchanged from c6bb4a935 (both a2a route
  identities banked under fastapi-route-handler and granted in
  ratchet-authorizations.json). Against trusted base 20e6cd4a7 the gate
  still reports the two a2a identities as unauthorized new debt — the
  documented two-merge transitional state (a candidate-side grant cannot
  authorize its own debt; it becomes prior when this branch merges). Steady
  state against the branch head exits 0.
