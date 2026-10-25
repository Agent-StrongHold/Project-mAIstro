---
inventory-delta:
  tests/: +15
---
# 330-mutation-critical-list-gate

Fifteen additions, all in `tests/test_mutation_critical.py`. Nothing was
removed or renamed.

**`TestLoadRejectsUnusableLists` (+7).** The critical-file list decides where
the PR gate mutates; a list that is missing, unparseable, emptied, missing a
field, carrying an undeclared domain, duplicating a source, or naming a
non-existent file must each fail loudly. A silently emptied list is the worst
of these: the gate would run against nothing and report green — the exact
placeholder behaviour #330 removes.

**`TestTheCommittedList` (+3).** Pins the committed governance artifact: it
validates, the three demonstrated modules (#320/#321/#322: `secret_equal.py`,
`resource_policy.py`, `privilege.py`) are present, and every declared audit
domain has at least one entry.

**`TestIntersectAndEmit` (+5).** Critical∩changed intersection, TSV emission,
the unresolvable-test-scope error (zero selected tests must be an error, never
a silent widening to the whole suite), the explicit zero-overlap path, and the
`--sources` mode that lists every entry.

All fail against the pre-#330 tree: there was no loader and no artifact.
