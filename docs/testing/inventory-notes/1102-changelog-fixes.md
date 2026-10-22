---
inventory-delta:
  tests/: +5
---
# 1102-changelog-fixes

CHANGELOG enforcement repairs for issue #1102, all in
`scripts/check-release-consistency.py`:

1. `_entries` now flushes the pending bullet when a `###` category heading
   begins, so the last entry of every non-final category is validated instead
   of silently dropped.
2. `_release_readiness_problems` treats a heading-only section (bare `###`
   categories, no entries) as non-releasable, via `_body_has_meaningful_content`.
3. `_NO_ISSUE_RE` requires a complete, balanced `(...)` whose reason holds at
   least one character that is neither whitespace nor a delimiter, so
   `(no linked issue: )` and `(no linked issue:)` no longer pass as exemptions.

Tests added to `tests/test_check_release_consistency.py`:

- `test_an_empty_no_issue_exclusion_is_rejected` — pins the delimiter-only
  no-issue escape.
- `test_the_last_entry_before_a_category_heading_is_validated` — pins the
  category-boundary flush escape (untraceable entry hidden by a heading).
- `test_a_well_formed_last_entry_before_a_category_heading_passes` — the
  flush does not over-reject a linked entry that closes its category.
- `test_releasing_against_a_heading_only_target_section_fails` — pins the
  heading-only release-readiness escape.
- `test_releasing_against_a_heading_plus_trailing_link_defs_target_fails` —
  pins the heading-only escape's follow-up: when the target is the final
  CHANGELOG section, `section_body` sweeps the file's trailing
  Keep-a-Changelog definitions (`[1.0.0]: ...`) into the body, which made the
  heading-only rejection see "meaningful content" and pass. Readiness now
  drops those definitions first (`_drop_trailing_link_defs`), mirroring
  `release_notes.py`'s identical normalization before it publishes, so a
  `### Added` heading plus stray link definitions is still rejected.

Mutation evidence: running the new tests against the pre-fix script
(`git show 28614700bd9a:scripts/check-release-consistency.py`) reproduces
each escape — the old `_entries` loses the `Untraceable` bullet, the old
`_release_readiness_problems` passes a heading-only section, and the old
`_NO_ISSUE_RE` accepts `(no linked issue: )` — so each test fails if its
escape returns. The link-definitions case was re-proven against the
intermediate HEAD (92ae3a926, which has the heading-only rejection but not
the normalization): `_release_readiness_problems` returns `[]` for
`### Added` plus trailing `[0.9.0]:`/`[1.0.0]:` definitions there, while
`release_notes.extract_section` publishes exactly `### Added` — the fixed
check rejects it.
