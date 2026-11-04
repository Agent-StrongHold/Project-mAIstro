---
inventory-delta:
  tests/: +1
---

# End-to-end two-merge-rule proof at the vulture gate (#319)

Adds one regression to
`tests/test_ratchet_provenance_integration_base.py`:
`test_one_pr_weakening_banking_and_authorizing_fails_the_vulture_gate`. It
runs the real vulture gate's decision path (real `resolve_baseline`, real
`load_authorizations`, real git) over a synthetic two-branch history shaped
exactly as issue #319's final acceptance bullet names: one PR that weakens
the metric (a new dead-code finding), banks the regression into the
candidate ledger, and writes the authorizing grant. The gate must fail; the
byte-identical candidate tree must pass once the grant landed separately on
the base first. Under a mutation that makes `load_authorizations` read the
candidate worktree instead of the trusted base, this test (and 15 others)
fail, proving the enforcement is load-bearing.
