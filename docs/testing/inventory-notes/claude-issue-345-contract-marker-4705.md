---
inventory-delta:
  tests/: +39
---
# claude-issue-345-contract-marker-4705

<!-- Say what moved and why, not just how much. The count alone hides
     compensating changes; that is the case these notes exist for. -->

One new file, thirty-nine tests, nothing moved or deleted.

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

Eleven more came from a Codex review that found three ways the scanner's
reading of the tree was narrower than its own stated rule.

`pytestmark` at module level was invisible, because the walk only visited
function definitions. pytest applies it to every test the module collects, so
it is evidence exactly as a decorator is — and the tree already held one such
file, `test_scorer_contract.py`, whose `pytest.mark.contract` named no kind at
all. That is an undefined kind the ledger had been silently not reporting.
Fixed rather than banked: the file's own docstring says `contract /
behavioral`, so the marker had simply lost its argument.

A marker on a fixture, a nested function, or a method of a non-`Test` class
counted as evidence, though pytest never runs any of them. That contradicts
the rule the gate already enforces for statically skipped tests, for the same
reason: evidence has to be able to run. Three parametrised cases cover the
uncollectable shapes and one covers the `Test*` method that *is* collected, so
the boundary is tested from both sides rather than only the exclusion.

`tests:` entries written as `path.py::test_func` — the form
`ADR-000-template.md` documents, so the sanctioned one — were looked up whole
against a path-keyed index and never matched, flagging every template-compliant
document as unproven. A node ID now resolves to the test it names rather than
to the file around it, since a document pointing at one test is claiming that
test is the evidence; four tests pin both directions and the plain-path form
that must not regress.

Worth recording: the ledger counts are unchanged at 171/202/2 after all three.
The node-ID fix moves nothing today because no document yet uses the form — it
unblocks the template rather than clearing a backlog. The collectability fix
moving nothing is the more informative result: no document was being proven by
a marker pytest would not run, so a false-evidence path closed without any
document losing evidence it was relying on.

The last eight came from the diff-coverage gate a second time, and they are
the error paths rather than the rules: an unparseable test file, a vendored
directory, a document with no front matter, one whose front matter does not
parse, a scalar `pytestmark` instead of a list, an unrelated module-level
assignment, and a baseline that is absent or has no `categories` key.

None is decoration. A gate that dies on one malformed file reports nothing
about the other 326, and the two front-matter cases are the boundary with the
registry gate that owns them: a parse error there is its finding, not this
one's. The impl is at 100% now, which is a consequence of covering those
paths rather than the goal.
