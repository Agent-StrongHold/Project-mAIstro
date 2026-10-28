---
inventory-delta:
  packages/maistro-evolve/tests: +2
---

# Issue 76 inventory delta — evolve evaluator fail-closed repair

Validation of the #76 cutover found a real regression in the committed
`sandbox_exec.py` converge: `run_function_checks` — the only place
`maistro-evolve` executes candidate Python — swapped its import to the canonical
`maistro.tools.sandbox.canonical.create_sandbox`, but its fail-closed except
clause still listed only `(FileNotFoundError, PermissionError, RuntimeError,
ValueError, OSError)`. The canonical selector raises `NoSuitableBackendError`
(plain `Exception`) when no backend satisfies the workload policy, so on a host
without a Kata/gvisor/container backend the refusal escaped the handler and
propagated to `run_swebench`, which recorded the sample as a zero-score
"failure" — and on a selector-less host crashed the evaluator. Two
`test_swebench.py` cases (`test_correct_fix_scores_full_marks`,
`test_malformed_response_fails_via_sandboxed_syntax_error`) failed as a result;
`test_unfixed_buggy_code_scores_zero` still "passed" only by scoring zero for
the wrong reason. The same host without the canonical surface was already
fail-closed (the pre-#76 behaviour for a host without Docker); the repair
restores that contract uniformly.

Changes:

* `packages/maistro-evolve/src/maistro_evolve/benchmarks/sandbox_exec.py`:
  catch `NoSuitableBackendError` alongside the existing OSError family in the
  sandbox-create/exec handler, so a selector refusal returns
  `(False, "isolated sandbox unavailable: …")` exactly as Docker absence did.
* `packages/maistro-evolve/tests/benchmarks/test_sandbox_exec.py` (+2): pin
  the fail-closed contract — a `NoSuitableBackendError` from the selector and a
  missing canonical module both return a `False` verdict with the
  "isolated sandbox unavailable" detail, never an escaping exception.
* `packages/maistro-evolve/tests/benchmarks/test_swebench.py` (no net count):
  the three cases that assert a *check outcome* (full marks / zero / syntax
  error) are skip-gated on `_selector_satisfies_trusted_tool()`, following the
  repo's `requires_bwrap` pattern. On a host whose selector cannot evidence a
  backend at the `TRUSTED_TOOL` tier they skip rather than fail; the evaluator
  scoring contract stays covered on hosts that can run the check.

No baseline edit: the +2 is recorded here, so `check-suite-inventory` sums the
baseline plus this note.
