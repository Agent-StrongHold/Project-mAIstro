---
inventory-delta:
  tests/: +16
---
# M1 #465 shipped-surface truth inventory

Adds sixteen collected root-suite tests in `tests/test_shipped_surface_truth.py`.

Twelve cover the checker itself: mutating-route discovery (including `api_route` methods= expansion), repo-wide backend discovery exclusions (tests/examples), obvious success-shaped no-op detection, timer-driven frontend execution signals (success-callback flagged, request-abort timeout with unrelated progress copy not flagged), literal mutating frontend `fetch` discovery, fail-closed missing dispositions for new backend routes and frontend mutations, fake-success misclassification, strict Gate D blocking for owned unresolved production surfaces, disabled-surface owner requirements, and the live repository matrix.

Four cover the checker CLI wrapper `scripts/check-shipped-surface-truth.py` end to end (required by the per-file diff-coverage floor): the clean no-args report, `--discover-json` machine output, the exit-code-reflects-reported-errors invariant under `--require-clean`, and the `__main__` guard via `runpy` script execution.

The original note recorded +8; the discovery-strengthening commits in this branch added four collected node IDs without updating the delta, and the CI repair added the four CLI tests. This note corrects the ledger to the collected truth.
