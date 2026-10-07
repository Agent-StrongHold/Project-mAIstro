inventory-delta:
  tests/: +0
---
# 1102-changelog-fixes

Fix CHANGELOG-related enforcement gaps from issue #1102:

1. Fix `_entries` function to not lose the last entry before a category heading.
2. Enhance `_release_readiness_problems` to treat heading-only sections as non-releasable.
3. Tighten `_NO_ISSUE_RE` pattern to require non-empty reason for no-issue exemptions.

These changes fix the following gaps from the issue:
- CHANGELOG entry parsing loses the last item before a category heading
- Structure-only release sections can pass nonempty checks
- Empty no-issue exemptions satisfy the release traceability escape hatch