---
inventory-delta:
  tests/: +8
---
# Issue 1136: Literal Lifecycle Discovery

Eight test cases extend `tests/test_check_execution_lifecycles.py` for status-shaped
Literal aliases, qualified and aliased imports, PEP 604 unions, multiline
values, bounded name/value heuristics, non-canonical dispositions, and the
expanded shipped ledger. The existing Enum tests remain the regression
coverage for the shared detector and ledger audit.
