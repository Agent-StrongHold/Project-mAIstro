---
inventory-delta:
  packages/maistro-design/tests: +20
---
# Versioned creative artifact state inventory

Issue #780 adds `packages/maistro-design/tests/test_artifact_versions.py`
(+20 collected node IDs, all marked `contract: behavioral` and traced to
SPEC-092826-a780/AC-1..AC-9). The tests drive the real
`PgArtifactVersionStore` against SQLite file databases, including
close-and-reopen cycles, because the criteria are about what survives:
prior AI/human versions with distinct provenance, locks, guidance, and
per-branch control state across a refresh/reconnect or process restart.
No existing node IDs were removed or renamed.
