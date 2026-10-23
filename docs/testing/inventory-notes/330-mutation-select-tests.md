---
inventory-delta:
  tests/: +12
---
# 330-mutation-select-tests

Twelve additions in `tests/test_mutation_select_tests.py`; nothing removed.

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

**`TestEndToEnd` (+1).** Runs real pytest+coverage with per-test contexts over
a tiny fixture module and proves line 2 and line 6 each select their own
killing test — different lines, different tests, no union widening.

All fail against the pre-#330 tree: mutation ran the whole mirror suite per
mutant with no per-line selection.
