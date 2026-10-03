# Independent verifier round — #718 canonical Invocation quota ledger (head 879728c)

Verification-only round at head `879728c96f6c8c6e90066b281fa0f39c9439fb11`; no
production code changed. Recorded evidence, all executed in this round:

- Develop-sync block from the prior round is resolved: origin/develop
  (`20e6cd4a7`) is a full ancestor of the lane head (merge `50c38b876`), 0
  commits behind, worktree clean.
- Tests re-run by the verifier, not trusted from logs: the 14-file
  core/server quota suite 237 passed; the 4-file hive governed-quota suite
  52 passed; migration tests 3 passed / 11 skipped (DB-dependent skips).
- Gates re-run: `ruff check .` clean; `check-reachability.py` exit 0 (1136
  production modules; 186 unreachable matches the recorded baseline);
  `check-model-egress.py` exit 0 (23 direct callers; 49 direct-effect sites,
  all dispositioned).
- Acceptance re-derived from the issue, all hold at this head:
  - governed calls record once via the Invocation authority: the container
    builds `capability_effects = new_effect_context(..., quota_tracker=...)`
    (container.py:1930), which installs `CanonicalInvocationUsageRecorder`
    as the Invocation service's single `on_completed` hook
    (effect_context.py:129-132); `dag_node_completion` crosses
    `ModelChatEgress` with Run/NodeRun/Attempt identity, and the governed
    branch wins over the raw builder (legacy_dag_node.py:430-445,
    canonical_dag_runner.py:582).
  - TaskRunner conductor class records (conductor_agent.py -> run_task with
    governed egress) and missing usage is unreported evidence, never zero
    (`record_invocation`/`record_unreported`, tracker.py:46-75).
  - ambient/header reconciliation is explicitly retired as a production
    recording path (recorder.py:1-10, build_quota_recording_hook docstring;
    disposition id `quota-verification` in
    quality/reachability-dispositions.json records the verifier half as
    owed); no shipped caller supplies the CONNECT hook (grep: none outside
    the docstring example).
  - verifier outages return `ReconciliationOutcome(error=...)` with
    `reconciliation_errors_total` instead of raising (reconciliation.py
    maybe_reconcile); `matched=False` bumps `reconciliation_mismatches_total`,
    logs a warning and shrinks the policy interval (_compare_and_update).
  - reconciled `APPLIED` usage records exactly once and a settled Invocation
    cannot double-count (`test_applied_reconciliation_records_recovered_usage_exactly_once`,
    `test_physical_completion_records_once_and_reconciliation_cannot_add`).
- Closure-keyword audit: regex scan of every commit message in
  origin/develop..HEAD finds no `fixes/closes/resolves #N` pattern; the
  tainted `d3cf984f` commit is not an ancestor of the head; PR #1386 body
  (live refresh) says `Refs #718` only and remains draft.
