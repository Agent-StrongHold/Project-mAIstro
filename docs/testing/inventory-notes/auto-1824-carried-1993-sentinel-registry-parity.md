---
inventory-delta:
  tests/: 0
---

# Branch-carried #1993 sentinel registry-parity test (develop-history rewrite orphan)

> **Superseded — delta zeroed in the #1824 CI-repair round (2026-10-18).**
> This note recorded a +1 for a node develop's then-tip supposedly lacked.
> After the branch merged develop `35a72ff54` (and through origin/develop tip
> `e708451b3`), the node `test_hive_preset_tracks_the_executable_registry`
> exists in the merged develop lineage too, and develop's own suite-inventory
> gate passes with no note carrying its delta — the shared compacted baseline
> (identical on both sides) already accounts for it. The +1 below therefore
> became a double count: this branch expected 5585 while collecting 5584.
> The delta is set to 0 to keep the gate truthful; the record below is kept
> for provenance.

One node ID in `tests/security/test_sentinel_permission_table_armed.py`:
`test_hive_preset_tracks_the_executable_registry` — `PERMISSION_PRESETS[
"hive_conductor_tools"]` must equal exactly the Conductor `dispatch_tool`
registry, so a registry change cannot silently re-arm grants nothing can
execute. (The test itself is untouched by the supersession above; only this
note's recorded delta changed.)

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

(The verification above is the original round's evidence, kept verbatim. It
describes a develop tip that has since been superseded — see the
supersession block at the top.)
