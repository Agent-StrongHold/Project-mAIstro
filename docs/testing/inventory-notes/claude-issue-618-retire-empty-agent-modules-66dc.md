---
inventory-delta:
  tests/: +4
---
# claude-issue-618-retire-empty-agent-modules-66dc

`tests/test_no_placeholder_modules.py` (+4, new). Nothing was moved, renamed or
deleted from any suite: the fourteen modules this change removes had no tests,
because they had no code.

The four are a check, its control, and two tests of the detector's edges.

The check derives the set of modules under `maistro/agents/` whose entire AST
body defines nothing, and asserts it is empty. The control builds one of each
kind in a tmp directory and asserts the detector separates them — a placeholder,
a real module that merely starts with a docstring, and an empty `__init__.py`
beside a real sibling — so that a detector which found nothing anywhere could
not satisfy the check by being broken.

The two edge tests exist because the first detector was wrong in both
directions, and Codex caught both on review:

- `test_a_no_op_statement_does_not_buy_a_pass` — matching only string
  expressions meant one conventional `from __future__ import annotations`, or a
  `pass`, or a bare `...`, turned a placeholder into something the check waved
  through while the module still defined nothing. A gate that can be satisfied
  by typing is not a gate.
- `test_an_empty_package_marker_is_a_placeholder_when_it_stands_over_nothing` —
  the exemption for `__init__.py` was unconditional. An empty one beside real
  modules means "this directory is a package" and carries that meaning by
  existing; alone in an empty directory it means nothing at all. The exemption
  is now earned from the package it marks.

**Deriving rather than listing is not stylistic here — it found more than
reading did, twice.** The issue was written against six placeholders found by
reading; the first derived run failed on nine, adding `forge/strategy.py`,
`scribe/strategy.py` and `warden_at_arms/strategy.py`. Fixing the `__init__.py`
exemption then added five more: `forge`, `scribe` and `warden_at_arms` lost
their only real sibling to this very change, and `frank` and `mason` had been
empty packages already. All fourteen are docstring-only or empty with no
reference anywhere in the tree, so the reachability baseline falls 207 → 193
rather than the 201 the issue predicted.

No test exercises the deleted modules' *absence* beyond this, and none needs to:
`check-reachability.py` fails if the baseline grows, and
`check-reachability-dispositions.py` fails if a baseline module has no
disposition or a disposition names a module that is gone — so the two quality
files cannot drift apart from the tree.
