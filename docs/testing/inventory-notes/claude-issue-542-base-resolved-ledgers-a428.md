---
inventory-delta:
  tests/: +28
---
# claude-issue-542-base-resolved-ledgers-a428

Twenty-three are `tests/test_check_ratchet_provenance.py`, the suite for the
ratchet-provenance inventory (#542). Nothing removed or moved.

They are written against synthetic trees in `tmp_path` rather than the
repository's own 21 ledger-reading scripts. Asserting over the real corpus
would restate today's inventory and go red as unrelated gates changed; what is
under test is what the *rules* do. Four exceptions at the end deliberately do
run against the real tree, because they are the claims the committed inventory
file makes: every recorded script still reads a ledger, none has since been
converted, every candidate-read script is recorded, and every row is well
formed.

Two of them found defects in the gate while it was being written, which is why
they are the shape they are.

`test_a_ledger_named_by_variable_still_counts_as_a_use` failed first. The
detector matched `ROOT / "quality" / "<name>"` and kept the trailing constant;
where the segment was a variable it kept nothing and reported the script as
touching no ledger at all — the one spelling that escaped the inventory
entirely, and the only one a script avoiding this gate would have to reach for.

Fixing that broke `test_a_path_expression_is_a_use`, because `ast.walk` yields
the inner `ROOT / "quality"` of `ROOT / "quality" / "x"` as well as the whole
expression, so every named ledger also reported an unnamed one. Only the
outermost expression of each chain is considered now.


The remaining five are `TestANewlyPublicRouteIsNotSelfApproved` in
`tests/test_check_public_routes.py`, added with that gate's conversion to a
base-resolved registry. They pass a trusted registry directly rather than
staging a git history: what is under test is the rule, and the part that reads
the base is exercised against the real repository by the gate's own run.

Two of the five are the ones that keep the rule from over-reaching. A route the
base already declared must pass — judging it again every run would make an old
exemption indistinguishable from a new one — and *removing* a route must pass
with no ceremony, because closing a public route is the direction this gate
wants and ceremony there discourages the fix.

No test was deleted for this. The existing `bench` fixture gained a substituted
`trusted_registry` returning the no-base state, because a bench registry lives
in `tmp_path` and therefore has no path at the base revision; the cases it
serves keep testing the consistency rules they were written for.
