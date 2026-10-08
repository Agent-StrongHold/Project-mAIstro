---
inventory-delta:
  packages/maistro-core/tests: +32
---
# 885 M8-A5: differential reference-model harness (+32)

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
(+32 node IDs). It drives a maistro-free `ReferenceModel` (transition tables
and stamping/cascade/acceptance/lease rules transcribed from the contract
prose, pinned by an AST test to stay import-free *and* free of references to
the production symbols the driver imports) and the real
`maistro.runs.lifecycle` functions through the same generated operation
streams, comparing refusal agreement (including refusal category and
post-refusal state — refusals must be atomic) and the full normalized
observable state after every step, including lease identity (holder, fencing
token, expiry; renewals present the oracle's token so identity drift cannot
renew against itself). It adds no product code and touches no authority path;
the module is test-side, imported by nothing, and defines no new work-state
vocabulary (the execution-lifecycles ledger gate still polices that
independently).

The 32 cases: the differential property itself over Hypothesis-generated
streams and over a frozen 32-stream seeded corpus, plus a reproducible
1,000-stream deep sweep (zero divergences at this head — the recorded
real-drift count); non-vacuity and detection for ten hand-written semantic
mutants (terminal-absorbing edges lost, evidenceless completion, stale
acceptance kept, oldest-NodeRun-wins, paused-node cascadable, lease-expiry
off-by-one, expired-lease renewal, started_at re-stamped on resume,
anonymized reclaim, anonymized cascade); the frozen matched-scenario
defect-yield table (ordinary assertions 7/10, differential on the shared
generated corpus 4/10, differential with each mutant's targeted probe
10/10 — the probe column is reported separately because it is written from
its mutant, with a guard that the generated-only comparison stays an
under-detection until the note is re-measured); shrinking of a recorded
18-op counterexample to a 2-op minimal divergence by committed deterministic
delta-debugging, plus an independent byte-stable `hypothesis.find` result in
a reduced alphabet; and the evidence-only contract tests (advisory marker,
maistro-free oracle, test-side placement).

Count history: the first recorded revision of this note said +31; the repair
round re-scored the yield comparison on matched scenarios, folded the deep
sweep into a committed test, and strengthened the oracle-independence and
refusal-atomicity guards (+1 net node ID, several tests rewritten in place).
