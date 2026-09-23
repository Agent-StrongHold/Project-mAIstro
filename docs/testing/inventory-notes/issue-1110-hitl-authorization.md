---
inventory-delta:
  packages/hive-conductor/backend/tests: +2
---
# Issue 1110 HITL authorization

Adds end-to-end reviewer isolation coverage for canonical Project grants/denies, payload isolation, answer/cancel settlement, actor-only denial audit evidence, and two-principal Workspace-scoped expiry.

## Merge reconciliation (develop `ba2f1f077`)

Develop landed #1275's bounded discovery fairness (keyset walk in
`/pending`) and #1455's security-rejected attribution/redaction after this
branch forked. The merge composes them rather than choosing: `/pending` now
keyset-walks inside each *authorized Project* (not just each Workspace), so
#1109's fairness and #1110's authorization both hold; `/expire` keeps the
caller-scoped, actor-attributed tick. Develop tests that seeded pauses under
the fixture's fake default Project were re-seeded into each Workspace's
canonical root Project, and the settlement suite's `_OverEagerIndexStore`
fake was widened to the store protocol's `project_ids`/`workspace_ids`
signature — discovery and settlement now only ever see canonical scopes.
