---
inventory-delta:
  tests/: -3
---

# Develop sync merge: one fork-proof resolution instead of two

Merging origin/develop (f956a8142) into auto-35 conflicted in
`scripts/check-image-lock-reconciliation.py`: both branches had independently
fork-proofed the same `parse_expected` last-line-wins defect for lock names
split across marker partitions (beartype 0.22.9/0.23.1 since fastmcp-slim
4.1.3).

- auto-35 (fb413438e, `35-container-scan-pypdf-beartype-fork.md`, +3): a
  3-tuple `parse_expected` returning a per-name version-set, with an
  `_expected_display` mismatch format (`beartype in {0.22.9, 0.23.1} (any
  fork)`).
- develop (f956a8142, `1182-image-lock-split-resolution.md`, +5 nodes): a
  per-name pin-string set with an `_expected_clause` format (`one of
  beartype==0.22.9, beartype==0.23.1`).

The two variants are semantically identical — a shipped version is judged
against every version the lock names for that name; a version no fork allows
is one named mismatch, not a missing+extra pair — but their test files pin
mutually exclusive report formats, so the textual union of the two test
suites could not pass against either script.

## Resolution

Kept develop's script and test file verbatim (as sibling lanes auto-1836
4693f1f3d and auto-330 1f6ee2e23 did for the same conflict). auto-35's three
fork tests are removed; every behaviour they pinned is asserted by develop's
outstanding +5 nodes:

- keep-every-version parse: `test_parse_expected_keeps_every_version_of_a_split_resolution`
  (auto-35's `test_parse_expected_records_every_fork_version`)
- either resolved fork reconciles: `test_split_resolution_reconciles_with_whichever_branch_the_image_resolved`
  ×2 (auto-35's `test_forked_pin_shipping_one_partition_reconciles`)
- an unlocked version still fails once, by name:
  `test_split_resolution_still_fails_on_a_version_neither_branch_pins`
  (auto-35's `test_forked_pin_shipping_an_unlocked_version_fails`)
- single-pin skews keep the exact historical format:
  `test_split_resolution_leaves_single_pin_skews_and_requirements_alone`

Net: −3 nodes against the pre-merge head (develop's +5 stand; auto-35's +3
are withdrawn with their tests). auto-35's variant remains reachable at
fb413438e. 32/32 tests in `tests/test_check_image_lock_reconciliation.py`
pass on the resolved file.
