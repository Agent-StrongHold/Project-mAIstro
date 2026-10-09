---
inventory-delta:
  packages/maistro-core/tests: +31
---
# 885 M8-A5: differential reference-model harness (+31)

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Issue #885 (epic M8-A, initiative #879) asked whether a deliberately simple
reference model can act as an independent oracle for the canonical state
machines and expose semantic drift that ordinary assertions miss. Unlike the
other M8 leaves, this experiment is fully runnable offline — the Run/NodeRun/
Attempt lifecycle (`maistro.runs.lifecycle`) is pure, in-memory, and needs no
services — so the deliverable is a working prototype, not a registered WATCH.
The research record with the measured defect-yield comparison and the terminal
disposition is `docs/research/885-differential-reference-model-testing.md`.

This change adds one self-contained research module,
`packages/maistro-core/tests/runs/test_m8a5_differential_reference_model_research.py`
(+31 node IDs). It drives a maistro-free `ReferenceModel` (transition tables
and stamping/cascade/acceptance/lease rules transcribed from the contract
prose, pinned by an AST test to stay import-free) and the real
`maistro.runs.lifecycle` functions through the same generated operation
streams, comparing refusal agreement (including refusal category) and the
full normalized observable state after every step. It adds no product code
and touches no authority path; the module is test-side, imported by nothing,
and defines no new work-state vocabulary (the execution-lifecycles ledger
gate still polices that independently).

The 31 cases: the differential property itself over Hypothesis-generated
streams and over a frozen 32-stream seeded corpus (zero divergences at this
head — the recorded real-drift count); non-vacuity and detection for ten
hand-written semantic mutants (terminal-absorbing edges lost, evidenceless
completion, stale acceptance kept, oldest-NodeRun-wins, paused-node
cascadable, lease-expiry off-by-one, expired-lease renewal, started_at
re-stamped on resume, anonymized reclaim, anonymized cascade); the frozen
defect-yield table (ordinary assertions 6/10 vs differential 10/10, with a
green-on-real-implementation guard for the control group); Hypothesis
shrinking of an injected divergence to a ≤4-op minimal trace, byte-stable
across reruns; and the evidence-only contract tests (advisory marker,
maistro-free oracle, test-side placement).
