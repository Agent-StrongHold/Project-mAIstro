---
inventory-delta:
  packages/maistro-core/tests: +1
---
# claude-issue-556-persona-catalog-ac8

One added test, no removals, nothing renamed or moved, no production file
touched.

`test_a_returned_persona_is_a_snapshot_not_a_live_view` in
`packages/maistro-core/tests/personas/test_store.py` pins the copy
discipline of `InMemoryPersonaStore.update`. Every other test in that file
compares a returned Persona against the store immediately, while the two are
equal either way, so none of them can tell a snapshot from a live view.

This does not carry an `@pytest.mark.ac`. It was written while proving
SPEC-081226-bb3a AC-8 and is what that work turned up, but AC-8 itself is
proved by `tests/personas/test_catalog_membership.py` on the
`claude/issue-556-persona-legacy-acs` branch (#577), which covers the
criterion more directly. Marking this too would claim a criterion twice
without adding evidence for it.
