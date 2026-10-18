---
inventory-delta:
  tests/: +1
---
# #1198 develop sync — inherited `tests/` suite delta

Merge `201c7ea22` (syncing develop `2f56be40ad`, PR #1993 lineage) into
`auto-1198` changed no `tests/` file on this branch's side — the branch's own
delta vs its merge-base is exactly the six #1198 PR files. Collection evidence
(node-ID diff of `pytest tests/ --collect-only -q`):

- at `41d2a73d7` (before the second sync): 5210 nodes;
- at HEAD `201c7ea22`: 5261 nodes, 51 additions, 0 removals, all from
  develop-side commits (`test_ratchet_provenance.py` +20,
  `test_backup_restore_oracle.py` +15, `test_restore_oracle_characterization.py` +4,
  `cross_product_parity` +3, `test_m1_542_diff_coverage_edges.py` +2,
  `test_check_vulture_baseline.py` +2, four check-gate suites +1 each, and
  `tests/security/test_sentinel_permission_table_armed.py` +1).

The folded inventory notes already cover 50 of the 51 (expected 5260). The
residual +1 is
`tests/security/test_sentinel_permission_table_armed.py::test_hive_preset_tracks_the_executable_registry`,
added by the `feat/cutover-p0.9-sentinel-armed` lineage, which recorded no
suite-inventory note on develop. This note records that merge-brought delta so
the branch inventory matches the tree; it is not a test authored for #1198,
and no test was removed or weakened to get here. The suite collects cleanly —
this is a count move, not a collection failure.
