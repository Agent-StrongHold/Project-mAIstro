---
inventory-delta:
  tests/: +14
---
# m4-385 — CHANGELOG content gate

#385 made the release-consistency gate check Unreleased *content*, not heading
presence: entries must sit under a recognized category and link the issue or PR
they belong to (or carry the explicit `(no linked issue: <reason>)` exclusion),
placeholder-only sections fail, and at tag time (`--releasing vX.Y.Z`) the
section being published must be meaningful because `release_notes.py` publishes
exactly that section.

The +14 node IDs are all in `tests/test_check_release_consistency.py`:

- Ten Unreleased shape tests: categorized+linked passes, genuinely empty
  passes an ordinary run, placeholder-only fails, unlinked entry fails, a link
  on a wrapped line counts (the shipped CHANGELOG's entries are multi-line),
  the no-issue exclusion is accepted, entry outside a category fails, unknown
  category fails, `Dependencies` is recognized, and prose with no entries
  fails.
- Four release-readiness tests: empty target section at `--releasing` fails,
  placeholder-only target section fails, an rc checks the base-version
  section, and a curated target section passes.

One existing fixture gained content (`test_the_tag_being_released_is_excluded`)
because its dated section was empty and the gate now refuses to release
against emptiness — the same change, seen from the fixture side.
