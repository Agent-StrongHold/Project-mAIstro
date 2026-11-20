---
inventory-delta:
    tests/: 1
---

# CR-2372 mutation gate reaches nightly-workflow edits (inventory delta)

## Repair

PR #2372 (dependabot: `actions/download-artifact` v7 → v8 in
`mutation-nightly.yml`) was stuck with the required `gates-ran` commit status
pending forever ("Required execution evidence is still arriving") across 10
publisher runs, while all 78 check-runs on the head were success or
skipped-for-scope. CI-exact replay on the captured head `34c0da9fa488`:

- `scripts/check-gates-ran.py --check-runs <captured> --require-complete
  --base-branch develop --event-name pull_request --changed-files
  <envelope: ['.github/workflows/mutation-nightly.yml']>` → exit 2,
  `not present yet (1): Mutation gate (changed critical lines)`.
- Appending one synthetic successful mutation-gate check-run to the same
  captured payload flips the replay to `ok: all 72 required check(s) ran on
  this head` (exit 0) — the absent path-scoped producer is the sole blocker.

Root cause is the class documented in `mutation.yml`'s own `paths:` comment
from the #2120 repair: `check-required-checks.py` keeps the mutation gate's
row in the required evidence set on every PR, but `mutation.yml`'s
`pull_request.paths` filter did not name `.github/workflows/mutation-nightly.yml`,
so a PR touching only that file never triggers the workflow and `gates-ran`
can never see the required check-run. The repair is additive and follows the
reviewed #2120 precedent (`quality/image-pins.json`): the nightly sibling
workflow file joins the paths list, so this PR class now produces real
zero-overlap mutation evidence ("No mutation-critical file changed") instead
of permanent absence. No gate is weakened; the mutation gate keeps failing
closed whenever a mutation-critical file does change.

## Test

`tests/test_mutation_targets.py::TestNightlyWorkflowEditsReachTheGate::
test_a_nightly_only_pr_triggers_the_mutation_gate` (+1, `tests/` 4117 → 4118
expected) pins the property, parsed from the workflow YAML rather than
substring-matched: the `pull_request.paths` filter of `.github/workflows/mutation.yml`
must contain `.github/workflows/mutation-nightly.yml`, or the next
nightly-only PR re-introduces the permanent pending. The class docstring
records the CI-exact replay evidence above.

## Validation executed this round

- `uv run python scripts/check-gates-ran.py` pending/ok replays (above).
- `uv run pytest tests/test_mutation_targets.py -q` → all passed, including
  the new test and the pre-existing workflow-wiring pins it sits beside.
- `uv run python scripts/check-required-checks.py` → exit 0 ("77 PR checks
  match docs/ci/REQUIRED-CHECKS.md"); the table is unchanged — the mutation
  row's scope stays `paths`.
- `uv run python scripts/check-workflow-inventory.py` → exit 0; triggers are
  unchanged (`pull_request`, `workflow_dispatch`), so
  `quality/workflow-inventory.json` needs no edit.
- `uv run python scripts/check-suite-inventory.py` → exit 0 with the +1 delta
  declared here.
