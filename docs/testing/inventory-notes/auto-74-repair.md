---
inventory-delta:
  packages/maistro-core/tests: +6
---
# Issue #74 repair evidence

## Repair: unreachable whole-text semantic composition removed (post-merge)

Merging develop surfaced one new exact-debt item:
`security/warden/semantic.py: semantic_tool_poisoning_scan` (vulture
`core-public-api-surface`, reproduced against trusted base `ba2f1f07`). The
function was a whole-text composition of the Layer 2.5 signals that the product
path no longer uses: `Warden.scan` aggregates the same bounded signals across
overlapping scan windows in `detector._scan_semantic_windowed`, which is
strictly more sensitive (cross-window signal carry) and carries the corrected
capture-ordering semantics. No ledger grant was sought; the dead composition was
removed and its callers were retargeted onto the real product path:

- `formal/models/test_warden_semantic.py` now exercises
  `Warden._scan_semantic_windowed` — the evaluator `Warden.scan` runs per
  window. Equivalent for these inputs (all ≤500 chars, one window) and identical
  in flag/verdict shape, so every Hypothesis property keeps its strength under
  the CI seed (`pytest formal/models/ --hypothesis-seed=0`: 411 passed).
- `test_warden_pii_bypass.py::TestWardenCodeSyntaxDoesNotBypass` now goes
  through the `Warden.scan` product boundary and asserts the Layer 2.5 flag
  strings, so a semantic-layer wiring defect cannot hide behind a direct call
  to a pure helper (the exact blind spot that class docstring described).
  The benign-code no-false-positive property targets the Layer 2.5 evaluator
  itself, since the full boundary additionally applies the heuristic density
  layer, which is not what that property is about.
- `scripts/check-vulture-baseline.py packages/*/src --min-confidence 60
  --exclude '*/third_party/*'` exits 0 (1413 reviewed identities → 1413
  findings, no deltas).

## Prior repair evidence (windows/timeouts, equivalence, PIIMatch)

Four product-path security regressions extend the initial #74 evidence:

- Sentinel's real Warden scans a pathological reject pattern across overlapping
  windows, records a fail-closed timeout, and never hands a search more than the
  configured window; the fallback semantic phase gets the same product-path
  window bound and preserves a padded capture/full-conversation signal across
  windows without an unbounded regex.
- The complete Warden verdict is compared on the accelerated and stdlib fallback
  regex engines, rather than comparing only individual pattern APIs.
- Sentinel output redaction is paired with a `PIIMatch` masking assertion so the
  raw credential is absent from both the product result and match metadata.
- The prior semantic false positive is reproduced through `Sentinel.post_call`: a
  complete-object phrase before `capture` remains clean, while the ordered
  capture/full-conversation form remains blocked.
