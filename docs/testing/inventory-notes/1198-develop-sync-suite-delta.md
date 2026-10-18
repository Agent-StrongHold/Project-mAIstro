# #1198 develop sync — inherited `tests/` suite delta (superseded; records no delta)

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

Resolution: this note originally carried `inventory-delta: tests/: +1` because
develop had recorded no note for its residual +1,
`tests/security/test_sentinel_permission_table_armed.py::test_hive_preset_tracks_the_executable_registry`,
at the time. The final develop sync merge (`f70cbba2f`) then brought develop's
own
[1993-hive-permission-preset-inventory.md](1993-hive-permission-preset-inventory.md),
which records that same node as `tests/: +1`. Keeping both notes charged one
collected test twice and drifted the ledger — CI-exact
`python3 scripts/check-suite-inventory.py` reported
`DRIFT tests/: expected 5505, collected 5504`. The upstream note is the
canonical record of that test, so this note's delta block is withdrawn and it
now records no delta; no other count moved. It is not a test authored for
#1198, and no test was removed or weakened — the suite collects cleanly at
5,504 nodes and the gate passes (17 suites match).
