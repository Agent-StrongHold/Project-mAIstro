---
inventory-delta:
  packages/maistro-core/tests: +2
---
# auto-855-0ec6

The browser guard repair adds two collected cases in
`packages/maistro-core/tests/tools/browser/test_net_guard.py`: an endless
redirect chain is bounded and denied, and a route lacking Playwright's
`fetch`/`fulfill` API fails closed instead of continuing unguarded.
