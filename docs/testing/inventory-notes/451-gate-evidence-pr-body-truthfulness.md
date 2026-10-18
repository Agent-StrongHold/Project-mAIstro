---
inventory-delta:
  packages/maistro-rsi/tests: +28
---
# 451-gate-evidence-pr-body-truthfulness

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Twenty-eight node IDs added under `packages/maistro-rsi/tests`, no other suite
moved. All of them pin the #304/#820 gate-evidence contract (issue #451 Wave 2):
a required analyzer that never executed must reach the promotion record and the
generated PR text as a blocking `not_run` — never as an omission a
success-shaped sentence renders as a pass.

- `test_gate_evidence.py` (new, 23 cases): fail-closed `_lint_gates` (missing /
  wedged / unreadable-output causes), executed-gate provenance (command, tool
  version, candidate SHA, exit status, output digest), `GateState` semantics
  shared with maistro-evolve's scorecard, runner-image analyzer parity for
  `Dockerfile.rsi-runner`, and the evidence chain scorecard → git-notes
  `gate_evidence` → export manifest row → `harvest.pr_body`.
- `test_selfbranch.py` (+5 cases): the self-branch default PR body is derived
  from the recorded run (command, exit status, output digest) and claims no
  gate the path never executed — the literal "full fitness scorecard" sentence
  #820 names is asserted absent.

maistro-evolve's count is unchanged: `GateState` support in
`maistro_evolve.scorecard` is exercised from the rsi suite, which imports the
evolve package by design (`_EVOLVE_RSI` pythonpath).
