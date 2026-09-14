---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---

Adds two focused Conductor transport tests. The dashboard screenshot route is
verified to attach `BrowserNetworkGuard` before its fixed localhost navigation,
and the UI hill-climber screenshot path is verified to abort a loopback URL
before the fake wire is reached. The shared maistro-core browser suite already
covers explicit browse, autonomous search/model navigation, subresources, and
redirect-to-private behavior at the real Playwright route boundary.
