---
inventory-delta:
  packages/maistro-core/tests: +17
---
# 1827-governed-llm-execution-identity

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

#1827 binds `GovernedLLMClient` to the canonical execution identities:
`set_turn` now reads the Run/NodeRun/Attempt triple the correlation context
already carries (`RunExecutionService` binds `run_id`;
`AttemptExecutionService.execute_claimed` binds `node_run_id`/`attempt_id`)
and refuses with `RunIntegrityError` instead of fabricating
`agent-turn-…`/`agent-node-…`/`agent-attempt-…` ids. `complete` re-checks the
live context against the stored turn and drops stale tuples.

The +17 are the new adapter-boundary suite
`packages/maistro-core/tests/capabilities/test_governed_llm_execution_identity.py`
(exact forwarding, parametrized missing/blank/conflicting-id refusals with
zero egress, failure-atomic `set_turn`, stale-turn refusal after
clear/leave/move-to-next-Attempt, per-turn effect-key reset, two-task identity
isolation through one shared client). No tests were deleted: the older
`test_client_complete_without_prior_turn_mints_one` was rewritten 1:1 as
`test_client_complete_adopts_bound_context_or_refuses` — its minted-identity
expectation contradicted the admission-before-model rule, so it now asserts
refusal (zero egress) with no context and wholesale adoption of a bound one;
`test_governed_quota` binds the canonical context its `agent.handle` call
previously lacked. Net count unchanged for both touched files.
