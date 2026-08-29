---
inventory-delta:
  tests/: +23
---
# claude-issue-542-base-resolved-ledgers-a428

All twenty-three are `tests/test_check_ratchet_provenance.py`, the suite for
the ratchet-provenance inventory (#542). Nothing removed or moved.

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
