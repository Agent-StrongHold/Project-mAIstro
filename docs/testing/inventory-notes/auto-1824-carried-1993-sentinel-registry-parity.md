---
inventory-delta:
  tests/: +1
---

# Branch-carried #1993 sentinel registry-parity test (develop-history rewrite orphan)

One node ID in `tests/security/test_sentinel_permission_table_armed.py`:
`test_hive_preset_tracks_the_executable_registry` — `PERMISSION_PRESETS[
"hive_conductor_tools"]` must equal exactly the Conductor `dispatch_tool`
registry, so a registry change cannot silently re-arm grants nothing can
execute.

This is not a new test written by this branch: it was added by
`edb669149` ("fix(security): arm the Conductor with tools its runtime can
execute", PR #1993 cutover-p0.9-sentinel-armed) and reaches this branch through
the `2f56be40a` merge. Develop's current tip (`c2a22e55d`) does not contain
that lineage — its history was rewritten after the branch diverged — so the
compacted `counts` baseline (recorded on develop tip, `tests/: 5241`) never
folded this node, and no note on either side carried its delta: expected was
5241 + 19 (`1881-restore-oracle-snapshot-consistency.md`, the two oracle files)
= 5260 while the branch collects 5261. This note records the missing +1 so the
shared count plus per-change deltas matches what the branch actually collects.

No test was added, removed or rewritten by this change. Verified:
`uv run pytest tests/security/test_sentinel_permission_table_armed.py -q` →
10 passed (develop tip collects 9 for the same file; the difference is exactly
this node), and
`uv run python scripts/check-suite-inventory.py` → ok after this note.
