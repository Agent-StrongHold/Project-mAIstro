---
inventory-delta:
  tests/: +45
---
# claude-issue-262-gates-must-have-run

Forty-five new node IDs across two files, both testing new gates in
`scripts/`. Nothing removed or reparametrised.

Both gates currently find nothing — `m0-merge-candidate.yml` was removed before
either was written — so these tests are the only thing keeping them honest. A
guard with nothing to catch and no tests is a guard nobody knows is broken.

## `test_check_workflow_write_safety.py` — the static guard (19)

Three writes a workflow can make that leave no signal a reviewer or a gate would
notice: `git push` (AC-1), a blanket `-X ours`/`-X theirs` (AC-3), and an
automated `--bank` (AC-4). Each rule is tested on the shape actually found in
`m0-merge-candidate.yml`, including the merge line verbatim.

The escape-hatch cases are the ones that matter as much as the rules. A waiver
works on the offending line or the line above it, because YAML line length
pushes comments up as often as it leaves room at the end and a rule accepting
only one placement is one people reformat around. A waiver **without a reason**
does not suppress: the reason is the whole mechanism, and a bare marker would
let the silent behaviour back in under a token that reads as review while
recording nothing. A waiver two lines above does not reach, so one waiver cannot
drift over unrelated steps as a file grows.

`test_the_waiver_comment_is_not_itself_a_finding` covers the self-reference: the
marker's own text contains the words it waives, so a scanner that read comments
would flag its own escape hatch.

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

`TestItRefusesToGuess` is the half that keeps the gate from becoming harmful. An
unparseable payload, a missing file, a payload with no `check_runs` array, and
an empty check list are each asserted to fail rather than pass — reporting green
because it could not tell would convert "we do not know" into "we checked",
which is the same `set()`-versus-`None` distinction `passing_ac_ids` draws.

`test_base_coupled_checks_are_excluded` records a deliberate narrowing. CodeQL
runs only on PRs based on `main`, so on a `develop` PR its three checks
legitimately produce no run; requiring them would paint every PR in the
repository red for correct behaviour. The required set is read from
`check-required-checks.py`'s own `base_coupled()` rather than a second list.

`test_it_triggers_on_every_workflow_that_produces_a_required_check` guards the
wiring: a producer workflow missing from `gates-ran.yml`'s `workflow_run:` list
would mean its completion never re-evaluates the head, so an early red could be
the last word.

## What the report itself is tested for

Both files end with a `TestTheReport` class, because a gate is read by someone
deciding whether to trust a merge — what it prints is part of what it does. A
gate that says only "no" gets worked around rather than followed, so a finding
is asserted to carry the reason, the fix, and the waiver syntax.

Two of those cases are about refusing to answer rather than about wording.
`test_an_empty_required_set_is_refused` covers the contract coming back empty:
this gate would then pass everything while appearing to check, which is the
failure it exists to prevent, one level up. `test_finding_no_workflows_at_all_is_a_failure`
is the same shape for the static guard — an empty scan reporting "ok: 0
workflows" is the same false green as a gate that never ran.
