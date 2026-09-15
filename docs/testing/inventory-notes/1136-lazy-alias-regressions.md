---
inventory-delta:
  tests/: +24
---
# Issue 1136: Lazy lifecycle alias regressions

Twenty-four tests compare the execution-lifecycle scanner with native Python's
PEP 695 alias evaluation across module rebinding, enclosing functions, typing
imports, class-local shadowing, eager aliases, and two real Git revisions.
The fixtures execute only test snippets; production scanner source is loaded
as a test module and never imported or executed by the snippets.
