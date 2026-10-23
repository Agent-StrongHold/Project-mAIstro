---
inventory-delta:
  tests/: +14
---
# 330-mutation-pr-gate

Fourteen additions in `tests/test_mutation_pr_gate.py`; nothing removed.

**`TestTimeoutDerivation` (+3).** The cosmic-ray timeout in the generated
config is derived from the selected-test baseline duration (not the old
constant 60s), floors at the minimum, and the pytest per-test timeout scales
with the same baseline.

**`TestToolchainFingerprint` (+2).** The cache fingerprint is a stable hash of
the mutation toolchain versions — the dependency dimension of the resume key —
and the environment row carries runner and versions.

**`TestBaselineReading` (+3).** A missing baseline aborts (the gate refuses to
run without its trusted base), a malformed one aborts, a valid one loads.

**`TestCombineReports` (+2).** Per-group reports sum into one per-source
report (raw killed/total, adjusted denominator, rate), and survivor
identities are stable across sessions — the property the fail-fast baseline
comparison depends on.

**`TestTheGateDecisions` (+5).** The decision matrix: a baselined survivor
passes; an un-baselined survivor fails fast; a kill rate below the reviewed
floor fails even when every survivor is baselined; zero viable mutants is a
failure, never a pass; and an unmeasured source is report-only (neither pass
nor fail), which is what makes monotonic baseline expansion possible.

All fail against the pre-#330 tree: the packet runner had no baseline
decision, no fail-fast, and a fixed timeout.
