---
inventory-delta:
  tests/: +11
---
# claude-issue-268-branch-protection-doc-gate-d4ac

All 11 are additions to `tests/test_check_branch_protection.py` (29 -> 40), in
one new `TestGeneratedTables` class. Nothing was removed or reparametrised.

They cover the gate #268 adds — that `docs/ci/BRANCH-PROTECTION.md`'s two
tables are generated from `.github/branch-protection.json` rather than
remembered:

- **Rendering (3).** The count column comes from the ruleset; a check that
  cannot report on a branch renders as `○` rather than a blank; a check that
  *could* report but is not required renders distinctly again, because a
  judgement must not be able to hide inside a constraint.
- **The live claim (1).** The document that ships agrees with the ruleset that
  will be applied.
- **Drift, both halves (2).** The acceptance for #268: mutate a count, and
  separately mutate one membership mark while leaving every total correct.
  Each fails on its own — the second is the harder error, since the arithmetic
  still adds up.
- **Failing safe (2).** A document with the markers deleted fails rather than
  reading as "nothing to check", which is how a gate stops gating silently;
  and a change to the surrounding prose alone does not fail, because the
  reasoning in that document is the half worth keeping and the gate must not
  own it.
- **The write path and the exit (3).** `--update-doc` produces a region that
  then passes its own check and leaves the narrative intact — a generator that
  disagreed with its checker would emit a document that still fails, or one
  that passes while saying something the ruleset does not. A missing document
  is reported rather than crashed on. And the drift reaches a non-zero exit
  with a diagnosis, not just a helper returning a list nobody prints.

The last three were added because the diff-coverage gate put the file at 88.3%
of 60 changed lines against a 90% floor, and the seven uncovered lines were the
update path, the missing-file path and the failure exit — the three worth
having tests for rather than the three worth waiving.
