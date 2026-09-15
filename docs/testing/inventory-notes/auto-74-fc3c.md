---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-74-fc3c

Added two Sentinel product-path regression tests. They invoke the real Warden
through `Sentinel.post_call` to prove the regex timeout fails closed and that
large fallback heuristic scans stay within the shared scan window.
