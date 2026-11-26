---
inventory-delta:
  tests/: +7
---
# 358-suite-parent-resolution

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

Seven new tests in `tests/test_check_suite_inventory.py`
(`TestSuitePathResolution`), all for the `--suite` argument of
`scripts/check-suite-inventory.py`. No production or test code outside that
script moved; the root suite is the only one affected.

Why: `--suite` matched recipes by exact key only, so an argument naming a
parent directory — `packages/hive-conductor/tests`, the path scope evidence
derives for changed files under `tests/e2e/` — exited 2 with `no collection
recipe` instead of checking the nested `tests/e2e` suite. Resolution now
expands a directory argument to every recipe beneath it (component-wise, so
`form` never reaches `formal/`), keeps exact matches exact, and still errors
on arguments matching nothing. The seven tests pin: the hive-conductor parent
resolves to the nested e2e suite; a parent selects everything beneath it;
exact arguments select only themselves; prefix matching is component-wise; a
resolved suite's drift still fails the narrowed check; a matching nested suite
passes; and an unresolvable argument still exits 2 without collecting.

Verified the new tests fail against the pre-change script: the old
`main()` exits 2 on `--suite packages/hive-conductor/tests` (the exact
invocation this repairs), the new one collects and checks `tests/e2e` and
exits 0.
