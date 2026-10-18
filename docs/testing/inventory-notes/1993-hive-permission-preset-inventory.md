---
inventory-delta:
  tests/: +1
---
# Record the registry parity test landed in #1993

PR #1993, merged as `2f56be40ad241262b0384ab0b97834ebd37fe4d7`, added
`tests/security/test_sentinel_permission_table_armed.py::test_hive_preset_tracks_the_executable_registry`
without recording its inventory delta. The module now collects ten cases,
including its nine existing cases and this new parity assertion.

This note records that already-landed test. It changes no test, collection rule,
security configuration or expected behavior. The original module's +9 entry in
`cutover-s1-9-warden-aggregate.md` and the CI split's +243 entry in
`1357-granular-ci-recovery.md` remain unchanged.

The #2155 merge-queue candidate exposed the omission: root collection was 5,504
against a recorded 5,503, while all other sixteen suite inventories matched.
The same +1 mismatch was reproduced after merging develop `2f56be40` into the
CI split branch. This note brings the recorded root inventory to the collected
5,504; it does not mask a missing or removed test.
