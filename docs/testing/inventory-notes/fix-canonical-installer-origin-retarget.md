---
inventory-delta:
  tests/: +2
---
# fix-canonical-installer-origin-retarget

Two additive contract tests for `ensure_git_origin` in `get.sh`: retarget an
existing checkout whose `origin` still points at the retired default repository,
and leave a checkout alone when it already matches the canonical source.
