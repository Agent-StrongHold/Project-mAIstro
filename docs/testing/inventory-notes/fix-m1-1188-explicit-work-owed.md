---
inventory-delta:
  packages/maistro-core/tests: +4
---
# fix-m1-1188-explicit-work-owed

Four new tests in `test_run_terminal_precedence.py` for #1188, which removes
`derive_run_terminal_status`'s permissive `work_owed: bool = False` default:

- a signature test proving `work_owed` now has no default and omitting it
  raises `TypeError`;
- an empty NodeRun frontier with `work_owed=True` derives no terminal status
  (work is still owed, so "nothing observed yet" is not "nothing to observe");
- an empty NodeRun frontier with `work_owed=False` derives `COMPLETED` (the
  one case the removed default used to reach by accident instead of by a
  caller's explicit say-so);
- a partial observation (one in-flight NodeRun alongside a terminal one)
  derives no terminal status regardless of `work_owed`, proving the boolean
  only ever gates the *empty*-frontier case, never an in-progress one.

The one existing call site relying on the old default
(`test_terminal_precedence_is_total_and_order_independent`) now passes
`work_owed=False` explicitly; both production callers
(`runs/reconciliation.py`, `graph/durable_runs/executor.py`) already did.
No tests removed or renamed.
