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

## Addendum (issue #363 repair round: runner-image parity vs the combined
install layer)

Count unchanged (+0): `test_runner_image_declares_every_required_analyzer`
was repaired to match Dockerfile.rsi-runner's real shape, not relaxed on
intent. The image's analyzer install moved from a dedicated
`RUN uv pip install ...` line into the combined
`RUN uv sync ... && uv pip install ... && uv cache clean` layer (so the uv
wheel cache — which keeps METADATA for vulnerable tuples the secret scanner
flags — never persists to the final image), leaving the old
`startswith("RUN uv pip install")` filter empty and the parity gate red
(CI run 39400043178, coverage job, 1 failed / 1717 passed). The test now
joins backslash continuations into whole RUN instructions and accepts any RUN
instruction that invokes `uv pip install`; the assertions themselves are
touched not at all (required-analyzer coverage, locked-dev-group sync,
`coverage` in the explicit install). Mutation-checked in all four directions:
the merged-layer form matches, a dedicated line still matches, a Dockerfile
without the install fails, and a comment mentioning `uv pip install` does not
count.
