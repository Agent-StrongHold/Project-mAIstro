---
inventory-delta:
  packages/maistro-core/tests: +32
---
# 276-run-terminal-derivation

Retroactive. `6ea2c9c` ("Derive terminal Run state from canonical NodeRun
frontier (#276)") added five test modules and shipped no note, so
`packages/maistro-core/tests` has been 32 node IDs over its expected count on
`develop` ever since — which means the suite-inventory check has been red on
`develop` for everyone.

The five:

- `tests/runs/test_run_terminal_derivation.py`
- `tests/runs/test_run_terminal_precedence.py`
- `tests/runs/test_spine_conformance.py`
- `tests/tasks/test_run_result_projection.py`
- and edits to `tests/runs/test_attempt_result_acceptance.py`,
  `test_execution.py`, `test_service.py`

Attribution is exact rather than inferred: the ledger was correct for this
suite at `8b0c654`, `8395b4f` (#498) touched only Conductor tests, and the
whole +32 appears at `6ea2c9c`. Recorded here as part of #497 — this is the
same class as the `+1` in `485-public-registration-fail-closed.md`, and a delta
absorbed into whichever branch next runs the check is a delta nobody can trace.
