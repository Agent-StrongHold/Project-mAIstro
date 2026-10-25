---
inventory-delta:
  tests/: +22
---
# Gates-ran publisher cancellation guard

The root publisher contract suite gains 22 collected cases, from 6 to 28:

- One workflow wiring case checks the cancellation-aware condition and exact
  evaluator, job-status, and candidate-head environment bindings.
- Seven Node-backed cases execute the actual inline publisher JavaScript with
  fake APIs and verify cancelled publishers write no status for absent, blank,
  success, failure, pending, unexpected, or malformed evaluator output.
- Fourteen Node-backed cases cross those seven outputs with noncancelled
  success/failure job status. They preserve fail-closed missing/error handling,
  explicit 0/1/2 verdict mapping, and the exact SHA/context/status payload.

No existing cases were removed, and missing Node fails rather than skips.
Against base `cf4a562b65e0f459eec8e77e8b10ca7aa4f847d0`, the repaired
root suite collects 4476 tests against the prior recorded 4454, exactly +22.
The front matter was generated with
`python scripts/check-suite-inventory.py --suite tests/ --update --note gates-ran-cancellation-guard`
in an isolated worktree environment; no shared baseline or unrelated drift
was recorded.
