---
inventory-delta:
  tests/: +13
---
# claude-issue-345-contract-marker-4705

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

One new file, thirteen tests, nothing moved or deleted.

`tests/test_check_contract_markers.py` covers `scripts/check-contract-markers.py`,
which enters the repository under the `scripts/` diff-coverage root (#257) —
the gate that governs the gates.

Built against a throwaway corpus in `tmp_path` rather than the repository's own
327 documents, deliberately. The claim under test is what the *rules* do; a test
asserting over the real corpus would only restate today's ledger, and would go
green or red as unrelated documents changed.

One case per rule: a declared kind with a marked test is evidenced; without one
it is flagged; a document with no `tests:` lands in its own category because it
is vacuous rather than false; a document declaring no contracts is not this
gate's business; a statically skipped test is not evidence; an undefined marker
kind fails and all three defined kinds pass. Four more hold the ledger
mechanics — a new finding is reported, a recorded one is not, a fixed one must
shrink the ledger, and a category banked with a blank disposition fails,
because banked and explained have to be the same act.
