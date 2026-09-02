---
inventory-delta:
  packages/maistro-core/tests: +13
---
# chatgpt-m1-544-consumer-claim-recovery-9e83

PR #640 adds the atomic consumer-claim recovery regressions and wiring contract.
The net +13 node-ID movement is exact from the PR diff: +11 in
`test_consumer_claim_recovery.py`, +1 in
`test_consumer_claim_wiring_contract.py`, +2 in `test_execution.py`, and -1
net in `test_consumption.py` after replacing the old settlement-path tests.
`test_wiring.py` changes an assertion only, and none of the added cases is
parametrized.

This records the count movement without changing the substantive test surface
or weakening the suite-inventory gate.
