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
