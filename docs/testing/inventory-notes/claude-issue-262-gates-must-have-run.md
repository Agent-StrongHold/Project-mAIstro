---
inventory-delta:
  tests/: +42
---
# claude-issue-262-gates-must-have-run

Forty-two new node IDs across two files, both testing new gates in
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

## `test_check_gates_ran.py` — did the gates reach the commit (23)

The script tells apart three states that all render as "not green": a check that
ran and failed (someone else's gate reports that), one still running (nobody's
problem yet), and one that never ran at all. Only the third and its
`action_required` cousin are findings —
`test_action_required_is_the_finding_it_was_written_for` is the exact symptom a
push with the default `GITHUB_TOKEN` produces, where a run exists so it looks
checked and will never execute.

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
