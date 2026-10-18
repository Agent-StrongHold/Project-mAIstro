---
inventory-delta:
  packages/maistro-core/tests: +7
---
# Coin-ledger billing identity inventory

Issue #827 adds `packages/maistro-core/tests/agents/test_coin_ledger_conformance.py`
(+7 collected node IDs): four adapter-conformance tests (the reference adapter
passes all three named rules; a request-id-deduping adapter and an
unkeyed-suppressing adapter each fail by name; an object without
`charge_usage` is not a `CoinLedger`) and three agent-level tests driving the
real `Agent.handle` (canonical retry charges once, a reused client request id
charges every Run, a turn outside any Run charges under no key).

`test_outcome_names_its_session.py` renames one test in place
(`test_a_turn_with_no_run_falls_back_to_the_request` ->
`test_a_turn_with_no_run_charges_under_no_key_and_keeps_the_audit_id`):
net zero collected node IDs.
