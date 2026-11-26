---
inventory-delta:
  tests/: +15
---
# 330-mutation-select-tests

Fifteen additions in `tests/test_mutation_select_tests.py`; nothing removed.

**`TestContextResolution` (+6).** Coverage contexts (`test_mod.TestX.test_y`)
must resolve to runnable node ids for plain functions, class methods, and
parametrized tests; a parameterless context resolves to EVERY parameter
(under-selection could drop the only test that kills a mutant — the risk is
asymmetric); unknown and bare-module contexts resolve to nothing.

**`TestCoverageParsing` (+2).** Per-line context extraction for the target
source, empty-context lines dropped, and a missing source entry in the
coverage JSON is an error rather than a silent empty selection.

**`TestGrouping` (+2).** Lines sharing a selected-test set collapse into one
group; a changed line nothing executes is named explicitly in `no_coverage`
(the "zero selected tests" condition that must never pass silently).

**`TestCollectedParsing` (+2).** `pytest --collect-only` output maps to
context keys for plain functions, class methods, and parametrized node ids,
and the parametrized node id keeps its parameter suffix.

**`TestPackageRootedContexts` (+2).** Coverage roots context names at the test
module's *import path*, so a packaged suite prefixes them with the package
(`security.test_secret_equal.TestX.test_y`) while the collected key is
stem-based. The suffix match must resolve the prefixed context to its node id
and must not swallow a foreign stem — under-selection here silently drops the
only killing test (found by running the real gate against
`secret_equal.py`, whose contexts carry the `security.` package prefix).

**`TestEndToEnd` (+1).** Runs real pytest+coverage with per-test contexts over
a tiny fixture module and proves line 2 and line 6 each select their own
killing test — different lines, different tests, no union widening.

All fail against the pre-#330 tree: mutation ran the whole mirror suite per
mutant with no per-line selection.
