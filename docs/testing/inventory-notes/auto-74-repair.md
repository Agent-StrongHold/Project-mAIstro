---
inventory-delta:
  packages/maistro-core/tests: +4
---
# Issue #74 repair evidence

Three product-path security regressions extend the initial #74 evidence:

- Sentinel's real Warden scans a pathological reject pattern across overlapping
  windows, records a fail-closed timeout, and never hands a search more than the
  configured window; the fallback semantic phase gets the same product-path
  window bound.
- The complete Warden verdict is compared on the accelerated and stdlib fallback
  regex engines, rather than comparing only individual pattern APIs.
- Sentinel output redaction is paired with a `PIIMatch` masking assertion so the
  raw credential is absent from both the product result and match metadata.
