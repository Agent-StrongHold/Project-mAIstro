---
inventory-delta:
  tests/: +49
---
# claude-issue-262-gates-must-have-run

Forty-nine new node IDs across three files test the execution-truth gate, its
trusted publisher, and the static workflow-write guard. Nothing was removed or
reparametrised.

## `test_check_workflow_write_safety.py` — the static guard (19)

Three writes a workflow can make that leave no signal a reviewer or a gate would
notice: `git push` (AC-1), a blanket `-X ours`/`-X theirs` (AC-3), and an
automated `--bank` (AC-4). Each rule is tested on the shape actually found in
`m0-merge-candidate.yml`, including the merge line verbatim.

The escape-hatch cases are the ones that matter as much as the rules. A waiver
works on the offending line or the line above it. A waiver **without a reason**
does not suppress, and a waiver two lines above does not reach, so one waiver
cannot drift over unrelated steps as a file grows.

## `test_check_gates_ran.py` — did the gates reach the commit (26)

The script distinguishes actual execution evidence from states that merely
create a check-run record. A check that ran and failed is someone else's gate to
report, and an in-progress check is acceptable until `--require-complete` is
requested. A missing run remains the original finding. A present run whose
conclusion is `action_required`, `stale`, `skipped`, or `cancelled` is also a
finding because presence alone cannot prove the required enforcement executed
to a verdict.

The skipped/cancelled cases close the M0 false-green discovered while validating
live branch protection. `test_skipped_required_check_is_not_execution_evidence`
and `test_cancelled_required_check_is_not_execution_evidence` pin the evaluator
semantics directly. `test_one_skipped_check_fails_the_real_contract` exercises
the same condition through `main()` with the repository's actual required-check
set, so a future refactor cannot silently weaken the aggregate result.

`TestItRefusesToGuess` keeps the gate from becoming harmful. An unparseable
payload, a missing file, a payload with no `check_runs` array, and an empty check
list each fail rather than pass.

`test_base_coupled_checks_are_excluded` records the default/develop behavior:
CodeQL and the container scan do not execute on a develop-based PR, so they are
not evidence there. Main-specific inclusion is pinned separately by the
publisher contract tests below.

`test_it_triggers_on_every_workflow_that_produces_a_required_check` guards the
wiring: a producer workflow missing from `gates-ran.yml`'s `workflow_run:` list
would mean its completion never re-evaluates the head.

## `test_gates_ran_publisher_contract.py` — publish the verdict where protection reads it (4)

These tests pin the M0 wiring discovered during live validation. A
`workflow_run` job's native check is attached to the protected default-branch
SHA, not the triggering PR head, so the trusted workflow must explicitly publish
`gates-ran` onto the exact candidate SHA.

The contract asserts that:

- a `main` promotion includes CodeQL and container-scan execution evidence;
- a `develop` PR excludes those main-only checks;
- the publisher has only `checks: read`, `contents: read`, and `statuses: write`;
- the workflow remains `workflow_run`-based, runs trusted default-branch code,
  and publishes the literal `gates-ran` context on the triggering head rather
  than moving the judge into candidate-controlled `pull_request` code.

## What the report itself is tested for

A gate is read by someone deciding whether to trust a merge, so what it prints
is part of what it does. The report tests keep absent, non-executed, and
unfinished states diagnostically separate. The empty-required-set and empty
workflow-list cases also fail closed: a gate that reports green because it had
nothing measurable is the failure this machinery exists to prevent.
