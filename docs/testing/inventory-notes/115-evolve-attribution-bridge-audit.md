---
inventory-delta:
  packages/maistro-rsi/tests: +1
---

# Evolve attribution audit emission — run_evolution logs the producer-credit report (#115, M4-A8)

`run_evolution` (maistro-rsi's production driver of `EvolutionCycle`) now emits
the ledger's `attribution_report()` once per cycle as a structured
`evolve_attribution_report` debug event, so a live run's producer credit — the
append-only event history plus folded per-(producer, context) statistics with
repeated-regressor flags — is auditable from the run's logs without
introspecting the process (AC5).

The added test pins, with `structlog.testing.capture_logs` and a seeded
deterministic harness:

- exactly one emission per cycle, in cycle order (`cycle=0,1`);
- the report carries the attribution schema version;
- cycle 0's report is legitimately empty (only unattributable seed genomes
  were evaluated — outside the credit system by design);
- cycle 1's report credits the bred children (they carry `CandidateOrigin`
  stamps): non-empty event log, non-empty producer view, every producer row
  showing `attempts >= 1` and the `repeated_regressor` flag.

Supporting src change in the same change-set (no additional test count):
`attribution_report` was reshaped from a bare event list into
`{schema, events, producers}` so one dump answers both audit questions, and
`ProducerKind.SOURCE` (a kind with no producing path — dead taxonomy) was
removed, mirroring the #853 precedent for `mutate_eval_weights`.
