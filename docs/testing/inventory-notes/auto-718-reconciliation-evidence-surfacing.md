---
inventory-delta:
  packages/maistro-core/tests: +1
---

Repair-run strengthening for #718: the reconciliation engine's mismatch and
outage evidence must be operator-reachable even when a background caller
discards the returned `ReconciliationOutcome`, so the tests now assert the
surfacing itself, not just the returned value:

- `test_verifier_outage_surfaces_error_evidence_metric` (new) — a verifier
  outage increments `quota_reconciliation_errors_total` and emits the
  `quota verification unavailable` warning (`reconciliation.py` isolates the
  exception into `ReconciliationOutcome.error`; the metric/log are what make
  the outage inspectable).
- `test_mismatching_delta_records_mismatch_and_shrinks_interval` — extended in
  place (no count change) to assert a `matched=False` drift increments
  `quota_reconciliation_mismatches_total` and logs the mismatch where it is
  computed, so it cannot be computed and discarded silently.

Both counters are read as before/after deltas from the shared metrics registry
(`maistro.observability.metrics.registry`), which is idempotent per metric name,
so the assertions stay order-independent under the full suite.
