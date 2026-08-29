---
inventory-delta:
  tests/: +20
---
# claude-issue-345-contract-marker-4705

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

One new file, twenty tests, nothing moved or deleted.

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

The last seven arrived after the diff-coverage gate failed this PR: the
measurement lives in `check_contract_markers_impl.py` and the thirteen tests
above all pointed at it, leaving `scripts/check-contract-markers.py` — the file
CI actually invokes — at 0% of its forty changed lines.

Splitting an entry point off a measured module does not move it out of the
measured set, and the split is exactly what made the gap easy to miss: the
tests looked thorough because they were, about the wrong file. So the entry
point is now loaded as a module the same way `test_check_diff_coverage.py`
loads its own, and `main` is called for real: a clean corpus exits 0, an
unevidenced claim exits 1 and names the document, `--update` writes the
baseline, banking then re-checking passes, and a category banked with a blank
disposition fails. Exit codes are the contract CI reads, and none of them is
exercised by testing the measurement underneath — a `main` that computed every
finding correctly and then returned 0 would have passed all thirteen.

Two tests cover `_report`'s truncation, which exists so a gate with two hundred
findings stays readable; it prints twenty and says how many it withheld.

The entry point is at 98% now. The remaining line is the `if __name__ ==
"__main__"` guard, which importing the module cannot reach by construction.
