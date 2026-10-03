---
inventory-delta:
  packages/maistro-evolve/tests: +19
---

# auto-24-provenance-retention-and-lane-measurement

Repair round for #24 (SPEC-282, M4-D) addressing the two acceptance items a
prior review left UNVERIFIED: provenance retention on admitted challenges, and
the measured curriculum-vs-external lane comparison. Net +19 tests, no
removals:

- `tests/test_curriculum.py` +10 — new `TestProvenanceRetention` class
  (SPEC-282 AC-9): items retain generator/validator versions, exact content
  identity (`content_digest`), their admitting `AdmissionDecision`, and
  host-supplied canonical run references; construction from a non-admitted or
  foreign-draft decision raises; mismatched content hashes and blank run refs
  raise; `provenance_record()` exposes the full retention set. One existing
  rebranding test became async (item construction now requires the admitting
  decision) and one vacuous assertion was replaced with a pin of the
  validator-version derivation — same test count there, +9 net.
- `tests/test_lane_comparison.py` +9 (new file, SPEC-282 AC-10) —
  `compare_lanes` measures identical external evidence on both lanes: the
  "no improvement" verdict is a measured result (delta exactly 0.0), verdicts
  provably flip with capability movement (monkeypatched recomputation),
  cost probes and per-gate refusals match the artifact recorded in
  SPEC-282's "Measured lane comparison" section, budgets refuse non-positive
  rounds, and accepted challenges ride in the report as provenance records.

Existing suites untouched; no parametrization changes, so the delta is
strictly additive.
