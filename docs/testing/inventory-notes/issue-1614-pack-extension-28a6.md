---
inventory-delta:
  packages/maistro-design/tests: +4
---
# issue-1614-pack-extension-28a6

Suite-inventory delta for PR #1619 ([M7-A15] Domain pack registry and open
pack cohort, fixes #1614) at head `ad55a205d13717c724787fbb096bd44207ea618f`
(branch `issue-1614-pack-extension`, develop base `833a98a9112612d1dd2557db234b6e4dacd8d0e4`).

## What moved and why

`packages/maistro-design/tests: +4` — the four tests added with the open-cohort
pack registry in `packages/maistro-design/tests/test_domain_packs.py`:

- `test_bundled_packs_load_through_one_registry` — all eight `catalog/*.json`
  manifests (the five new `interactive`, `novel`, `small_business`,
  `training_program`, `website` plus `product`, `game`, `book`) load through
  the single `load_bundled_packs()` registry with canonical run identity and a
  shared graph template.
- `test_same_goal_two_packs_share_identity_scheme` — one Goal bound to `game`,
  `novel`, `training_program`, and `product` keeps one `goal_id`/`run_identity`
  scheme across packs.
- `test_missing_rubric_is_rejected` — a manifest without a rubric catalog is a
  loud `PackContractError` (extension rule: required rubric + graph template).
- `test_canvas_cannot_be_a_pack_id` — backend names such as `canvas` are
  rejected as `pack_id` by the same contract.

No tests were removed or renamed; the movement is purely additive, matching
the PR's new test file contents. Broader suite run at this head:
`uv run pytest packages/maistro-design/tests -q` → 666 passed, 1 skipped
(667 collected node IDs).

Addendum (repair round at this lane): `PackRegistry` sibling
`_as_pack` in `registry.py` was decomposed into `_require_contract_fields` +
`_rubric_dimensions` (identical observable behavior) because the inline version
was a new C-grade block (CC 14) the radon ratchet rightly refused; no test
counts moved in that repair.
