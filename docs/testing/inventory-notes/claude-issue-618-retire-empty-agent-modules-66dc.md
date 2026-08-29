---
inventory-delta:
  tests/: +2
---
# claude-issue-618-retire-empty-agent-modules-66dc

`tests/test_no_placeholder_modules.py` (+2, new). Nothing was moved, renamed or
deleted from any suite: the nine modules this change removes had no tests,
because they had no code.

The two are a check and its control. The check derives the set of modules under
`maistro/agents/` whose entire AST body is bare string expressions — a docstring
and nothing else — and asserts it is empty. The control builds one of each kind
in a tmp directory and asserts the detector separates them: a placeholder, a
real module that merely starts with a docstring, and an empty `__init__.py`,
which is not a placeholder because an empty one is how Python is told a
directory is a package.

**Deriving rather than listing is not stylistic here — it found three modules I
had missed.** The issue was written against six placeholders found by reading;
the test failed on nine, adding `forge/strategy.py`, `scribe/strategy.py` and
`warden_at_arms/strategy.py`. All three were docstring-only with no reference
anywhere in the tree, so all three are deleted too, and the reachability
baseline falls 207 → 198 rather than the 201 the issue predicted.

No test exercises the deleted modules' *absence* beyond this, and none needs to:
`check-reachability.py` fails if the baseline grows, and
`check-reachability-dispositions.py` fails if a baseline module has no
disposition or a disposition names a module that is gone — so the two quality
files cannot drift apart from the tree.
