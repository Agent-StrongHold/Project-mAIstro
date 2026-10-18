---
inventory-delta:
  packages/maistro-rsi/tests: +1
---
# Issue #890 review repair — CrossHair harness (+1, re-bounded budgets)

Follow-up to `890-m8a-crosshair-prototype.md` on the same leaf. Net delta:
`packages/maistro-rsi/tests` **+1 node** (1201 → 1202).

The added test, `test_unknown_cycle_contract_catches_mutant`, closes the
review's P2 on the PEP 316 `raises:` clause (it only permits an exception, it
never requires one): the unknown-cycle contract is now a sentinel-returning
wrapper with a `post:` condition, and the new test drives the real
`crosshair check` engine against a seam mutant that swallows
`UnknownBillingCycleError` and returns normally, asserting the sentinel
postcondition — not the permissive `raises:` — produces the counterexample.

No test was removed; every previously committed node still collects. The
budget-dependent false-positive test
(`test_documented_false_positive_replays_clean`) remains collected but is now
**opt-in** via `MAISTRO_CROSSHAIR_BUDGET_REPRO=1` (`pytest.mark.skipif`): a
skipped node still counts here, so it contributes no delta. That switch, and
re-bounding the contract-prototype subprocess from `--per_path_timeout 60`
(~19.7 s wall) to `5` (~7 s wall), keeps every default-collected CrossHair
test comfortably under the 30 s per-test kill the quality gate's rsi leg runs
with — the review flagged both the timeout headroom and the advisory
experiment blocking CI. The research note
(`docs/research/890-crosshair-symbolic-execution-pure-invariants.md`) records
the corrected isolation and reproducibility picture, including mutant
re-verification against the committed contracts.

No other suite count moved.
