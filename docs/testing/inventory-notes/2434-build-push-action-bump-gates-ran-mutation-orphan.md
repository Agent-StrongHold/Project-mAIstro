---
inventory-delta:
  tests/: +1
---

# 2434 CI-repair: the mutation-gate row is orphaned on a workflow-only PR head

<!-- pytest inventory delta is +1: one incident-replay test added to
     tests/test_check_gates_ran.py (TestTheRequiredSet). The branch's
     tests/ci/integration-scope.test.cjs change is the develop-sync conflict
     resolution and ships no new node tests — `node --test` still runs the
     same 14 tests develop ships (13 starvation/budget replays plus the
     permissions pin; the #2433 and #2435 notes record the same accounting). -->

CI-repair round for PR #2434 (docker/build-push-action 6 → 7.4.0) whose
merge-queue evaluation stayed red with the single finding "commit status
not successful" (prior block: "CI gates red with no repairable
findings"). Diagnosis from the checks-API evidence captured for head
`0382be897c02`:

- All 80 check runs on the head concluded `success`, including
  `integration-scope` itself, `docker-build`, `exact-debt-ledger`, and
  every Quality/* sub-gate.
- The commit status `gates-ran` on the same head was `pending`
  ("Required execution evidence is still arriving") five times over
  (publisher runs 44905934392 → 44909375407), and
  `enqueue-merge-queue.yml`'s `published-gate` step requires the latest
  `gates-ran` status to be `success` — that is the exact "commit status
  not successful" verdict. PR state: `mergeable: true`,
  `mergeable_state: unstable`.

Reproducing the CI-exact evaluator against the captured head evidence
pinpoints the one missing producer:

```
python3 scripts/check-gates-ran.py \
  --check-runs <check-runs.json for 0382be897c02> \
  --require-complete --base-branch develop \
  --event-name pull_request --changed-files <PR #2434 files envelope>

PENDING: execution evidence is still arriving

  not present yet (1):
    Mutation gate (changed critical lines)
```

Mechanism: the PR's changed-file set is exactly
`.github/workflows/fleet-images.yml`,
`.github/workflows/integration-scope.yml`, `.github/workflows/release.yml`,
`tests/ci/integration-scope.test.cjs`. None of these matches
`mutation.yml`'s `pull_request.paths` (the workflow lists
`packages/**/*.py`, the quality ledgers, `docs/testing/inventory-notes/**`,
and its own file), so mutation.yml never triggered on this head and its
required-set row (REQUIRED-CHECKS.md line "mutation | Mutation gate
(changed critical lines) | paths") had no check run. `check-gates-ran.py`
requires every row unconditionally on `pull_request` heads — the row is
absent, and absence is `pending`, never green and never excusable
(`Mutation gate (changed critical lines)` is not in
`PATH_SCOPED_CHECKS`). This is the #2120/#2371 failure mode verbatim:
"the required-set row ... has no check-run on the candidate head and
gates-ran stays pending forever ... every producer had completed, so no
later publisher run could ever flip the verdict."

Repair, following the same precedent: the repair PR carries this
inventory note, whose path matches mutation.yml's
`docs/testing/inventory-notes/**` trigger, so the workflow runs on the
repaired head and produces real zero-overlap evidence ("No
mutation-critical file changed" — no `packages/**/*.py` is touched).
Sibling repair PRs #2433 and #2435 shipped the identical mechanism: their
heads each carried `2433-*`/`2435-integration-scope-starvation-budget.md`
notes and their mutation gates concluded `success`. Nothing about the
evaluator, the publisher, the enqueue controller, or any gate's verdict
semantics changed; the branch's only substantive delta remains the
build-push-action SHA pin (`fleet-images.yml` v6 → v7.4.0) and the
`release.yml` v7 → v7.4.0 pins, plus the comment-only integration-scope
budget conflict resolution carried from the develop sync.

The one added pytest test replays the incident through the CI-exact
evaluator: a head whose check runs contain every required develop-PR row
as success except the mutation row must be `PENDING` naming exactly that
row (with a measured PR changed-file envelope, ruling out the ambiguous-
scope pending path), and adding the row to the identical evidence must
flip the verdict to `ok` — pinning that the repair is trigger coverage,
not evaluator leniency. Against the incident's captured evidence the
first half reproduces the publisher's `pending` verdict verbatim.
