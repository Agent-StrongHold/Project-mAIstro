---
inventory-delta: {}
---
# auto-42 independent verification (L42 verify, head d646cee4)

Read-only acceptance verification of PR 1326 against issue #42 at head
d646cee4772f2b87fc35ed4c63583846dac2fa0c. No product code changed by this note.

Executed locally at this head (all pass): driver check logs 0-7 (uv sync, ruff
check/format, 171 core+server tests, 4 conductor tests, 3 suite-inventory
gates); 113 tests across chat Attempt lease/reclaim recovery, execution
fencing, runtime/task cancellation, durable executor, harness replay dedupe,
delegate child-run claim and binding Invocations; 20 tests across event
correlation and the Conductor cancel route + subprocess-kill E2E; 103 tests
across Attempt result acceptance/reconciliation/repair and chat execution.

Independently reproduced the prior double-dispatch finding scenario: an unkeyed
EFFECT_KEY node now fails closed (one visit, Run failed); a keyed node whose
provider fails ambiguously performs exactly one physical dispatch and later
visits raise UnsafeEffectRetry (outcome UNKNOWN); only a proven
EffectNotApplied authorizes a second dispatch. Each retry produces a new
chronological NodeRun + Attempt.

Blocking findings (repair required, none addressed by this note):

- Issue #1169 and issue #1194 are OPEN upstream; #42 acceptance requires
  #1169/#1170/#1194 closed before #42 is complete. Only #1170 is CLOSED.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` fails at this head: 6 NEW unauthorized
  identities from this branch (graph/nodes/agent_delegate_remote.py:463
  `_create_child_run` — genuinely dead, docstring-only references;
  runs/store.py:344,808 / sqlite_store.py:317 / pg_store.py:468
  `find_child_run_by_effect` — test-only callers; server api/a2a.py:62
  `create_a2a_task` — live route, unbanked) plus 2 stale ledger entries to
  prune (tools/reversibility.py `idempotency_key`, durable_runs/executor.py
  `_replace_node_run`).
- PR 1326 is draft with red CI (integration-scope, exact-debt-ledger, CI test,
  coverage (MinIO), object storage (MinIO), quality gate).
