---
inventory-delta:
  tests/: +15
---
# #2503: closure guard recognizes declared direct children

Adds 15 parametrized pytest nodes to the existing root closure-target test suite in
`tests/test_check_closure_targets.py`:
- Seven explicit direct-child section parser examples;
- An open prose-only child that blocks auto-closure;
- A closed prose-only child that does not block;
- A missing declared child that fails closed;
- Three malformed native child response cases;
- Exhausted native pagination and self-parent refusal.

The existing 404 fixture was changed from accepting a missing sub-issues endpoint
to rejecting an unverified native hierarchy; its existing node count did not change.
This ledger delta counts the parameterized cases rather than source functions.
The collected count must be verified by CI, since this branch's tests were not
executed in the originating connector session. No floor or baseline reduction.
