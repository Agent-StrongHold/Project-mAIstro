---
inventory-delta:
  tests/: +24
---

# gates-ran: choose duplicate check attempts independently of API order

Adds 24 collected pytest cases in `tests/test_check_gates_ran.py`:

- The three scoped jobs seen on #2110, reconstructed from the Actions jobs
  API's IDs/conclusions, with the old cancelled and newer skipped checks in
  both list orders. This is not a captured publisher check-runs payload.
- A newer cancellation, stale check, or action-required check cannot be
  excused by an older scoped skip, in either order.
- Success, failure and timeout remain execution evidence rather than being
  hidden by a newer skip. This gate proves execution; producer checks still
  enforce their own success requirements.
- A newer queued attempt remains pending rather than reusing older success.
- A skipped check still requires measured, out-of-scope evidence.
- Check-run IDs resolve equal/missing timestamps, delayed starts and late
  completion; legacy payloads without IDs retain the ordered-list contract.

The first 22 added cases were run against the unchanged base evaluator:
8 failed and 14 passed. The failures include all three reconstructed #2110
newest-first inputs, newer genuine non-execution, and newer pending evidence.
The fix uses the same numeric check-run ID ordering already used by
`integration-scope.yml`, within gates-ran's existing execution-precedence
classes. It changes no required names, classifiers, publisher permissions,
trusted-checkout selection, or producer verdict policy.
