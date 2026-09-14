---
inventory-delta:
  packages/maistro-core/tests: +5
---
# #1197 — bounded sandbox output capture

The sandbox protocol now treats stdout and stderr as host-owned resources. Fake
backend coverage drives concurrent unbounded writers and proves retained bytes
stay within the configured per-stream policy, overflow terminates execution,
and the result reports truncation. The real bubblewrap test runs the same
exhaustion case when the production backend is available; otherwise the test's
capability skip is explicit.
