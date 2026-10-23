---
inventory-delta:
  tests/: +14
---
# 330-mutation-diff-scope

Fourteen additions in `tests/test_mutation_diff_scope.py`; nothing removed.

**`TestChangedLineParsing` (+5).** Only `+` lines on the new side of a
single-file unified diff count as changed; deleted lines have no new-side
position; hunk offsets are honoured; an empty diff yields an empty scope; and
a garbled hunk header is rejected rather than guessed at (a misparse here
silently changes what is mutated).

**`TestTheSkipRule` (+3).** Only mutants wholly outside the changed set are
skipped; a mutant whose span touches a changed line stays in scope; and a
work item spanning several modules is refused, never guessed about.

**`TestExplicitFailures` (+3).** An empty changed-line set and a session with
zero in-scope mutants each exit non-zero ("zero mutants is a configuration
error, not a pass"), and the real-session case proves off-scope mutants get
`SKIPPED` results persisted in an actual cosmic-ray sqlite session while
in-scope mutants stay pending.

All fail against the pre-#330 tree: whole files were mutated regardless of
what the PR changed.
