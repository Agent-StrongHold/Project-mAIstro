---
inventory-delta:
  packages/hive-conductor/backend/tests: +0
  packages/hive-conductor/tests/e2e: +0
---
# 2275 hide Evolution for v1.0

Product-surface hide only (`conductor-411`). Evolve implementation remains #51.

## packages/hive-conductor/tests/e2e: +0

Playwright specs are not collected by the pytest suite inventory. This slice
removes `/evolution` from `URL_ONLY_ENTRIES` and adds an assertion that the
Evolution Engine heading and nav link are absent — same suite file, no pytest
node delta.

Review follow-up (#2275 thread): the absence assertions originally polled
while `AppShellSkeleton` was still up, so a restored `/evolution` route
passed them vacuously (reproduced 3/3 with the route re-added). The test now
waits out the skeleton (`.app-shell[aria-busy='true']` gone — it is removed
only once AuthGuard's setup/whoami round trips answer and the route
resolves); with the route restored the test then fails on the heading count
(3/3), and passes as shipped.
